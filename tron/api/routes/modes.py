"""PLAN and BUILD mode triggers (Temporal)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from tron.api.config import settings
from tron.api.middleware.auth import require_api_key
from tron.api.middleware.scopes import enforce_api_key_route_scope
from tron.domain.models import Project
from tron.infra.db.session import get_session

logger = logging.getLogger(__name__)
router = APIRouter(
    dependencies=[
        Depends(require_api_key),
        Depends(enforce_api_key_route_scope),
    ]
)


class PlanStartBody(BaseModel):
    """Start PLAN workflow — use free-text and/or structured questionnaire from the UI wizard."""

    goals: str = ""
    constraints: str = ""
    questionnaire: Optional[dict[str, Any]] = None
    # When True and repo_url is set, worker attempts git push if TRON_PLAN_GIT_TOKEN is configured.
    write_tron_files: bool = True

    @model_validator(mode="after")
    def _require_goals_or_questionnaire(self) -> "PlanStartBody":
        from tron.services.plan_questionnaire import questionnaire_has_substance

        g = (self.goals or "").strip()
        if len(g) < 3 and not questionnaire_has_substance(self.questionnaire):
            raise ValueError(
                "Provide at least 3 characters in goals or complete the plan questionnaire"
            )
        return self


class BuildStartBody(BaseModel):
    task: str = Field(..., min_length=3)


class EvolveStartBody(BaseModel):
    directive: str = Field(..., min_length=3)


class WorkflowStarted(BaseModel):
    workflow_id: str
    status: str = "started"


async def _require_project(session: AsyncSession, project_id: UUID) -> Project:
    res = await session.execute(
        select(Project).where(Project.id == project_id, Project.deleted_at.is_(None))
    )
    p = res.scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=404, detail="Project not found")
    return p


@router.post("/plan/{project_id}", response_model=WorkflowStarted)
async def start_plan_workflow(
    project_id: UUID,
    body: PlanStartBody,
    session: AsyncSession = Depends(get_session),
):
    """Start PLAN workflow — fills `projects.plan_artifact_json` when complete."""
    await _require_project(session, project_id)
    if body.questionnaire is not None:
        await session.execute(
            update(Project)
            .where(Project.id == project_id, Project.deleted_at.is_(None))
            .values(
                plan_questionnaire_json=body.questionnaire,
                updated_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()
    if not settings.temporal_enabled:
        raise HTTPException(status_code=503, detail="Temporal not enabled")
    from temporalio.client import Client
    from tron.workflows.activities import PlanJobInput

    wid = f"plan-{project_id}-{uuid4().hex[:8]}"
    client = await Client.connect(settings.temporal_host)
    await client.start_workflow(
        "PlanWorkflow",
        PlanJobInput(
            project_id=str(project_id),
            goals=body.goals,
            constraints=body.constraints,
            write_tron_files=body.write_tron_files,
            questionnaire=body.questionnaire,
        ),
        id=wid,
        task_queue=settings.temporal_task_queue,
    )
    logger.info("PlanWorkflow started %s", wid)
    return WorkflowStarted(workflow_id=wid)


@router.post("/build/{project_id}", response_model=WorkflowStarted)
async def start_build_workflow(
    project_id: UUID,
    body: BuildStartBody,
    session: AsyncSession = Depends(get_session),
):
    """Start BUILD workflow — runs Builder ISO with task; saves `last_build_result_json`."""
    await _require_project(session, project_id)
    if not settings.temporal_enabled:
        raise HTTPException(status_code=503, detail="Temporal not enabled")
    from temporalio.client import Client
    from tron.workflows.activities import BuildJobInput

    run_id = str(uuid4())
    wid = f"build-{project_id}-{run_id[:8]}"
    client = await Client.connect(settings.temporal_host)
    await client.start_workflow(
        "BuildWorkflow",
        BuildJobInput(
            project_id=str(project_id),
            task=body.task,
            build_run_id=run_id,
        ),
        id=wid,
        task_queue=settings.temporal_task_queue,
    )
    logger.info("BuildWorkflow started %s", wid)
    return WorkflowStarted(workflow_id=wid)


@router.post("/evolve/{project_id}", response_model=WorkflowStarted)
async def start_evolve_workflow(
    project_id: UUID,
    body: EvolveStartBody,
    session: AsyncSession = Depends(get_session),
):
    """Start EVOLVE workflow — iterative improvement; saves ``evolve_artifact_json``."""
    await _require_project(session, project_id)
    if not settings.temporal_enabled:
        raise HTTPException(status_code=503, detail="Temporal not enabled")
    from temporalio.client import Client
    from tron.workflows.activities import EvolveJobInput

    run_id = str(uuid4())
    wid = f"evolve-{project_id}-{run_id[:8]}"
    client = await Client.connect(settings.temporal_host)
    await client.start_workflow(
        "EvolveWorkflow",
        EvolveJobInput(
            project_id=str(project_id),
            directive=body.directive,
            evolve_run_id=run_id,
        ),
        id=wid,
        task_queue=settings.temporal_task_queue,
    )
    logger.info("EvolveWorkflow started %s", wid)
    return WorkflowStarted(workflow_id=wid)
