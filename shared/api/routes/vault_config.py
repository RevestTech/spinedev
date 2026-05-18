"""``/api/v2/vault`` — vault config UI backend (#3 + #9).

The "vault config" Hub surface lets a hub-admin inspect the active
``SecretAdapter`` (vault URL, adapter kind, mount, status) and trigger
a rotation cycle. Per #9 we never expose secret VALUES — only metadata
(paths + kind + status).

Endpoints:

* ``GET  /api/v2/vault/status``    — adapter health + kind + endpoint
* ``GET  /api/v2/vault/secrets``   — enumerate known secret PATHS (no values)
* ``POST /api/v2/vault/rotate``    — rotate one secret (hub-admin only)

Dependencies: ``fastapi``, ``pydantic`` (already required).
"""

from __future__ import annotations

import logging
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from shared.api.dependencies import actor_label, current_user
from shared.audit.audit_record import AuditRecord, chain_to_previous
from shared.identity.models import User
from shared.identity.rbac import require_role

logger = logging.getLogger("spine.api.vault_config")
router = APIRouter(prefix="/api/v2/vault", tags=["vault"])


class VaultStatusResponse(BaseModel):
    """``GET /vault/status`` envelope."""

    model_config = ConfigDict(extra="forbid")
    ok: bool
    adapter_kind: str
    endpoint: Optional[str] = None
    healthy: bool
    last_error: Optional[str] = None


class VaultSecretList(BaseModel):
    """``GET /vault/secrets`` envelope — only PATHS, never VALUES."""

    model_config = ConfigDict(extra="forbid")
    ok: bool = True
    paths: list[str]
    prefix: str = ""


class RotateRequest(BaseModel):
    """``POST /vault/rotate`` body."""

    model_config = ConfigDict(extra="forbid")
    path: str = Field(..., min_length=1)
    reason: str = Field(..., min_length=1, max_length=4_000)


class RotateResponse(BaseModel):
    """``POST /vault/rotate`` response."""

    model_config = ConfigDict(extra="forbid")
    ok: bool
    path: str
    rotated_at: str
    actor: str
    audit_event_uuid: str


@router.get("/status", response_model=VaultStatusResponse)
async def vault_status(user: Annotated[User, Depends(current_user)]) -> VaultStatusResponse:
    """Adapter health snapshot. Reports kind + endpoint; never any value."""
    try:
        from shared.secrets import get_default_adapter  # noqa: PLC0415
    except Exception as exc:  # pragma: no cover
        raise HTTPException(500, detail={"error_code": "import_failed", "message": str(exc)})
    try:
        adapter: Any = get_default_adapter()
    except Exception as exc:  # noqa: BLE001
        return VaultStatusResponse(ok=False, adapter_kind="none", healthy=False, last_error=str(exc))
    kind = type(adapter).__name__
    endpoint = getattr(adapter, "endpoint", None) or getattr(adapter, "address", None)
    healthy = True
    last_error: Optional[str] = None
    ping = getattr(adapter, "ping", None)
    if callable(ping):
        try:
            healthy = bool(await ping())
        except Exception as exc:  # noqa: BLE001
            healthy = False
            last_error = str(exc)
    return VaultStatusResponse(
        ok=True,
        adapter_kind=kind,
        endpoint=str(endpoint) if endpoint else None,
        healthy=healthy,
        last_error=last_error,
    )


@router.get("/secrets", response_model=VaultSecretList)
async def list_vault_secrets(
    user: Annotated[User, Depends(require_role("hub-admin"))],
    prefix: str = "",
) -> VaultSecretList:
    """Enumerate vault paths. Hub-admin only; values never returned."""
    try:
        from shared.secrets import list_secrets  # noqa: PLC0415

        paths = await list_secrets(prefix)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, detail={"error_code": "vault_error", "message": str(exc)})
    return VaultSecretList(paths=list(paths), prefix=prefix)


@router.post("/rotate", response_model=RotateResponse, status_code=status.HTTP_200_OK)
async def rotate_secret(
    body: RotateRequest,
    user: Annotated[User, Depends(require_role("hub-admin"))],
) -> RotateResponse:
    """Rotate a single secret. Hub-admin only; audited."""
    try:
        from shared.secrets.rotation import rotate as _rotate  # noqa: PLC0415

        rotated_at = await _rotate(body.path)
        rotated_at_iso = str(rotated_at)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=502,
            detail={"error_code": "rotation_failed", "message": str(exc), "path": body.path},
        )
    actor = actor_label(user)
    rec = AuditRecord(
        role="hub_admin",
        subsystem="hub",
        action="vault_rotate",
        actor=actor,
        subject_type="secret",
        subject_id=body.path,
        rationale=body.reason,
        metadata={"surface": "vault_config"},
    )
    rec = chain_to_previous(rec, prev_hash=None)
    return RotateResponse(
        ok=True,
        path=body.path,
        rotated_at=rotated_at_iso,
        actor=actor,
        audit_event_uuid=str(rec.event_uuid),
    )


__all__ = ["router", "VaultStatusResponse", "VaultSecretList", "RotateRequest", "RotateResponse"]
