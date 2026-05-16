"""Compute the supersede-pattern diff between two snapshots of one file.

V2 schema (db/flyway/sql/V2__spine_kg_schema.sql) uses point-in-time
semantics: rather than UPDATE-in-place, the indexer closes a superseded
row (`valid_to = now()`) and inserts a fresh row carrying the new
`commit_sha`. That keeps historical "what did the graph look like at
commit X?" queries cheap (see V2 README §point-in-time).

This module is pure data; it does NOT talk to Postgres. The indexer
applies the four returned lists inside one transaction per file.

Matching keys:
  - nodes: `node_id` (stable external ID built by the parser runtime).
  - edges: `(from_node_id, to_node_id, type)` triple — same edge type
    between the same pair is treated as the same edge.

"Changed" means any of (type/subtype/name/path/properties) differ.
A changed node closes the old row + inserts a new one with a fresh
`commit_sha` (idempotent re-runs at the same commit are no-ops because
content is identical).
"""

from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass
class FileDiff:
    """Result of `diff_file_index` — four parallel lists for the indexer
    to apply transactionally (close-old-then-insert-new per the V2
    supersede pattern)."""
    insert_nodes: list[dict]
    insert_edges: list[dict]
    close_node_ids: list[str]   # node_id strings (stable external IDs).
    close_edge_keys: list[tuple[str, str, str]]  # (from, to, type) triples.


def diff_file_index(
    old_nodes: list[dict],
    old_edges: list[dict],
    new_nodes: list[dict],
    new_edges: list[dict],
) -> FileDiff:
    """Match old↔new by stable key; emit (insert_nodes, insert_edges,
    close_node_ids, close_edge_keys). Three cases per entity:
      - present in new only          → INSERT.
      - present in old only          → CLOSE.
      - present in both, unchanged   → no-op.
      - present in both, changed     → CLOSE old + INSERT new
                                       (the V2 supersede pattern)."""
    n_close, n_insert = _diff_nodes(old_nodes, new_nodes)
    e_close, e_insert = _diff_edges(old_edges, new_edges)
    return FileDiff(
        insert_nodes=n_insert,
        insert_edges=e_insert,
        close_node_ids=n_close,
        close_edge_keys=e_close,
    )


# ─── nodes ───────────────────────────────────────────────────────────


def _diff_nodes(old: list[dict], new: list[dict]) -> tuple[list[str], list[dict]]:
    old_by_id = {n["node_id"]: n for n in old}
    new_by_id = {n["node_id"]: n for n in new}
    close: list[str] = []
    insert: list[dict] = []
    for nid, n in new_by_id.items():
        if nid not in old_by_id:
            insert.append(n)
            continue
        if _node_changed(old_by_id[nid], n):
            close.append(nid)
            insert.append(n)
    for nid in old_by_id:
        if nid not in new_by_id:
            close.append(nid)
    return close, insert


def _node_changed(old: dict, new: dict) -> bool:
    """Compare every field the schema persists, except those that move
    monotonically across re-runs (commit_sha, valid_from)."""
    for key in ("type", "subtype", "name", "path", "repo"):
        if old.get(key) != new.get(key):
            return True
    return _props_changed(old.get("properties"), new.get("properties"))


def _props_changed(a: object, b: object) -> bool:
    """Stable-sorted JSON comparison so key ordering doesn't trigger a
    false diff. NULL == {}."""
    return _normalize_props(a) != _normalize_props(b)


def _normalize_props(p: object) -> str:
    if p is None:
        return "{}"
    if isinstance(p, str):
        try:
            p = json.loads(p)
        except (ValueError, TypeError):
            return p
    return json.dumps(p, sort_keys=True, separators=(",", ":"))


# ─── edges ───────────────────────────────────────────────────────────


def _edge_key(e: dict) -> tuple[str, str, str]:
    return (e["from_node_id"], e["to_node_id"], e["type"])


def _diff_edges(
    old: list[dict], new: list[dict],
) -> tuple[list[tuple[str, str, str]], list[dict]]:
    """Edges have no stable external ID, so a triple of (from, to, type)
    is the next-best key. If an edge's *properties* changed we still
    supersede (close old + insert new) so the new properties land."""
    old_by_key: dict[tuple[str, str, str], dict] = {}
    for e in old:
        # Last write wins if the same triple appears multiple times in
        # the old snapshot — pathological but harmless.
        old_by_key[_edge_key(e)] = e
    new_by_key: dict[tuple[str, str, str], dict] = {}
    for e in new:
        new_by_key[_edge_key(e)] = e

    close: list[tuple[str, str, str]] = []
    insert: list[dict] = []
    for key, e in new_by_key.items():
        if key not in old_by_key:
            insert.append(e)
            continue
        if _props_changed(old_by_key[key].get("properties"), e.get("properties")):
            close.append(key)
            insert.append(e)
    for key in old_by_key:
        if key not in new_by_key:
            close.append(key)
    return close, insert


# ─── utility: full-file replace ──────────────────────────────────────


def replace_file_index(new_nodes: list[dict], new_edges: list[dict]) -> FileDiff:
    """Treat the new snapshot as a complete replacement (use when the
    file was deleted-then-re-added, or when the caller has no `old`
    snapshot handy — e.g., the first incremental run after upgrading the
    parser runtime). Inserts everything new; closes nothing."""
    return FileDiff(
        insert_nodes=list(new_nodes),
        insert_edges=list(new_edges),
        close_node_ids=[],
        close_edge_keys=[],
    )


def close_file_index(old_nodes: list[dict], old_edges: list[dict]) -> FileDiff:
    """Treat the file as deleted: close every node and edge from the old
    snapshot; insert nothing. Used by the indexer on `D` (deleted) entries
    from `git diff --name-status`."""
    return FileDiff(
        insert_nodes=[],
        insert_edges=[],
        close_node_ids=[n["node_id"] for n in old_nodes],
        close_edge_keys=[_edge_key(e) for e in old_edges],
    )
