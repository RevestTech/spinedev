"""Populate code_files / file_dependencies from a scan (proposal graph layer)."""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Dict, Optional, Set, Tuple
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from tron.domain.models import CodeFile, FileDependency
from tron.parsers.python import PythonParser

logger = logging.getLogger(__name__)


def _norm_path(p: str) -> str:
    return p.replace("\\", "/").lstrip("./")


_LT_INVALID_IN_LABEL = re.compile(r"[^A-Za-z0-9_]+")


def _directory_path_as_ltree(file_path_norm: str) -> Optional[str]:
    """
    Parent directory of ``file_path_norm`` as dot-separated ltree text.

    ``code_files.directory_path`` is indexed with ``CAST(directory_path AS ltree)``;
    slash-separated paths and many punctuation characters are invalid ltree syntax.
    """
    if "/" not in file_path_norm:
        return None
    dir_part = file_path_norm.rsplit("/", 1)[0]
    if not dir_part:
        return None
    labels: list[str] = []
    for raw in dir_part.split("/"):
        if raw == "":
            continue
        lab = _LT_INVALID_IN_LABEL.sub("_", raw)
        if lab == "" or not any(ch.isalnum() for ch in lab):
            lab = "x"
        labels.append(lab)
    if not labels:
        return None
    return ".".join(labels)


def _resolve_module(module: str, paths: Set[str]) -> Optional[str]:
    """Map Python module path to a file key present in paths."""
    parts = module.split(".")
    for i in range(len(parts), 0, -1):
        rel = "/".join(parts[:i])
        for cand in (f"{rel}.py", f"{rel}/__init__.py"):
            if cand in paths:
                return cand
        # nested package: a/b/c -> try suffix match on paths
        for p in paths:
            if p.endswith(f"/{rel}.py") or p.endswith(f"/{rel}/__init__.py"):
                return _norm_path(p)
    return None


async def sync_project_graph(
    session: AsyncSession,
    project_id: UUID,
    file_contents: Dict[str, str],
) -> Tuple[int, int]:
    """
    Replace graph data for a project with nodes/edges derived from this scan.

    Returns (node_count, edge_count).
    """
    if not file_contents:
        return 0, 0

    # Remove old edges then nodes for this project
    subq = select(CodeFile.id).where(CodeFile.project_id == project_id)
    await session.execute(
        delete(FileDependency).where(FileDependency.source_file_id.in_(subq))
    )
    await session.execute(delete(CodeFile).where(CodeFile.project_id == project_id))

    norm_map: Dict[str, str] = {_norm_path(k): k for k in file_contents}
    path_set = set(norm_map.keys())

    nodes: Dict[str, CodeFile] = {}
    for norm, original in norm_map.items():
        content = file_contents[original]
        h = hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()
        loc = len(content.splitlines())
        lang = "python" if norm.endswith(".py") else None
        cf = CodeFile(
            project_id=project_id,
            file_path=norm,
            file_hash=h,
            language=lang,
            file_type="source",
            lines_of_code=loc,
            directory_path=_directory_path_as_ltree(norm),
        )
        session.add(cf)
        nodes[norm] = cf

    await session.flush()

    id_by_path: Dict[str, UUID] = {norm: nodes[norm].id for norm in nodes}

    parser = PythonParser()
    edges = 0
    seen: Set[Tuple[UUID, UUID]] = set()
    for norm, original in norm_map.items():
        if not norm.endswith(".py"):
            continue
        src_id = id_by_path.get(norm)
        if not src_id:
            continue
        try:
            pr = parser.parse(file_contents[original], original)
        except SyntaxError:
            continue
        for imp in pr.imports:
            mod = (imp.module or "").strip()
            if imp.is_from and not mod:
                continue  # relative import
            if not mod:
                continue
            tgt_path = _resolve_module(mod, path_set)
            if not tgt_path:
                continue
            tgt_id = id_by_path.get(tgt_path)
            if not tgt_id or tgt_id == src_id:
                continue
            key = (src_id, tgt_id)
            if key in seen:
                continue
            seen.add(key)
            session.add(
                FileDependency(
                    source_file_id=src_id,
                    target_file_id=tgt_id,
                    dependency_type="import",
                    import_statement=f"{'from' if imp.is_from else 'import'}:{mod}",
                    is_external=False,
                )
            )
            edges += 1

    logger.info(
        "Graph sync project=%s nodes=%d edges=%d", project_id, len(nodes), edges
    )
    return len(nodes), edges
