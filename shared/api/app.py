"""FastAPI app factory for the Spine REST API (STORY-9.9.2).

Run::

    uvicorn shared.api.app:create_app --factory --port 8088

Wires CORS, JSON logging (no secrets), a request-id middleware, a
lifespan that pre-warms the DB handle + MCP registry, health endpoints
(``/healthz``, ``/readyz``), and the OpenAPI spec at ``/api/v2/spec``.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from shared.api.dependencies import get_db_pool
from shared.api.routes import ALL_ROUTERS

logger = logging.getLogger("spine.api")
_SECRET_KEYS = frozenset(
    {"approval_token", "token", "api_key", "secret", "password", "hmac_key", "authorization"}
)
_REQUIRED_SCHEMAS = ("spine_lifecycle", "spine_audit")


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
        logger.info("request_end", extra={"request_id": req_id, "status_code": response.status_code})
        return response


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Boot/teardown — DB ping + pre-warm MCP registry."""
    _configure_logging()
    db = get_db_pool()
    ok = await db.ping()
    logger.info("lifespan_start", extra={"db_reachable": ok})
    try:
        from shared.mcp.tools import TOOL_REGISTRY, discover_tools

        if not TOOL_REGISTRY:
            discover_tools("shared.mcp.tools")
        logger.info("mcp_loaded", extra={"tool_count": len(TOOL_REGISTRY)})
    except Exception as exc:  # noqa: BLE001
        logger.warning("mcp_load_failed", extra={"error": str(exc)})
    yield
    logger.info("lifespan_stop")


def _cors_origins() -> list[str]:
    """CORS origins from env, default to dashboard dev URL."""
    raw = os.environ.get("SPINE_API_CORS_ORIGINS", "http://localhost:8080")
    return [o.strip() for o in raw.split(",") if o.strip()]


def create_app() -> FastAPI:
    """Construct and return the configured FastAPI app."""
    app = FastAPI(
        title="Spine Orchestrator REST API", version="0.2.0",
        description="REST surface over the unified MCP server + Postgres (STORY-9.9.2).",
        lifespan=lifespan, openapi_url="/api/v2/spec",
        docs_url="/api/v2/docs", redoc_url=None,
    )
    app.add_middleware(
        CORSMiddleware, allow_origins=_cors_origins(), allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["content-type", "x-request-id", "x-spine-actor"],
    )
    app.add_middleware(RequestIdMiddleware)
    for r in ALL_ROUTERS:
        app.include_router(r)

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
        body = {"ok": db_ok and mcp_ok, "db": db_ok, "mcp": mcp_ok}
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
            {"ok": ok, "schemas_required": list(_REQUIRED_SCHEMAS), "schemas_found": sorted(found)},
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


__all__: list[str] = ["create_app", "lifespan"]
