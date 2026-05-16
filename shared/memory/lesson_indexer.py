"""Parse ``memory.md`` → ``spine_memory.lesson`` rows — STORY-4.2.2.

Grammar: ``## <Heading>`` introduces a tag, each ``- <text>`` line is a
lesson tagged with the most-recent heading slug; indented continuations
fold onto the prior bullet. Idempotent via SHA-256 ``text_hash``; changed
or removed lessons use V20 supersede (``valid_to = now()``). Embeddings
are NOT computed here — lazy on first recall.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

DEFAULT_DB_URL = "postgresql://spine:spine@localhost:33000/spine"
_HEADING_RE = re.compile(r"^##\s+(.+?)\s*$")
_BULLET_RE = re.compile(r"^[-*]\s+(.+?)\s*$")
_CONT_RE = re.compile(r"^\s{2,}\S")


class IndexResult(BaseModel):
    role: str
    source_path: str
    lessons_added: int = Field(ge=0, default=0)
    lessons_updated: int = Field(ge=0, default=0)
    lessons_unchanged: int = Field(ge=0, default=0)


class ParsedLesson(BaseModel):
    text: str
    tags: list[str] = Field(default_factory=list)
    line: int


# ─── parsing ─────────────────────────────────────────────────────────


def _slug(heading: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", heading.strip().lower()).strip("-")


def parse_memory_md(path: Path) -> list[ParsedLesson]:
    """Parse a memory.md file into a flat list of ``ParsedLesson``."""
    if not path.exists():
        return []
    lessons: list[ParsedLesson] = []
    tag: Optional[str] = None
    cur: Optional[ParsedLesson] = None
    for i, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.rstrip()
        if not line.strip():
            if cur:
                lessons.append(cur); cur = None
            continue
        if (h := _HEADING_RE.match(line)):
            if cur:
                lessons.append(cur); cur = None
            tag = _slug(h.group(1)); continue
        if (b := _BULLET_RE.match(line)):
            if cur:
                lessons.append(cur)
            cur = ParsedLesson(text=b.group(1).strip(),
                               tags=[tag] if tag else [], line=i)
            continue
        if cur and _CONT_RE.match(line):
            cur.text = (cur.text + " " + line.strip()).strip()
    if cur:
        lessons.append(cur)
    return [l for l in lessons if l.text]


# ─── psql plumbing ───────────────────────────────────────────────────


def _q(v: object) -> str:
    return "NULL" if v is None else "'" + str(v).replace("'", "''") + "'"


def _pg_text_array(items: list[str]) -> str:
    return ("ARRAY[" + ",".join(_q(s) for s in items) + "]::text[]"
            if items else "ARRAY[]::text[]")


def _psql(sql: str, db_url: str) -> str:
    r = subprocess.run(["psql", db_url, "-At", "-F", "\x1f",
                        "-v", "ON_ERROR_STOP=1", "-c", sql],
                       capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError(f"psql failed: {r.stderr.strip()}")
    return r.stdout


class LessonIndexer:
    """Idempotent parser → ``spine_memory.lesson`` writer."""

    def __init__(self, db_url: Optional[str] = None) -> None:
        self._db_url = (db_url or os.environ.get("SPINE_DB_URL")
                        or os.environ.get("DATABASE_URL") or DEFAULT_DB_URL)

    def index(self, role: str, memory_path: Path,
              project_id: Optional[str] = None,
              scope: str = "project") -> IndexResult:
        """Parse + upsert lessons; never embed (lazy on recall)."""
        result = IndexResult(role=role, source_path=str(memory_path))
        existing = self._existing_hashes(role, scope, project_id)
        pid = "NULL" if project_id is None else str(int(project_id))
        pid_cmp = "IS NULL" if project_id is None else f"= {int(project_id)}"
        sp = str(memory_path)
        for p in parse_memory_md(memory_path):
            text = p.text.strip()
            th = hashlib.sha256(text.encode("utf-8")).hexdigest()
            if th in existing:
                result.lessons_unchanged += 1
                existing.pop(th, None); continue
            _psql("UPDATE spine_memory.lesson SET valid_to = now() WHERE "
                  f"role = {_q(role)} AND scope = {_q(scope)} AND project_id "
                  f"{pid_cmp} AND source_path = {_q(sp)} AND line_in_source "
                  f"= {int(p.line)} AND valid_to IS NULL;", self._db_url)
            _psql("INSERT INTO spine_memory.lesson (role, scope, project_id,"
                  " lesson_text, source_path, line_in_source, tags, text_hash"
                  f") VALUES ({_q(role)}, {_q(scope)}, {pid}, {_q(text)}, "
                  f"{_q(sp)}, {int(p.line)}, {_pg_text_array(p.tags)}, "
                  f"{_q(th)});", self._db_url)
            result.lessons_added += 1
        for th_lost in existing:  # vanished from source → supersede
            _psql("UPDATE spine_memory.lesson SET valid_to = now() WHERE "
                  f"text_hash = {_q(th_lost)} AND role = {_q(role)} AND "
                  f"scope = {_q(scope)} AND project_id {pid_cmp} AND "
                  "valid_to IS NULL;", self._db_url)
            result.lessons_updated += 1
        return result

    def _existing_hashes(self, role: str, scope: str,
                         project_id: Optional[str]) -> dict[str, int]:
        pid_cmp = "IS NULL" if project_id is None else f"= {int(project_id)}"
        out: dict[str, int] = {}
        rows = _psql("SELECT text_hash, id FROM spine_memory.lesson "
                     f"WHERE role = {_q(role)} AND scope = {_q(scope)} "
                     f"AND project_id {pid_cmp} AND valid_to IS NULL;",
                     self._db_url)
        for ln in (l for l in rows.splitlines() if l):
            parts = ln.split("\x1f")
            if len(parts) >= 2:
                try:
                    out[parts[0]] = int(parts[1])
                except ValueError:
                    pass
        return out


def index_role_memory(role: str, memory_md_path: Path,
                      project_id: Optional[str] = None,
                      scope: str = "project",
                      db_url: Optional[str] = None) -> IndexResult:
    """Module-level convenience wrapper around :class:`LessonIndexer`."""
    return LessonIndexer(db_url=db_url).index(role, memory_md_path,
                                              project_id, scope)


def _main() -> int:
    p = argparse.ArgumentParser(prog="lesson_indexer")
    p.add_argument("--role", required=True)
    p.add_argument("--memory-path", required=True, type=Path)
    p.add_argument("--project-id", default=None)
    p.add_argument("--scope", default="project",
                   choices=("project", "cross_project"))
    a = p.parse_args()
    print(index_role_memory(a.role, a.memory_path, a.project_id,
                            a.scope).model_dump_json(indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
