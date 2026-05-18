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
from .writer_hooks import (EVENT_KEYS, LessonDraft, clear_hooks,
                           dispatch as dispatch_audit_event,
                           flush_pending as flush_pending_lessons,
                           register_hook as register_memory_hook,
                           _register_default_hooks)

# Wave 1 wiring (V3 #27): install the 7 canonical extractors at import.
# Idempotent; safe in tests (call ``clear_hooks`` to reset).
_register_default_hooks()

__all__ = ["EVENT_KEYS", "IndexResult", "Lesson", "LessonDraft",
           "LessonIndexer", "LessonStore", "PlaybookStore", "RecallResult",
           "clear_hooks", "dispatch_audit_event", "flush_pending_lessons",
           "format_for_prompt_injection", "index_role_memory",
           "playbook_recall", "promote_to_playbook",
           "recall_lessons", "register_memory_hook"]
