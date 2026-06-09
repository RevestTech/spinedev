"""
Cost dashboard API routes.

Aggregates `llm_usage` for the Admin UI. Budget cap from `TRON_LLM_BUDGET_USD` / settings.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
import logging
logger = logging.getLogger(__name__)
from sqlalchemy.ext.asyncio import AsyncSession

from tron.api.config import settings
from tron.api.middleware.auth import require_api_key
from tron.api.middleware.scopes import enforce_api_key_route_scope
from tron.domain.models import AuditRun, LLMUsage, Project
from tron.infra.db.session import get_session

router = APIRouter(
    dependencies=[
        Depends(require_api_key),
        Depends(enforce_api_key_route_scope),
    ]
)


def _parse_iso_dt(value: Optional[str], *, default: Optional[datetime] = None) -> datetime:
    if not value:
        if default is not None:
            return default
        raise ValueError("missing datetime")
    raw = value.strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ── Response Models ──


class CostSummary(BaseModel):
    total_cost_usd: float = 0.0
    total_tokens: int = 0
    total_audits: int = 0
    avg_cost_per_audit: float = 0.0
    period_start: str
    period_end: str


class CostByProvider(BaseModel):
    provider: str
    model: str
    cost_usd: float = 0.0
    tokens: int = 0
    requests: int = 0


class CostByProject(BaseModel):
    project_id: str
    project_name: str
    cost_usd: float = 0.0
    audit_count: int = 0


class DailyCost(BaseModel):
    date: str
    cost_usd: float = 0.0
    tokens: int = 0
    audits: int = 0


class CostDashboardResponse(BaseModel):
    summary: CostSummary
    by_provider: list[CostByProvider] = Field(default_factory=list)
    by_project: list[CostByProject] = Field(default_factory=list)
    daily_trend: list[DailyCost] = Field(default_factory=list)
    budget_limit_usd: float = 500.0
    budget_used_pct: float = 0.0


def _usage_window(period_start: datetime, period_end: datetime):
    return (LLMUsage.created_at >= period_start) & (LLMUsage.created_at <= period_end)


def _audit_window(period_start: datetime, period_end: datetime):
    return (AuditRun.created_at >= period_start) & (AuditRun.created_at <= period_end)


@router.get("/costs/dashboard", response_model=CostDashboardResponse)
async def get_cost_dashboard(
    start_date: Optional[str] = Query(
        None, description="Start datetime (ISO 8601, UTC recommended)"
    ),
    end_date: Optional[str] = Query(
        None, description="End datetime (ISO 8601, UTC recommended)"
    ),
    session: AsyncSession = Depends(get_session),
) -> CostDashboardResponse:
    try:
        now = datetime.now(timezone.utc)
        period_end = _parse_iso_dt(end_date, default=now)
        period_start = _parse_iso_dt(
            start_date, default=period_end - timedelta(days=30)
        )
        if period_start > period_end:
            period_start, period_end = period_end - timedelta(days=30), period_end

        uw = _usage_window(period_start, period_end)
        aw = _audit_window(period_start, period_end)

        total_cost_raw = await session.scalar(select(func.coalesce(func.sum(LLMUsage.cost_usd), 0)).where(uw))
        total_tokens_raw = await session.scalar(
            select(
                func.coalesce(
                    func.sum(LLMUsage.prompt_tokens + LLMUsage.completion_tokens),
                    0,
                )
            ).where(uw)
        )
        total_audits_raw = await session.scalar(select(func.count()).select_from(AuditRun).where(aw))

        total_cost_usd = float(total_cost_raw or 0.0)
        total_tokens = int(total_tokens_raw or 0)
        total_audits = int(total_audits_raw or 0)
        
        avg_cost_per_audit = (
            total_cost_usd / total_audits if total_audits else 0.0
        )

        prov_rows = await session.execute(
            select(
                LLMUsage.provider,
                LLMUsage.model,
                func.coalesce(func.sum(LLMUsage.cost_usd), 0),
                func.coalesce(
                    func.sum(LLMUsage.prompt_tokens + LLMUsage.completion_tokens),
                    0,
                ),
                func.count(LLMUsage.id),
            )
            .where(uw)
            .group_by(LLMUsage.provider, LLMUsage.model)
            .order_by(func.sum(LLMUsage.cost_usd).desc())
        )
        by_provider = [
            CostByProvider(
                provider=r[0],
                model=r[1],
                cost_usd=float(r[2] or 0),
                tokens=int(r[3] or 0),
                requests=int(r[4] or 0),
            )
            for r in prov_rows.all()
        ]

        proj_cost_rows = await session.execute(
            select(
                Project.id,
                Project.name,
                func.coalesce(func.sum(LLMUsage.cost_usd), 0),
            )
            .join(LLMUsage, LLMUsage.project_id == Project.id)
            .where(uw, Project.deleted_at.is_(None))
            .group_by(Project.id, Project.name)
            .order_by(func.sum(LLMUsage.cost_usd).desc())
        )
        audit_count_rows = await session.execute(
            select(AuditRun.project_id, func.count(AuditRun.id))
            .where(aw)
            .group_by(AuditRun.project_id)
        )
        audit_by_project = {row[0]: int(row[1]) for row in audit_count_rows.all()}

        by_project = [
            CostByProject(
                project_id=str(r[0]),
                project_name=r[1],
                cost_usd=float(r[2] or 0),
                audit_count=audit_by_project.get(r[0], 0),
            )
            for r in proj_cost_rows.all()
        ]

        day_cost = await session.execute(
            select(
                func.date(LLMUsage.created_at),
                func.coalesce(func.sum(LLMUsage.cost_usd), 0),
                func.coalesce(
                    func.sum(LLMUsage.prompt_tokens + LLMUsage.completion_tokens),
                    0,
                ),
                func.count(LLMUsage.id),
            )
            .where(uw)
            .group_by(func.date(LLMUsage.created_at))
            .order_by(func.date(LLMUsage.created_at))
        )
        day_audits = await session.execute(
            select(
                func.date(AuditRun.created_at),
                func.count(AuditRun.id),
            )
            .where(aw)
            .group_by(func.date(AuditRun.created_at))
        )
        
        # Ensure keys are strings for dictionary lookup
        audits_per_day = {str(row[0]): int(row[1]) for row in day_audits.all() if row[0]}

        daily_trend: list[DailyCost] = []
        for row in day_cost.all():
            dval = row[0]
            if dval is None:
                continue
            dkey = str(dval)
            daily_trend.append(
                DailyCost(
                    date=dkey,
                    cost_usd=float(row[1] or 0),
                    tokens=int(row[2] or 0),
                    audits=audits_per_day.get(dkey, 0),
                )
            )

        budget_limit = float(settings.tron_llm_budget_usd)
        budget_used_pct = (
            (total_cost_usd / budget_limit * 100.0) if budget_limit > 0 else 0.0
        )

        summary = CostSummary(
            total_cost_usd=total_cost_usd,
            total_tokens=total_tokens,
            total_audits=total_audits,
            avg_cost_per_audit=avg_cost_per_audit,
            period_start=period_start.isoformat(),
            period_end=period_end.isoformat(),
        )

        return CostDashboardResponse(
            summary=summary,
            by_provider=by_provider,
            by_project=by_project,
            daily_trend=daily_trend,
            budget_limit_usd=budget_limit,
            budget_used_pct=min(budget_used_pct, 999.0),
        )
    except Exception:
        logger.exception("Cost dashboard failed")
        raise


@router.get("/costs/summary", response_model=CostSummary)
async def get_cost_summary(
    days: int = Query(30, ge=1, le=365, description="Number of days to summarize"),
    session: AsyncSession = Depends(get_session),
) -> CostSummary:
    now = datetime.now(timezone.utc)
    period_start = now - timedelta(days=days)
    uw = _usage_window(period_start, now)
    aw = _audit_window(period_start, now)

    total_cost_raw = await session.scalar(select(func.coalesce(func.sum(LLMUsage.cost_usd), 0)).where(uw))
    total_tokens_raw = await session.scalar(
        select(
            func.coalesce(
                func.sum(LLMUsage.prompt_tokens + LLMUsage.completion_tokens),
                0,
            )
        ).where(uw)
    )
    total_audits = int(
        await session.scalar(select(func.count()).select_from(AuditRun).where(aw)) or 0
    )
    total_cost_usd = float(total_cost_raw or 0)
    total_tokens = int(total_tokens_raw or 0)
    avg_cost_per_audit = (
        total_cost_usd / total_audits if total_audits else 0.0
    )

    return CostSummary(
        total_cost_usd=total_cost_usd,
        total_tokens=total_tokens,
        total_audits=total_audits,
        avg_cost_per_audit=avg_cost_per_audit,
        period_start=period_start.isoformat(),
        period_end=now.isoformat(),
    )
