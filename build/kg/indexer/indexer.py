"""Spine KG indexer — STORY-6.4.1 / 6.4.2 / 6.4.3 (REQ-INIT-6 FR-5).

Modes:
  - cold_start_index: walk repo, parse every supported file, batch-insert.
    Target ≤5min per 100k LOC (NFR-1).
  - incremental_index: parse only files changed since
    `kg_index_state.last_indexed_commit_sha`; supersede or close per
    `diff_engine.FileDiff`. Target ≤5s for a 10-file commit (NFR-1).

All Postgres I/O via subprocess `psql` (no psycopg dep here, so this can
run in a slim sidecar). One BEGIN/COMMIT per file batch — a poisoned row
cannot roll back unrelated batches.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from .diff_engine import FileDiff, close_file_index, diff_file_index, replace_file_index
from .parser_runtime import ExtractorConfig, load_extractors, parse_file, pick_extractor

log = logging.getLogger("spine.kg.indexer")
BATCH_SIZE = 1000  # rows per psql multi-row INSERT (perf-tested sweet spot).


@dataclass
class IndexResult:
    """Counts NEW rows only — superseded rows still live with `valid_to`."""
    node_count: int = 0
    edge_count: int = 0
    files_indexed: int = 0
    duration_seconds: float = 0.0
    errors: list[str] = field(default_factory=list)


# ─── Public API ──────────────────────────────────────────────────────


def cold_start_index(repo_root: Path, languages: list[str] | None = None,
                     database_url: str | None = None) -> IndexResult:
    """Full repo walk → parse → batch-insert. Records HEAD into
    `kg_index_state` BEFORE the walk so a crash mid-cold-start is
    recoverable (next incremental run will re-diff what changed)."""
    started = time.monotonic(); result = IndexResult()
    db = _db_url(database_url); repo_root = repo_root.resolve()
    commit_sha = _git_head(repo_root); repo = repo_root.name

    extractors = _filter_extractors(languages)
    if not extractors:
        result.errors.append("no extractors loaded"); return result
    _upsert_index_state(db, repo, commit_sha, 0, 0)

    p_nodes: list[dict] = []; p_edges: list[dict] = []
    for fp, rel, cfg in _walk_repo(repo_root, extractors):
        try:
            nodes, edges = parse_file(fp, rel, cfg, repo, commit_sha)
        except Exception as e:  # noqa: BLE001
            log.warning("parse failure %s: %s", rel, e)
            result.errors.append(f"{rel}: {e}"); continue
        p_nodes.extend(nodes); p_edges.extend(edges); result.files_indexed += 1
        if len(p_nodes) >= BATCH_SIZE or len(p_edges) >= BATCH_SIZE:
            _flush_inserts(db, p_nodes, p_edges)
            result.node_count += len(p_nodes); result.edge_count += len(p_edges)
            p_nodes.clear(); p_edges.clear()
    if p_nodes or p_edges:
        _flush_inserts(db, p_nodes, p_edges)
        result.node_count += len(p_nodes); result.edge_count += len(p_edges)

    _upsert_index_state(db, repo, commit_sha, result.node_count, result.edge_count)
    result.duration_seconds = time.monotonic() - started
    log.info("cold-start: %d files, %d nodes, %d edges in %.1fs",
             result.files_indexed, result.node_count, result.edge_count, result.duration_seconds)
    return result


def incremental_index(repo_root: Path, commit_sha: str | None = None,
                      database_url: str | None = None) -> IndexResult:
    """Parse only files changed since last recorded commit; supersede or
    close per diff. Caller should run cold-start first if no cursor."""
    started = time.monotonic(); result = IndexResult()
    db = _db_url(database_url); repo_root = repo_root.resolve()
    repo = repo_root.name; head = commit_sha or _git_head(repo_root)
    last = _read_last_commit(db, repo)
    if not last:
        result.errors.append("no kg_index_state row; run cold-start first")
        return result
    if last == head:
        result.duration_seconds = time.monotonic() - started
        return result

    extractors = _filter_extractors(None)
    for status, rel in _git_diff_name_status(repo_root, last, head):
        cfg = pick_extractor(rel, extractors)
        if cfg is None:
            continue
        try:
            diff = _diff_one_file(repo_root, rel, status, cfg, repo, head, db)
        except Exception as e:  # noqa: BLE001
            log.warning("incremental failure %s: %s", rel, e)
            result.errors.append(f"{rel}: {e}"); continue
        _apply_diff(db, diff)
        result.files_indexed += 1
        result.node_count += len(diff.insert_nodes); result.edge_count += len(diff.insert_edges)

    _upsert_index_state(db, repo, head, result.node_count, result.edge_count)
    result.duration_seconds = time.monotonic() - started
    log.info("incremental: %d files, +%d nodes, +%d edges in %.2fs",
             result.files_indexed, result.node_count, result.edge_count, result.duration_seconds)
    return result


def reindex_file(repo_root: Path, file_path: Path,
                 database_url: str | None = None) -> IndexResult:
    """Force re-parse of one file (testing / manual repair). The on-disk
    file is authoritative; whatever is in DB gets superseded."""
    started = time.monotonic(); result = IndexResult()
    db = _db_url(database_url); repo_root = repo_root.resolve()
    rel = str(file_path.resolve().relative_to(repo_root))
    cfg = pick_extractor(rel, load_extractors())
    if cfg is None:
        result.errors.append(f"no extractor for {rel}"); return result
    repo = repo_root.name; head = _git_head(repo_root)
    nodes, edges = parse_file(file_path, rel, cfg, repo, head)
    old_n, old_e = _load_existing_for_path(db, repo, rel)
    diff = diff_file_index(old_n, old_e, nodes, edges)
    _apply_diff(db, diff)
    result.files_indexed = 1
    result.node_count = len(diff.insert_nodes); result.edge_count = len(diff.insert_edges)
    result.duration_seconds = time.monotonic() - started
    return result


# ─── Walk + git helpers ──────────────────────────────────────────────


def _filter_extractors(languages: list[str] | None) -> dict[str, ExtractorConfig]:
    all_ex = load_extractors()
    return all_ex if not languages else {k: v for k, v in all_ex.items() if k in set(languages)}


def _walk_repo(repo_root: Path, extractors: dict[str, ExtractorConfig]):
    skip = {".git", "__pycache__", "node_modules", "dist", "build"}
    for root, dirs, files in os.walk(repo_root):
        dirs[:] = [d for d in dirs if d not in skip and not d.startswith(".venv")]
        for fname in files:
            fp = Path(root) / fname
            rel = str(fp.relative_to(repo_root))
            cfg = pick_extractor(rel, extractors)
            if cfg is not None:
                yield fp, rel, cfg


def _git_head(repo_root: Path) -> str:
    r = subprocess.run(["git", "-C", str(repo_root), "rev-parse", "HEAD"],
                       capture_output=True, text=True, check=True)
    return r.stdout.strip()


def _git_diff_name_status(repo_root: Path, base: str, head: str):
    """Yield (status, rel_path). Status A/M/D/R/C/T; collapse R/C/T to M."""
    r = subprocess.run(
        ["git", "-C", str(repo_root), "diff", "--name-status", f"{base}..{head}"],
        capture_output=True, text=True, check=True)
    for line in r.stdout.splitlines():
        parts = line.split("\t")
        if parts:
            yield parts[0][:1], parts[-1]


def _diff_one_file(repo_root: Path, rel: str, status: str, cfg: ExtractorConfig,
                   repo: str, head: str, db: str) -> FileDiff:
    fp = repo_root / rel
    if status == "D":
        old_n, old_e = _load_existing_for_path(db, repo, rel)
        return close_file_index(old_n, old_e)
    if status == "A":
        nodes, edges = parse_file(fp, rel, cfg, repo, head)
        return replace_file_index(nodes, edges)
    nodes, edges = parse_file(fp, rel, cfg, repo, head)
    old_n, old_e = _load_existing_for_path(db, repo, rel)
    return diff_file_index(old_n, old_e, nodes, edges)


# ─── Postgres I/O (subprocess psql) ──────────────────────────────────


def _db_url(database_url: str | None) -> str:
    url = database_url or os.environ.get("DATABASE_URL", "")
    if not url:
        raise RuntimeError("DATABASE_URL not set and no --database-url passed")
    return url


def _psql(db: str, sql: str) -> str:
    r = subprocess.run(["psql", db, "-At", "-v", "ON_ERROR_STOP=1", "-c", sql],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"psql failed: {r.stderr.strip()}")
    return r.stdout


def _flush_inserts(db: str, nodes: list[dict], edges: list[dict]) -> None:
    parts = ["BEGIN;"]
    if nodes:
        parts.append(_nodes_sql(nodes))
    if edges:
        parts.append(_edges_sql(edges))
    parts.append("COMMIT;")
    _psql(db, "\n".join(parts))


def _nodes_sql(nodes: list[dict]) -> str:
    rows = [
        f"({_q(n['node_id'])}, {_q(n['type'])}, {_q(n.get('subtype'))}, "
        f"{_q(n['repo'])}, {_q(n['commit_sha'])}, {_q(n.get('path'))}, "
        f"{_q(n.get('name'))}, {_q(json.dumps(n.get('properties') or {}))}::jsonb)"
        for n in nodes
    ]
    return ("INSERT INTO spine_kg.kg_node (node_id, type, subtype, repo, commit_sha, "
            "path, name, properties) VALUES\n" + ",\n".join(rows) + "\n"
            "ON CONFLICT (node_id) DO NOTHING;")


def _edges_sql(edges: list[dict]) -> str:
    """Edges resolve `from`/`to` text node_ids → bigint ids via subquery."""
    rows = [
        f"((SELECT id FROM spine_kg.kg_node WHERE node_id = {_q(e['from_node_id'])} "
        f"AND valid_to IS NULL ORDER BY id DESC LIMIT 1), "
        f"(SELECT id FROM spine_kg.kg_node WHERE node_id = {_q(e['to_node_id'])} "
        f"AND valid_to IS NULL ORDER BY id DESC LIMIT 1), "
        f"{_q(e['type'])}, {_q(e['commit_sha'])}, "
        f"{_q(json.dumps(e.get('properties') or {}))}::jsonb)"
        for e in edges
    ]
    return ("INSERT INTO spine_kg.kg_edge (from_node_id, to_node_id, type, commit_sha, "
            "properties) SELECT * FROM (VALUES\n" + ",\n".join(rows) + "\n"
            ") AS v(from_node_id, to_node_id, type, commit_sha, properties) "
            "WHERE from_node_id IS NOT NULL AND to_node_id IS NOT NULL;")


def _apply_diff(db: str, diff: FileDiff) -> None:
    """Close superseded rows then insert new rows in one transaction."""
    parts = ["BEGIN;"]
    if diff.close_node_ids:
        ids = ",".join(_q(nid) for nid in diff.close_node_ids)
        parts.append(f"UPDATE spine_kg.kg_node SET valid_to = now() "
                     f"WHERE node_id IN ({ids}) AND valid_to IS NULL;")
    for src, tgt, typ in diff.close_edge_keys:
        parts.append(
            "UPDATE spine_kg.kg_edge SET valid_to = now() WHERE valid_to IS NULL "
            f"AND type = {_q(typ)} AND from_node_id = (SELECT id FROM spine_kg.kg_node "
            f"WHERE node_id = {_q(src)} ORDER BY id DESC LIMIT 1) "
            f"AND to_node_id = (SELECT id FROM spine_kg.kg_node "
            f"WHERE node_id = {_q(tgt)} ORDER BY id DESC LIMIT 1);")
    if diff.insert_nodes:
        parts.append(_nodes_sql(diff.insert_nodes))
    if diff.insert_edges:
        parts.append(_edges_sql(diff.insert_edges))
    parts.append("COMMIT;")
    _psql(db, "\n".join(parts))


def _load_existing_for_path(db: str, repo: str, rel: str) -> tuple[list[dict], list[dict]]:
    """Pull currently-valid nodes/edges anchored at this file path so
    diff_file_index has an old snapshot to compare against."""
    out = _psql(db,
        "SELECT node_id, type, subtype, repo, commit_sha, path, name, properties::text "
        f"FROM spine_kg.kg_node WHERE repo = {_q(repo)} AND path = {_q(rel)} "
        "AND valid_to IS NULL;")
    nodes: list[dict] = []
    for line in (l for l in out.splitlines() if l):
        f = line.split("|")
        if len(f) >= 8:
            nodes.append({"node_id": f[0], "type": f[1], "subtype": f[2] or None,
                          "repo": f[3], "commit_sha": f[4], "path": f[5] or None,
                          "name": f[6] or None, "properties": f[7]})
    node_ids = [n["node_id"] for n in nodes]
    if not node_ids:
        return nodes, []
    in_clause = ",".join(_q(nid) for nid in node_ids)
    out = _psql(db,
        "SELECT n_from.node_id, n_to.node_id, e.type, e.commit_sha, e.properties::text "
        "FROM spine_kg.kg_edge e "
        "JOIN spine_kg.kg_node n_from ON n_from.id = e.from_node_id "
        "JOIN spine_kg.kg_node n_to   ON n_to.id   = e.to_node_id "
        f"WHERE e.valid_to IS NULL AND n_from.node_id IN ({in_clause});")
    edges: list[dict] = []
    for line in (l for l in out.splitlines() if l):
        f = line.split("|")
        if len(f) >= 5:
            edges.append({"from_node_id": f[0], "to_node_id": f[1], "type": f[2],
                          "commit_sha": f[3], "properties": f[4]})
    return nodes, edges


def _read_last_commit(db: str, repo: str) -> str | None:
    out = _psql(db, f"SELECT last_indexed_commit_sha FROM spine_kg.kg_index_state "
                    f"WHERE repo = {_q(repo)};").strip()
    return out or None


def _upsert_index_state(db: str, repo: str, commit_sha: str,
                        node_delta: int, edge_delta: int) -> None:
    _psql(db, (
        "INSERT INTO spine_kg.kg_index_state "
        "(repo, last_indexed_commit_sha, last_indexed_at, node_count, edge_count) VALUES "
        f"({_q(repo)}, {_q(commit_sha)}, now(), {node_delta}, {edge_delta}) "
        "ON CONFLICT (repo) DO UPDATE SET "
        "last_indexed_commit_sha = EXCLUDED.last_indexed_commit_sha, "
        "last_indexed_at         = EXCLUDED.last_indexed_at, "
        "node_count              = spine_kg.kg_index_state.node_count + EXCLUDED.node_count, "
        "edge_count              = spine_kg.kg_index_state.edge_count + EXCLUDED.edge_count;"))


def _q(v: object) -> str:
    if v is None:
        return "NULL"
    s = str(v).replace("'", "''")
    return f"'{s}'"
