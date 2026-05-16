"""Generic markdown → KG nodes/edges — STORY-6.3.1 (REQ-INIT-6 FR-4).

Parallels ``build/kg/indexer/parser_runtime.py`` (code AST → KG). Walks
markdown line-by-line (regex; no third-party markdown lib) and produces:

  * one ``Document`` root node (subtype inferred from path/content)
  * one ``Heading`` node per ATX heading (#…######) with level + line
  * one ``LINKS_TO`` edge per inline link ``[text](url)``
  * one ``CITES`` edge per embedded Spine ID, via ``spine_id_resolver``
  * doc-subtype-specific child nodes appended by spine_doc_parser /
    role_prompt_parser (passed through ``custom_nodes`` list)

Output shape is intentionally identical to ``parser_runtime`` so the
indexer can flush either parser's output through the same psql INSERT
path. Schema reference: ``db/flyway/sql/V2__spine_kg_schema.sql``.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any

from pydantic import BaseModel, Field

from .spine_id_resolver import (ResolvedReference, extract_references,
                                external_node_id)

# ─── Output models — mirror parser_runtime dict shape ────────────────


class NodeData(BaseModel):
    """One ``spine_kg.kg_node`` row payload."""
    node_id: str
    type: str
    subtype: str | None = None
    repo: str
    commit_sha: str | None = None
    path: str
    name: str
    properties: dict[str, Any] = Field(default_factory=dict)


class EdgeData(BaseModel):
    """One ``spine_kg.kg_edge`` row payload. ``from_node_id`` /
    ``to_node_id`` are external IDs; indexer resolves to bigint PKs at
    INSERT time (same as code edges)."""
    from_node_id: str
    to_node_id: str
    type: str
    commit_sha: str | None = None
    properties: dict[str, Any] = Field(default_factory=dict)


class ParsedDoc(BaseModel):
    """Bundle returned by every doc parser."""
    document_node: NodeData
    headings: list[NodeData] = Field(default_factory=list)
    links: list[EdgeData] = Field(default_factory=list)
    references: list[EdgeData] = Field(default_factory=list)
    custom_nodes: list[NodeData] = Field(default_factory=list)
    custom_edges: list[EdgeData] = Field(default_factory=list)
    extracted_at: datetime
    doc_path: str
    text_hash: str

    @property
    def all_nodes(self) -> list[NodeData]:
        return [self.document_node, *self.headings, *self.custom_nodes]

    @property
    def all_edges(self) -> list[EdgeData]:
        return [*self.links, *self.references, *self.custom_edges]


# ─── Line-oriented regex parser ──────────────────────────────────────

# Markdown is mostly line-oriented; a few well-targeted regexes get us
# ≥95% recall on heading/link extraction. Block-level structures (code
# fences, HTML blocks) are detected and skipped so we don't emit
# spurious headings or links from inside a code sample.

_ATX = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")
_HTML_BLOCK_OPEN = re.compile(r"^\s*<(script|style|pre)\b", re.IGNORECASE)
_HTML_BLOCK_CLOSE = re.compile(r"</(script|style|pre)\s*>", re.IGNORECASE)
_INLINE_LINK = re.compile(r"\[([^\]\n]+)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_REF_DEF = re.compile(r"^\s*\[([^\]]+)\]:\s*(\S+)")

_SUBTYPE_BY_BASENAME = {
    "readme.md": "README", "changelog.md": "CHANGELOG",
    "backlog.md": "Roadmap", "prd.md": "PRD", "trd.md": "TRD",
    "requirements.md": "REQ", "memory.md": "memory",
}
_SUBTYPE_BY_PREFIX = {"req-": "REQ", "adr-": "ADR", "prd-": "PRD",
                      "trd-": "TRD", "rfc-": "RFC"}


def parse_markdown(content: str, doc_path: str, *, repo: str = "spine",
                   commit_sha: str | None = None,
                   subtype: str | None = None) -> ParsedDoc:
    """Parse any markdown file → :class:`ParsedDoc`.

    The optional ``subtype`` lets callers (spine_doc_parser) override
    the path-based inference (e.g., the file is named ``ADR-7.md`` and
    the caller already knows it's an ADR)."""
    text_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
    subtype = subtype or _infer_subtype(doc_path)
    doc_name = PurePosixPath(doc_path).name
    doc_id = _doc_id(repo, doc_path)
    doc_node = NodeData(
        node_id=doc_id, type="Document", subtype=subtype, repo=repo,
        commit_sha=commit_sha, path=doc_path, name=doc_name,
        properties={"text_hash": text_hash, "lines": str(len(content.splitlines()))})

    headings, links, refs = _walk(content, doc_id, repo, commit_sha)
    return ParsedDoc(
        document_node=doc_node, headings=headings, links=links,
        references=refs,
        extracted_at=datetime.now(timezone.utc),
        doc_path=doc_path, text_hash=text_hash)


# ─── Walk ────────────────────────────────────────────────────────────


def _walk(content: str, doc_id: str, repo: str,
          commit_sha: str | None) -> tuple[list[NodeData], list[EdgeData],
                                           list[EdgeData]]:
    """Single linear pass: emit Heading nodes, LINKS_TO edges, and the
    inline-text accumulator that feeds spine_id_resolver."""
    headings: list[NodeData] = []
    links: list[EdgeData] = []
    inline_buffer: list[tuple[int, str]] = []
    in_fence = False; in_html_block = False
    for lineno, line in enumerate(content.splitlines(), start=1):
        if _FENCE.match(line):
            in_fence = not in_fence; continue
        if in_fence:
            continue
        if in_html_block:
            if _HTML_BLOCK_CLOSE.search(line):
                in_html_block = False
            continue
        if _HTML_BLOCK_OPEN.match(line):
            in_html_block = True; continue
        m = _ATX.match(line)
        if m:
            level = len(m.group(1)); text = m.group(2).strip()
            headings.append(_heading_node(doc_id, repo, commit_sha,
                                          level, text, lineno))
            inline_buffer.append((lineno, text)); continue
        # Reference-style link definitions become LINKS_TO too.
        rd = _REF_DEF.match(line)
        if rd:
            links.append(_link_edge(doc_id, commit_sha,
                                    rd.group(1), rd.group(2), lineno))
        for lm in _INLINE_LINK.finditer(line):
            links.append(_link_edge(doc_id, commit_sha,
                                    lm.group(1), lm.group(2), lineno))
        inline_buffer.append((lineno, line))
    refs = _references_from_buffer(inline_buffer, doc_id, commit_sha)
    return headings, links, refs


def _references_from_buffer(buf: list[tuple[int, str]], doc_id: str,
                            commit_sha: str | None) -> list[EdgeData]:
    """Run spine_id_resolver on the accumulated inline text. Each match
    becomes one CITES edge; targets that aren't (yet) in the KG point at
    a synthetic ``external_node_id`` so the edge isn't lost."""
    if not buf:
        return []
    # Join with newlines so the resolver's line numbers stay correct.
    joined = "\n".join(line for _, line in buf)
    first_lineno = buf[0][0]
    refs: list[ResolvedReference] = extract_references(
        joined, line_offset=first_lineno - 1)
    edges: list[EdgeData] = []
    for r in refs:
        target = r.target_node_id or external_node_id(r.id_text)
        edges.append(EdgeData(
            from_node_id=doc_id, to_node_id=target, type="CITES",
            commit_sha=commit_sha,
            properties={"cited_id": r.id_text, "kind": r.id_kind,
                        "line": str(r.line_in_source),
                        "target_type": r.target_type}))
    return edges


# ─── Builders / helpers ──────────────────────────────────────────────


def _heading_node(doc_id: str, repo: str, commit_sha: str | None,
                  level: int, text: str, lineno: int) -> NodeData:
    return NodeData(
        node_id=f"{doc_id}#heading:L{lineno}",
        type="Heading", subtype=f"H{level}",
        repo=repo, commit_sha=commit_sha,
        path=f"{doc_id.split(':', 2)[-1]}:{lineno}",
        name=text,
        properties={"level": str(level), "line": str(lineno),
                    "text": text})


def _link_edge(doc_id: str, commit_sha: str | None, text: str, url: str,
               lineno: int) -> EdgeData:
    return EdgeData(
        from_node_id=doc_id,
        to_node_id=_link_target_id(url),
        type="LINKS_TO", commit_sha=commit_sha,
        properties={"anchor_text": text, "url": url, "line": str(lineno)})


def _link_target_id(url: str) -> str:
    """Internal links (``./foo.md``, ``#anchor``) resolve to doc IDs in
    a follow-up pass; for now everything becomes a deterministic
    external ID so edges are insertable."""
    if url.startswith("#"):
        return f"spine:external:anchor:{url[1:]}"
    if url.startswith(("http://", "https://", "mailto:")):
        return f"spine:external:url:{url}"
    # Relative path → strip anchor, normalize.
    bare = url.split("#", 1)[0]
    return f"spine:external:doc:{bare}"


def _doc_id(repo: str, doc_path: str) -> str:
    return f"markdown:document:{repo}:{doc_path}"


def _infer_subtype(doc_path: str) -> str | None:
    """Path heuristics matching markdown.yaml's ``__infer_from_path__``.
    Order: basename hit → filename prefix → directory hint → None."""
    p = PurePosixPath(doc_path)
    base = p.name.lower()
    if base in _SUBTYPE_BY_BASENAME:
        return _SUBTYPE_BY_BASENAME[base]
    low = base.lower()
    for prefix, st in _SUBTYPE_BY_PREFIX.items():
        if low.startswith(prefix):
            return st
    parts = [s.lower() for s in p.parts]
    if "role-prompts" in parts or "role_prompts" in parts:
        return "role-prompt"
    if "playbook" in parts:
        return "playbook"
    if "reqs" in parts or "requirements" in parts:
        return "REQ"
    if "adr" in parts or "decisions" in parts:
        return "ADR"
    return None
