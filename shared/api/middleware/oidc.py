"""OIDC cookie/session middleware for the Hub SPA browser flow (#25).

Scope split with ``shared.identity``:

* ``shared.identity.current_user`` validates **Bearer JWTs** for API callers
  (CLI, agent harness, programmatic clients).
* This module adds the **cookie/session** layer the Hub SPA needs for the
  browser auth-code flow — i.e. a user logs in once via Keycloak, gets a
  session cookie, and subsequent SPA requests don't need to ship Bearer
  tokens explicitly. The middleware translates the cookie into an
  ``Authorization: Bearer …`` header *before* the dependency graph runs,
  so the rest of the API surface only sees the Bearer contract.

Per design decision #25, every auth concern delegates to Keycloak —
this module never validates passwords, MFA, social, SAML, or SCIM. It
only:

1. Issues a Keycloak login redirect (``GET /api/v2/auth/login``).
2. Receives the code callback (``GET /api/v2/auth/callback``), exchanges
   it for tokens via ``KeycloakClient.token_url``, signs a session
   cookie that wraps the access token.
3. Translates the cookie back into a Bearer header on subsequent
   requests so ``shared.identity.current_user`` works unchanged.
4. Logs the user out (``POST /api/v2/auth/logout``) — clears the cookie
   and redirects to the Keycloak end-session endpoint.

The cookie is signed with a vault-fetched HMAC key (per #9) — we do
*not* store the access token itself in client-side cookies; we store an
opaque session ID that maps to an in-process token store. The store is
intentionally process-local for Wave 3 part 1; Wave 3 part 2 will move
it to ``shared/runtime/session_store.py`` so federation Hubs can share
session state.

Dependencies: ``fastapi``, ``starlette``, ``httpx`` (already required by
``shared.identity``).
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import time
from dataclasses import dataclass, field
from typing import Annotated, Any, Awaitable, Callable, Optional
from urllib.parse import urlencode

try:  # pragma: no cover - guarded for py_compile
    from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response, status
    from fastapi.responses import RedirectResponse
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.types import ASGIApp

    from shared.api.dependencies import current_user
    from shared.identity.models import User
except Exception:  # pragma: no cover
    APIRouter = object  # type: ignore[assignment,misc]
    Depends = lambda x: x  # type: ignore[assignment,misc]
    FastAPI = object  # type: ignore[assignment,misc]
    Request = object  # type: ignore[assignment,misc]
    Response = object  # type: ignore[assignment,misc]
    RedirectResponse = object  # type: ignore[assignment,misc]
    BaseHTTPMiddleware = object  # type: ignore[assignment,misc]
    ASGIApp = object  # type: ignore[assignment,misc]
    current_user = None  # type: ignore[assignment,misc]
    User = object  # type: ignore[assignment,misc]

    class HTTPException(Exception):  # type: ignore[no-redef]
        """Stand-in HTTPException for py_compile in stripped environments."""

        def __init__(self, status_code: int, detail: Any = None) -> None:
            super().__init__(str(detail))
            self.status_code = status_code
            self.detail = detail

    class _StatusShim:  # noqa: D401
        HTTP_302_FOUND = 302
        HTTP_401_UNAUTHORIZED = 401
        HTTP_500_INTERNAL_SERVER_ERROR = 500

    status = _StatusShim()  # type: ignore[assignment]

logger = logging.getLogger("spine.api.oidc")

#: Name of the cookie carrying the opaque session ID. Short, no PII.
SESSION_COOKIE_NAME = "spine_sid"

#: Default session TTL — short enough to limit blast radius if a cookie
#: leaks, long enough that an SPA user doesn't hit the login flow
#: between coffees. Refresh-token rotation is Wave 3 part 2.
DEFAULT_SESSION_TTL_SECONDS = 60 * 60 * 8

#: Default scopes requested from Keycloak. ``openid`` + ``profile`` +
#: ``email`` give us everything ``User.from_claims()`` consumes.
DEFAULT_SCOPES = ("openid", "profile", "email")


# ---------------------------------------------------------------------------
# Session config + in-process store
# ---------------------------------------------------------------------------


@dataclass
class OidcSessionConfig:
    """Static config for the cookie/session layer.

    ``hmac_key`` is read at app startup from
    ``shared.secrets.get_secret('spine/api/session_hmac_key')`` — per #9
    we never accept it from env vars. The key signs cookie values so a
    cookie cannot be forged by an attacker who only owns the session ID.
    """

    hmac_key: bytes
    keycloak_login_url: str
    keycloak_logout_url: str
    redirect_uri: str
    scopes: tuple[str, ...] = field(default_factory=lambda: DEFAULT_SCOPES)
    session_ttl_seconds: int = DEFAULT_SESSION_TTL_SECONDS
    cookie_secure: bool = True
    cookie_domain: Optional[str] = None
    post_logout_redirect_uri: Optional[str] = None


@dataclass
class _Session:
    """One in-memory session entry — opaque to the client."""

    access_token: str
    expires_at: float
    user_id: str  # Keycloak ``sub`` (for diagnostics; not authoritative)


class _SessionStore:
    """Process-local session store.

    Wave 3 part 2 will swap this for a federation-aware backend
    (``shared/runtime/session_store.py``) so a user logged into Hub A
    is recognised by Hub B in the same federation. The interface here
    is the minimal surface that swap needs to satisfy: ``put`` / ``get``
    / ``invalidate``.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, _Session] = {}

    def put(self, session_id: str, session: _Session) -> None:
        """Insert (or replace) a session entry."""
        self._sessions[session_id] = session

    def get(self, session_id: str) -> Optional[_Session]:
        """Look up; returns ``None`` if missing or expired."""
        s = self._sessions.get(session_id)
        if s is None:
            return None
        if s.expires_at <= time.time():
            self._sessions.pop(session_id, None)
            return None
        return s

    def invalidate(self, session_id: str) -> None:
        """Drop a session ID — used on logout."""
        self._sessions.pop(session_id, None)


_GLOBAL_STORE = _SessionStore()
_GLOBAL_CONFIG: OidcSessionConfig | None = None


def set_session_config(cfg: OidcSessionConfig | None) -> None:
    """Install (or clear) the global session config — called at startup."""
    global _GLOBAL_CONFIG
    _GLOBAL_CONFIG = cfg


def get_session_config() -> OidcSessionConfig:
    """Return the global session config; raise if unset."""
    if _GLOBAL_CONFIG is None:
        raise HTTPException(
            status_code=getattr(status, "HTTP_500_INTERNAL_SERVER_ERROR", 500),
            detail="OIDC session middleware not configured",
        )
    return _GLOBAL_CONFIG


def get_session_store() -> _SessionStore:
    """Return the process-local session store (test seam)."""
    return _GLOBAL_STORE


# ---------------------------------------------------------------------------
# Cookie signing helpers
# ---------------------------------------------------------------------------


def _sign(value: str, hmac_key: bytes) -> str:
    """Return ``value|hex(hmac_sha256(value, key))``."""
    mac = hmac.new(hmac_key, value.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{value}|{mac}"


def _verify_signed(cookie_value: str, hmac_key: bytes) -> Optional[str]:
    """Constant-time verify; return ``value`` or ``None`` if forged/malformed."""
    if not cookie_value or "|" not in cookie_value:
        return None
    value, _, mac = cookie_value.rpartition("|")
    expected = hmac.new(hmac_key, value.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(mac, expected):
        return None
    return value


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------


class OidcCookieMiddleware(BaseHTTPMiddleware):  # type: ignore[misc]
    """Translate a signed session cookie into an ``Authorization`` header.

    If the request already carries a Bearer header we leave it alone —
    explicit Bearer always wins (CLI > SPA). Otherwise: look up the
    cookie, verify the signature, fetch the access token from the
    session store, and inject it as ``Authorization: Bearer <token>``
    *before* the request reaches the dependency graph.

    The middleware never authenticates or rejects — that's the
    dependency layer's job. A missing/invalid cookie just means the
    request remains anonymous; downstream ``current_user`` will 401.
    """

    def __init__(self, app: "ASGIApp", config: OidcSessionConfig | None = None) -> None:
        super().__init__(app)
        self._cfg = config  # falls back to module-level config at request time

    async def dispatch(  # type: ignore[override]
        self, request: "Request", call_next: Callable[["Request"], Awaitable[Any]]
    ) -> "Response":
        existing = request.headers.get("Authorization")
        if not existing:
            cfg = self._cfg or _GLOBAL_CONFIG
            if cfg is not None:
                cookie = request.cookies.get(SESSION_COOKIE_NAME) if hasattr(request, "cookies") else None
                if cookie:
                    session_id = _verify_signed(cookie, cfg.hmac_key)
                    if session_id is not None:
                        sess = _GLOBAL_STORE.get(session_id)
                        if sess is not None:
                            # Starlette ``Headers`` is immutable; mutate raw scope.
                            new_hdr = (b"authorization", f"Bearer {sess.access_token}".encode("ascii"))
                            scope_headers = list(request.scope.get("headers", []))
                            scope_headers.append(new_hdr)
                            request.scope["headers"] = scope_headers
        return await call_next(request)


# ---------------------------------------------------------------------------
# Login / callback / logout routes
# ---------------------------------------------------------------------------


def build_login_redirect_url(
    cfg: OidcSessionConfig, *, state: str, nonce: str
) -> str:
    """Construct the Keycloak authorization-code URL."""
    params = {
        "response_type": "code",
        "client_id": "spine-hub",
        "redirect_uri": cfg.redirect_uri,
        "scope": " ".join(cfg.scopes),
        "state": state,
        "nonce": nonce,
    }
    sep = "&" if "?" in cfg.keycloak_login_url else "?"
    return f"{cfg.keycloak_login_url}{sep}{urlencode(params)}"


def install_oidc_routes(
    app: "FastAPI",
    *,
    token_exchanger: Callable[[str], Awaitable[dict[str, Any]]] | None = None,
) -> None:
    """Register ``/api/v2/auth/{login,callback,logout,whoami}`` on ``app``.

    ``token_exchanger`` is a seam for tests — production callers leave it
    ``None`` and the route uses ``shared.identity.get_keycloak_client()``
    to swap a code for an access token. The seam keeps the route async-
    testable without spinning up Keycloak.
    """

    router = APIRouter(prefix="/api/v2/auth", tags=["auth"])

    @router.get("/login")
    async def login() -> "Response":
        cfg = get_session_config()
        state = secrets.token_urlsafe(24)
        nonce = secrets.token_urlsafe(24)
        url = build_login_redirect_url(cfg, state=state, nonce=nonce)
        return RedirectResponse(url=url, status_code=302)

    @router.get("/callback")
    async def callback(code: str = "", state: str = "") -> "Response":
        cfg = get_session_config()
        if not code:
            raise HTTPException(status_code=400, detail="missing 'code'")
        if token_exchanger is not None:
            tokens = await token_exchanger(code)
        else:
            tokens = await _default_token_exchange(code, cfg)
        access_token = tokens.get("access_token")
        if not access_token:
            raise HTTPException(status_code=502, detail="keycloak returned no access_token")
        session_id = secrets.token_urlsafe(32)
        # We use ``id_token`` claims if present so we don't decode JWT in
        # the SPA path; the access token decode happens later via the
        # standard ``current_user`` dependency.
        user_id = (tokens.get("id_token_claims") or {}).get("sub", "unknown")
        _GLOBAL_STORE.put(
            session_id,
            _Session(
                access_token=access_token,
                expires_at=time.time() + cfg.session_ttl_seconds,
                user_id=user_id,
            ),
        )
        signed = _sign(session_id, cfg.hmac_key)
        # Successful callback → land on the SPA root (or wherever the SPA
        # passed in ``state`` — Wave 3 part 2 wires deep-link handling).
        resp = RedirectResponse(url="/", status_code=302)
        resp.set_cookie(
            SESSION_COOKIE_NAME,
            signed,
            max_age=cfg.session_ttl_seconds,
            httponly=True,
            secure=cfg.cookie_secure,
            samesite="lax",
            domain=cfg.cookie_domain,
            path="/",
        )
        return resp

    @router.get("/whoami")
    async def whoami(
        user: Annotated[User, Depends(current_user)],
    ) -> dict[str, Any]:
        """Dedicated SPA session probe (Wave 4 contract).

        Mirrors ``GET /api/v2/registry/me`` so callers can use the auth
        prefix without reaching into the registry surface.
        """
        from shared.api.routes.registry import session_user_payload  # noqa: PLC0415

        return {"ok": True, "user": session_user_payload(user)}

    @router.post("/logout")
    async def logout(request: "Request") -> "Response":
        cfg = get_session_config()
        cookie = request.cookies.get(SESSION_COOKIE_NAME) if hasattr(request, "cookies") else None
        if cookie:
            sid = _verify_signed(cookie, cfg.hmac_key)
            if sid:
                _GLOBAL_STORE.invalidate(sid)
        redirect_target = cfg.post_logout_redirect_uri or cfg.keycloak_logout_url
        resp = RedirectResponse(url=redirect_target, status_code=302)
        resp.delete_cookie(SESSION_COOKIE_NAME, path="/", domain=cfg.cookie_domain)
        return resp

    app.include_router(router)


async def _default_token_exchange(code: str, cfg: OidcSessionConfig) -> dict[str, Any]:
    """Exchange auth-code for tokens via Keycloak (httpx POST).

    Lives here (not in ``shared.identity``) because it's an SPA-flow
    concern, not a JWT-verification concern. Identity is responsible
    for *trusting* tokens; the SPA flow is responsible for *getting* them.
    """
    try:
        import httpx  # noqa: PLC0415
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("httpx is required for the OIDC SPA flow") from exc
    from shared.identity import get_keycloak_client  # noqa: PLC0415

    client = get_keycloak_client()
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": client.client_id,
        "redirect_uri": cfg.redirect_uri,
    }
    if client.client_secret:
        data["client_secret"] = client.client_secret
    async with httpx.AsyncClient(timeout=10.0) as http:
        r = await http.post(client.token_url, data=data)
    if r.status_code >= 400:
        raise HTTPException(
            status_code=502,
            detail=f"keycloak token endpoint returned {r.status_code}",
        )
    return r.json()


__all__ = [
    "SESSION_COOKIE_NAME",
    "DEFAULT_SESSION_TTL_SECONDS",
    "OidcCookieMiddleware",
    "OidcSessionConfig",
    "build_login_redirect_url",
    "install_oidc_routes",
    "set_session_config",
    "get_session_config",
    "get_session_store",
]
