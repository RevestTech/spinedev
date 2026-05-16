"""Subtype-specific doc parsers — STORY-6.3.2 (REQ-INIT-6 FR-4).

Each ``parse_<type>`` builds on :func:`markdown_parser.parse_markdown`
and overlays doc-shape-specific child nodes/edges into ``custom_nodes``/
``custom_edges`` so the indexer flushes everything through one path.
REQ/PRD → Requirement (FR-N) + AcceptanceCriterion + PART_OF; TRD →
Requirement (NFR-N + FR-N); Roadmap → Initiative + Epic + Story with
PART_OF (status/priority/size in properties); ADR → SUPERSEDES edges
when the doc says "Supersedes ADR-N"; CHANGELOG → Release nodes. New
doc type: drop a ``parse_<type>`` here + extend :func:`parser_for_path`.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

from .markdown_parser import EdgeData, NodeData, ParsedDoc, parse_markdown
from .spine_id_resolver import extract_references, external_node_id

_ATX_ANY = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_FR_HEAD = re.compile(r"^#{2,4}\s+FR-(\d+(?:\.\d+)?)\s*[—\-:]\s*(.+?)\s*$")
_NFR_HEAD = re.compile(r"^#{2,4}\s+NFR-(\d+(?:\.\d+)?)\s*[—\-:]\s*(.+?)\s*$")
_CHECK_ITEM = re.compile(r"^\s*-\s*\[[ xX]\]\s+(.+)$")
# Roadmap bullet: `- \`STORY-6.3.1\` · \`Backlog\` · \`P0\` · \`M\` — text…`
_ROADMAP_BULLET = re.compile(
    r"^\s*-\s+`(?P<id>(?:STORY|EPIC|INIT)-[\d.]+)`"
    r"(?:\s*·\s*`(?P<status>[^`]+)`)?"
    r"(?:\s*·\s*`(?P<priority>P\d)`)?"
    r"(?:\s*·\s*`(?P<size>XS|S|M|L|XL)`)?"
    r"\s*[—\-:]\s*(?P<text>.*)$")
_INIT_HEAD = re.compile(r"^##\s+(INIT-\d+)\b\s*[—\-:]?\s*(.*)$")
_EPIC_HEAD = re.compile(r"^###\s+(EPIC-\d+\.\d+)\b\s*[—\-:]?\s*(.*)$")
_ADR_SUPERSEDES = re.compile(r"^##\s+Supersede", re.IGNORECASE)
_CHANGELOG_VER = re.compile(
    r"^##\s+\[?v?(?P<ver>\d+\.\d+(?:\.\d+)?(?:-[\w.]+)?)\]?"
    r"(?:\s*[—\-:]\s*(?P<date>\d{4}-\d{2}-\d{2}))?")


# ─── REQ / PRD / TRD ─────────────────────────────────────────────────

def parse_req(content: str, doc_path: str, **kw) -> ParsedDoc:
    """REQ doc → markdown + Requirement(FR-N) + AcceptanceCriterion."""
    doc = parse_markdown(content, doc_path, subtype="REQ", **kw)
    _attach_requirements(content, doc, "FR")
    _attach_acceptance(content, doc); return doc


def parse_prd(content: str, doc_path: str, **kw) -> ParsedDoc:
    """PRD is REQ-shaped — FR + NFR + acceptance lists."""
    doc = parse_markdown(content, doc_path, subtype="PRD", **kw)
    _attach_requirements(content, doc, "FR")
    _attach_requirements(content, doc, "NFR")
    _attach_acceptance(content, doc); return doc


def parse_trd(content: str, doc_path: str, **kw) -> ParsedDoc:
    """TRD: section headings already covered by markdown_parser; emit
    NFR-N + FR-N nodes so impact_radius can find them."""
    doc = parse_markdown(content, doc_path, subtype="TRD", **kw)
    _attach_requirements(content, doc, "NFR")
    _attach_requirements(content, doc, "FR"); return doc


def _attach_requirements(content: str, doc: ParsedDoc, kind: str) -> None:
    """``### FR-N — title`` (or NFR-N) → Requirement + PART_OF edge."""
    pat = _FR_HEAD if kind == "FR" else _NFR_HEAD
    did = doc.document_node.node_id; sha = doc.document_node.commit_sha
    for lineno, line in enumerate(content.splitlines(), start=1):
        m = pat.match(line)
        if not m: continue
        rid = f"{kind}-{m.group(1)}"; nid = f"{did}#req:{rid}"
        doc.custom_nodes.append(NodeData(
            node_id=nid, type="Requirement", subtype=kind,
            repo=doc.document_node.repo, commit_sha=sha,
            path=f"{doc.doc_path}:{lineno}", name=rid,
            properties={"title": m.group(2).strip(),
                        "line": str(lineno), "kind": kind}))
        doc.custom_edges.append(EdgeData(
            from_node_id=nid, to_node_id=did, type="PART_OF",
            commit_sha=sha, properties={"role": "requirement"}))


def _attach_acceptance(content: str, doc: ParsedDoc) -> None:
    """Checklist items under an 'Acceptance' heading → AcceptanceCriterion."""
    did = doc.document_node.node_id; sha = doc.document_node.commit_sha
    in_ac = False; idx = 0
    for lineno, line in enumerate(content.splitlines(), start=1):
        h = _ATX_ANY.match(line)
        if h:
            in_ac = "accept" in h.group(2).lower(); continue
        if not in_ac: continue
        m = _CHECK_ITEM.match(line)
        if not m: continue
        idx += 1; nid = f"{did}#ac:L{lineno}"
        doc.custom_nodes.append(NodeData(
            node_id=nid, type="AcceptanceCriterion",
            repo=doc.document_node.repo, commit_sha=sha,
            path=f"{doc.doc_path}:{lineno}", name=f"AC-{idx}",
            properties={"text": m.group(1).strip(), "line": str(lineno),
                        "checked": "true" if "[x]" in line.lower() else "false"}))
        doc.custom_edges.append(EdgeData(
            from_node_id=nid, to_node_id=did, type="PART_OF",
            commit_sha=sha, properties={"role": "acceptance"}))


# ─── Roadmap ─────────────────────────────────────────────────────────

def parse_roadmap(content: str, doc_path: str, **kw) -> ParsedDoc:
    """BACKLOG-style roadmap → Initiative + Epic + Story nodes wired
    PART_OF. Per-story status/priority/size go into properties. Bullet
    shape is documented in BACKLOG.md ID-scheme."""
    doc = parse_markdown(content, doc_path, subtype="Roadmap", **kw)
    repo = doc.document_node.repo; sha = doc.document_node.commit_sha
    init: str | None = None; epic: str | None = None
    for lineno, line in enumerate(content.splitlines(), start=1):
        im = _INIT_HEAD.match(line)
        if im:
            init = im.group(1); epic = None
            nid = f"spine:initiative:{init}"
            doc.custom_nodes.append(NodeData(
                node_id=nid, type="Initiative", repo=repo, commit_sha=sha,
                path=f"{doc_path}:{lineno}", name=init,
                properties={"title": im.group(2).strip(), "line": str(lineno)}))
            doc.custom_edges.append(EdgeData(
                from_node_id=nid, to_node_id=doc.document_node.node_id,
                type="DERIVED_FROM", commit_sha=sha, properties={}))
            continue
        em = _EPIC_HEAD.match(line)
        if em and init:
            epic = em.group(1); nid = f"spine:epic:{epic}"
            doc.custom_nodes.append(NodeData(
                node_id=nid, type="Epic", repo=repo, commit_sha=sha,
                path=f"{doc_path}:{lineno}", name=epic,
                properties={"title": em.group(2).strip(), "line": str(lineno)}))
            doc.custom_edges.append(EdgeData(
                from_node_id=nid, to_node_id=f"spine:initiative:{init}",
                type="PART_OF", commit_sha=sha, properties={}))
            continue
        bm = _ROADMAP_BULLET.match(line)
        if bm: _emit_story(bm, lineno, epic, init, doc)
    return doc


def _emit_story(bm: re.Match, lineno: int, epic: str | None,
                init: str | None, doc: ParsedDoc) -> None:
    """Roadmap bullet → typed node + PART_OF to enclosing Epic
    (fallback: Initiative → Document)."""
    sid = bm.group("id"); kind = sid.split("-", 1)[0]
    nt = {"STORY": "Story", "EPIC": "Epic",
          "INIT": "Initiative"}.get(kind, "Story")
    nid = f"spine:{nt.lower()}:{sid}"
    props: dict[str, str] = {"line": str(lineno),
                             "text": (bm.group("text") or "").strip()}
    for k in ("status", "priority", "size"):
        v = bm.group(k)
        if v: props[k] = v
    doc.custom_nodes.append(NodeData(
        node_id=nid, type=nt, repo=doc.document_node.repo,
        commit_sha=doc.document_node.commit_sha,
        path=f"{doc.doc_path}:{lineno}", name=sid, properties=props))
    parent = (f"spine:epic:{epic}" if epic
              else f"spine:initiative:{init}" if init
              else doc.document_node.node_id)
    doc.custom_edges.append(EdgeData(
        from_node_id=nid, to_node_id=parent, type="PART_OF",
        commit_sha=doc.document_node.commit_sha, properties={}))


# ─── ADR / CHANGELOG ─────────────────────────────────────────────────

def parse_adr(content: str, doc_path: str, **kw) -> ParsedDoc:
    """ADR. Decision/Status/Consequences come from markdown_parser
    headings; this adds SUPERSEDES when the doc declares
    ``## Supersedes ADR-N``."""
    doc = parse_markdown(content, doc_path, subtype="ADR", **kw)
    for lineno, line in enumerate(content.splitlines(), start=1):
        if not _ADR_SUPERSEDES.match(line): continue
        for r in extract_references(line, line_offset=lineno - 1):
            if r.id_kind != "adr": continue
            doc.custom_edges.append(EdgeData(
                from_node_id=doc.document_node.node_id,
                to_node_id=r.target_node_id or external_node_id(r.id_text),
                type="SUPERSEDES",
                commit_sha=doc.document_node.commit_sha,
                properties={"superseded_id": r.id_text,
                            "line": str(r.line_in_source)}))
    return doc


def parse_changelog(content: str, doc_path: str, **kw) -> ParsedDoc:
    """CHANGELOG. ``## vX.Y.Z — YYYY-MM-DD`` → Release DERIVED_FROM doc."""
    doc = parse_markdown(content, doc_path, subtype="CHANGELOG", **kw)
    repo = doc.document_node.repo; sha = doc.document_node.commit_sha
    for lineno, line in enumerate(content.splitlines(), start=1):
        m = _CHANGELOG_VER.match(line)
        if not m: continue
        ver = m.group("ver"); date = m.group("date") or ""
        nid = f"spine:release:{ver}"
        props: dict[str, str] = {"version": ver, "line": str(lineno)}
        if date: props["date"] = date
        doc.custom_nodes.append(NodeData(
            node_id=nid, type="Release", repo=repo, commit_sha=sha,
            path=f"{doc_path}:{lineno}", name=f"v{ver}", properties=props))
        doc.custom_edges.append(EdgeData(
            from_node_id=nid, to_node_id=doc.document_node.node_id,
            type="DERIVED_FROM", commit_sha=sha, properties={}))
    return doc


def parser_for_path(doc_path: str):
    """Path → parser dispatch. Used by the CLI ``reindex`` walker."""
    base = PurePosixPath(doc_path).name.lower(); low = doc_path.lower()
    if base == "backlog.md" or base.endswith("roadmap.md"): return parse_roadmap
    if base == "changelog.md": return parse_changelog
    if base.startswith("adr-") or "/adr/" in low or "/decisions/" in low: return parse_adr
    if base.startswith("trd-") or base == "trd.md": return parse_trd
    if base.startswith("prd-") or base == "prd.md": return parse_prd
    if base.startswith("req-") or "/reqs/" in low: return parse_req
    return parse_markdown
