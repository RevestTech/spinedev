"""
WebSocket endpoint for real-time audit progress streaming.

Clients connect to /ws/audits/{audit_id}?token=<api_key> and receive
JSON events as the audit runs: progress updates, finding discoveries,
agent status changes, and completion/failure notifications.

Protocol:
  1. Client opens WebSocket with API key as query param
  2. Server authenticates, subscribes to Redis pub/sub channel
  3. Server pushes events as JSON frames until audit completes or fails
  4. Server sends a final "close" frame and disconnects

Events are JSON objects with this shape:
  {
    "event": "progress_update",
    "audit_run_id": "uuid",
    "timestamp": "iso8601",
    "data": { ... }
  }
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
from uuid import UUID

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from tron.api.admin_session import ADMIN_COOKIE_NAME, verify_admin_jwt
from tron.api.config import settings
from tron.api.middleware.auth import lookup_scoped_api_key_scopes
from tron.api.middleware.scopes import WS_AUDIT_PROGRESS_SCOPES, scopes_satisfy
from tron.infra.redis.client import get_redis

logger = logging.getLogger(__name__)
router = APIRouter()

# Track active connections for the max-connections guard
_active_connections: set[WebSocket] = set()


async def _authenticate_ws(websocket: WebSocket) -> bool:
    """Validate the API key from query params.

    WebSockets can't use headers easily from browser JS,
    so we accept the token as a query parameter.

    Master key is allowed. Scoped keys must include the ``audits`` scope (or ``*``),
    matching REST access to audit APIs.
    """
    if not settings.ws_require_auth:
        return True

    master_key = websocket.app.state.secrets.get("auth/master-key")
    if not master_key:
        logger.error("Master key not loaded — cannot authenticate WebSocket")
        return False

    jwt_secret = websocket.app.state.secrets.get("auth/jwt-secret")
    cookie_raw = websocket.cookies.get(ADMIN_COOKIE_NAME)
    if jwt_secret and cookie_raw and verify_admin_jwt(cookie_raw, jwt_secret):
        return True

    token = websocket.query_params.get("token")
    if not token:
        return False

    if hmac.compare_digest(token, master_key):
        return True

    scopes = await lookup_scoped_api_key_scopes(token)
    if scopes is None:
        return False
    return scopes_satisfy(WS_AUDIT_PROGRESS_SCOPES, scopes)


async def _send_json(ws: WebSocket, data: dict) -> bool:
    """Send a JSON message, returning False if the connection is dead."""
    try:
        await ws.send_json(data)
        return True
    except Exception:
        return False


@router.websocket("/ws/audits/{audit_id}")
async def audit_progress_ws(
    websocket: WebSocket,
    audit_id: UUID,
):
    """Stream live audit progress events over WebSocket.

    Query params:
      - token: API key for authentication (required if WS_REQUIRE_AUTH=true)

    The connection will:
      1. Send the current audit status as the first message
      2. Subscribe to Redis pub/sub for live events
      3. Forward all events until audit_completed or audit_failed
      4. Auto-close after the terminal event
    """
    # ── Guard: max connections ──
    if len(_active_connections) >= settings.ws_max_connections:
        await websocket.close(code=1013, reason="Too many connections")
        return

    # ── Authenticate ──
    if not await _authenticate_ws(websocket):
        await websocket.close(code=4001, reason="Authentication required")
        return

    # ── Accept connection ──
    await websocket.accept()
    _active_connections.add(websocket)

    logger.info("WebSocket connected for audit %s (total=%d)", audit_id, len(_active_connections))

    try:
        # ── Send current status snapshot ──
        await _send_current_status(websocket, audit_id)

        # ── Subscribe to Redis pub/sub ──
        await _stream_from_redis(websocket, audit_id)

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected for audit %s", audit_id)
    except Exception as exc:
        logger.exception("WebSocket error for audit %s: %s", audit_id, exc)
        try:
            await websocket.close(code=1011, reason="Internal error")
        except Exception:
            pass
    finally:
        _active_connections.discard(websocket)
        logger.info("WebSocket cleaned up for audit %s (total=%d)", audit_id, len(_active_connections))


async def _send_current_status(websocket: WebSocket, audit_id: UUID) -> None:
    """Send the current audit status as the first message.

    This lets clients that connect mid-audit immediately see where things are.
    """
    from tron.infra.db.session import _session_factory

    try:
        from tron.domain.models import AuditRun

        async with _session_factory() as session:
            result = await session.execute(
                select(AuditRun).where(AuditRun.id == audit_id)
            )
            audit = result.scalar_one_or_none()

        if not audit:
            await _send_json(websocket, {
                "event": "error",
                "data": {"message": f"Audit {audit_id} not found"},
            })
            return

        await _send_json(websocket, {
            "event": "snapshot",
            "audit_run_id": str(audit_id),
            "data": {
                "status": audit.status,
                "progress": audit.progress,
                "findings_total": audit.findings_total,
                "findings_critical": audit.findings_critical,
                "findings_high": audit.findings_high,
                "findings_medium": audit.findings_medium,
                "findings_low": audit.findings_low,
                "started_at": audit.started_at.isoformat() if audit.started_at else None,
                "completed_at": audit.completed_at.isoformat() if audit.completed_at else None,
                "error_message": audit.error_message,
            },
        })

        # If audit already finished, close immediately
        if audit.status in ("completed", "failed"):
            await _send_json(websocket, {
                "event": "close",
                "data": {"reason": f"Audit already {audit.status}"},
            })
            await websocket.close(code=1000)
            return

    except Exception as exc:
        logger.warning("Failed to send current status for audit %s: %s", audit_id, exc)


async def _stream_from_redis(websocket: WebSocket, audit_id: UUID) -> None:
    """Subscribe to Redis pub/sub and forward events to the WebSocket.

    Uses a dedicated Redis connection for the subscription (pub/sub
    requires a dedicated connection in Redis).

    Also listens for client pings/messages to detect disconnection.
    """
    redis = get_redis()
    pubsub = redis.pubsub()
    channel = f"audit:{audit_id}:progress"

    try:
        await pubsub.subscribe(channel)
        logger.debug("Subscribed to Redis channel: %s", channel)

        # Run two tasks concurrently:
        # 1. Forward Redis messages → WebSocket
        # 2. Listen for client disconnection (ping/pong or receive)
        forward_task = asyncio.create_task(
            _forward_redis_to_ws(pubsub, websocket, channel)
        )
        keepalive_task = asyncio.create_task(
            _ws_keepalive(websocket)
        )

        # Wait for either task to finish (disconnect or terminal event)
        done, pending = await asyncio.wait(
            [forward_task, keepalive_task],
            return_when=asyncio.FIRST_COMPLETED,
        )

        # Cancel the other task
        for task in pending:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.aclose()
        logger.debug("Unsubscribed from Redis channel: %s", channel)


async def _forward_redis_to_ws(
    pubsub,
    websocket: WebSocket,
    channel: str,
) -> None:
    """Read from Redis pub/sub and push to WebSocket.

    Stops when a terminal event (audit_completed/audit_failed) is received.
    """
    terminal_events = {"audit_completed", "audit_failed"}

    while True:
        message = await pubsub.get_message(
            ignore_subscribe_messages=True,
            timeout=1.0,
        )

        if message is None:
            # No message this cycle — send a heartbeat every ~30s
            # (handled by keepalive task instead)
            continue

        if message["type"] != "message":
            continue

        try:
            payload = json.loads(message["data"])
        except (json.JSONDecodeError, TypeError):
            continue

        # Forward to WebSocket
        sent = await _send_json(websocket, payload)
        if not sent:
            # Client disconnected
            return

        # Check for terminal event
        event_type = payload.get("event", "")
        if event_type in terminal_events:
            logger.info(
                "Terminal event %s for audit — closing WebSocket",
                event_type,
            )
            await _send_json(websocket, {
                "event": "close",
                "data": {"reason": f"Audit {event_type}"},
            })
            try:
                await websocket.close(code=1000)
            except Exception:
                pass
            return


async def _ws_keepalive(websocket: WebSocket) -> None:
    """Keep the WebSocket alive by:
    1. Sending periodic heartbeat pings
    2. Listening for client messages (including disconnect)

    If the client disconnects, this task completes, which triggers
    cleanup of the Redis subscription.
    """
    heartbeat_interval = 30  # seconds

    while True:
        try:
            # Wait for a client message with timeout (acts as heartbeat check)
            message = await asyncio.wait_for(
                websocket.receive_text(),
                timeout=heartbeat_interval,
            )

            # Handle client commands
            if message == "ping":
                await _send_json(websocket, {"event": "pong"})

        except asyncio.TimeoutError:
            # No message from client — send heartbeat
            sent = await _send_json(websocket, {"event": "heartbeat"})
            if not sent:
                return  # Client gone

        except WebSocketDisconnect:
            return  # Client disconnected
        except Exception:
            return  # Connection error
