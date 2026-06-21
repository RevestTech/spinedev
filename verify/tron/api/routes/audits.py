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
from decimal import Decimal
from typing import Any, List, Optional, Set
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
import json

from pydantic import BaseModel, Field, model_validator
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


class AuditDiffCreate(BaseModel):
    """Pre-PR diff-mode audit.

    Restricts the audit to exactly ``changed_files``. Optional
    ``base_ref`` / ``head_ref`` are stored on the audit_run row for
    traceability (no git operations happen inside the API — the caller,
    typically a CI runner, computes the diff and passes the path list).
    """

    project_id: UUID
    changed_files: list[str] = Field(
        ..., min_length=1, max_length=2000,
        description="Relative paths to scan. Anything outside this set "
        "is skipped by the pipeline. Empty/oversized lists rejected.",
    )
    base_ref: Optional[str] = Field(
        default=None, max_length=255,
        description="Base git ref the diff was computed from (informational).",
    )
    head_ref: Optional[str] = Field(
        default=None, max_length=255,
        description="Head git ref the diff was computed from (informational).",
    )
    branch: Optional[str] = "main"
    commit_hash: Optional[str] = None
    trigger_type: str = "pr"  # default to "pr" since that's the canonical use

    @model_validator(mode="after")
    def _validate_paths(self) -> "AuditDiffCreate":
        # Reject paths with traversal or absolute prefixes — this endpoint
        # operates on relative paths inside the cloned repo only.
        for p in self.changed_files:
            if not p or not p.strip():
                raise ValueError("changed_files must not contain empty entries")
            if ".." in p.split("/"):
                raise ValueError(
                    f"changed_files entry {p!r} contains '..' traversal"
                )
            if p.startswith("/"):
                raise ValueError(
                    f"changed_files entry {p!r} must be repo-relative, not absolute"
                )
        return self


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
    confidence: Optional[float] = None
    deterministic_tool_confirmed: bool = False
    layer3_execution: Optional[str] = None
    confirming_tools: Optional[List[Any]] = None
    path_role: Optional[str] = None
    follow_up_recommended: bool = False
    evidence_source: Optional[str] = None
    verification_summary: str = Field(
        default="",
        description="Derived line: confidence, L3, tool-backed, path role, evidence source.",
    )
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


def _verification_summary_line(f: Finding) -> str:
    parts: List[str] = []
    if f.confidence is not None:
        try:
            parts.append(f"confidence {float(f.confidence):.0%}")
        except (TypeError, ValueError, OverflowError):
            parts.append("confidence (set)")
    if f.deterministic_tool_confirmed:
        parts.append("tool-backed")
    l3 = f.layer3_execution
    if l3:
        parts.append(f"L3 {l3}")
    if getattr(f, "path_role", None) == "test":
        parts.append("test path")
    evs = getattr(f, "evidence_source", None)
    if evs:
        parts.append(f"source: {evs}")
    if getattr(f, "follow_up_recommended", False):
        parts.append("follow-up recommended")
    if parts:
        return " · ".join(parts)
    return "Candidates for review — not a pentest verdict without corroboration."


def _finding_to_response(f: Finding) -> FindingResponse:
    """Map ORM ``Finding``; ``confirming_tools_json`` → ``confirming_tools``."""
    return FindingResponse(
        id=f.id,
        audit_run_id=f.audit_run_id,
        project_id=f.project_id,
        fingerprint=f.fingerprint,
        rule_id=f.rule_id,
        file_path=f.file_path,
        line_start=f.line_start,
        line_end=f.line_end,
        severity=f.severity,
        category=f.category,
        title=f.title,
        description=f.description,
        suggested_fix=f.suggested_fix,
        status=f.status,
        code_snippet=f.code_snippet,
        confidence=float(f.confidence) if f.confidence is not None else None,
        deterministic_tool_confirmed=bool(f.deterministic_tool_confirmed),
        layer3_execution=f.layer3_execution,
        confirming_tools=f.confirming_tools_json,
        path_role=getattr(f, "path_role", None),
        follow_up_recommended=bool(getattr(f, "follow_up_recommended", False)),
        evidence_source=getattr(f, "evidence_source", None),
        verification_summary=_verification_summary_line(f),
        created_at=f.created_at,
        updated_at=f.updated_at,
    )


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


@router.post("/audits/diff", response_model=AuditSummary, status_code=201)
async def create_diff_audit(
    body: AuditDiffCreate,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
):
    """Start a PR-time audit restricted to a specific list of changed files.

    The pipeline runs the same agents and verification layers as a full
    audit — Bandit/Semgrep/Safety/ESLint/Ruff still execute, schema
    validation still applies, Layer 5 scope still enforces. The
    difference is the file set: only ``changed_files`` (and config files
    they reference, by way of the existing audit_path_filters) are
    handed to the agents.

    Use case: a GitHub Action runs ``git diff --name-only origin/main``,
    POSTs the path list here, and gates the PR on the resulting
    findings. Turns Tron from "weekly audit" into "PR gate."
    """
    result = await session.execute(
        select(Project).where(
            Project.id == body.project_id,
            Project.deleted_at.is_(None),
        )
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    audit_run = AuditRun(
        project_id=body.project_id,
        workflow_id="pending",
        workflow_run_id="pending",
        branch=body.branch,
        commit_hash=body.commit_hash,
        trigger_type=body.trigger_type,
        status="queued",
        progress=0,
        # The diff scope is the load-bearing field. AuditExecutor /
        # workflow activities read this and restrict file_contents to it.
        diff_files_json=list(body.changed_files),
        diff_base_ref=body.base_ref,
        diff_head_ref=body.head_ref,
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

    await session.commit()

    logger.info(
        "Diff-mode audit created: %s for project %s, %d changed files",
        audit_run.id,
        body.project_id,
        len(body.changed_files),
    )

    if settings.temporal_enabled:
        try:
            await _dispatch_temporal_audit(
                audit_run.id, body.project_id, body.trigger_type
            )
        except Exception as exc:
            logger.exception(
                "Temporal dispatch failed for diff audit %s", audit_run.id
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
                detail="Temporal unavailable; diff audit was not started",
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


class AuditCostBreakdownRow(BaseModel):
    """One row of the per-audit cost breakdown."""

    provider: str
    model: str
    operation_detail: Optional[str] = None
    request_count: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_usd: float


class AuditCostResponse(BaseModel):
    audit_run_id: UUID
    total_cost_usd: float
    total_tokens: int
    request_count: int
    breakdown: list[AuditCostBreakdownRow]


@router.get("/audits/{audit_id}/cost", response_model=AuditCostResponse)
async def get_audit_cost(
    audit_id: UUID,
    session: AsyncSession = Depends(get_session),
):
    """Per-audit LLM cost breakdown.

    Aggregates ``llm_usage`` rows whose ``workflow_run_id`` matches this
    audit. Both the in-process executor and the Temporal path persist
    rows with the audit_run_id in ``workflow_run_id`` (see
    `audit_executor.py:179` and `activities.py`), so this query covers
    both code paths.

    Buyer-relevant: lets a customer answer "what did this scan cost me"
    in one click, surfaced in the AuditDetail UI.
    """
    from sqlalchemy import func, text

    from tron.domain.models import LLMUsage

    # Confirm the audit exists (404 vs returning empty cost data which
    # would be confusing).
    audit = await session.execute(
        select(AuditRun).where(AuditRun.id == audit_id)
    )
    if audit.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Audit not found")

    # Aggregate by (provider, model, operation_detail). operation_detail
    # is what tells "which agent" — security_iso, builder_iso, etc.
    aid_str = str(audit_id)
    res = await session.execute(
        select(
            LLMUsage.provider,
            LLMUsage.model,
            LLMUsage.operation_detail,
            func.count().label("request_count"),
            func.coalesce(func.sum(LLMUsage.prompt_tokens), 0).label("prompt_tokens"),
            func.coalesce(func.sum(LLMUsage.completion_tokens), 0).label("completion_tokens"),
            func.coalesce(func.sum(LLMUsage.cost_usd), 0).label("cost_usd"),
        )
        .where(LLMUsage.workflow_run_id == aid_str)
        .group_by(
            LLMUsage.provider, LLMUsage.model, LLMUsage.operation_detail
        )
        .order_by(text("cost_usd DESC"))
    )

    rows = res.all()
    breakdown = [
        AuditCostBreakdownRow(
            provider=r.provider,
            model=r.model,
            operation_detail=r.operation_detail,
            request_count=int(r.request_count or 0),
            prompt_tokens=int(r.prompt_tokens or 0),
            completion_tokens=int(r.completion_tokens or 0),
            total_tokens=int((r.prompt_tokens or 0) + (r.completion_tokens or 0)),
            cost_usd=float(r.cost_usd or 0),
        )
        for r in rows
    ]
    total_cost = sum(b.cost_usd for b in breakdown)
    total_tokens = sum(b.total_tokens for b in breakdown)
    request_count = sum(b.request_count for b in breakdown)

    return AuditCostResponse(
        audit_run_id=audit_id,
        total_cost_usd=total_cost,
        total_tokens=total_tokens,
        request_count=request_count,
        breakdown=breakdown,
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


class SarifImportBody(BaseModel):
    sarif: dict


class SarifImportResponse(BaseModel):
    inserted: int
    skipped_duplicates: int


async def _resync_audit_run_counts(session: AsyncSession, audit_id: UUID) -> None:
    r = await session.execute(
        select(Finding).where(Finding.audit_run_id == audit_id)
    )
    rows = r.scalars().all()
    c = h = m = lo = 0
    for f in rows:
        if f.severity == "critical":
            c += 1
        elif f.severity == "high":
            h += 1
        elif f.severity == "medium":
            m += 1
        elif f.severity == "low":
            lo += 1
    await session.execute(
        update(AuditRun)
        .where(AuditRun.id == audit_id)
        .values(
            findings_total=len(rows),
            findings_critical=c,
            findings_high=h,
            findings_medium=m,
            findings_low=lo,
        )
    )


@router.post(
    "/audits/{audit_id}/import-sarif",
    response_model=SarifImportResponse,
)
async def import_sarif(
    audit_id: UUID,
    body: SarifImportBody,
    session: AsyncSession = Depends(get_session),
) -> SarifImportResponse:
    """Merge SARIF 2.1 results into a run (new fingerprints only). SEC-1."""
    from tron.services.sarif_import import parse_sarif_to_rows

    res = await session.execute(select(AuditRun).where(AuditRun.id == audit_id))
    audit = res.scalar_one_or_none()
    if not audit:
        raise HTTPException(status_code=404, detail="Audit run not found")

    # Best-effort: archive the raw SARIF blob to MinIO. Findings still go
    # into Postgres for query performance, but the original SARIF is
    # available for re-import / re-analysis. MinIO outage is logged but
    # does not block the import — the import is the source of truth here.
    try:
        from tron.infra.minio import get_minio_client

        client = await get_minio_client()
        await client.upload_artifact(
            audit_run_id=audit_id,
            artifact_name=f"sarif-import-{datetime.now(timezone.utc).isoformat()}.json",
            data=json.dumps(body.sarif).encode("utf-8"),
            content_type="application/sarif+json",
        )
    except Exception:
        logger.warning(
            "MinIO archive of SARIF import failed for audit %s",
            audit_id, exc_info=True,
        )

    ex = await session.execute(
        select(Finding.fingerprint).where(Finding.audit_run_id == audit_id)
    )
    existing: Set[str] = {x[0] for x in ex.all()}
    try:
        rows = parse_sarif_to_rows(body.sarif, str(audit.project_id), str(audit_id))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    n_ins = 0
    n_skip = 0
    for row in rows:
        if row["fingerprint"] in existing:
            n_skip += 1
            continue
        existing.add(row["fingerprint"])
        session.add(
            Finding(
                audit_run_id=UUID(row["audit_run_id"]),
                project_id=UUID(row["project_id"]),
                fingerprint=row["fingerprint"],
                rule_id=row["rule_id"],
                file_path=row["file_path"],
                line_start=row["line_start"],
                line_end=row["line_end"],
                severity=row["severity"],
                category=row["category"],
                title=row["title"],
                description=row["description"],
                suggested_fix=row.get("suggested_fix"),
                status=row.get("status", "open"),
                code_snippet=row.get("code_snippet"),
                confidence=row.get("confidence"),
                deterministic_tool_confirmed=row["deterministic_tool_confirmed"],
                layer3_execution=row.get("layer3_execution"),
                confirming_tools_json=row.get("confirming_tools_json"),
                path_role=row.get("path_role"),
                follow_up_recommended=bool(row.get("follow_up_recommended", False)),
                evidence_source=row.get("evidence_source"),
            )
        )
        n_ins += 1
    if n_ins:
        await _resync_audit_run_counts(session, audit_id)
    await session.commit()
    return SarifImportResponse(inserted=n_ins, skipped_duplicates=n_skip)


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
        items=[_finding_to_response(f) for f in findings],
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
