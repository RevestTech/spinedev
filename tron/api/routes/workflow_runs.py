"""Workflow run visibility — audit Temporal workflow IDs bound to `audit_runs`."""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tron.api.middleware.auth import require_api_key
from tron.api.middleware.scopes import enforce_api_key_route_scope
from tron.domain.models import AuditRun, Project
from tron.infra.db.session import get_session

router = APIRouter(
    dependencies=[
        Depends(require_api_key),
        Depends(enforce_api_key_route_scope),
    ]
)


class WorkflowRunRow(BaseModel):
    audit_run_id: UUID
    project_id: UUID
    project_name: str
    workflow_id: str
    workflow_run_id: str
    status: str
    progress: int
    trigger_type: Optional[str] = None
    branch: Optional[str] = None
    started_at: datetime
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None


class WorkflowRunListResponse(BaseModel):
    items: list[WorkflowRunRow] = Field(default_factory=list)
    total: int = 0
    limit: int = 50
    offset: int = 0


@router.get("/workflow-runs", response_model=WorkflowRunListResponse)
async def list_workflow_runs(
    session: AsyncSession = Depends(get_session),
    status: Optional[str] = Query(None, description="Filter by audit_runs.status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    filters = [Project.deleted_at.is_(None)]
    if status:
        filters.append(AuditRun.status == status)

    count_stmt = (
        select(func.count())
        .select_from(AuditRun)
        .join(Project, Project.id == AuditRun.project_id)
        .where(*filters)
    )
    total = int(await session.scalar(count_stmt) or 0)

    q = (
        select(AuditRun, Project.name)
        .join(Project, Project.id == AuditRun.project_id)
        .where(*filters)
        .order_by(AuditRun.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    res = await session.execute(q)
    rows = res.all()

    items = [
        WorkflowRunRow(
            audit_run_id=ar.id,
            project_id=ar.project_id,
            project_name=name or "",
            workflow_id=ar.workflow_id,
            workflow_run_id=ar.workflow_run_id,
            status=ar.status,
            progress=ar.progress,
            trigger_type=ar.trigger_type,
            branch=ar.branch,
            started_at=ar.started_at,
            completed_at=ar.completed_at,
            error_message=ar.error_message,
        )
        for ar, name in rows
    ]
    return WorkflowRunListResponse(
        items=items, total=total, limit=limit, offset=offset
    )
