"""
Finding triage: dismiss (SEC-4) and list/delete fingerprint suppressions.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from tron.domain.models import Finding, FindingSuppression, Project
from tron.api.middleware.auth import require_api_key
from tron.api.middleware.scopes import enforce_api_key_route_scope
from tron.infra.db.session import get_session

logger = logging.getLogger(__name__)
router = APIRouter(
    dependencies=[
        Depends(require_api_key),
        Depends(enforce_api_key_route_scope),
    ]
)


class DismissBody(BaseModel):
    reason: str = Field(..., min_length=1, max_length=2000)


class FindingSuppressionResponse(BaseModel):
    project_id: UUID
    fingerprint: str
    reason: str
    created_at: datetime

    model_config = {"from_attributes": True}


@router.post(
    "/findings/{finding_id}/dismiss",
    status_code=204,
    response_class=Response,
)
async def dismiss_finding(
    finding_id: UUID,
    body: DismissBody,
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Record suppression by fingerprint and mark finding ``dismissed``."""
    r = await session.execute(select(Finding).where(Finding.id == finding_id))
    f = r.scalar_one_or_none()
    if not f:
        raise HTTPException(status_code=404, detail="Finding not found")
    f.status = "dismissed"
    f.resolution = "dismissed"
    f.resolved_at = datetime.now(timezone.utc)
    ex = await session.execute(
        select(FindingSuppression).where(
            FindingSuppression.project_id == f.project_id,
            FindingSuppression.fingerprint == f.fingerprint,
        )
    )
    sup = ex.scalar_one_or_none()
    if sup:
        sup.reason = body.reason
    else:
        session.add(
            FindingSuppression(
                project_id=f.project_id,
                fingerprint=f.fingerprint,
                reason=body.reason,
            )
        )
    await session.commit()
    logger.info("Finding %s dismissed (fingerprint %s…)", finding_id, f.fingerprint[:8])
    return Response(status_code=204)


@router.post(
    "/findings/{finding_id}/restore",
    status_code=204,
    response_class=Response,
)
async def restore_finding(
    finding_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Re-open a finding and remove its fingerprint from the project suppression set."""
    r = await session.execute(select(Finding).where(Finding.id == finding_id))
    f = r.scalar_one_or_none()
    if not f:
        raise HTTPException(status_code=404, detail="Finding not found")
    f.status = "open"
    f.resolution = None
    f.resolved_at = None
    await session.execute(
        delete(FindingSuppression).where(
            FindingSuppression.project_id == f.project_id,
            FindingSuppression.fingerprint == f.fingerprint,
        )
    )
    await session.commit()
    return Response(status_code=204)


@router.get(
    "/projects/{project_id}/finding-suppressions",
    response_model=List[FindingSuppressionResponse],
)
async def list_finding_suppressions(
    project_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> List[FindingSuppressionResponse]:
    pr = await session.execute(
        select(Project).where(
            Project.id == project_id,
            Project.deleted_at.is_(None),
        )
    )
    if not pr.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Project not found")
    r = await session.execute(
        select(FindingSuppression)
        .where(FindingSuppression.project_id == project_id)
        .order_by(FindingSuppression.created_at.desc())
    )
    return [FindingSuppressionResponse.model_validate(x) for x in r.scalars().all()]


@router.delete(
    "/projects/{project_id}/finding-suppressions/{fingerprint}",
    status_code=204,
    response_class=Response,
)
async def delete_finding_suppression(
    project_id: UUID,
    fingerprint: str,
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Remove a suppression; the fingerprint may reappear on the next audit."""
    r = await session.execute(
        delete(FindingSuppression).where(
            FindingSuppression.project_id == project_id,
            FindingSuppression.fingerprint == fingerprint,
        )
    )
    if r.rowcount == 0:
        raise HTTPException(status_code=404, detail="Suppression not found")
    await session.commit()
    return Response(status_code=204)
