"""Standards & quality gates API (proposal: centralized enforcement)."""

from __future__ import annotations

import logging
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tron.api.middleware.auth import require_api_key
from tron.api.middleware.scopes import enforce_api_key_route_scope
from tron.domain.models import Project
from tron.infra.db.session import get_session
from tron.standards.control_packs import list_pack_ids, load_pack
from tron.standards.defaults import DEFAULT_QUALITY_GATES
from tron.standards.engine import merge_quality_gates

logger = logging.getLogger(__name__)
router = APIRouter(
    dependencies=[
        Depends(require_api_key),
        Depends(enforce_api_key_route_scope),
    ]
)


class MergedGatesResponse(BaseModel):
    project_id: Optional[UUID] = None
    gates: dict[str, Any]


class ControlPackSummary(BaseModel):
    id: str


class ControlPackListResponse(BaseModel):
    items: list[ControlPackSummary]


@router.get("/standards/control-packs", response_model=ControlPackListResponse)
async def list_control_packs():
    """Built-in SOC2/HIPAA/ISO-style *reference* packs (not third-party certification)."""
    return ControlPackListResponse(
        items=[ControlPackSummary(id=i) for i in list_pack_ids()],
    )


@router.get("/standards/control-packs/{pack_id}")
async def get_control_pack(pack_id: str) -> dict[str, Any]:
    """Return one reference pack JSON by id."""
    try:
        return load_pack(pack_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Unknown control pack id")


@router.get("/standards/defaults")
async def get_default_standards() -> dict[str, Any]:
    """Built-in default quality gate contract."""
    return DEFAULT_QUALITY_GATES


@router.get("/standards/merged", response_model=MergedGatesResponse)
async def get_merged_standards(
    project_id: Optional[UUID] = Query(None),
    session: AsyncSession = Depends(get_session),
):
    """Default gates merged with optional project override."""
    override = None
    if project_id:
        res = await session.execute(
            select(Project).where(Project.id == project_id, Project.deleted_at.is_(None))
        )
        p = res.scalar_one_or_none()
        if not p:
            raise HTTPException(status_code=404, detail="Project not found")
        override = p.quality_gates_json
        company = p.company_quality_gates_json
    else:
        company = None
    return MergedGatesResponse(
        project_id=project_id,
        gates=merge_quality_gates(override, company_override=company),
    )
