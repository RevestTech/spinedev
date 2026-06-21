"""
Tron API — FastAPI application entry point.

All secrets loaded from container keyvault at startup.
No secrets in environment variables or config files.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import (
    http_exception_handler,
    request_validation_exception_handler,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from tron.api.config import settings
from tron.api.routes import admin_auth, admin_metrics, alerts, api_keys, audits, costs, findings, fixes, graph, health, modes, projects, standards, ws, gdpr, workflow_runs, integrations
from tron.api.middleware.metrics import MetricsMiddleware
from tron.api.middleware.rate_limit import RateLimitMiddleware
from tron.api.middleware.security import SecurityHeadersMiddleware
from tron.infra.db.migrate import run_sync_migrations
from tron.infra.db.session import init_db, close_db
from tron.infra.observability import init_observability, shutdown_observability
from tron.infra.redis.client import init_redis, close_redis
from tron.infra.secrets import get_secrets
from tron.realtime.socket_server import socket_app, set_jwt_secret

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — init and teardown."""
    # ── Startup ──
    logger.info("Tron API starting up...")

    # 1. Load all secrets from keyvault (single concurrent batch)
    logger.info("Loading secrets from keyvault...")
    secrets = await get_secrets([
        "db/password",
        "redis/password",
        "auth/secret-key",
        "auth/jwt-secret",
        "auth/master-key",
    ])
    # Store in app state for access by route handlers
    app.state.secrets = secrets
    logger.info("Secrets loaded successfully.")

    # 2. Configure Socket.IO with JWT secret
    set_jwt_secret(secrets["auth/jwt-secret"])
    logger.info("Socket.IO JWT secret configured.")

    # 3. Database schema (sync Alembic) then async engine
    db_password = secrets["db/password"]
    run_sync_migrations(settings.database_url_sync(db_password))
    db_url = settings.database_url(db_password)
    await init_db(
        url=db_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
    )
    logger.info("Database connected.")

    # 4. Initialize Redis
    redis_password = secrets["redis/password"]
    redis_url = settings.redis_url(redis_password)
    await init_redis(url=redis_url, pool_size=settings.redis_pool_size)
    logger.info("Redis connected.")

    # 4b. Clear zombie ``queued`` rows (worker/Temporal never advanced DB) — unblocks Live / workflow-runs
    if settings.reconcile_stale_queued_on_startup:
        from tron.infra.db.session import _session_factory
        from tron.services.audit_reconcile import reconcile_stale_queued_audits

        if _session_factory is not None:
            try:
                async with _session_factory() as session:
                    out = await reconcile_stale_queued_audits(
                        session,
                        older_than_minutes=settings.stale_queued_audit_minutes_default,
                        dry_run=False,
                    )
                if out.updated:
                    logger.warning(
                        "Startup reconcile: marked %d stale queued audit(s) as failed "
                        "(queued longer than %s minutes; set TRON_RECONCILE_STALE_QUEUED_ON_STARTUP=false to skip)",
                        out.updated,
                        settings.stale_queued_audit_minutes_default,
                    )
            except Exception as exc:
                logger.warning("Startup stale-queue reconcile skipped: %s", exc)

    # 5. Initialise observability (tracing, metrics, structured logging)
    await init_observability(app)
    logger.info("Observability initialised.")

    logger.info("Tron API ready.")

    yield

    # ── Shutdown ──
    logger.info("Tron API shutting down...")
    await shutdown_observability()
    await close_redis()
    await close_db()
    logger.info("Tron API stopped.")


def create_app() -> FastAPI:
    """Factory function — creates and configures the FastAPI app."""
    app = FastAPI(
        title="Tron",
        description="Enterprise AI QA Platform — Verify Everything, Trust Nothing",
        version="5.4.0",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )

    # CORS — explicit origins (TRON_CORS_ORIGINS) and headers: browsers reject credentials + Allow-Headers: *
    _cors_hdr = [
        "Accept",
        "Accept-Language",
        "Content-Language",
        "Content-Type",
        "Authorization",
        "X-API-Key",
        "X-Request-ID",
        "Cookie",
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins(),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=_cors_hdr,
    )

    # Security headers (before CORS so headers are preserved)
    app.add_middleware(SecurityHeadersMiddleware)

    # Request metrics (raw ASGI — coverage-safe, zero overhead)
    app.add_middleware(MetricsMiddleware)

    # Rate limiting (Redis-backed sliding window)
    app.add_middleware(RateLimitMiddleware)

    # API-key audit log: one row per authed call. Installs after auth so
    # ``request.state.api_key_db_id`` / ``api_key_is_master`` /
    # ``admin_ui_session`` are populated. Best-effort write — never blocks
    # the response.
    from tron.api.middleware.audit_log import install_api_key_audit_log_middleware
    from tron.infra.db.session import _session_factory as _audit_log_sf
    if _audit_log_sf is not None:
        install_api_key_audit_log_middleware(app, _audit_log_sf)

    # Socket.IO mount (before routes)
    app.mount('/socket.io', socket_app)

    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(request: Request, exc: Exception):
        """Log server errors; avoid silent 500s during local debugging."""
        logger.exception(
            "Unhandled error during %s %s: %s",
            request.method,
            request.url.path,
            exc,
        )
        if isinstance(exc, HTTPException):
            return await http_exception_handler(request, exc)
        if isinstance(exc, RequestValidationError):
            return await request_validation_exception_handler(request, exc)
        
        payload: dict = {"detail": "Internal server error"}
        if settings.debug:
            payload["error_type"] = type(exc).__name__
            payload["error"] = str(exc)
        return JSONResponse(status_code=500, content=payload)

    # Routes
    app.include_router(health.router, tags=["Health"])
    # Alertmanager webhook receiver — intentionally NOT /api-prefixed so the
    # existing Alertmanager config ("url: http://tron-api:8000/alerts...") keeps
    # working. Sits on the internal docker network only; see alerts.py for auth
    # notes if exposing externally.
    app.include_router(alerts.router, tags=["Alerts"])
    app.include_router(admin_auth.router, prefix="/api", tags=["Admin UI"])
    app.include_router(admin_metrics.router, prefix="/api", tags=["Admin Metrics"])
    app.include_router(projects.router, prefix="/api", tags=["Projects"])
    app.include_router(audits.router, prefix="/api", tags=["Audits"])
    app.include_router(findings.router, prefix="/api", tags=["Findings"])
    app.include_router(standards.router, prefix="/api", tags=["Standards"])
    app.include_router(graph.router, prefix="/api", tags=["Graph"])
    app.include_router(modes.router, prefix="/api", tags=["Modes"])
    app.include_router(fixes.router, prefix="/api", tags=["Fixes"])
    app.include_router(costs.router, prefix="/api", tags=["Costs"])
    app.include_router(workflow_runs.router, prefix="/api", tags=["Workflows"])
    app.include_router(integrations.router, prefix="/api", tags=["Integrations"])
    app.include_router(api_keys.router, prefix="/api", tags=["API Keys"])
    app.include_router(gdpr.router, prefix="/api", tags=["GDPR"])
    app.include_router(ws.router, tags=["WebSocket"])

    return app


# Module-level app instance for uvicorn
app = create_app()
