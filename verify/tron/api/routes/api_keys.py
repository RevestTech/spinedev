"""Manage scoped API keys (master key only)."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tron.api.middleware.auth import require_api_key, require_master_api_key
from tron.api.middleware.scopes import enforce_api_key_route_scope
from tron.domain.models import ApiKey
from tron.infra.db.session import get_session

router = APIRouter(
    dependencies=[
        Depends(require_api_key),
        Depends(enforce_api_key_route_scope),
    ]
)


class ApiKeyCreate(BaseModel):
    label: str = Field(..., min_length=1, max_length=255)
    scopes: list[str] = Field(default_factory=lambda: ["*"])


class ApiKeyCreated(BaseModel):
    id: UUID
    label: str
    scopes: list[str]
    api_key: str = Field(
        ...,
        description="Shown once. Store securely.",
    )


class ApiKeySummary(BaseModel):
    id: UUID
    label: str
    scopes: list[str]
    active: bool
    created_at: datetime


@router.post("/api-keys", response_model=ApiKeyCreated, dependencies=[Depends(require_master_api_key)])
async def create_api_key(body: ApiKeyCreate, session: AsyncSession = Depends(get_session)):
    plain = f"tron_{secrets.token_urlsafe(32)}"
    key_hash = hashlib.sha256(plain.encode("utf-8")).hexdigest()
    row = ApiKey(
        label=body.label.strip(),
        key_hash=key_hash,
        scopes=list(body.scopes) if body.scopes else ["*"],
        active=True,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return ApiKeyCreated(
        id=row.id,
        label=row.label,
        scopes=list(row.scopes) if isinstance(row.scopes, list) else [],
        api_key=plain,
    )


@router.get("/api-keys", response_model=list[ApiKeySummary], dependencies=[Depends(require_master_api_key)])
async def list_api_keys(session: AsyncSession = Depends(get_session)):
    res = await session.execute(
        select(ApiKey)
        .where(ApiKey.revoked_at.is_(None), ApiKey.active.is_(True))
        .order_by(ApiKey.created_at.desc())
    )
    keys = res.scalars().all()
    return [
        ApiKeySummary(
            id=k.id,
            label=k.label,
            scopes=list(k.scopes) if isinstance(k.scopes, list) else [],
            active=k.active,
            created_at=k.created_at,
        )
        for k in keys
    ]


@router.delete("/api-keys/{key_id}", dependencies=[Depends(require_master_api_key)])
async def revoke_api_key(
    key_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> Response:
    row = await session.get(ApiKey, key_id)
    if not row:
        raise HTTPException(status_code=404, detail="API key not found")
    row.active = False
    row.revoked_at = datetime.now(timezone.utc)
    await session.commit()
    return Response(status_code=204)


class ApiKeyAuditLogRow(BaseModel):
    id: UUID
    api_key_id: Optional[UUID] = None
    is_master: bool
    is_admin_session: bool
    method: str
    path: str
    status_code: Optional[int] = None
    remote_addr: Optional[str] = None
    user_agent: Optional[str] = None
    created_at: datetime


@router.get(
    "/api-keys/{key_id}/usage",
    response_model=list[ApiKeyAuditLogRow],
    dependencies=[Depends(require_master_api_key)],
)
async def list_api_key_usage(
    key_id: UUID,
    limit: int = 200,
    session: AsyncSession = Depends(get_session),
):
    """Return recent audit-log rows for one API key.

    Master-only — answers "show me everywhere this key has been used"
    for security incident response. Default limit 200 most recent;
    capped at 5000 to keep responses bounded.
    """
    from tron.domain.models import ApiKeyAuditLog

    if not await session.get(ApiKey, key_id):
        raise HTTPException(status_code=404, detail="API key not found")

    capped = max(1, min(limit, 5000))
    res = await session.execute(
        select(ApiKeyAuditLog)
        .where(ApiKeyAuditLog.api_key_id == key_id)
        .order_by(ApiKeyAuditLog.created_at.desc())
        .limit(capped)
    )
    rows = res.scalars().all()
    return [
        ApiKeyAuditLogRow(
            id=r.id,
            api_key_id=r.api_key_id,
            is_master=r.is_master,
            is_admin_session=r.is_admin_session,
            method=r.method,
            path=r.path,
            status_code=r.status_code,
            remote_addr=r.remote_addr,
            user_agent=r.user_agent,
            created_at=r.created_at,
        )
        for r in rows
    ]
