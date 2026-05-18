"""
shared/identity/middleware.py
=============================

FastAPI dependencies for OIDC-authenticated requests.

Public surface:

* ``current_user(authorization: str = Header(...))`` — required-auth dependency.
  Returns a ``User``; raises ``HTTPException(401)`` on any failure.
* ``optional_user(authorization: str | None = Header(None))`` — same, but
  returns ``None`` if the header is missing (rather than 401-ing).

Wave 0 scope:

* Bearer JWT only. We deliberately do not introspect cookies, sessions, or
  reference tokens — those are Wave 3 work.
* The ``KeycloakClient`` instance is process-wide and is set once at app
  startup via ``set_keycloak_client(client)``. Wave 3 wires this in
  ``shared/api/app.py``; for Wave 0 the setter is exposed so tests and
  smoke scripts can inject mocks.

We do NOT touch ``shared/api/dependencies.py`` from Wave 0 — Wave 3 swaps
its header-stub ``current_user`` for the one defined here.
"""

from __future__ import annotations

from typing import Any

try:  # pragma: no cover - guarded so py_compile works without fastapi
    from fastapi import Header, HTTPException, status
except Exception:  # pragma: no cover

    def Header(default: Any = None, **_kwargs: Any) -> Any:  # type: ignore[misc]
        """Minimal Header() shim so the module imports without FastAPI installed."""
        return default

    class HTTPException(Exception):  # type: ignore[no-redef]
        """Minimal HTTPException stand-in so the module loads everywhere."""

        def __init__(
            self,
            status_code: int,
            detail: str | None = None,
            headers: dict[str, str] | None = None,
        ) -> None:
            super().__init__(detail or "")
            self.status_code = status_code
            self.detail = detail
            self.headers = headers

    class _StatusShim:  # noqa: D401 - shim
        """Minimal subset of starlette.status."""

        HTTP_401_UNAUTHORIZED = 401
        HTTP_403_FORBIDDEN = 403
        HTTP_500_INTERNAL_SERVER_ERROR = 500

    status = _StatusShim()  # type: ignore[assignment]


from .keycloak_client import InvalidTokenError, KeycloakClient
from .models import User


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class AuthenticationError(HTTPException):
    """401 Unauthorized — convenience wrapper around HTTPException."""

    def __init__(self, detail: str = "Not authenticated") -> None:
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            headers={"WWW-Authenticate": 'Bearer realm="spine"'},
        )


# ---------------------------------------------------------------------------
# Process-wide KeycloakClient registry
# ---------------------------------------------------------------------------


_KEYCLOAK_CLIENT: KeycloakClient | None = None


def set_keycloak_client(client: KeycloakClient | None) -> None:
    """Install (or clear) the process-wide KeycloakClient.

    Wave 3 calls this once at FastAPI startup. Tests use it to inject
    mock clients.
    """
    global _KEYCLOAK_CLIENT
    _KEYCLOAK_CLIENT = client


def get_keycloak_client() -> KeycloakClient:
    """Return the registered KeycloakClient or raise a 500."""
    if _KEYCLOAK_CLIENT is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="KeycloakClient not configured; call set_keycloak_client() at startup",
        )
    return _KEYCLOAK_CLIENT


# ---------------------------------------------------------------------------
# Bearer-token extraction
# ---------------------------------------------------------------------------


def bearer_token_from_header(authorization: str | None) -> str | None:
    """Extract a Bearer token from an ``Authorization`` header value."""
    if not authorization:
        return None
    parts = authorization.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    return token or None


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------


async def current_user(
    authorization: str = Header(..., alias="Authorization"),
) -> User:
    """Required-auth dependency: validate the Bearer JWT, return a ``User``.

    Raises ``HTTPException(401)`` if the header is missing/malformed or
    if Keycloak rejects the token.
    """
    token = bearer_token_from_header(authorization)
    if token is None:
        raise AuthenticationError("Missing or malformed Authorization: Bearer header")

    client = get_keycloak_client()
    try:
        claims = await client.verify_token(token)
    except InvalidTokenError as exc:
        raise AuthenticationError(str(exc)) from exc
    return User.from_claims(claims)


async def optional_user(
    authorization: str | None = Header(None, alias="Authorization"),
) -> User | None:
    """Optional-auth variant: return ``None`` when no header is present.

    Still raises 401 when a header IS present but the token is invalid —
    silently downgrading a bad token to anonymous would be a security
    footgun.
    """
    if authorization is None:
        return None
    token = bearer_token_from_header(authorization)
    if token is None:
        raise AuthenticationError("Malformed Authorization header")

    client = get_keycloak_client()
    try:
        claims = await client.verify_token(token)
    except InvalidTokenError as exc:
        raise AuthenticationError(str(exc)) from exc
    return User.from_claims(claims)
