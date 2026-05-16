"""
Security headers middleware.

Adds OWASP-recommended security headers to all HTTP responses:
- X-Content-Type-Options: nosniff (prevent MIME sniffing)
- X-Frame-Options: DENY (prevent clickjacking)
- X-XSS-Protection: 1; mode=block (enable XSS filter in legacy browsers)
- Strict-Transport-Security: max-age=31536000 (1 year HSTS) on HTTPS responses only
- Referrer-Policy: strict-origin-when-cross-origin (privacy)
- Permissions-Policy: camera=(), microphone=(), geolocation=() (disable powerful APIs)
- Cache-Control: no-store (API responses should never be cached)
- Content-Security-Policy: default-src 'self'; frame-ancestors 'none'

Uses raw ASGI middleware for zero-overhead instrumentation.
"""

from __future__ import annotations

import logging

from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)


def _request_is_https(scope: Scope) -> bool:
    """True when the client-facing request is HTTPS (direct or via X-Forwarded-Proto)."""
    scheme = str(scope.get("scheme") or "http").lower()
    if scheme == "https":
        return True
    for key, value in scope.get("headers") or []:
        if key.lower() != b"x-forwarded-proto":
            continue
        first = value.decode(errors="replace").split(",")[0].strip().lower()
        return first == "https"
    return False


class SecurityHeadersMiddleware:
    """ASGI middleware that adds security headers to all HTTP responses."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                
                # Security headers
                extra = [
                    (b"x-content-type-options", b"nosniff"),
                    (b"x-frame-options", b"DENY"),
                    (b"x-xss-protection", b"1; mode=block"),
                    (b"referrer-policy", b"strict-origin-when-cross-origin"),
                    (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
                    (b"cache-control", b"no-store"),
                    (b"content-security-policy", b"default-src 'self'; frame-ancestors 'none'"),
                ]
                if _request_is_https(scope):
                    extra.insert(
                        3,
                        (b"strict-transport-security", b"max-age=31536000; includeSubDomains"),
                    )
                headers.extend(extra)
                
                message["headers"] = headers
            
            await send(message)

        await self.app(scope, receive, send_wrapper)
