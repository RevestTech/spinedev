"""Spine-ID regex + KG node lookup — STORY-6.3.1 helper.

Detects embedded Spine identifiers (INIT-N / EPIC-N.M / STORY-N.M.K /
REQ-INIT-N / ADR-N / FR-N / FR-N.M) in doc text and resolves them to
``spine_kg.kg_node`` rows so emitted ``CITES`` edges anchor at real
nodes (REQ-INIT-6 FR-4). Alternation order in the combined pattern
matters: longest prefix first so ``REQ-INIT-N`` is not shadowed by
``INIT-N``. Unresolved refs return ``target_node_id=None``; callers may
emit a dangling edge against ``external_node_id`` for later
reconciliation. All DB I/O via subprocess ``psql`` (no psycopg dep).
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
from typing import Iterable

from pydantic import BaseModel, Field

log = logging.getLogger("spine.kg.doc_parser.spine_id_resolver")

SPINE_ID_PATTERNS: dict[str, re.Pattern[str]] = {
    "req_init": re.compile(r"\bREQ-INIT-(\d+)\b"),
    "story":    re.compile(r"\bSTORY-(\d+\.\d+\.\d+)\b"),
    "epic":     re.compile(r"\bEPIC-(\d+\.\d+)\b"),
    "init":     re.compile(r"\bINIT-(\d+)\b"),
    "adr":      re.compile(r"\bADR-(\d+)\b"),
    "epic_fr":  re.compile(r"\bFR-(\d+)\.(\d+)\b"),
    "fr":       re.compile(r"\bFR-(\d+)\b"),
}

_COMBINED = re.compile(
    r"\b(REQ-INIT-\d+|STORY-\d+\.\d+\.\d+|EPIC-\d+\.\d+|INIT-\d+"
    r"|ADR-\d+|FR-\d+\.\d+|FR-\d+)\b")

# Spine-flow KG taxonomy from V2__spine_kg_schema.sql.
_KIND_TO_TYPE = {"init": "Initiative", "epic": "Epic", "story": "Story",
                 "req_init": "Document", "adr": "Document",
                 "fr": "Requirement", "epic_fr": "Requirement"}


class ResolvedReference(BaseModel):
    """One Spine-ID match. ``target_node_id`` filled by
    :func:`resolve_references`; ``None`` until then."""
    id_text: str
    id_kind: str
    target_type: str
    target_node_id: str | None = None
    line_in_source: int = 0
    properties: dict[str, str] = Field(default_factory=dict)


def _classify(token: str) -> str:
    """Return ``id_kind`` slug. Regex order in SPINE_ID_PATTERNS guarantees
    the most specific kind wins (REQ-INIT before INIT, FR-N.M before FR-N)."""
    for kind, pat in SPINE_ID_PATTERNS.items():
        if pat.fullmatch(token):
            return kind
    return "unknown"


def extract_references(text: str, *, line_offset: int = 0) -> list[ResolvedReference]:
    """Find every Spine-ID occurrence in ``text``. ``line_offset`` lets
    callers parsing a snippet of a larger doc report absolute coords."""
    if not text:
        return []
    line_starts = [0]
    for i, ch in enumerate(text):
        if ch == "\n":
            line_starts.append(i + 1)
    out: list[ResolvedReference] = []
    for m in _COMBINED.finditer(text):
        token = m.group(1); kind = _classify(token)
        out.append(ResolvedReference(
            id_text=token, id_kind=kind,
            target_type=_KIND_TO_TYPE.get(kind, "Document"),
            line_in_source=_line_of(line_starts, m.start()) + line_offset))
    return _dedupe(out)


def _line_of(starts: list[int], offset: int) -> int:
    """Binary search ``offset`` in line-start table → 1-indexed line."""
    lo, hi = 0, len(starts) - 1
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if starts[mid] <= offset: lo = mid
        else: hi = mid - 1
    return lo + 1


def _dedupe(refs: Iterable[ResolvedReference]) -> list[ResolvedReference]:
    """One ref per (id_text, line) so a double-mention on one line does
    not inflate edge counts."""
    seen: set[tuple[str, int]] = set(); out: list[ResolvedReference] = []
    for r in refs:
        key = (r.id_text, r.line_in_source)
        if key in seen: continue
        seen.add(key); out.append(r)
    return out


def resolve_references(refs: list[ResolvedReference], *,
                       db_url: str | None = None) -> list[ResolvedReference]:
    """Look up each ref in ``spine_kg.kg_node``; populate
    ``target_node_id`` in place. Silent on failure — callers can then
    emit a dangling ``external_node_id`` edge for later reconciliation."""
    db = db_url or os.environ.get("DATABASE_URL", "")
    if not db or not refs:
        return refs
    unique = sorted({r.id_text for r in refs})
    quoted = ",".join("'" + s.replace("'", "''") + "'" for s in unique)
    sql = ("SELECT name, node_id FROM spine_kg.kg_node "
           f"WHERE name IN ({quoted}) AND valid_to IS NULL;")
    try:
        rows = subprocess.run(
            ["psql", db, "-At", "-F", "\t", "-v", "ON_ERROR_STOP=1", "-c", sql],
            capture_output=True, text=True, timeout=10, check=True).stdout
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
            FileNotFoundError) as e:
        log.warning("psql lookup failed (refs unresolved): %s", e)
        return refs
    by_name: dict[str, str] = {}
    for line in rows.splitlines():
        if "\t" in line:
            name, nid = line.split("\t", 1); by_name[name] = nid
    for r in refs:
        r.target_node_id = by_name.get(r.id_text)
    return refs


def external_node_id(id_text: str) -> str:
    """Synthetic ID for a Spine ref whose target node is not yet in the
    graph. Mirrors ``parser_runtime._external_id`` so follow-on indexing
    can repoint the edge when the real node lands."""
    return f"spine:external:{id_text.lower()}"
