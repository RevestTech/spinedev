"""Spine KG document parser — EPIC-6.3 (STORY-6.3.1 / 6.3.2 / 6.3.3).

Parallel to ``parser_runtime`` (which handles code AST). Walks markdown
docs and emits ``Document`` / ``Heading`` / ``Reference`` / ``MemoryLesson``
nodes plus ``LINKS_TO`` / ``CITES`` / ``SUPERSEDES`` / ``DECIDED_BY`` /
``PART_OF`` edges into ``spine_kg.kg_node`` and ``spine_kg.kg_edge`` (V2).
See ``doc_parser_README.md``.
"""

from .markdown_parser import EdgeData, NodeData, ParsedDoc, parse_markdown
from .role_prompt_parser import parse_memory_md, parse_playbook, parse_role_prompt
from .spine_doc_parser import (parse_adr, parse_changelog, parse_prd, parse_req,
                               parse_roadmap, parse_trd)
from .spine_id_resolver import (ResolvedReference, extract_references,
                                resolve_references)

__all__ = ["EdgeData", "NodeData", "ParsedDoc", "ResolvedReference",
           "extract_references", "parse_adr", "parse_changelog", "parse_markdown",
           "parse_memory_md", "parse_playbook", "parse_prd", "parse_req",
           "parse_roadmap", "parse_role_prompt", "parse_trd", "resolve_references"]
