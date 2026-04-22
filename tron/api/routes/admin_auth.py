"""Product admin UI: password login → httpOnly session cookie (JWT)."""

from __future__ import annotations

import hmac
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from tron.api.admin_session import ADMIN_COOKIE_NAME, issue_admin_jwt
from tron.api.config import settings
from tron.api.middleware.auth import require_api_key
from tron.infra.secrets import get_secret

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Admin UI"])


class AdminLoginBody(BaseModel):
    password: str = Field(..., min_length=1, max_length=4096)


def _admin_session_ttl_seconds() -> int:
    return int(settings.admin_session_hours * 3600)


async def _resolve_admin_password_plain(request: Request) -> Optional[str]:
    """Dedicated UI password from vault, or None if not configured."""
    try:
        raw = await get_secret("auth/admin-password")
        # Vault UIs and echo pipelines often store a trailing newline; strip edges only.
        return raw.strip() if raw else None
    except KeyError:
        return None
    except Exception as exc:
        logger.warning("Could not read auth/admin-password: %s", exc)
        return None


@router.post("/admin/login")
async def admin_login(request: Request, body: AdminLoginBody, response: Response):
    """
    Browser admin login.

    Password is checked against vault ``auth/admin-password`` when set; otherwise
    the **master API key** is accepted so a single vault secret can bootstrap the UI.
    """
    master = request.app.state.secrets.get("auth/master-key")
    if not master:
        raise HTTPException(status_code=500, detail="Authentication not configured")

    admin_pw = await _resolve_admin_password_plain(request)
    if admin_pw:
        ok = hmac.compare_digest(body.password, admin_pw)
    else:
        ok = hmac.compare_digest(body.password, master)

    if not ok:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    jwt_secret = request.app.state.secrets.get("auth/jwt-secret")
    if not jwt_secret:
        raise HTTPException(status_code=500, detail="JWT secret not configured")

    token = issue_admin_jwt(jwt_secret, _admin_session_ttl_seconds())
    secure = request.url.scheme == "https"
    response.set_cookie(
        key=ADMIN_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=_admin_session_ttl_seconds(),
        path="/",
    )
    return {"ok": True, "auth": "session"}


@router.post("/admin/logout")
async def admin_logout(response: Response):
    response.delete_cookie(ADMIN_COOKIE_NAME, path="/", samesite="lax")
    return {"ok": True}


@router.get("/admin/me")
async def admin_me(_: str = Depends(require_api_key)):
    """Presence check for SPA shell (cookie or X-API-Key)."""
    return {"ok": True}
