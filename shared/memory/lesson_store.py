"""Lesson store + recall — STORY-4.2.2 / STORY-4.2.3.

Vector-backed per-role lesson retrieval over ``spine_memory.lesson`` (V20).
Embeddings are lazy: on first ``recall_lessons`` call, any rows still
missing an embedding are populated through
:class:`build.kg.embeddings.embedder.EmbedderRunner` (the same provider
pipeline used by spine_kg). Cosine search uses pgvector's ``<=>``.

DB I/O is ``subprocess psql`` (no psycopg), matching the rest of Spine.
"""
from __future__ import annotations

import os
import subprocess
import time
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from build.kg.embeddings.embedder import (EmbedderRunner, SCHEMA_DIMENSIONS,
                                          select_provider)

DEFAULT_DB_URL = "postgresql://spine:spine@localhost:33000/spine"
CROSS_PROJECT_PENALTY = 0.85  # project lessons preferred on ties
DEFAULT_TOP_K = 5


# ─── Models ──────────────────────────────────────────────────────────


class Lesson(BaseModel):
    """One lesson row returned to a caller. Distance is cosine (lower=better)."""
    model_config = ConfigDict(frozen=False)
    id: int
    lesson_uuid: str
    role: str
    scope: str
    project_id: Optional[int] = None
    lesson_text: str
    source_path: str
    tags: list[str] = Field(default_factory=list)
    distance: float = Field(ge=0.0)


class RecallResult(BaseModel):
    """Outcome of one ``recall_lessons`` call — for prompt injection + telemetry."""
    lessons: list[Lesson]
    query: str
    latency_ms: float = Field(ge=0.0)
    cache_hits: int = Field(ge=0)
    embeddings_generated: int = Field(ge=0)


# ─── psql helpers ────────────────────────────────────────────────────


def _q(v: object) -> str:
    return "NULL" if v is None else "'" + str(v).replace("'", "''") + "'"


def _vec_literal(vec: list[float]) -> str:
    return "[" + ",".join(f"{float(x):.6f}" for x in vec) + "]"


def _fit_dim(vec: list[float]) -> list[float]:
    n = len(vec)
    if n == SCHEMA_DIMENSIONS:
        return vec
    if n < SCHEMA_DIMENSIONS:
        return vec + [0.0] * (SCHEMA_DIMENSIONS - n)
    return vec[:SCHEMA_DIMENSIONS]


def _psql(sql: str, db_url: str) -> str:
    r = subprocess.run(["psql", db_url, "-At", "-F", "\x1f",
                        "-v", "ON_ERROR_STOP=1", "-c", sql],
                       capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError(f"psql failed: {r.stderr.strip()}")
    return r.stdout


# ─── LessonStore — recall API ────────────────────────────────────────


class LessonStore:
    """Per-role lesson recall over ``spine_memory.lesson`` with lazy embed."""

    def __init__(self, db_url: Optional[str] = None,
                 runner: Optional[EmbedderRunner] = None) -> None:
        self._db_url = (db_url or os.environ.get("SPINE_DB_URL")
                        or os.environ.get("DATABASE_URL") or DEFAULT_DB_URL)
        # EmbedderRunner needs a DB URL too — we share ours.
        self._runner = runner or EmbedderRunner(select_provider(), self._db_url)

    # ---- public --------------------------------------------------------

    def recall(self, role: str, query_text: str,
               project_id: Optional[str] = None,
               top_k: int = DEFAULT_TOP_K,
               include_cross_project: bool = True) -> RecallResult:
        """Return top-K lessons by cosine distance to ``query_text``."""
        t0 = time.perf_counter()
        backfilled = self._lazy_embed_missing(role, project_id, include_cross_project)
        q_vec = _fit_dim(self._runner.provider.embed_one(query_text))
        rows = self._cosine_search(role, q_vec, project_id, top_k,
                                   include_cross_project)
        lessons = [Lesson(**r) for r in rows]
        ids = [l.id for l in lessons]
        self._touch_retrieval(ids)
        self._log_retrieval(role, project_id, query_text, ids, top_k)
        return RecallResult(lessons=lessons, query=query_text,
                            latency_ms=(time.perf_counter() - t0) * 1000.0,
                            cache_hits=len(lessons),
                            embeddings_generated=backfilled)

    # ---- internals -----------------------------------------------------

    def _lazy_embed_missing(self, role: str, project_id: Optional[str],
                            include_cross: bool) -> int:
        """Embed any in-scope lessons whose embedding column is still NULL."""
        scope_clause = self._scope_clause(project_id, include_cross)
        sql = ("SELECT id, lesson_text FROM spine_memory.lesson "
               f"WHERE role = {_q(role)} AND valid_to IS NULL "
               f"AND embedding IS NULL AND ({scope_clause});")
        out = _psql(sql, self._db_url)
        n = 0
        for ln in (l for l in out.splitlines() if l):
            parts = ln.split("\x1f")
            if len(parts) < 2:
                continue
            try:
                lid = int(parts[0])
            except ValueError:
                continue
            vec = _fit_dim(self._runner.provider.embed_one(parts[1]))
            _psql("UPDATE spine_memory.lesson SET embedding = "
                  f"{_q(_vec_literal(vec))}::vector WHERE id = {lid};",
                  self._db_url)
            n += 1
        return n

    def _cosine_search(self, role: str, q_vec: list[float],
                       project_id: Optional[str], top_k: int,
                       include_cross: bool) -> list[dict]:
        """Score project + cross_project lessons; cross gets ``CROSS_PROJECT_PENALTY``."""
        qv = _q(_vec_literal(q_vec))
        scope_clause = self._scope_clause(project_id, include_cross)
        # Multiply cross-project distance by 1/penalty (= 1/0.85) so its
        # "effective distance" is higher, i.e. project wins ties.
        inv = 1.0 / CROSS_PROJECT_PENALTY
        sql = (
            "SELECT id, lesson_uuid::text, role, scope, project_id, "
            "lesson_text, source_path, tags, "
            f"(CASE WHEN scope = 'cross_project' THEN {inv:.4f} ELSE 1.0 END) "
            f"* (embedding <=> {qv}::vector) AS d "
            "FROM spine_memory.lesson "
            f"WHERE role = {_q(role)} AND valid_to IS NULL "
            f"AND embedding IS NOT NULL AND ({scope_clause}) "
            f"ORDER BY d ASC LIMIT {int(top_k)};")
        out = _psql(sql, self._db_url)
        rows: list[dict] = []
        for ln in (l for l in out.splitlines() if l):
            parts = ln.split("\x1f")
            if len(parts) < 9:
                continue
            try:
                rows.append({
                    "id": int(parts[0]),
                    "lesson_uuid": parts[1],
                    "role": parts[2],
                    "scope": parts[3],
                    "project_id": int(parts[4]) if parts[4] else None,
                    "lesson_text": parts[5],
                    "source_path": parts[6],
                    "tags": _parse_pg_array(parts[7]),
                    "distance": float(parts[8]),
                })
            except (ValueError, IndexError):
                continue
        return rows

    @staticmethod
    def _scope_clause(project_id: Optional[str], include_cross: bool) -> str:
        parts: list[str] = []
        if project_id is not None:
            parts.append(f"(scope = 'project' AND project_id = {int(project_id)})")
        if include_cross:
            parts.append("scope = 'cross_project'")
        return " OR ".join(parts) if parts else "FALSE"

    def _touch_retrieval(self, lesson_ids: list[int]) -> None:
        if not lesson_ids:
            return
        ids = ",".join(str(int(i)) for i in lesson_ids)
        _psql("UPDATE spine_memory.lesson SET last_retrieved = now(), "
              f"retrieval_count = retrieval_count + 1 WHERE id IN ({ids});",
              self._db_url)

    def _log_retrieval(self, role: str, project_id: Optional[str],
                       query: str, lesson_ids: list[int], top_k: int) -> None:
        arr = "ARRAY[" + ",".join(str(int(i)) for i in lesson_ids) + "]::bigint[]" \
              if lesson_ids else "ARRAY[]::bigint[]"
        pid = "NULL" if project_id is None else str(int(project_id))
        _psql("INSERT INTO spine_memory.retrieval_log "
              "(role, project_id, query_text, lessons_returned, top_k) "
              f"VALUES ({_q(role)}, {pid}, {_q(query)}, {arr}, {int(top_k)});",
              self._db_url)


# ─── Helpers ─────────────────────────────────────────────────────────


def _parse_pg_array(raw: str) -> list[str]:
    """Parse Postgres text-array ``{a,b,c}`` (no embedded quotes/commas)."""
    if not raw or raw in ("{}", ""):
        return []
    inner = raw.strip()
    if inner.startswith("{") and inner.endswith("}"):
        inner = inner[1:-1]
    return [p.strip().strip('"') for p in inner.split(",") if p.strip()]


def recall_lessons(role: str, query_text: str,
                   project_id: Optional[str] = None,
                   top_k: int = DEFAULT_TOP_K,
                   include_cross_project: bool = True,
                   db_url: Optional[str] = None) -> RecallResult:
    """Module-level convenience wrapper around :class:`LessonStore`."""
    return LessonStore(db_url=db_url).recall(
        role, query_text, project_id, top_k, include_cross_project)


def format_for_prompt_injection(lessons: list[Lesson],
                                max_chars: int = 2000) -> str:
    """Render lessons as bullet markdown for direct paste into a role prompt."""
    if not lessons:
        return "## Relevant prior lessons\n\n_(none)_\n"
    out = ["## Relevant prior lessons", ""]
    used = sum(len(s) + 1 for s in out)
    for l in lessons:
        scope_tag = "[playbook]" if l.scope == "cross_project" else "[project]"
        tag_str = (" `" + ",".join(l.tags) + "`") if l.tags else ""
        line = f"- {scope_tag} {l.lesson_text}{tag_str}"
        if used + len(line) + 1 > max_chars:
            out.append("- _… (truncated; raise max_chars to see more)_")
            break
        out.append(line)
        used += len(line) + 1
    return "\n".join(out) + "\n"
