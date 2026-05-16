"""
API key authentication.

Validates `X-API-Key` against the vault master key, then against hashed rows in
`api_keys` (see migration005). Master key has full access; scoped keys carry
`scopes` (JSON array; `"*"` means all routes for this phase).
"""

from __future__ import annotations

import hashlib
import hmac
import logging

from fastapi import Depends, HTTPException, Request, Security
from fastapi.security import APIKeyHeader
from sqlalchemy import select

from tron.api.admin_session import ADMIN_COOKIE_NAME, verify_admin_jwt
from tron.domain.models import ApiKey
from tron.infra.db.session import _session_factory

logger = logging.getLogger(__name__)

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def lookup_scoped_api_key_scopes(plain_key: str) -> frozenset[str] | None:
    """
    Resolve a non-master API key against ``api_keys``.

    Returns scopes (possibly empty) when the key is valid; ``None`` when invalid
    or when the DB factory is unavailable.
    """
    key_hash = hashlib.sha256(plain_key.encode("utf-8")).hexdigest()
    if _session_factory is None:
        return None
    try:
        async with _session_factory() as session:
            row = await session.scalar(
                select(ApiKey).where(
                    ApiKey.key_hash == key_hash,
                    ApiKey.active.is_(True),
                    ApiKey.revoked_at.is_(None),
                )
            )
    except Exception as exc:
        logger.warning("api_keys lookup failed: %s", exc)
        return None

    if row is None:
        return None

    scopes_raw = row.scopes if isinstance(row.scopes, list) else []
    normalized = [str(s).strip() for s in scopes_raw if str(s).strip()]
    if "*" in normalized:
        return frozenset({"*"})
    return frozenset(normalized)


async def require_api_key(
    request: Request,
    api_key: str | None = Security(api_key_header),
) -> str:
    """
    Dependency: validates ``X-API-Key`` (master or ``api_keys`` table) **or**
    a valid admin UI session cookie (JWT from ``POST /api/admin/login``).

    Sets ``request.state.api_key_is_master`` and ``request.state.api_key_scopes``.
    """
    master_key = request.app.state.secrets.get("auth/master-key")
    jwt_secret = request.app.state.secrets.get("auth/jwt-secret")

    # Prefer admin UI cookie so a stale X-API-Key in localStorage does not shadow a valid session.
    cookie_raw = request.cookies.get(ADMIN_COOKIE_NAME)
    if jwt_secret and cookie_raw and verify_admin_jwt(cookie_raw, jwt_secret):
        request.state.api_key_is_master = True
        request.state.api_key_scopes = frozenset({"*"})
        request.state.admin_ui_session = True
        return "__admin_ui_session__"

    if not api_key:
        raise HTTPException(
            status_code=401,
            detail="Not authenticated. Log in via POST /api/admin/login or provide X-API-Key.",
        )

    if not master_key:
        logger.error("Master key not loaded from keyvault")
        raise HTTPException(status_code=500, detail="Authentication not configured")

    if hmac.compare_digest(api_key, master_key):
        request.state.api_key_is_master = True
        request.state.api_key_scopes = frozenset({"*"})
        request.state.admin_ui_session = False
        return api_key

    request.state.api_key_is_master = False
    request.state.admin_ui_session = False

    scopes = await lookup_scoped_api_key_scopes(api_key)
    if scopes is None:
        if _session_factory is None:
            _host = request.client.host if request.client else "unknown"
            logger.warning(
                "Invalid API key attempt from %s (scoped keys require DB; master key only in this process)",
                _host,
            )
        else:
            logger.warning(
                "Invalid API key attempt from %s",
                request.client.host if request.client else "unknown",
            )
        raise HTTPException(status_code=403, detail="Invalid API key")

    request.state.api_key_scopes = scopes
    return api_key


async def require_master_api_key(
    request: Request,
    _: str = Depends(require_api_key),
) -> None:
    """Only the vault master key may manage API keys."""
    if not getattr(request.state, "api_key_is_master", False):
        raise HTTPException(
            status_code=403,
            detail="This operation requires the master API key.",
        )
