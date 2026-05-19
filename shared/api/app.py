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
from pathlib import Path
from typing import Any, AsyncIterator, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from shared.api.dependencies import (
    close_db_pool,
    get_db_pool,
    get_mcp_transport,
    init_db_pool,
    set_mcp_transport,
    set_remote_mcp_client,
)
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

    # 1b. Wire the asyncpg-backed durability layer for the decision store
    # once at startup (was per-request in FIX3). Lifespan injection lets
    # the pool be cleanly torn down at shutdown and avoids re-stamping
    # the handle on every list/ack/reject call.
    try:
        from shared.api.routes.decisions import set_decisions_db  # noqa: PLC0415

        set_decisions_db(db if pool_ok else None)
        logger.info(
            "decisions_db_wired",
            extra={"durable": pool_ok},
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("decisions_db_wire_failed", extra={"error": str(exc)})

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

    # 4. Federation remote-MCP wiring (#4 control plane / #10 fractal Hub).
    # If the bundle (or, until Wave 4 ships the bundle loader, the
    # ``SPINE_FEDERATION_PARENT_MCP_URL`` env metadata override) declares
    # an upstream parent Hub, open one long-lived RemoteMcpClient at
    # startup. Vault IO happens once here, not per-request.
    remote_mcp_client = None
    parent_url = os.environ.get("SPINE_FEDERATION_PARENT_MCP_URL")
    if parent_url:
        role = os.environ.get("SPINE_FEDERATION_ROLE", "child")
        actor = os.environ.get("SPINE_FEDERATION_ACTOR", "federation_child")
        try:
            from shared.mcp.server_remote import (  # noqa: PLC0415
                RemoteMcpClient,
                RemoteMcpClientConfig,
            )

            set_mcp_transport("remote", url=parent_url, role=role, actor=actor)
            remote_cfg = RemoteMcpClientConfig(
                base_url=parent_url, role=role, actor=actor,
            )
            remote_mcp_client = await RemoteMcpClient.open(remote_cfg)
            set_remote_mcp_client(remote_mcp_client)
            logger.info(
                "remote_mcp_client_ready",
                extra={"parent_url": parent_url, "role": role},
            )
        except Exception as exc:  # noqa: BLE001 — federation parent down
            logger.warning(
                "remote_mcp_client_init_failed",
                extra={"parent_url": parent_url, "error": str(exc)},
            )
            # Fall back to in-process so the Hub stays up; federation
            # autonomy per #10 + DR layer 6 (#32) — a dead parent must
            # not take the child down with it.
            set_mcp_transport("in_process")
            set_remote_mcp_client(None)
    else:
        # Confirm in-process (default; idempotent).
        if get_mcp_transport().kind != "in_process":
            set_mcp_transport("in_process")

    try:
        yield
    finally:
        if remote_mcp_client is not None:
            try:
                await remote_mcp_client.aclose()
            except Exception:  # noqa: BLE001
                logger.warning("remote_mcp_client_close_failed")
            set_remote_mcp_client(None)
        # Clear the decisions-store DB handle BEFORE the pool closes so
        # any in-flight SSE callbacks fall back to cache-only writes
        # rather than racing against a dying pool.
        try:
            from shared.api.routes.decisions import (  # noqa: PLC0415
                set_decisions_db,
            )

            set_decisions_db(None)
        except Exception:  # noqa: BLE001 — defensive teardown
            pass
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


# ---------------------------------------------------------------------------
# Hub SPA mount (V3 Wave 3 part 2, Squad SPA1)
# ---------------------------------------------------------------------------

#: Default location of the built SPA inside the Hub container, matching the
#: COPY directive in hub/Dockerfile. Overrideable via env var so dev runs
#: outside the container can point at ``shared/ui/spa/dist`` directly.
DEFAULT_SPA_DIST = Path(
    os.environ.get("SPINE_SPA_DIST", "/app/static/spa")
).resolve()


def _mount_spa(app: FastAPI, *, dist_dir: Path = DEFAULT_SPA_DIST) -> None:
    """Mount the built Hub SPA at ``/static/spa/`` + catch-all at ``/spa/``.

    The SPA is built by ``shared/ui/spa/`` (SvelteKit + adapter-static)
    and produces a ``dist/`` directory whose layout is:

        dist/
          index.html
          favicon.svg
          _app/immutable/...   ← hashed JS/CSS bundles

    Two mounts give us:

    * ``/static/spa/*`` — direct static serving of the hashed bundle
      assets so the browser can fetch JS/CSS without invoking the SPA
      fallback. This is what ``<script src="/static/spa/_app/...">``
      tags resolve against.
    * ``/spa/{path:path}`` — SPA routing catch-all. Any path under
      ``/spa/`` that doesn't match an API route returns ``index.html`` so
      client-side routing (SvelteKit's history-mode) can handle deep
      links like ``/spa/panels/decision-queue`` after a hard refresh.

    If the dist directory isn't present at boot (e.g. the SPA hasn't been
    built yet in a freshly-cloned dev environment), the mount is skipped
    with a warning rather than failing — the API continues to serve and
    operators can still reach the OpenAPI docs at ``/api/v2/docs``.
    """
    if not dist_dir.exists():
        logger.warning(
            "spa_dist_missing",
            extra={"dist_dir": str(dist_dir), "hint": "run `npm run build` in shared/ui/spa/"},
        )
        return

    # Static assets — hashed bundle, served verbatim. ``html=False`` because
    # bundle paths are always concrete; SPA fallback is handled by the
    # catch-all route below.
    app.mount("/static/spa", StaticFiles(directory=dist_dir, html=False), name="spa-static")

    index_file = dist_dir / "index.html"

    @app.get("/spa", include_in_schema=False)
    async def _spa_root() -> FileResponse:
        """Root of the SPA — serves index.html."""
        if not index_file.exists():
            raise HTTPException(status_code=500, detail="spa index.html missing")
        return FileResponse(index_file, media_type="text/html")

    @app.get("/spa/{path:path}", include_in_schema=False)
    async def _spa_catchall(path: str) -> FileResponse:
        """SPA history-mode fallback.

        Resolves an asset under ``dist/`` first (so e.g.
        ``/spa/_app/immutable/foo.js`` still works), and falls back to
        ``index.html`` so the SvelteKit router can claim the URL.
        ``..`` segments are rejected to block path-traversal.
        """
        if ".." in path.split("/"):
            raise HTTPException(status_code=400, detail="invalid path")
        candidate = (dist_dir / path).resolve()
        try:
            candidate.relative_to(dist_dir)
        except ValueError:
            raise HTTPException(status_code=400, detail="path escapes spa dist") from None
        if candidate.is_file():
            return FileResponse(candidate)
        if not index_file.exists():
            raise HTTPException(status_code=500, detail="spa index.html missing")
        return FileResponse(index_file, media_type="text/html")

    logger.info("spa_mounted", extra={"dist_dir": str(dist_dir)})


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
        """Liveness — DB ping + MCP registry import.

        Returns 200 in two cases:
          - prod: db_ok AND mcp_ok
          - dev:  mcp_ok (db is intentionally absent in InMemoryAdapter
                  mode; reporting unhealthy would page on-call for what
                  is by-design behavior)
        """
        import os as _os

        dev_mode = _os.environ.get("SPINE_HUB_DEV") == "1"
        db_ok = await get_db_pool().ping()
        mcp_ok = True
        try:
            from shared.mcp.tools import TOOL_REGISTRY, discover_tools

            if not TOOL_REGISTRY:
                discover_tools("shared.mcp.tools")
        except Exception:  # noqa: BLE001
            mcp_ok = False
        body = {
            "ok": (db_ok and mcp_ok) if not dev_mode else mcp_ok,
            "db": db_ok,
            "mcp": mcp_ok,
            "dev_mode": dev_mode,
            "hub_id": HUB_ID,
        }
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

    # Mount the Hub SPA (V3 Wave 3 part 2). Done AFTER all API routes so
    # FastAPI's path-matching prefers the typed API routes; the SPA
    # catch-all only fires for /spa/* URLs.
    _mount_spa(app)

    @app.exception_handler(Exception)
    async def _unhandled(_request: Request, exc: Exception) -> JSONResponse:
        """Last-resort handler — log + return structured error envelope."""
        logger.exception("unhandled_error", extra={"error": type(exc).__name__})
        return JSONResponse(
            {"error_code": "internal_error", "message": "Unexpected server error."},
            status_code=500,
        )

    return app


__all__: list[str] = ["create_app", "lifespan", "HUB_ID", "_mount_spa", "DEFAULT_SPA_DIST"]
