"""Start FIX workflow for a persisted finding."""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tron.api.config import settings
from tron.api.middleware.auth import require_api_key
from tron.api.middleware.scopes import enforce_api_key_route_scope
from tron.domain.models import Finding
from tron.infra.db.session import get_session

logger = logging.getLogger(__name__)
router = APIRouter(
    dependencies=[
        Depends(require_api_key),
        Depends(enforce_api_key_route_scope),
    ]
)


class FixStarted(BaseModel):
    workflow_id: str
    status: str = "started"


@router.post("/findings/{finding_id}/fix", response_model=FixStarted)
async def start_fix_workflow(
    finding_id: UUID,
    session: AsyncSession = Depends(get_session),
):
    """Kick off Temporal FixWorkflow for one finding."""
    if not settings.temporal_enabled:
        raise HTTPException(status_code=503, detail="Temporal not enabled")

    res = await session.execute(select(Finding).where(Finding.id == finding_id))
    f = res.scalar_one_or_none()
    if not f:
        raise HTTPException(status_code=404, detail="Finding not found")

    from temporalio.client import Client
    from tron.workflows.activities import FindingInput

    workflow_id = f"fix-{finding_id}"
    client = await Client.connect(settings.temporal_host)
    fin = FindingInput(
        finding_id=str(f.id),
        audit_run_id=str(f.audit_run_id),
        project_id=str(f.project_id),
        file_path=f.file_path,
        line_number=f.line_start or 1,
        vulnerability_type=f.rule_id or f.category or "other",
        severity=f.severity,
        description=f.description,
        code_snippet=f.code_snippet or "",
    )
    await client.start_workflow(
        "FixWorkflow",
        fin,
        id=workflow_id,
        task_queue=settings.temporal_task_queue,
    )
    logger.info("FixWorkflow started %s", workflow_id)
    return FixStarted(workflow_id=workflow_id)
