"""Role-prompt + memory.md parser — STORY-6.3.3 (REQ-INIT-6 FR-4).

Three entrypoints, all built on :func:`markdown_parser.parse_markdown`:
:func:`parse_role_prompt` — captures role name + version + ``## You
may`` / ``## You may NOT`` blocks as ``Constraint`` nodes;
:func:`parse_memory_md` — each top-level bullet becomes a
``MemoryLesson`` node tagged with the last ``##`` section, with Spine
IDs inside the bullet emitted as ``TOUCHES`` edges (FR-7 memory
contract); :func:`parse_playbook` — same shape as memory_md but emits
``scope=cross_project`` so the KG query layer can filter.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

from .markdown_parser import EdgeData, NodeData, ParsedDoc, parse_markdown
from .spine_id_resolver import extract_references, external_node_id

_H1_ROLE = re.compile(r"^#\s+Role:\s*(.+?)\s*$", re.IGNORECASE)
_H2_ANY = re.compile(r"^##\s+(.+?)\s*$")
_VERSION_LINE = re.compile(r"version\s*[:=]\s*([0-9][\w.\-]*)", re.IGNORECASE)
_BULLET = re.compile(r"^\s*[-*]\s+(.+)$")
_AUTHORITY_HEADINGS = ("you may", "authority", "may not", "permissions",
                       "you may not", "constraints")
# Top-level bullet only — nested indented bullets roll into the parent
# lesson body so memory.md's "expand-the-thought" style survives.
_TOPLEVEL_BULLET = re.compile(r"^- (.+)$")


def parse_role_prompt(content: str, role_name: str | None = None,
                      prompt_path: str = "", **kw) -> ParsedDoc:
    """Parse a role-prompt markdown file. base markdown_parser already
    gives headings + LINKS_TO + CITES; this adds a ``Role`` node (name
    from H1 or path + version) plus ``Constraint`` nodes for
    ``## You may`` / ``## You may NOT`` / ``## Authority`` sections,
    OWNED_BY the role."""
    role_name = role_name or _infer_role_name(prompt_path)
    doc = parse_markdown(content, prompt_path, subtype="role-prompt", **kw)
    repo = doc.document_node.repo; sha = doc.document_node.commit_sha
    role_id = f"spine:role:{role_name.lower()}"
    version = _detect_version(content) or "unversioned"
    doc.custom_nodes.append(NodeData(
        node_id=role_id, type="Role", repo=repo, commit_sha=sha,
        path=prompt_path, name=role_name,
        properties={"version": version, "prompt_path": prompt_path}))
    doc.custom_edges.append(EdgeData(
        from_node_id=role_id, to_node_id=doc.document_node.node_id,
        type="DEFINES", commit_sha=sha, properties={"role": role_name}))
    _attach_constraints(content, doc, role_id)
    return doc


def _attach_constraints(content: str, doc: ParsedDoc, role_id: str) -> None:
    """Walk H2 sections; the bullets directly under an authority-flavored
    heading become Constraint nodes OWNED_BY the role."""
    sha = doc.document_node.commit_sha; repo = doc.document_node.repo
    in_section: str | None = None; idx = 0
    for lineno, line in enumerate(content.splitlines(), start=1):
        h = _H2_ANY.match(line)
        if h:
            title = h.group(1).strip().lower()
            in_section = title if any(k in title for k in _AUTHORITY_HEADINGS) else None
            continue
        if not in_section:
            continue
        bm = _BULLET.match(line)
        if not bm:
            continue
        idx += 1; text = bm.group(1).strip()
        polarity = "deny" if "not" in in_section else "allow"
        nid = f"{role_id}#constraint:L{lineno}"
        doc.custom_nodes.append(NodeData(
            node_id=nid, type="Constraint", subtype=polarity, repo=repo,
            commit_sha=sha, path=f"{doc.doc_path}:{lineno}",
            name=f"C-{idx}", properties={"text": text, "line": str(lineno),
                                         "section": in_section,
                                         "polarity": polarity}))
        doc.custom_edges.append(EdgeData(
            from_node_id=role_id, to_node_id=nid, type="OWNED_BY",
            commit_sha=sha, properties={"role": "constraint"}))


def parse_memory_md(content: str, role_name: str, project_id: str | None = None,
                    memory_path: str = "", **kw) -> ParsedDoc:
    """memory.md → MemoryLesson per top-level bullet, tagged with the
    most recent ``##`` heading. Spine IDs inside the bullet become
    TOUCHES edges (FR-7 contract: lessons surface when their referenced
    regions are queried)."""
    doc = parse_markdown(content, memory_path, subtype="memory", **kw)
    _attach_lessons(content, doc, role_name, project_id, scope="project")
    return doc


def parse_playbook(content: str, role_name: str,
                   playbook_path: str = "", **kw) -> ParsedDoc:
    """Same shape as :func:`parse_memory_md` but emits
    ``scope=cross_project`` so the query layer can prefer/exclude."""
    doc = parse_markdown(content, playbook_path, subtype="playbook", **kw)
    _attach_lessons(content, doc, role_name, None, scope="cross_project")
    return doc


def _attach_lessons(content: str, doc: ParsedDoc, role_name: str,
                    project_id: str | None, scope: str) -> None:
    """Walk lines; emit one MemoryLesson per top-level bullet. The
    section context (last seen H2) flows into a ``topic`` property so
    consumers can filter by topic without re-reading the file."""
    sha = doc.document_node.commit_sha; repo = doc.document_node.repo
    section: str = ""; lesson_idx = 0
    role_id = f"spine:role:{role_name.lower()}"
    for lineno, line in enumerate(content.splitlines(), start=1):
        h = _H2_ANY.match(line)
        if h:
            section = h.group(1).strip(); continue
        bm = _TOPLEVEL_BULLET.match(line)
        if not bm:
            continue
        lesson_idx += 1; body = bm.group(1).strip()
        lesson_id = (f"spine:memorylesson:{role_name.lower()}:"
                     f"{project_id or 'cross'}:{lesson_idx}")
        props = {"text": body, "topic": section, "line": str(lineno),
                 "scope": scope, "role": role_name}
        if project_id:
            props["project_id"] = project_id
        doc.custom_nodes.append(NodeData(
            node_id=lesson_id, type="MemoryLesson", subtype=scope,
            repo=repo, commit_sha=sha,
            path=f"{doc.doc_path}:{lineno}",
            name=f"lesson-{role_name}-{lesson_idx}", properties=props))
        # OWNED_BY the role; PART_OF the memory doc.
        doc.custom_edges.append(EdgeData(
            from_node_id=lesson_id, to_node_id=role_id, type="OWNED_BY",
            commit_sha=sha, properties={"scope": scope}))
        doc.custom_edges.append(EdgeData(
            from_node_id=lesson_id, to_node_id=doc.document_node.node_id,
            type="PART_OF", commit_sha=sha, properties={"role": "lesson"}))
        # TOUCHES — anything the lesson body mentions by Spine ID.
        for r in extract_references(body, line_offset=lineno - 1):
            target = r.target_node_id or external_node_id(r.id_text)
            doc.custom_edges.append(EdgeData(
                from_node_id=lesson_id, to_node_id=target,
                type="TOUCHES", commit_sha=sha,
                properties={"via_id": r.id_text, "kind": r.id_kind}))


def _infer_role_name(prompt_path: str) -> str:
    """``lib/role-prompts/architect.md`` → ``architect``. Fallback:
    parent directory (for ``teams/<role>/memory.md`` reuse)."""
    if not prompt_path: return "unknown"
    p = PurePosixPath(prompt_path); stem = p.stem
    if stem in ("memory", "lessons", "playbook"):
        return p.parent.name or "unknown"
    return stem or "unknown"


def _detect_version(content: str) -> str | None:
    """First ``version: X.Y`` token in the first 50 lines; or H1
    ``# Role: architect (v2)``; ``None`` otherwise."""
    for line in content.splitlines()[:50]:
        m = _VERSION_LINE.search(line)
        if m: return m.group(1)
    for line in content.splitlines()[:5]:
        h = _H1_ROLE.match(line)
        if h and "(" in h.group(1):
            inside = h.group(1).split("(", 1)[1].rstrip(")")
            if inside.startswith("v"): return inside[1:]
    return None
