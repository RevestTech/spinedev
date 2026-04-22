"""
Socket.IO real-time server for Tron.

Handles:
- Async WebSocket connections via Socket.IO
- JWT authentication on connect
- Room-based messaging (user, project, workflow)
- Redis adapter for horizontal scaling
- Event broadcasting to subscribed clients
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any

import jwt
import socketio

logger = logging.getLogger(__name__)

# Module-level JWT secret (set during initialization)
_jwt_secret: str | None = None

# Socket.IO server with async_mode='asgi'
sio = socketio.AsyncServer(
    async_mode='asgi',
    cors_allowed_origins='*',
    ping_interval=10,
    ping_timeout=5,
)

# Redis adapter configuration
_redis_url = os.getenv('SOCKETIO_REDIS_URL', 'redis://redis:6379/1')


def set_jwt_secret(secret: str) -> None:
    """Set the JWT secret after keyvault loads it."""
    global _jwt_secret
    _jwt_secret = secret
    logger.debug("JWT secret configured for Socket.IO server")


def get_jwt_secret() -> str | None:
    """Get the current JWT secret."""
    return _jwt_secret


def _verify_jwt(token: str) -> dict[str, Any] | None:
    """Verify JWT token and return payload.

    Returns decoded token if valid, None if invalid.
    """
    if not _jwt_secret:
        logger.warning("JWT verification requested but secret not configured")
        return None

    try:
        from tron.api.config import settings

        payload = jwt.decode(
            token,
            _jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
        return payload
    except jwt.InvalidTokenError as e:
        logger.debug("JWT verification failed: %s", e)
        return None
    except Exception as e:
        logger.warning("JWT verification error: %s", e)
        return None


@sio.event
async def connect(sid: str, environ: dict, auth: dict | None = None) -> None:
    """Handle client connect with JWT auth.

    Auth dict should contain 'token' key with JWT.
    """
    client_addr = environ.get('REMOTE_ADDR', 'unknown')
    logger.info("Socket.IO client connecting: %s from %s", sid, client_addr)

    # Verify JWT token
    if not auth or not auth.get('token'):
        logger.warning("Connection rejected: no token provided (sid=%s)", sid)
        return False

    token = auth.get('token')
    payload = _verify_jwt(token)

    if not payload:
        logger.warning("Connection rejected: invalid token (sid=%s)", sid)
        return False

    # Store user_id and project_id from JWT payload in the connection context
    user_id = payload.get('sub')  # Standard JWT claim
    project_id = payload.get('project_id')

    if not user_id:
        logger.warning("Connection rejected: no user_id in token (sid=%s)", sid)
        return False

    # Store context in session data
    sio.environ[sid] = {
        'user_id': user_id,
        'project_id': project_id,
        'token_payload': payload,
    }

    logger.info("Socket.IO client connected: %s (user=%s, project=%s)", sid, user_id, project_id)


@sio.event
async def disconnect(sid: str) -> None:
    """Handle client disconnect."""
    user_context = sio.environ.get(sid, {})
    user_id = user_context.get('user_id', 'unknown')
    logger.info("Socket.IO client disconnected: %s (user=%s)", sid, user_id)

    # Clean up context
    if sid in sio.environ:
        del sio.environ[sid]


@sio.event
async def subscribe_workflow(sid: str, workflow_id: str) -> None:
    """Subscribe client to workflow events.

    Joins the room: workflow:{workflow_id}
    """
    user_context = sio.environ.get(sid, {})
    user_id = user_context.get('user_id', 'unknown')

    room = f"workflow:{workflow_id}"
    sio.enter_room(sid, room)
    logger.debug("Client %s (user=%s) subscribed to workflow %s", sid, user_id, workflow_id)

    # Send confirmation
    await sio.emit('subscribed', {
        'workflow_id': workflow_id,
        'timestamp': datetime.utcnow().isoformat(),
    }, room=sid)


@sio.event
async def unsubscribe_workflow(sid: str, workflow_id: str) -> None:
    """Unsubscribe client from workflow events.

    Leaves the room: workflow:{workflow_id}
    """
    user_context = sio.environ.get(sid, {})
    user_id = user_context.get('user_id', 'unknown')

    room = f"workflow:{workflow_id}"
    sio.leave_room(sid, room)
    logger.debug("Client %s (user=%s) unsubscribed from workflow %s", sid, user_id, workflow_id)

    # Send confirmation
    await sio.emit('unsubscribed', {
        'workflow_id': workflow_id,
        'timestamp': datetime.utcnow().isoformat(),
    }, room=sid)


@sio.event
async def subscribe_project(sid: str, project_id: str) -> None:
    """Subscribe client to project events.

    Joins the room: project:{project_id}
    """
    user_context = sio.environ.get(sid, {})
    user_id = user_context.get('user_id', 'unknown')

    room = f"project:{project_id}"
    sio.enter_room(sid, room)
    logger.debug("Client %s (user=%s) subscribed to project %s", sid, user_id, project_id)

    # Send confirmation
    await sio.emit('subscribed', {
        'project_id': project_id,
        'timestamp': datetime.utcnow().isoformat(),
    }, room=sid)


@sio.event
async def unsubscribe_project(sid: str, project_id: str) -> None:
    """Unsubscribe client from project events.

    Leaves the room: project:{project_id}
    """
    user_context = sio.environ.get(sid, {})
    user_id = user_context.get('user_id', 'unknown')

    room = f"project:{project_id}"
    sio.leave_room(sid, room)
    logger.debug("Client %s (user=%s) unsubscribed from project %s", sid, user_id, project_id)

    # Send confirmation
    await sio.emit('unsubscribed', {
        'project_id': project_id,
        'timestamp': datetime.utcnow().isoformat(),
    }, room=sid)


@sio.event
async def ping(sid: str) -> None:
    """Handle client ping — send pong response."""
    await sio.emit('pong', {
        'timestamp': datetime.utcnow().isoformat(),
    }, room=sid)


# ── Broadcast functions ──


async def broadcast_workflow_event(
    workflow_id: str,
    event_type: str,
    data: dict[str, Any],
) -> None:
    """Broadcast event to all clients subscribed to workflow.

    Sends to room: workflow:{workflow_id}
    """
    room = f"workflow:{workflow_id}"
    payload = {
        'event_type': event_type,
        'workflow_id': workflow_id,
        'timestamp': datetime.utcnow().isoformat(),
        'data': data,
    }

    logger.debug("Broadcasting to workflow %s: %s", workflow_id, event_type)
    await sio.emit('workflow_event', payload, room=room)


async def broadcast_project_event(
    project_id: str,
    event_type: str,
    data: dict[str, Any],
) -> None:
    """Broadcast event to all clients subscribed to project.

    Sends to room: project:{project_id}
    """
    room = f"project:{project_id}"
    payload = {
        'event_type': event_type,
        'project_id': project_id,
        'timestamp': datetime.utcnow().isoformat(),
        'data': data,
    }

    logger.debug("Broadcasting to project %s: %s", project_id, event_type)
    await sio.emit('project_event', payload, room=room)


async def broadcast_metric_update(
    metric_type: str,
    data: dict[str, Any],
) -> None:
    """Broadcast metric update to all connected clients.

    Sends to all clients globally.
    """
    payload = {
        'metric_type': metric_type,
        'timestamp': datetime.utcnow().isoformat(),
        'data': data,
    }

    logger.debug("Broadcasting metric update: %s", metric_type)
    await sio.emit('metric_update', payload)


# ── ASGI app ──


socket_app = socketio.ASGIApp(
    sio,
    static_files={
        '/': {'content_type': 'text/html', 'filename': 'index.html'}
    }
)

__all__ = [
    'sio',
    'socket_app',
    'set_jwt_secret',
    'get_jwt_secret',
    'broadcast_workflow_event',
    'broadcast_project_event',
    'broadcast_metric_update',
]
