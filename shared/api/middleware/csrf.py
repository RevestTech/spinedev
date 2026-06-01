"""Double-submit CSRF guard for cookie-authenticated SPA mutating requests.

When the browser sends ``spine_sid`` (OIDC session cookie), state-changing
methods must also send ``X-Spine-Csrf`` matching the readable ``spine_csrf``
cookie set at login callback. Bearer-only API clients skip this check.

Per #9 this does not replace vault-only secrets; it complements SameSite=Lax
on the session cookie for cross-site POST protection.
"""

from __future__ import annotations

import os
import secrets
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from shared.api.middleware.oidc import SESSION_COOKIE_NAME

CSRF_COOKIE_NAME = "spine_csrf"
CSRF_HEADER_NAME = "x-spine-csrf"
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_CSRF_EXEMPT_PREFIXES = (
    "/healthz",
    "/readyz",
    "/api/v2/auth/",
    "/api/v2/docs",
    "/api/v2/spec",
    "/spa/",
)


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def _exempt(path: str) -> bool:
    return any(path.startswith(p) for p in _CSRF_EXEMPT_PREFIXES)


class CsrfMiddleware(BaseHTTPMiddleware):
    """Reject cookie-session mutating requests without a matching CSRF token."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if os.environ.get("SPINE_HUB_SKIP_CSRF") == "1":
            return await call_next(request)

        method = request.method.upper()
        path = request.url.path

        if method in _SAFE_METHODS or _exempt(path):
            return await call_next(request)

        # Programmatic clients use Bearer directly — no session cookie CSRF surface.
        auth = request.headers.get("authorization") or ""
        if auth.lower().startswith("bearer "):
            return await call_next(request)

        if not request.cookies.get(SESSION_COOKIE_NAME):
            return await call_next(request)

        cookie_token = request.cookies.get(CSRF_COOKIE_NAME) or ""
        header_token = request.headers.get(CSRF_HEADER_NAME) or ""
        if not cookie_token or not header_token or not secrets.compare_digest(
            cookie_token, header_token
        ):
            return JSONResponse(
                {
                    "error_code": "csrf_failed",
                    "message": "Missing or invalid CSRF token for cookie-authenticated request.",
                },
                status_code=403,
            )

        return await call_next(request)


def install_csrf_middleware(app: ASGIApp) -> ASGIApp:
    app.add_middleware(CsrfMiddleware)  # type: ignore[attr-defined]
    return app


__all__ = [
    "CSRF_COOKIE_NAME",
    "CSRF_HEADER_NAME",
    "CsrfMiddleware",
    "install_csrf_middleware",
    "new_csrf_token",
]
