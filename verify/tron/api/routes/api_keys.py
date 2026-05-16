"""Manage scoped API keys (master key only)."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone
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
