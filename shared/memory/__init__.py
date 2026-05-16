"""Spine vector-backed role memory — EPIC-4.2 (STORY-4.2.1/2/3).

Per-role lesson retrieval at directive time (project scope) plus cross-
project semantic recall from ``~/.spine-development/playbook/`` (cross
scope). Embeddings reuse :mod:`build.kg.embeddings.embedder` and the
``vector(768)`` shape from V2; persistence lives in the ``spine_memory``
schema (V20). See ``memory_README.md`` for the architecture diagram.
"""
from .lesson_store import (Lesson, LessonStore, RecallResult,
                           format_for_prompt_injection, recall_lessons)
from .lesson_indexer import IndexResult, LessonIndexer, index_role_memory
from .playbook_store import (PlaybookStore, playbook_recall,
                             promote_to_playbook)

__all__ = ["IndexResult", "Lesson", "LessonIndexer", "LessonStore",
           "PlaybookStore", "RecallResult", "format_for_prompt_injection",
           "index_role_memory", "playbook_recall", "promote_to_playbook",
           "recall_lessons"]
