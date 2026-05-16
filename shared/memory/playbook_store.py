"""Cross-project playbook lessons — STORY-4.2.3.

Wraps :class:`shared.memory.lesson_store.LessonStore` for the cross-
project case. Reads ``~/.spine-development/playbook/<role>/lessons.md``
and indexes them with ``scope='cross_project'``. Recall is identical to
the project case but constrained to ``scope='cross_project'`` (no
project_id). A ``promote_to_playbook`` helper copies a project lesson
into the playbook directory and re-indexes that role's playbook file.

The on-disk playbook is the source of truth (so it is readable by humans
and shareable across machines); the DB is a derived index used at recall
time. ``promote`` is idempotent — re-promoting a lesson that already
exists in the file is a no-op.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from .lesson_indexer import LessonIndexer
from .lesson_store import DEFAULT_DB_URL, LessonStore, RecallResult, _psql

DEFAULT_PLAYBOOK_DIR = Path.home() / ".spine-development" / "playbook"
PLAYBOOK_FILENAME = "lessons.md"
PROMOTION_HEADING = "## Promoted from project memory"


def _playbook_path(role: str,
                   root: Optional[Path] = None) -> Path:
    return (root or DEFAULT_PLAYBOOK_DIR) / role / PLAYBOOK_FILENAME


# ─── Store ───────────────────────────────────────────────────────────


class PlaybookStore:
    """Cross-project recall + promote. Wraps LessonStore + LessonIndexer."""

    def __init__(self, db_url: Optional[str] = None,
                 playbook_root: Optional[Path] = None) -> None:
        self._db_url = (db_url or os.environ.get("SPINE_DB_URL")
                        or os.environ.get("DATABASE_URL") or DEFAULT_DB_URL)
        self._root = playbook_root or DEFAULT_PLAYBOOK_DIR
        self._store = LessonStore(db_url=self._db_url)
        self._indexer = LessonIndexer(db_url=self._db_url)
        self._indexed_roles: set[str] = set()

    # ---- recall -------------------------------------------------------

    def recall(self, role: str, query_text: str,
               top_k: int = 5) -> RecallResult:
        """Recall only cross_project lessons for ``role`` (no project ones)."""
        self._ensure_indexed(role)
        return self._store.recall(role=role, query_text=query_text,
                                  project_id=None, top_k=top_k,
                                  include_cross_project=True)

    def _ensure_indexed(self, role: str) -> None:
        """Index this role's playbook file once per process."""
        if role in self._indexed_roles:
            return
        path = _playbook_path(role, self._root)
        if path.exists():
            self._indexer.index(role=role, memory_path=path,
                                project_id=None, scope="cross_project")
        self._indexed_roles.add(role)

    def reindex(self, role: str) -> None:
        """Force re-index of a single role's playbook file."""
        self._indexed_roles.discard(role)
        self._ensure_indexed(role)

    # ---- promote ------------------------------------------------------

    def promote(self, lesson_id: int, rationale: str) -> Path:
        """Copy a project lesson into the role's playbook + re-index it.

        Idempotent — if the exact text already appears in the playbook
        file, it is not appended a second time.
        """
        row = _psql("SELECT role, lesson_text FROM spine_memory.lesson "
                    f"WHERE id = {int(lesson_id)} AND valid_to IS NULL;",
                    self._db_url).strip()
        if not row:
            raise ValueError(f"lesson_id {lesson_id} not found / superseded")
        role, text = row.split("\x1f", 1)
        path = _playbook_path(role, self._root)
        path.parent.mkdir(parents=True, exist_ok=True)
        prior = path.read_text(encoding="utf-8") if path.exists() else ""
        marker = f"- {text.strip()}"
        if marker in prior:
            self.reindex(role)
            return path
        # Append under a dedicated heading so origin is greppable.
        out_parts: list[str] = []
        if prior and not prior.endswith("\n"):
            out_parts.append("\n")
        if PROMOTION_HEADING not in prior:
            out_parts.append(f"\n{PROMOTION_HEADING}\n\n")
        rationale_clean = " ".join(rationale.split())
        out_parts.append(f"{marker}  <!-- {rationale_clean} -->\n")
        with path.open("a", encoding="utf-8") as fh:
            fh.write("".join(out_parts))
        self.reindex(role)
        return path


# ─── module-level convenience ────────────────────────────────────────


def playbook_recall(role: str, query_text: str, top_k: int = 5,
                    db_url: Optional[str] = None) -> RecallResult:
    return PlaybookStore(db_url=db_url).recall(role, query_text, top_k)


def promote_to_playbook(lesson_id: int, rationale: str,
                        db_url: Optional[str] = None,
                        playbook_root: Optional[Path] = None) -> Path:
    return PlaybookStore(db_url=db_url,
                         playbook_root=playbook_root).promote(lesson_id,
                                                              rationale)
