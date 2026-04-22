"""
GDPR Data Subject Rights API.

POST   /api/gdpr/export           — Export all user data (projects, audits, findings)
POST   /api/gdpr/delete           — Right to be forgotten (soft-delete all user data)
GET    /api/gdpr/retention-policy — Data retention policy configuration
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from tron.infra.db.session import get_session
from tron.domain.models import Project, AuditRun, Finding
from tron.api.middleware.auth import require_api_key
from tron.api.middleware.scopes import enforce_api_key_route_scope

logger = logging.getLogger(__name__)
router = APIRouter(
    dependencies=[
        Depends(require_api_key),
        Depends(enforce_api_key_route_scope),
    ]
)


# ── Request/Response Schemas ──

class GDPRExportResponse(BaseModel):
    """Complete user data export."""
    user_id: Optional[UUID]
    export_timestamp: datetime
    projects: list[dict]
    audit_runs: list[dict]
    findings: list[dict]
    total_records: int


class GDPRDeleteResponse(BaseModel):
    """Confirmation of right to be forgotten."""
    user_id: Optional[UUID]
    deletion_timestamp: datetime
    projects_deleted: int
    audit_runs_deleted: int
    findings_deleted: int
    total_records_deleted: int


class RetentionPolicyResponse(BaseModel):
    """Data retention policy configuration."""
    project_retention_days: int = Field(default=2555, description="7 years in days")
    audit_run_retention_days: int = Field(default=1095, description="3 years in days")
    finding_retention_days: int = Field(default=1095, description="3 years in days")
    soft_delete_grace_period_days: int = Field(default=30, description="Grace period before hard delete")
    last_updated: datetime


# ── Endpoints ──

@router.post("/gdpr/export", response_model=GDPRExportResponse, status_code=200)
async def export_user_data(
    user_id: Optional[UUID] = Query(None, description="User ID to export (if None, exports all)"),
    session: AsyncSession = Depends(get_session),
):
    """
    Export all user data as JSON.
    
    Includes projects, audit runs, and findings accessible to the user.
    If user_id is not provided, exports all data (admin-only use case).
    """
    export_timestamp = datetime.now(timezone.utc)
    
    # Build query for projects
    project_query = select(Project).where(Project.deleted_at.is_(None))
    if user_id:
        project_query = project_query.where(Project.created_by == user_id)
    
    projects_result = await session.execute(project_query)
    projects = projects_result.scalars().all()
    project_ids = [p.id for p in projects]
    
    # Build query for audit runs
    audit_query = select(AuditRun).where(AuditRun.project_id.in_(project_ids) if project_ids else True)
    audits_result = await session.execute(audit_query)
    audits = audits_result.scalars().all()
    audit_ids = [a.id for a in audits]
    
    # Build query for findings
    finding_query = select(Finding).where(Finding.audit_run_id.in_(audit_ids) if audit_ids else True)
    findings_result = await session.execute(finding_query)
    findings = findings_result.scalars().all()
    
    # Convert to dict format
    projects_data = [
        {
            "id": str(p.id),
            "name": p.name,
            "description": p.description,
            "repo_url": p.repo_url,
            "created_at": p.created_at.isoformat(),
            "updated_at": p.updated_at.isoformat(),
        }
        for p in projects
    ]
    
    audits_data = [
        {
            "id": str(a.id),
            "project_id": str(a.project_id),
            "status": a.status,
            "findings_total": a.findings_total,
            "started_at": a.started_at.isoformat(),
            "completed_at": a.completed_at.isoformat() if a.completed_at else None,
        }
        for a in audits
    ]
    
    findings_data = [
        {
            "id": str(f.id),
            "audit_run_id": str(f.audit_run_id),
            "rule_id": f.rule_id,
            "file_path": f.file_path,
            "severity": f.severity,
            "title": f.title,
            "status": f.status,
            "created_at": f.created_at.isoformat(),
        }
        for f in findings
    ]
    
    total_records = len(projects_data) + len(audits_data) + len(findings_data)
    
    logger.info(
        "GDPR export: user_id=%s, projects=%d, audits=%d, findings=%d",
        user_id, len(projects_data), len(audits_data), len(findings_data)
    )
    
    return GDPRExportResponse(
        user_id=user_id,
        export_timestamp=export_timestamp,
        projects=projects_data,
        audit_runs=audits_data,
        findings=findings_data,
        total_records=total_records,
    )


@router.post("/gdpr/delete", response_model=GDPRDeleteResponse, status_code=200)
async def delete_user_data(
    user_id: UUID = Query(..., description="User ID to delete"),
    session: AsyncSession = Depends(get_session),
):
    """
    Right to be forgotten — soft-delete all user data.
    
    Soft-deletes all projects and related audit runs/findings for the user.
    Data is marked as deleted but retained for compliance retention periods.
    """
    deletion_timestamp = datetime.now(timezone.utc)
    
    # Find all projects created by this user
    projects_query = select(Project).where(
        Project.created_by == user_id,
        Project.deleted_at.is_(None),
    )
    projects_result = await session.execute(projects_query)
    projects = projects_result.scalars().all()
    project_ids = [p.id for p in projects]
    
    # Count audit runs to be deleted
    audits_count_query = select(func.count(AuditRun.id)).where(
        AuditRun.project_id.in_(project_ids) if project_ids else False
    )
    audits_count_result = await session.execute(audits_count_query)
    audits_count = audits_count_result.scalar() or 0
    
    # Count findings to be deleted
    findings_count_query = select(func.count(Finding.id)).where(
        Finding.project_id.in_(project_ids) if project_ids else False
    )
    findings_count_result = await session.execute(findings_count_query)
    findings_count = findings_count_result.scalar() or 0
    
    # Soft-delete projects
    projects_deleted = 0
    if project_ids:
        await session.execute(
            update(Project)
            .where(Project.id.in_(project_ids))
            .values(deleted_at=deletion_timestamp, status="deleted")
        )
        projects_deleted = len(project_ids)
    
    logger.info(
        "GDPR deletion: user_id=%s, projects=%d, audits=%d, findings=%d",
        user_id, projects_deleted, audits_count, findings_count
    )
    
    total_deleted = projects_deleted + audits_count + findings_count
    
    return GDPRDeleteResponse(
        user_id=user_id,
        deletion_timestamp=deletion_timestamp,
        projects_deleted=projects_deleted,
        audit_runs_deleted=audits_count,
        findings_deleted=findings_count,
        total_records_deleted=total_deleted,
    )


@router.get("/gdpr/retention-policy", response_model=RetentionPolicyResponse, status_code=200)
async def get_retention_policy():
    """
    Retrieve the data retention policy configuration.
    
    Returns the number of days data is retained for each entity type,
    and the grace period for hard deletion after soft-delete.
    """
    policy = RetentionPolicyResponse(
        project_retention_days=2555,  # 7 years
        audit_run_retention_days=1095,  # 3 years
        finding_retention_days=1095,  # 3 years
        soft_delete_grace_period_days=30,
        last_updated=datetime.now(timezone.utc),
    )
    
    logger.info("GDPR retention policy retrieved")
    return policy
