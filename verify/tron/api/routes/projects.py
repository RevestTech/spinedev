"""
Projects CRUD API.

POST   /api/projects          — Create a project
GET    /api/projects          — List projects
GET    /api/projects/{id}     — Get project by ID
PUT    /api/projects/{id}     — Update project
DELETE /api/projects/{id}     — Soft-delete project
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from tron.api.config import settings
from tron.infra.db.session import get_session
from tron.domain.models import Project
from tron.api.middleware.auth import require_api_key
from tron.api.middleware.scopes import enforce_api_key_route_scope
from tron.services.path_safety import (
    UnsafePathError,
    parse_allowed_roots,
    resolve_under_allowlist,
)

logger = logging.getLogger(__name__)
router = APIRouter(
    dependencies=[
        Depends(require_api_key),
        Depends(enforce_api_key_route_scope),
    ]
)


# ── Request/Response Schemas ──


def _validate_agent_handoff_path(raw: Optional[str]) -> Optional[str]:
    """Shared validator for agent_handoff_path on create + update.

    - ``None`` or empty string → allowed (means "unset").
    - Any non-empty value must resolve under ``TRON_AGENT_HANDOFF_ALLOWED_ROOTS``.
      Fail-closed: if no allowlist is configured the API refuses the field
      entirely — the only accepted value is "clear it".

    Raises ``ValueError`` so FastAPI emits a 422 with a clean detail.
    """
    if raw is None:
        return None
    stripped = raw.strip()
    if not stripped:
        return None  # treat blank as clear-field

    roots = parse_allowed_roots(settings.tron_agent_handoff_allowed_roots)
    try:
        resolved = resolve_under_allowlist(stripped, roots)
    except UnsafePathError as exc:
        # Re-raise as plain ValueError so Pydantic produces a concise 422.
        raise ValueError(str(exc)) from exc
    # Store the canonical form — keeps DB rows predictable and makes the
    # worker's re-validation cheap.
    return str(resolved)


class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    repo_url: Optional[str] = None
    default_branch: str = "main"
    # Absolute path on the audit worker host where Tron writes agent handoff
    # files after each audit. Must resolve under a root in
    # TRON_AGENT_HANDOFF_ALLOWED_ROOTS, or the field is refused.
    agent_handoff_path: Optional[str] = None

    @field_validator("agent_handoff_path")
    @classmethod
    def _check_handoff_path(cls, v: Optional[str]) -> Optional[str]:
        return _validate_agent_handoff_path(v)


class ProjectUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    repo_url: Optional[str] = None
    default_branch: Optional[str] = None
    agent_handoff_path: Optional[str] = None
    status: Optional[str] = None
    company_quality_gates_json: Optional[dict[str, Any]] = None
    quality_gates_json: Optional[dict[str, Any]] = None
    plan_questionnaire_json: Optional[dict[str, Any]] = None
    compliance_control_pack_ids: Optional[list[str]] = None
    audit_exclude_globs_json: Optional[list[str]] = None
    audit_test_path_globs_json: Optional[list[str]] = None

    @field_validator("agent_handoff_path")
    @classmethod
    def _check_handoff_path(cls, v: Optional[str]) -> Optional[str]:
        return _validate_agent_handoff_path(v)


class ProjectResponse(BaseModel):
    id: UUID
    name: str
    description: Optional[str]
    repo_url: Optional[str]
    agent_handoff_path: Optional[str] = None
    default_branch: str
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProjectDetailResponse(ProjectResponse):
    """Project + proposal artifacts (PLAN/BUILD/gates)."""

    company_quality_gates_json: Optional[dict[str, Any]] = None
    quality_gates_json: Optional[dict[str, Any]] = None
    plan_questionnaire_json: Optional[dict[str, Any]] = None
    plan_artifact_json: Optional[dict[str, Any]] = None
    last_build_result_json: Optional[dict[str, Any]] = None
    evolve_artifact_json: Optional[dict[str, Any]] = None
    compliance_control_pack_ids: Optional[list[str]] = None
    audit_exclude_globs_json: Optional[list[str]] = None
    audit_test_path_globs_json: Optional[list[str]] = None

    model_config = {"from_attributes": True}


class ProjectListResponse(BaseModel):
    items: list[ProjectResponse]
    total: int
    page: int
    page_size: int


# ── Endpoints ──

@router.post("/projects", response_model=ProjectResponse, status_code=201)
async def create_project(
    body: ProjectCreate,
    session: AsyncSession = Depends(get_session),
):
    """Create a new project."""
    project = Project(
        name=body.name,
        description=body.description,
        repo_url=body.repo_url,
        agent_handoff_path=body.agent_handoff_path,
        default_branch=body.default_branch,
    )
    session.add(project)
    await session.flush()
    await session.refresh(project)
    logger.info("Project created: %s (%s)", project.name, project.id)
    return project


@router.get("/projects", response_model=ProjectListResponse)
async def list_projects(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None),
    session: AsyncSession = Depends(get_session),
):
    """List projects with pagination."""
    query = select(Project).where(Project.deleted_at.is_(None))
    count_query = select(func.count(Project.id)).where(Project.deleted_at.is_(None))

    if status:
        query = query.where(Project.status == status)
        count_query = count_query.where(Project.status == status)

    # Total count
    total_result = await session.execute(count_query)
    total = total_result.scalar() or 0

    # Paginated results
    query = query.order_by(Project.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await session.execute(query)
    projects = result.scalars().all()

    return ProjectListResponse(
        items=[ProjectResponse.model_validate(p) for p in projects],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/projects/{project_id}", response_model=ProjectDetailResponse)
async def get_project(
    project_id: UUID,
    session: AsyncSession = Depends(get_session),
):
    """Get a project by ID."""
    result = await session.execute(
        select(Project).where(
            Project.id == project_id,
            Project.deleted_at.is_(None),
        )
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return ProjectDetailResponse.model_validate(project)


@router.put("/projects/{project_id}", response_model=ProjectDetailResponse)
async def update_project(
    project_id: UUID,
    body: ProjectUpdate,
    session: AsyncSession = Depends(get_session),
):
    """Update a project."""
    result = await session.execute(
        select(Project).where(
            Project.id == project_id,
            Project.deleted_at.is_(None),
        )
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    update_data = body.model_dump(exclude_unset=True)
    if update_data:
        update_data["updated_at"] = datetime.now(timezone.utc)
        await session.execute(
            update(Project)
            .where(Project.id == project_id)
            .values(**update_data)
        )
        await session.refresh(project)

    logger.info("Project updated: %s (%s)", project.name, project.id)
    return ProjectDetailResponse.model_validate(project)


@router.delete("/projects/{project_id}", status_code=204)
async def delete_project(
    project_id: UUID,
    session: AsyncSession = Depends(get_session),
):
    """Soft-delete a project."""
    result = await session.execute(
        select(Project).where(
            Project.id == project_id,
            Project.deleted_at.is_(None),
        )
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    await session.execute(
        update(Project)
        .where(Project.id == project_id)
        .values(
            deleted_at=datetime.now(timezone.utc),
            status="deleted",
        )
    )
    logger.info("Project soft-deleted: %s (%s)", project.name, project.id)
