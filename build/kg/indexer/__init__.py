"""Spine KG indexer — fills `spine_kg.kg_node` and `kg_edge` from the repo.

Implements STORY-6.4.1 / 6.4.2 / 6.4.3 (REQ-INIT-6 FR-5). See `indexer_README.md`
for algorithm, wiring, and performance targets.

Public surface kept intentionally small — wrappers compose into either the
`kg-index` CLI or the watcher daemon hook (no other entrypoints supported).
"""

from .indexer import IndexResult, cold_start_index, incremental_index, reindex_file

__all__ = ["IndexResult", "cold_start_index", "incremental_index", "reindex_file"]
