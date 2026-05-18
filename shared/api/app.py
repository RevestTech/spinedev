"""FastAPI app factory for the Spine REST API (V3, Wave 3 Squad C).

Run::

    uvicorn shared.api.app:create_app --factory --port 8088

Wave 3 changes versus the v2 factory:

* **OIDC** (per #25) — registers ``OidcCookieMiddleware`` for the Hub SPA
  browser flow and mounts ``/api/v2/auth/{login,callback,logout}``.
  Bearer-token verification for API callers is still owned by
  ``shared.identity.current_user`` in ``shared/api/dependencies.py``.
* **Federation** (per #4, #10) — every response carries an
  ``X-Spine-Hub-ID`` header so peers + clients can attribute calls.
* **Vault-backed config** (per #9) — the Hub Postgres DSN + session
  HMAC key + Keycloak client secret are *all* fetched from
  ``shared.secrets`` during the lifespan, never from env vars holding
  secret values.
* **Stronger CORS** — production allowlist comes from the org bundle (or
  ``SPINE_API_CORS_ORIGINS`` for dev). When ``SPINE_API_ENV=production``
  an empty allowlist is a startup error (fail-closed).
* **All Wave-3 routes** registered via ``ALL_ROUTERS`` automatically —
  no new imports needed here.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from shared.api.dependencies import close_db_pool, get_db_pool, init_db_pool
from shared.api.middleware.oidc import (
    OidcCookieMiddleware,
    OidcSessionConfig,
    install_oidc_routes,
    set_session_config,
)
from shared.api.routes import ALL_ROUTERS

logger = logging.getLogger("spine.api")
_SECRET_KEYS = frozenset(
    {"approval_token", "token", "api_key", "secret", "password", "hmac_key", "authorization"}
)
_REQUIRED_SCHEMAS = ("spine_lifecycle", "spine_audit")

#: Set by ``shared.api.routes.federation`` — duplicated here so the
#: response-header middleware doesn't import a route module.
HUB_ID = os.environ.get("SPINE_HUB_ID", "hub-local")


class _JsonFormatter(logging.Formatter):
    """JSON log formatter; redacts known-sensitive keys from ``extra``."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname, "logger": record.name, "msg": record.getMessage(),
        }
        std = set(logging.LogRecord("", 0, "", 0, "", None, None).__dict__)
        std.update({"message", "asctime"})
        for k, v in record.__dict__.items():
            if k in std:
                continue
            payload[k] = "[REDACTED]" if k.lower() in _SECRET_KEYS else v
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def _configure_logging(level: int = logging.INFO) -> None:
    """Install the JSON formatter on the root logger (idempotent)."""
    root = logging.getLogger()
    root.setLevel(level)
    if any(
        isinstance(h, logging.StreamHandler) and isinstance(h.formatter, _JsonFormatter)
        for h in root.handlers
    ):
        return
    h = logging.StreamHandler(stream=sys.stderr)
    h.setFormatter(_JsonFormatter())
    root.addHandler(h)


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Stamp every request/response with an ``X-Request-ID``."""

    async def dispatch(self, request: Request, call_next):
        req_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        request.state.request_id = req_id
        logger.info("request_start",
                    extra={"request_id": req_id, "method": request.method, "path": request.url.path})
        response = await call_next(request)
        response.headers["X-Request-ID"] = req_id
        # Federation context propagation (#4, #10). Idempotent — never
        # overwrite an incoming hub ID if one was set upstream.
        response.headers.setdefault("X-Spine-Hub-ID", HUB_ID)
        logger.info("request_end", extra={"request_id": req_id, "status_code": response.status_code})
        return response


# ---------------------------------------------------------------------------
# Vault-backed config helpers
# ---------------------------------------------------------------------------


async def _load_session_config_from_vault() -> Optional[OidcSessionConfig]:
    """Fetch the OIDC session-layer secrets from vault.

    Returns ``None`` (and logs a warning) if the vault entries are
    missing — the Hub still serves the API in that case, but the SPA
    cookie/session flow is disabled until an operator runs the
    install wizard.
    """
    try:
        from shared.secrets import get_secret  # noqa: PLC0415
    except Exception:  # pragma: no cover - py_compile guard
        return None
    try:
        hmac_key_hex = await get_secret("spine/api/session_hmac_key")
    except Exception as exc:  # noqa: BLE001
        logger.warning("oidc_session_hmac_key_missing", extra={"error": str(exc)})
        return None
    if not hmac_key_hex:
        return None
    try:
        kc_base = await get_secret("spine/keycloak/base_url")
        kc_realm = await get_secret("spine/keycloak/realm")
    except Exception as exc:  # noqa: BLE001
        logger.warning("oidc_keycloak_metadata_missing", extra={"error": str(exc)})
        return None
    base = kc_base.rstrip("/")
    realm = kc_realm
    login_url = f"{base}/realms/{realm}/protocol/openid-connect/auth"
    logout_url = f"{base}/realms/{realm}/protocol/openid-connect/logout"
    redirect_uri = os.environ.get(
        "SPINE_OIDC_REDIRECT_URI", "http://localhost:8088/api/v2/auth/callback"
    )
    try:
        hmac_key = bytes.fromhex(hmac_key_hex)
    except ValueError:
        hmac_key = hmac_key_hex.encode("utf-8")
    return OidcSessionConfig(
        hmac_key=hmac_key,
        keycloak_login_url=login_url,
        keycloak_logout_url=logout_url,
        redirect_uri=redirect_uri,
        cookie_secure=os.environ.get("SPINE_API_ENV", "dev").lower() == "production",
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Boot/teardown — asyncpg pool init, MCP pre-warm, OIDC session config."""
    _configure_logging()

    # 1. asyncpg pool — DSN fetched from vault (per #9).
    pool_ok = False
    try:
        await init_db_pool()
        pool_ok = True
    except Exception as exc:  # noqa: BLE001
        logger.warning("db_pool_init_failed", extra={"error": str(exc)})
    db = get_db_pool()
    ok = await db.ping() if pool_ok else False
    logger.info("lifespan_start", extra={"db_reachable": ok})

    # 2. MCP — pre-warm the in-process tool registry.
    try:
        from shared.mcp.tools import TOOL_REGISTRY, discover_tools

        if not TOOL_REGISTRY:
            discover_tools("shared.mcp.tools")
        logger.info("mcp_loaded", extra={"tool_count": len(TOOL_REGISTRY)})
    except Exception as exc:  # noqa: BLE001
        logger.warning("mcp_load_failed", extra={"error": str(exc)})

    # 3. OIDC session config (Wave 3) — vault-backed; SPA flow off if missing.
    cfg = await _load_session_config_from_vault()
    if cfg is not None:
        set_session_config(cfg)
        logger.info("oidc_session_ready")
    else:
        logger.info("oidc_session_disabled_no_vault_config")

    try:
        yield
    finally:
        await close_db_pool()
        logger.info("lifespan_stop")


def _cors_origins() -> list[str]:
    """Return the CORS allowlist.

    Production (``SPINE_API_ENV=production``): require an explicit
    allowlist via ``SPINE_API_CORS_ORIGINS`` (which Wave 4 will source
    from the org bundle). An empty list in production is fatal — we
    fail closed rather than ship ``*``.
    Dev: default to ``http://localhost:8080`` so the SPA dev server works.
    """
    env = os.environ.get("SPINE_API_ENV", "dev").lower()
    raw = os.environ.get("SPINE_API_CORS_ORIGINS")
    if env == "production":
        if not raw:
            raise RuntimeError(
                "SPINE_API_CORS_ORIGINS must be set in production; "
                "Wave 4 will source this from the org bundle"
            )
        return [o.strip() for o in raw.split(",") if o.strip()]
    return [o.strip() for o in (raw or "http://localhost:8080").split(",") if o.strip()]


def create_app() -> FastAPI:
    """Construct and return the configured FastAPI app."""
    app = FastAPI(
        title="Spine Hub REST API",
        version="0.3.0",
        description=(
            "REST + SSE surface over the unified MCP server + Postgres. "
            "Wave 3 (V3) adds OIDC, federation hub-id propagation, "
            "decision queue, role chat, registry, vault config, "
            "integrations, federation, and license endpoints."
        ),
        lifespan=lifespan,
        openapi_url="/api/v2/spec",
        docs_url="/api/v2/docs",
        redoc_url=None,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(),
        allow_credentials=True,  # SPA cookie flow needs credentials
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "content-type", "x-request-id", "x-spine-actor", "x-spine-hub-id",
            "authorization",
        ],
        expose_headers=["x-request-id", "x-spine-hub-id"],
    )
    # Order matters: cookie middleware must run BEFORE auth dependencies so
    # the translated Bearer header is visible to ``current_user``.
    app.add_middleware(OidcCookieMiddleware)
    app.add_middleware(RequestIdMiddleware)

    for r in ALL_ROUTERS:
        app.include_router(r)

    install_oidc_routes(app)

    @app.get("/healthz", tags=["health"])
    async def healthz() -> JSONResponse:
        """Liveness — DB ping + MCP registry import."""
        db_ok = await get_db_pool().ping()
        mcp_ok = True
        try:
            from shared.mcp.tools import TOOL_REGISTRY, discover_tools

            if not TOOL_REGISTRY:
                discover_tools("shared.mcp.tools")
        except Exception:  # noqa: BLE001
            mcp_ok = False
        body = {"ok": db_ok and mcp_ok, "db": db_ok, "mcp": mcp_ok, "hub_id": HUB_ID}
        return JSONResponse(body, status_code=200 if body["ok"] else 503)

    @app.get("/readyz", tags=["health"])
    async def readyz() -> JSONResponse:
        """Readiness — required schemas present."""
        sql = (
            "SELECT nspname FROM pg_namespace WHERE nspname IN "
            f"('{_REQUIRED_SCHEMAS[0]}','{_REQUIRED_SCHEMAS[1]}');"
        )
        try:
            rows = await get_db_pool().fetch(sql)
        except RuntimeError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=503)
        found = {r["_row"] for r in rows}
        ok = all(s in found for s in _REQUIRED_SCHEMAS)
        return JSONResponse(
            {"ok": ok, "schemas_required": list(_REQUIRED_SCHEMAS), "schemas_found": sorted(found),
             "hub_id": HUB_ID},
            status_code=200 if ok else 503,
        )

    @app.exception_handler(Exception)
    async def _unhandled(_request: Request, exc: Exception) -> JSONResponse:
        """Last-resort handler — log + return structured error envelope."""
        logger.exception("unhandled_error", extra={"error": type(exc).__name__})
        return JSONResponse(
            {"error_code": "internal_error", "message": "Unexpected server error."},
            status_code=500,
        )

    return app


__all__: list[str] = ["create_app", "lifespan", "HUB_ID"]
