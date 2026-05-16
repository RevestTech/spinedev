"""
Audit Run API.

POST   /api/audits                — Start a new audit run
GET    /api/audits                — List audit runs
GET    /api/audits/{id}           — Get audit run status + summary
GET    /api/audits/{id}/findings  — Get findings for an audit run
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID
from decimal import Decimal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from tron.infra.db.session import get_session
from tron.domain.models import AuditRun, Finding, Project
from tron.api.middleware.auth import require_api_key, require_master_api_key
from tron.api.middleware.scopes import enforce_api_key_route_scope
from tron.api.config import settings

logger = logging.getLogger(__name__)
router = APIRouter(
    dependencies=[
        Depends(require_api_key),
        Depends(enforce_api_key_route_scope),
    ]
)


# ── Request/Response Schemas ──


class AuditCreate(BaseModel):
    project_id: UUID
    branch: Optional[str] = "main"
    commit_hash: Optional[str] = None
    trigger_type: str = "manual"


class AuditSummary(BaseModel):
    id: UUID
    project_id: UUID
    workflow_id: str
    workflow_run_id: str
    status: str
    progress: int
    commit_hash: Optional[str] = None
    branch: Optional[str] = None
    trigger_type: Optional[str] = None
    triggered_by: Optional[UUID] = None
    quality_score: Optional[Decimal] = None
    findings_total: int
    findings_critical: int
    findings_high: int
    findings_medium: int
    findings_low: int
    started_at: datetime
    completed_at: Optional[datetime]
    error_message: Optional[str]
    error_stack: Optional[str] = None
    threat_intel_alerts_json: Optional[list[str]] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class AuditListResponse(BaseModel):
    items: list[AuditSummary]
    total: int
    page: int
    page_size: int


class FindingResponse(BaseModel):
    id: UUID
    audit_run_id: UUID
    project_id: UUID
    fingerprint: str
    rule_id: str
    file_path: str
    line_start: Optional[int]
    line_end: Optional[int]
    severity: str
    category: Optional[str]
    title: str
    description: str
    suggested_fix: Optional[str]
    status: str
    code_snippet: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class FindingListResponse(BaseModel):
    items: list[FindingResponse]
    total: int
    page: int
    page_size: int


# ── Endpoints ──


@router.post("/audits", response_model=AuditSummary, status_code=201)
async def create_audit(
    body: AuditCreate,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
):
    """Start a new audit run for a project."""
    # Verify project exists
    result = await session.execute(
        select(Project).where(
            Project.id == body.project_id,
            Project.deleted_at.is_(None),
        )
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Create audit run record (workflow_id / workflow_run_id aligned with dispatch path)
    audit_run = AuditRun(
        project_id=body.project_id,
        workflow_id="pending",
        workflow_run_id="pending",
        branch=body.branch,
        commit_hash=body.commit_hash,
        trigger_type=body.trigger_type,
        status="queued",
        progress=0,
    )
    session.add(audit_run)
    await session.flush()
    await session.refresh(audit_run)
    aid = audit_run.id
    if settings.temporal_enabled:
        audit_run.workflow_id = f"audit-{aid}"
        audit_run.workflow_run_id = "pending-temporal-run"
    else:
        audit_run.workflow_id = f"background-audit-{aid}"
        audit_run.workflow_run_id = f"background-{aid}"
    
    # CRITICAL: Commit immediately so background task can see the row!
    # Without this, the background task runs in a separate transaction
    # and gets rowcount=0 on all UPDATEs because the row doesn't exist yet.
    await session.commit()

    logger.info(
        "Audit run created: %s for project %s",
        audit_run.id,
        body.project_id,
    )

    # Dispatch to Temporal if configured, otherwise fall back to BackgroundTasks
    if settings.temporal_enabled:
        try:
            await _dispatch_temporal_audit(
                audit_run.id, body.project_id, body.trigger_type
            )
        except Exception as exc:
            logger.exception(
                "Temporal dispatch failed for audit %s", audit_run.id
            )
            err_msg = f"Temporal dispatch failed: {exc}"[:1000]
            await session.execute(
                update(AuditRun)
                .where(AuditRun.id == audit_run.id)
                .values(
                    status="failed",
                    error_message=err_msg,
                    completed_at=datetime.now(timezone.utc),
                )
            )
            await session.commit()
            raise HTTPException(
                status_code=503,
                detail="Temporal unavailable; audit was not started",
            ) from exc
    else:
        background_tasks.add_task(
            _execute_audit_background,
            audit_run_id=audit_run.id,
            project_id=body.project_id,
        )

    return audit_run


@router.get("/audits", response_model=AuditListResponse)
async def list_audits(
    project_id: Optional[UUID] = Query(None),
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
):
    """List audit runs with optional filters."""
    query = select(AuditRun)
    count_query = select(func.count(AuditRun.id))

    if project_id:
        query = query.where(AuditRun.project_id == project_id)
        count_query = count_query.where(AuditRun.project_id == project_id)
    if status:
        query = query.where(AuditRun.status == status)
        count_query = count_query.where(AuditRun.status == status)

    total_result = await session.execute(count_query)
    total = total_result.scalar() or 0

    query = query.order_by(AuditRun.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await session.execute(query)
    runs = result.scalars().all()

    return AuditListResponse(
        items=[AuditSummary.model_validate(r) for r in runs],
        total=total,
        page=page,
        page_size=page_size,
    )


class ReconcileStaleQueuedBody(BaseModel):
    """Optional body for stale-queue reconciliation."""

    older_than_minutes: Optional[int] = Field(
        default=None,
        ge=1,
        le=10080,
        description="Age threshold; defaults to TRON_STALE_QUEUED_AUDIT_MINUTES / settings.",
    )
    dry_run: bool = Field(default=False, description="If true, only list matching audit IDs.")


class ReconcileStaleQueuedResponse(BaseModel):
    matched: int
    updated: int
    dry_run: bool
    audit_run_ids: list[str]
    older_than_minutes: int


@router.post(
    "/audits/reconcile-stale-queued",
    response_model=ReconcileStaleQueuedResponse,
    dependencies=[Depends(require_master_api_key)],
)
async def post_reconcile_stale_queued_audits(
    body: ReconcileStaleQueuedBody,
    session: AsyncSession = Depends(get_session),
):
    """
    Mark **queued** audit runs older than ``older_than_minutes`` as **failed**
    (operator cleanup when workers or Temporal are unavailable).

    **Master API key** (or admin UI session treated as master) only.
    """
    from tron.services.audit_reconcile import reconcile_stale_queued_audits as reconcile_svc

    threshold = body.older_than_minutes
    if threshold is None:
        threshold = settings.stale_queued_audit_minutes_default

    out = await reconcile_svc(session, older_than_minutes=threshold, dry_run=body.dry_run)
    return ReconcileStaleQueuedResponse(
        matched=out.matched,
        updated=out.updated,
        dry_run=out.dry_run,
        audit_run_ids=out.audit_run_ids,
        older_than_minutes=threshold,
    )


@router.get("/audits/{audit_id}", response_model=AuditSummary)
async def get_audit(
    audit_id: UUID,
    session: AsyncSession = Depends(get_session),
):
    """Get audit run status and summary."""
    result = await session.execute(
        select(AuditRun).where(AuditRun.id == audit_id)
    )
    audit = result.scalar_one_or_none()
    if not audit:
        raise HTTPException(status_code=404, detail="Audit run not found")
    return audit


@router.get("/audits/{audit_id}/findings", response_model=FindingListResponse)
async def list_audit_findings(
    audit_id: UUID,
    severity: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
):
    """List findings for a specific audit run."""
    # Verify audit exists
    audit_result = await session.execute(
        select(AuditRun).where(AuditRun.id == audit_id)
    )
    if not audit_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Audit run not found")

    query = select(Finding).where(Finding.audit_run_id == audit_id)
    count_query = select(func.count(Finding.id)).where(
        Finding.audit_run_id == audit_id
    )

    if severity:
        query = query.where(Finding.severity == severity)
        count_query = count_query.where(Finding.severity == severity)
    if status:
        query = query.where(Finding.status == status)
        count_query = count_query.where(Finding.status == status)

    total_result = await session.execute(count_query)
    total = total_result.scalar() or 0

    query = query.order_by(
        # Critical first, then high, medium, low
        Finding.severity.asc(),
        Finding.created_at.desc(),
    )
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await session.execute(query)
    findings = result.scalars().all()

    return FindingListResponse(
        items=[FindingResponse.model_validate(f) for f in findings],
        total=total,
        page=page,
        page_size=page_size,
    )


class QualityGateEvaluation(BaseModel):
    audit_id: UUID
    project_id: UUID
    passed: bool
    criteria_results: list


@router.post(
    "/audits/{audit_id}/evaluate-quality-gates",
    response_model=QualityGateEvaluation,
)
async def evaluate_audit_quality_gates(
    audit_id: UUID,
    session: AsyncSession = Depends(get_session),
):
    """Evaluate merged quality gates against completed audit counts."""
    from tron.standards.engine import evaluate_quality_gates, merge_quality_gates

    res = await session.execute(select(AuditRun).where(AuditRun.id == audit_id))
    audit = res.scalar_one_or_none()
    if not audit:
        raise HTTPException(status_code=404, detail="Audit run not found")

    pres = await session.execute(select(Project).where(Project.id == audit.project_id))
    project = pres.scalar_one_or_none()
    gates = merge_quality_gates(
        project.quality_gates_json if project else None,
        company_override=project.company_quality_gates_json if project else None,
    )
    fres = await session.execute(
        select(Finding).where(Finding.audit_run_id == audit_id)
    )
    finding_rows = [
        {
            "rule_id": f.rule_id,
            "title": f.title,
            "category": f.category or "",
            "severity": f.severity,
        }
        for f in fres.scalars().all()
    ]
    passed, criteria = evaluate_quality_gates(
        gates,
        findings_total=audit.findings_total,
        findings_critical=audit.findings_critical,
        findings_high=audit.findings_high,
        findings_medium=audit.findings_medium,
        findings_low=audit.findings_low,
        coverage_percent=None,
        finding_rows=finding_rows,
    )
    return QualityGateEvaluation(
        audit_id=audit.id,
        project_id=audit.project_id,
        passed=passed,
        criteria_results=criteria,
    )


# ── Temporal Dispatch ──


async def _dispatch_temporal_audit(
    audit_run_id: UUID,
    project_id: UUID,
    trigger_type: str = "manual",
) -> None:
    """Dispatch an audit to Temporal for durable execution."""
    from temporalio.client import Client
    from tron.workflows.activities import AuditInput

    logger.info("Dispatching audit to Temporal: %s", audit_run_id)

    from tron.infra.db.session import _session_factory

    client = await Client.connect(settings.temporal_host)
    workflow_id = f"audit-{audit_run_id}"

    handle = await client.start_workflow(
        "AuditWorkflow",
        AuditInput(
            audit_run_id=str(audit_run_id),
            project_id=str(project_id),
            triggered_by=trigger_type,
            scope="full",
        ),
        id=workflow_id,
        task_queue=settings.temporal_task_queue,
    )
    run_id = (handle.run_id or handle.first_execution_run_id or "").strip()
    if not run_id:
        run_id = "unknown-temporal-run"

    if _session_factory is not None:
        try:
            async with _session_factory() as session:
                await session.execute(
                    update(AuditRun)
                    .where(AuditRun.id == audit_run_id)
                    .values(workflow_id=workflow_id, workflow_run_id=run_id)
                )
                await session.commit()
        except Exception as exc:
            logger.warning("Failed to persist Temporal run id for audit %s: %s", audit_run_id, exc)

    logger.info(
        "Temporal workflow started: %s run_id=%s on queue %s",
        workflow_id,
        run_id,
        settings.temporal_task_queue,
    )


# ── Background Execution (Fallback) ──


async def _execute_audit_background(
    audit_run_id: UUID,
    project_id: UUID,
) -> None:
    """Execute an audit via the AuditExecutor when Temporal dispatch is unavailable.

    Loads secrets from the app state (populated at startup from keyvault),
    then delegates to AuditExecutor which runs the same multi-ISO agent pipeline
    as the primary Temporal path.
    """
    from tron.infra.db.session import _session_factory
    from tron.infra.secrets import get_secret, get_secrets, merge_anthropic_key_aliases
    from tron.services.audit_executor import AuditExecutor

    logger.info("Background audit starting: %s", audit_run_id)

    try:
        # Load secrets needed for the agent pipeline
        secrets = await get_secrets([
            "llm/anthropic-key",
            "llm/openai-key",
        ])
        try:
            secrets["anthropic-key"] = await get_secret("anthropic-key")
        except KeyError:
            pass
        secrets = merge_anthropic_key_aliases(secrets)

        executor = AuditExecutor(
            session_factory=_session_factory,
            secrets=secrets,
        )

        await executor.run(audit_run_id, project_id)

    except Exception as exc:
        logger.exception("Background audit failed: %s", audit_run_id)
        try:
            async with _session_factory() as session:
                await session.execute(
                    update(AuditRun)
                    .where(AuditRun.id == audit_run_id)
                    .values(
                        status="failed",
                        error_message=str(exc)[:1000],
                        completed_at=datetime.now(timezone.utc),
                    )
                )
                await session.commit()
        except Exception:
            logger.exception("Failed to update audit status to failed")
