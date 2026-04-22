"""
Unit tests for WebSocket handler functions (ws.py).

Covers the main audit_progress_ws handler and its sub-functions:
  _send_current_status, _stream_from_redis, _forward_redis_to_ws, _ws_keepalive
"""

from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import WebSocketDisconnect

from tron.api.routes.ws import (
    _active_connections,
    _forward_redis_to_ws,
    _send_current_status,
    _stream_from_redis,
    _ws_keepalive,
    audit_progress_ws,
)


def _make_ws(token="master-key-123", secrets=None):
    """Create a mock WebSocket with query params and app state."""
    ws = AsyncMock()
    ws.query_params = {"token": token} if token else {}
    ws.app = MagicMock()
    ws.app.state.secrets = secrets or {"auth/master-key": "master-key-123"}
    ws.accept = AsyncMock()
    ws.close = AsyncMock()
    ws.send_json = AsyncMock()
    ws.receive_text = AsyncMock()
    return ws


def _mock_session_factory(audit=None):
    """Build an async context manager that mimics _session_factory()."""
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = audit
    mock_session.execute = AsyncMock(return_value=mock_result)

    @asynccontextmanager
    async def factory():
        yield mock_session

    return factory


# ── audit_progress_ws ──


class TestAuditProgressWs:

    async def test_max_connections_rejected(self):
        ws = _make_ws()
        audit_id = uuid.uuid4()

        fakes = {MagicMock() for _ in range(200)}
        _active_connections.update(fakes)
        try:
            with patch("tron.api.routes.ws.settings") as s:
                s.ws_max_connections = 200
                s.ws_require_auth = True
                await audit_progress_ws(ws, audit_id)
            ws.close.assert_called_once()
        finally:
            _active_connections.difference_update(fakes)

    async def test_auth_failure_closes(self):
        ws = _make_ws(token="wrong-key")
        audit_id = uuid.uuid4()
        _active_connections.clear()

        with patch("tron.api.routes.ws.settings") as s:
            s.ws_max_connections = 100
            s.ws_require_auth = True
            await audit_progress_ws(ws, audit_id)

        ws.close.assert_called()

    async def test_successful_connect_and_disconnect(self):
        ws = _make_ws()
        audit_id = uuid.uuid4()
        _active_connections.clear()

        with patch("tron.api.routes.ws.settings") as s, \
             patch("tron.api.routes.ws._send_current_status", new_callable=AsyncMock), \
             patch("tron.api.routes.ws._stream_from_redis", new_callable=AsyncMock) as mock_stream:
            s.ws_max_connections = 100
            s.ws_require_auth = True
            mock_stream.side_effect = WebSocketDisconnect()
            await audit_progress_ws(ws, audit_id)

        ws.accept.assert_called_once()
        assert ws not in _active_connections

    async def test_exception_closes_with_1011(self):
        ws = _make_ws()
        audit_id = uuid.uuid4()
        _active_connections.clear()

        with patch("tron.api.routes.ws.settings") as s, \
             patch("tron.api.routes.ws._send_current_status", new_callable=AsyncMock), \
             patch("tron.api.routes.ws._stream_from_redis", new_callable=AsyncMock) as mock_stream:
            s.ws_max_connections = 100
            s.ws_require_auth = True
            mock_stream.side_effect = RuntimeError("boom")
            await audit_progress_ws(ws, audit_id)

        assert ws.close.call_count >= 1


# ── _send_current_status ──


class TestSendCurrentStatus:

    async def test_audit_not_found(self):
        ws = _make_ws()
        audit_id = uuid.uuid4()
        factory = _mock_session_factory(audit=None)

        with patch("tron.infra.db.session._session_factory", factory):
            await _send_current_status(ws, audit_id)

        ws.send_json.assert_called()
        call_data = ws.send_json.call_args[0][0]
        assert call_data["event"] == "error"

    async def test_completed_audit_sends_snapshot_and_close(self):
        ws = _make_ws()
        audit_id = uuid.uuid4()

        mock_audit = MagicMock()
        mock_audit.status = "completed"
        mock_audit.progress = 100
        mock_audit.findings_total = 5
        mock_audit.findings_critical = 1
        mock_audit.findings_high = 2
        mock_audit.findings_medium = 1
        mock_audit.findings_low = 1
        mock_audit.started_at = MagicMock()
        mock_audit.started_at.isoformat.return_value = "2024-01-01T00:00:00"
        mock_audit.completed_at = MagicMock()
        mock_audit.completed_at.isoformat.return_value = "2024-01-01T00:01:00"
        mock_audit.error_message = None

        factory = _mock_session_factory(audit=mock_audit)

        with patch("tron.infra.db.session._session_factory", factory):
            await _send_current_status(ws, audit_id)

        assert ws.send_json.call_count >= 2
        events = [c[0][0]["event"] for c in ws.send_json.call_args_list]
        assert "snapshot" in events
        assert "close" in events

    async def test_running_audit_sends_snapshot_only(self):
        ws = _make_ws()
        audit_id = uuid.uuid4()

        mock_audit = MagicMock()
        mock_audit.status = "running"
        mock_audit.progress = 50
        mock_audit.findings_total = 2
        mock_audit.findings_critical = 0
        mock_audit.findings_high = 1
        mock_audit.findings_medium = 1
        mock_audit.findings_low = 0
        mock_audit.started_at = MagicMock()
        mock_audit.started_at.isoformat.return_value = "2024-01-01T00:00:00"
        mock_audit.completed_at = None
        mock_audit.error_message = None

        factory = _mock_session_factory(audit=mock_audit)

        with patch("tron.infra.db.session._session_factory", factory):
            await _send_current_status(ws, audit_id)

        assert ws.send_json.call_count == 1
        call_data = ws.send_json.call_args[0][0]
        assert call_data["event"] == "snapshot"
        assert call_data["data"]["status"] == "running"

    async def test_db_error_handled_gracefully(self):
        ws = _make_ws()
        audit_id = uuid.uuid4()

        @asynccontextmanager
        async def broken_factory():
            raise RuntimeError("DB down")
            yield  # pragma: no cover

        with patch("tron.infra.db.session._session_factory", broken_factory):
            await _send_current_status(ws, audit_id)


# ── _forward_redis_to_ws ──


class TestForwardRedisToWs:

    async def test_forwards_message(self):
        ws = _make_ws()
        pubsub = AsyncMock()
        channel = "audit:test:progress"

        payload = {"event": "progress_update", "data": {"progress": 50}}
        pubsub.get_message = AsyncMock(side_effect=[
            {"type": "message", "data": json.dumps(payload)},
            {"type": "message", "data": json.dumps({"event": "audit_completed"})},
        ])

        await _forward_redis_to_ws(pubsub, ws, channel)
        assert ws.send_json.call_count >= 2

    async def test_skips_non_message_types(self):
        ws = _make_ws()
        pubsub = AsyncMock()
        channel = "audit:test:progress"

        pubsub.get_message = AsyncMock(side_effect=[
            {"type": "subscribe", "data": 1},
            {"type": "message", "data": json.dumps({"event": "audit_failed"})},
        ])

        await _forward_redis_to_ws(pubsub, ws, channel)
        events = [c[0][0].get("event") for c in ws.send_json.call_args_list]
        assert "audit_failed" in events

    async def test_invalid_json_skipped(self):
        ws = _make_ws()
        pubsub = AsyncMock()
        channel = "audit:test:progress"

        pubsub.get_message = AsyncMock(side_effect=[
            {"type": "message", "data": "not json {{{"},
            {"type": "message", "data": json.dumps({"event": "audit_completed"})},
        ])

        await _forward_redis_to_ws(pubsub, ws, channel)
        assert ws.send_json.call_count >= 1

    async def test_client_disconnect_returns(self):
        ws = _make_ws()
        pubsub = AsyncMock()
        channel = "audit:test:progress"

        pubsub.get_message = AsyncMock(return_value={
            "type": "message",
            "data": json.dumps({"event": "progress_update"}),
        })

        with patch("tron.api.routes.ws._send_json", new_callable=AsyncMock, return_value=False):
            await _forward_redis_to_ws(pubsub, ws, channel)

    async def test_none_message_continues(self):
        ws = _make_ws()
        pubsub = AsyncMock()
        channel = "audit:test:progress"

        call_count = 0

        async def get_msg(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return None
            return {"type": "message", "data": json.dumps({"event": "audit_completed"})}

        pubsub.get_message = get_msg
        await _forward_redis_to_ws(pubsub, ws, channel)
        assert call_count == 3


# ── _ws_keepalive ──


class TestWsKeepalive:

    async def test_ping_returns_pong(self):
        ws = _make_ws()
        call_count = 0

        async def receive():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return "ping"
            raise WebSocketDisconnect()

        ws.receive_text = receive
        await _ws_keepalive(ws)
        ws.send_json.assert_called()
        sent = ws.send_json.call_args[0][0]
        assert sent["event"] == "pong"

    async def test_timeout_sends_heartbeat(self):
        ws = _make_ws()
        call_count = 0

        async def receive():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise asyncio.TimeoutError()
            raise WebSocketDisconnect()

        ws.receive_text = receive

        with patch("tron.api.routes.ws._send_json", new_callable=AsyncMock, return_value=True):
            await _ws_keepalive(ws)

    async def test_disconnect_returns(self):
        ws = _make_ws()
        ws.receive_text = AsyncMock(side_effect=WebSocketDisconnect())
        await _ws_keepalive(ws)

    async def test_heartbeat_failure_returns(self):
        ws = _make_ws()

        async def receive():
            raise asyncio.TimeoutError()

        ws.receive_text = receive

        with patch("tron.api.routes.ws._send_json", new_callable=AsyncMock, return_value=False):
            await _ws_keepalive(ws)


# ── WebSocket Close Exception Tests ──────────────────────────────


class TestWebSocketCloseExceptions:
    """Test exception handling in websocket.close() calls."""

    async def test_exception_in_websocket_close_during_error_handling(self):
        """Exception in websocket.close() during error handler should be caught."""
        ws = _make_ws()
        audit_id = uuid.uuid4()
        _active_connections.clear()

        # Mock close to raise an exception
        ws.close = AsyncMock(side_effect=RuntimeError("close failed"))

        with patch("tron.api.routes.ws.settings") as s, \
             patch("tron.api.routes.ws._send_current_status", new_callable=AsyncMock), \
             patch("tron.api.routes.ws._stream_from_redis", new_callable=AsyncMock) as mock_stream:
            s.ws_max_connections = 100
            s.ws_require_auth = True
            mock_stream.side_effect = RuntimeError("boom")

            # Should not raise even though close() fails
            await audit_progress_ws(ws, audit_id)

        # Connection should still be cleaned up
        assert ws not in _active_connections

    async def test_exception_in_websocket_close_during_terminal_event(self):
        """Exception in websocket.close() when sending terminal event."""
        ws = _make_ws()
        pubsub = AsyncMock()
        channel = "audit:test:progress"

        # Close will fail
        ws.close = AsyncMock(side_effect=RuntimeError("Connection closed"))

        payload1 = {"event": "progress_update", "data": {"progress": 50}}
        payload2 = {"event": "audit_completed", "data": {}}
        pubsub.get_message = AsyncMock(side_effect=[
            {"type": "message", "data": json.dumps(payload1)},
            {"type": "message", "data": json.dumps(payload2)},
        ])

        # Should not raise despite close() failure
        await _forward_redis_to_ws(pubsub, ws, channel)
        # Still sent close message before attempting to close
        assert ws.send_json.call_count >= 2


# ── Stream From Redis Full Implementation Tests ──────────────────


class TestStreamFromRedisFull:
    """Test full _stream_from_redis implementation with all code paths."""

    async def test_stream_subscribes_and_unsubscribes(self):
        """_stream_from_redis should subscribe and unsubscribe from channel."""
        ws = _make_ws()
        redis = AsyncMock()
        pubsub = AsyncMock()
        pubsub.subscribe = AsyncMock()
        pubsub.unsubscribe = AsyncMock()
        pubsub.aclose = AsyncMock()
        pubsub.get_message = AsyncMock(return_value=None)

        redis.pubsub = MagicMock(return_value=pubsub)

        audit_id = uuid.uuid4()

        with patch("tron.api.routes.ws.get_redis", return_value=redis), \
             patch("tron.api.routes.ws._forward_redis_to_ws", new_callable=AsyncMock), \
             patch("tron.api.routes.ws._ws_keepalive", new_callable=AsyncMock):
            try:
                await asyncio.wait_for(
                    asyncio.create_task(_stream_from_redis(ws, audit_id)),
                    timeout=0.5,
                )
            except asyncio.TimeoutError:
                pass

        pubsub.subscribe.assert_called_once()
        pubsub.unsubscribe.assert_called_once()
        pubsub.aclose.assert_called_once()

    async def test_stream_runs_forward_and_keepalive_tasks(self):
        """_stream_from_redis should run both forward and keepalive tasks."""
        ws = _make_ws()
        redis = AsyncMock()
        pubsub = AsyncMock()
        pubsub.subscribe = AsyncMock()
        pubsub.unsubscribe = AsyncMock()
        pubsub.aclose = AsyncMock()

        redis.pubsub = MagicMock(return_value=pubsub)

        audit_id = uuid.uuid4()

        forward_called = False
        keepalive_called = False

        async def mock_forward(*args, **kwargs):
            nonlocal forward_called
            forward_called = True
            await asyncio.sleep(10)  # Will be cancelled

        async def mock_keepalive(*args, **kwargs):
            nonlocal keepalive_called
            keepalive_called = True
            raise WebSocketDisconnect()

        with patch("tron.api.routes.ws.get_redis", return_value=redis), \
             patch("tron.api.routes.ws._forward_redis_to_ws", side_effect=mock_forward), \
             patch("tron.api.routes.ws._ws_keepalive", side_effect=mock_keepalive):
            try:
                await _stream_from_redis(ws, audit_id)
            except WebSocketDisconnect:
                pass

        # Both should have been called
        assert forward_called
        assert keepalive_called


# ── Keepalive Exception Handling Tests ──────────────────────────


class TestKeepaliveExceptionHandling:
    """Test keepalive exception handling for various error conditions."""

    async def test_keepalive_handles_general_exception(self):
        """Keepalive should return on general exception."""
        ws = _make_ws()

        async def receive():
            raise RuntimeError("Unexpected error")

        ws.receive_text = receive

        # Should not raise, should return gracefully
        await _ws_keepalive(ws)

    async def test_keepalive_send_failure_during_timeout(self):
        """Keepalive should return if send fails during timeout heartbeat."""
        ws = _make_ws()
        call_count = 0

        async def receive():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise asyncio.TimeoutError()
            raise WebSocketDisconnect()

        ws.receive_text = receive

        with patch("tron.api.routes.ws._send_json", new_callable=AsyncMock, return_value=False):
            await _ws_keepalive(ws)
