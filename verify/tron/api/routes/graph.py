"""Code / dependency graph API (proposal: graph analytics)."""

from __future__ import annotations

import re
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from tron.api.middleware.auth import require_api_key
from tron.api.middleware.scopes import enforce_api_key_route_scope
from tron.domain.models import CodeFile, FileDependency, Project, Standard
from tron.infra.db.session import get_session
from tron.services.graph_analytics import SimpleEdge, impact_transitive_dependents, transitive_dependencies

router = APIRouter(
    dependencies=[
        Depends(require_api_key),
        Depends(enforce_api_key_route_scope),
    ]
)


class CodeFileNode(BaseModel):
    id: UUID
    file_path: str
    language: Optional[str]
    lines_of_code: Optional[int]
    dependency_count: int
    dependent_count: int


class DependencyEdge(BaseModel):
    source_path: str
    target_path: str
    dependency_type: str
    import_statement: Optional[str]
    is_external: bool
    is_circular: bool


class ProjectGraphResponse(BaseModel):
    project_id: UUID
    nodes: list[CodeFileNode]
    edges: list[DependencyEdge]
    total_nodes: int
    total_edges: int


@router.get("/projects/{project_id}/graph", response_model=ProjectGraphResponse)
async def get_project_graph(
    project_id: UUID,
    limit_nodes: int = Query(500, ge=1, le=5000),
    session: AsyncSession = Depends(get_session),
):
    """Return code_files nodes and import edges for a project (populated on audit)."""
    pres = await session.execute(
        select(Project).where(Project.id == project_id, Project.deleted_at.is_(None))
    )
    if not pres.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Project not found")

    nres = await session.execute(
        select(CodeFile)
        .where(CodeFile.project_id == project_id)
        .order_by(CodeFile.file_path)
        .limit(limit_nodes)
    )
    files = list(nres.scalars().all())
    id_to_path = {f.id: f.file_path for f in files}
    file_ids = list(id_to_path.keys())

    edges_out: list[DependencyEdge] = []
    if file_ids:
        eres = await session.execute(
            select(FileDependency).where(FileDependency.source_file_id.in_(file_ids))
        )
        for dep in eres.scalars().all():
            sp = id_to_path.get(dep.source_file_id)
            tp = id_to_path.get(dep.target_file_id)
            if not sp or not tp:
                continue
            edges_out.append(
                DependencyEdge(
                    source_path=sp,
                    target_path=tp,
                    dependency_type=dep.dependency_type,
                    import_statement=dep.import_statement,
                    is_external=dep.is_external,
                    is_circular=dep.is_circular,
                )
            )

    nodes = [
        CodeFileNode(
            id=f.id,
            file_path=f.file_path,
            language=f.language,
            lines_of_code=f.lines_of_code,
            dependency_count=f.dependency_count,
            dependent_count=f.dependent_count,
        )
        for f in files
    ]

    return ProjectGraphResponse(
        project_id=project_id,
        nodes=nodes,
        edges=edges_out,
        total_nodes=len(nodes),
        total_edges=len(edges_out),
    )


async def _project_graph_bundle(
    session: AsyncSession,
    project_id: UUID,
    *,
    limit_nodes: int,
) -> tuple[list[CodeFile], list[DependencyEdge]]:
    """Shared loader: project must exist; returns files and edges among loaded files."""
    pres = await session.execute(
        select(Project).where(Project.id == project_id, Project.deleted_at.is_(None))
    )
    if not pres.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Project not found")

    nres = await session.execute(
        select(CodeFile)
        .where(CodeFile.project_id == project_id)
        .order_by(CodeFile.file_path)
        .limit(limit_nodes)
    )
    files = list(nres.scalars().all())
    id_to_path = {f.id: f.file_path for f in files}
    file_ids = list(id_to_path.keys())
    edges_out: list[DependencyEdge] = []
    if file_ids:
        eres = await session.execute(
            select(FileDependency).where(FileDependency.source_file_id.in_(file_ids))
        )
        for dep in eres.scalars().all():
            sp = id_to_path.get(dep.source_file_id)
            tp = id_to_path.get(dep.target_file_id)
            if not sp or not tp:
                continue
            edges_out.append(
                DependencyEdge(
                    source_path=sp,
                    target_path=tp,
                    dependency_type=dep.dependency_type,
                    import_statement=dep.import_statement,
                    is_external=dep.is_external,
                    is_circular=dep.is_circular,
                )
            )
    return files, edges_out


_LTSAFE = re.compile(r"^[a-zA-Z0-9_.]+$")


@router.get("/projects/{project_id}/graph/subtree", response_model=ProjectGraphResponse)
async def get_project_graph_subtree(
    project_id: UUID,
    path_prefix: str = Query(
        ...,
        min_length=1,
        max_length=512,
        description="ltree root label (e.g. src or backend.api); uses code_files.directory_path",
    ),
    limit_nodes: int = Query(2000, ge=1, le=5000),
    session: AsyncSession = Depends(get_session),
):
    """Files under an ltree prefix (requires `directory_path` populated on rows)."""
    if not _LTSAFE.match(path_prefix):
        raise HTTPException(
            status_code=400,
            detail="path_prefix must contain only letters, digits, dots, and underscores",
        )

    pres = await session.execute(
        select(Project).where(Project.id == project_id, Project.deleted_at.is_(None))
    )
    if not pres.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Project not found")

    sql = text(
        """
        SELECT id, file_path, language, lines_of_code, dependency_count, dependent_count
        FROM code_files
        WHERE project_id = :pid
          AND directory_path IS NOT NULL
          AND CAST(directory_path AS ltree) <@ CAST(:prefix AS ltree)
        ORDER BY file_path
        LIMIT :lim
        """
    )
    res = await session.execute(
        sql, {"pid": str(project_id), "prefix": path_prefix, "lim": limit_nodes}
    )
    raw_rows = res.mappings().all()
    if not raw_rows:
        return ProjectGraphResponse(
            project_id=project_id,
            nodes=[],
            edges=[],
            total_nodes=0,
            total_edges=0,
        )

    file_ids = [r["id"] for r in raw_rows]
    id_to_path = {r["id"]: r["file_path"] for r in raw_rows}
    nodes = [
        CodeFileNode(
            id=r["id"],
            file_path=r["file_path"],
            language=r["language"],
            lines_of_code=r["lines_of_code"],
            dependency_count=r["dependency_count"] or 0,
            dependent_count=r["dependent_count"] or 0,
        )
        for r in raw_rows
    ]

    edges_out: list[DependencyEdge] = []
    eres = await session.execute(
        select(FileDependency).where(FileDependency.source_file_id.in_(file_ids))
    )
    for dep in eres.scalars().all():
        sp = id_to_path.get(dep.source_file_id)
        tp = id_to_path.get(dep.target_file_id)
        if not sp or not tp:
            continue
        edges_out.append(
            DependencyEdge(
                source_path=sp,
                target_path=tp,
                dependency_type=dep.dependency_type,
                import_statement=dep.import_statement,
                is_external=dep.is_external,
                is_circular=dep.is_circular,
            )
        )

    return ProjectGraphResponse(
        project_id=project_id,
        nodes=nodes,
        edges=edges_out,
        total_nodes=len(nodes),
        total_edges=len(edges_out),
    )


@router.get("/projects/{project_id}/graph/transitive", response_model=ProjectGraphResponse)
async def get_project_graph_transitive(
    project_id: UUID,
    root_path: str = Query(
        ...,
        min_length=1,
        max_length=2048,
        description="code_files.file_path entry to expand transitive imports from",
    ),
    limit_nodes: int = Query(5000, ge=1, le=5000),
    session: AsyncSession = Depends(get_session),
):
    """Transitive internal dependency closure from ``root_path``."""
    files, edges_out = await _project_graph_bundle(session, project_id, limit_nodes=limit_nodes)
    paths = frozenset(f.file_path for f in files)
    if root_path not in paths:
        raise HTTPException(status_code=404, detail="root_path not found in project graph")

    simple = [SimpleEdge(e.source_path, e.target_path, e.is_external) for e in edges_out]
    reachable, edge_pairs = transitive_dependencies(root_path, paths, simple)
    edge_filter = {(s, t) for s, t in edge_pairs}
    filtered_edges = [e for e in edges_out if (e.source_path, e.target_path) in edge_filter]
    by_path = {f.file_path: f for f in files}
    nodes = [
        CodeFileNode(
            id=by_path[p].id,
            file_path=by_path[p].file_path,
            language=by_path[p].language,
            lines_of_code=by_path[p].lines_of_code,
            dependency_count=by_path[p].dependency_count,
            dependent_count=by_path[p].dependent_count,
        )
        for p in sorted(reachable)
        if p in by_path
    ]
    return ProjectGraphResponse(
        project_id=project_id,
        nodes=nodes,
        edges=filtered_edges,
        total_nodes=len(nodes),
        total_edges=len(filtered_edges),
    )


@router.get("/projects/{project_id}/graph/impact", response_model=ProjectGraphResponse)
async def get_project_graph_impact(
    project_id: UUID,
    target_path: str = Query(
        ...,
        min_length=1,
        max_length=2048,
        description="File whose upstream dependents (reverse imports) are returned",
    ),
    limit_nodes: int = Query(5000, ge=1, le=5000),
    session: AsyncSession = Depends(get_session),
):
    """Impact set: sources that transitively depend on ``target_path``."""
    files, edges_out = await _project_graph_bundle(session, project_id, limit_nodes=limit_nodes)
    paths = frozenset(f.file_path for f in files)
    if target_path not in paths:
        raise HTTPException(status_code=404, detail="target_path not found in project graph")

    simple = [SimpleEdge(e.source_path, e.target_path, e.is_external) for e in edges_out]
    impacted, edge_pairs = impact_transitive_dependents(target_path, paths, simple)
    edge_filter = {(s, t) for s, t in edge_pairs}
    filtered_edges = [e for e in edges_out if (e.source_path, e.target_path) in edge_filter]
    by_path = {f.file_path: f for f in files}
    nodes = [
        CodeFileNode(
            id=by_path[p].id,
            file_path=by_path[p].file_path,
            language=by_path[p].language,
            lines_of_code=by_path[p].lines_of_code,
            dependency_count=by_path[p].dependency_count,
            dependent_count=by_path[p].dependent_count,
        )
        for p in sorted(impacted)
        if p in by_path
    ]
    return ProjectGraphResponse(
        project_id=project_id,
        nodes=nodes,
        edges=filtered_edges,
        total_nodes=len(nodes),
        total_edges=len(filtered_edges),
    )


class StandardChainItem(BaseModel):
    id: UUID
    name: str
    hierarchy_path: str
    parent_id: Optional[UUID]
    version: Optional[str]


class StandardsChainResponse(BaseModel):
    project_id: UUID
    items: list[StandardChainItem]


@router.get(
    "/projects/{project_id}/graph/standards-chain",
    response_model=StandardsChainResponse,
)
async def get_standards_chain(
    project_id: UUID,
    session: AsyncSession = Depends(get_session),
):
    """Active standards hierarchy rows scoped to the project (``hierarchy_path`` / ltree)."""
    pres = await session.execute(
        select(Project).where(Project.id == project_id, Project.deleted_at.is_(None))
    )
    if not pres.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Project not found")

    sres = await session.execute(
        select(Standard)
        .where(Standard.project_id == project_id, Standard.is_active.is_(True))
        .order_by(Standard.hierarchy_path)
    )
    rows = list(sres.scalars().all())
    return StandardsChainResponse(
        project_id=project_id,
        items=[
            StandardChainItem(
                id=r.id,
                name=r.name,
                hierarchy_path=str(r.hierarchy_path),
                parent_id=r.parent_id,
                version=r.version,
            )
            for r in rows
        ],
    )
