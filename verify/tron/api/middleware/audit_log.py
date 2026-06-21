"""
HTTP middleware that writes an ``api_key_audit_log`` row per authed call.

Sits AFTER auth dependency resolution so the row records:
  * which API key (or master / admin-session) made the call
  * the route + method
  * the resulting status code
  * IP + user-agent

Why a middleware instead of a per-route hook
--------------------------------------------
Per-route would require touching every router. Middleware sees every
request including ones that 404 before route resolution, which is what
you want in an audit log — "someone hit /api/admin/users with key X and
got a 404" is a real signal in a security review.

Why best-effort writes
----------------------
Audit-log writes must never block the user request. Failures here are
logged but never propagated; the alternative (raising) would make every
request fragile to a transient DB blip on a non-critical path.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional, Set
from uuid import UUID

from fastapi import FastAPI, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tron.domain.models import ApiKeyAuditLog

logger = logging.getLogger(__name__)


# Routes excluded from audit logging — health endpoints, OpenAPI docs,
# static assets — would generate noise without forensic value.
_EXCLUDED_PATH_PREFIXES = (
    "/health",
    "/ready",
    "/api/docs",
    "/api/openapi.json",
    "/api/redoc",
    "/static/",
)

# In-flight audit-log writes. Bounded so a sudden DB stall can't cause
# unbounded task accumulation. New writes past the cap are dropped with
# a counter increment — losing some audit log rows is preferable to
# OOMing the API.
_INFLIGHT_TASKS: Set[asyncio.Task] = set()
_INFLIGHT_CAP = 1000
_dropped_due_to_backpressure = 0


def install_api_key_audit_log_middleware(
    app: FastAPI,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Install the middleware on ``app``.

    The session factory is captured at install time. Each request gets
    its own short-lived session for the audit-log write; we don't reuse
    the request-scoped session because that may have already been
    closed by the time the response leaves the handler.
    """

    @app.middleware("http")
    async def _api_key_audit_log_mw(request: Request, call_next):
        response: Optional[Response] = None
        try:
            response = await call_next(request)
            return response
        finally:
            # Schedule the audit write as a background task so it does
            # NOT add latency to the user's response. Cap the in-flight
            # set so a stalled DB can't accumulate unbounded tasks; on
            # overflow we drop the row and bump a counter (a missed
            # audit-log row is better than an OOMed API process).
            global _dropped_due_to_backpressure
            if len(_INFLIGHT_TASKS) >= _INFLIGHT_CAP:
                _dropped_due_to_backpressure += 1
                if _dropped_due_to_backpressure % 100 == 1:
                    logger.warning(
                        "Audit-log backpressure: dropped %d rows so far "
                        "(in-flight cap=%d). DB likely slow.",
                        _dropped_due_to_backpressure, _INFLIGHT_CAP,
                    )
                return

            task = asyncio.create_task(
                _write_audit_row_safe(
                    request_state_snapshot=_snapshot_request(request, response),
                    session_factory=session_factory,
                )
            )
            _INFLIGHT_TASKS.add(task)
            task.add_done_callback(_INFLIGHT_TASKS.discard)

    app.state._api_key_audit_log_installed = True


def _snapshot_request(request: Request, response: Optional[Response]) -> dict:
    """Capture everything we need from request/response BEFORE the task runs.

    The request object lives only for the lifetime of the response; by
    the time the background task executes, ``request.client``,
    ``request.state``, and ``request.headers`` may all be torn down.
    Snapshot eagerly into a plain dict and pass that into the writer.
    """
    return {
        "path": request.url.path,
        "method": request.method,
        "is_master": getattr(request.state, "api_key_is_master", None),
        "is_admin": getattr(request.state, "admin_ui_session", None),
        "api_key_id": getattr(request.state, "api_key_db_id", None),
        "remote_addr": (
            request.client.host if request.client else None
        ),
        "user_agent": request.headers.get("user-agent", "")[:512] or None,
        "status_code": (
            response.status_code if response is not None else None
        ),
    }


async def _write_audit_row_safe(
    *,
    request_state_snapshot: dict,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Background-task wrapper that ALWAYS swallows errors.

    The user request has already returned by the time this runs, so a
    raised exception here would be reported by asyncio as "Task
    exception was never retrieved" with no useful effect. Trap, log,
    move on.
    """
    try:
        await _write_audit_row_from_snapshot(
            snapshot=request_state_snapshot,
            session_factory=session_factory,
        )
    except Exception:
        logger.warning(
            "API-key audit log write failed (background task)",
            exc_info=True,
        )


async def _write_audit_row_from_snapshot(
    *,
    snapshot: dict,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Insert one row into ``api_key_audit_log`` from a captured snapshot.

    Skip conditions:
      * request path is in ``_EXCLUDED_PATH_PREFIXES``
      * no auth was performed (snapshot has neither is_master nor is_admin)
    """
    path = snapshot.get("path", "")
    for prefix in _EXCLUDED_PATH_PREFIXES:
        if path.startswith(prefix):
            return

    is_master = snapshot.get("is_master")
    is_admin = snapshot.get("is_admin")
    if is_master is None and is_admin is None:
        return

    api_key_id: Optional[UUID] = snapshot.get("api_key_id")
    remote_addr = snapshot.get("remote_addr")

    async with session_factory() as session:
        row = ApiKeyAuditLog(
            api_key_id=api_key_id,
            is_master=bool(is_master),
            is_admin_session=bool(is_admin),
            method=snapshot.get("method", ""),
            path=path[:512],
            status_code=snapshot.get("status_code"),
            remote_addr=remote_addr[:64] if remote_addr else None,
            user_agent=snapshot.get("user_agent"),
        )
        session.add(row)
        await session.commit()
