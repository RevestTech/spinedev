"""
Tests for Socket.IO server module.

Tests (pure unit tests, no actual connections):
- sio is AsyncServer instance
- socket_app is ASGIApp instance
- set_jwt_secret / get_jwt_secret work correctly
- broadcast functions call sio.emit with correct room and data
- Timestamps included in payloads
- Room name formatting
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
import socketio

from tron.realtime.socket_server import (
    sio,
    socket_app,
    set_jwt_secret,
    get_jwt_secret,
    broadcast_workflow_event,
    broadcast_project_event,
    broadcast_metric_update,
)


class TestSocketIOInstance:
    """Tests for sio and socket_app instances."""

    def test_sio_is_async_server(self) -> None:
        """sio is a socketio.AsyncServer instance."""
        assert isinstance(sio, socketio.AsyncServer)

    def test_sio_has_async_mode_asgi(self) -> None:
        """sio is configured with async_mode='asgi'."""
        assert sio.async_mode == 'asgi'

    def test_socket_app_is_asgi_app(self) -> None:
        """socket_app is a socketio.ASGIApp instance."""
        assert isinstance(socket_app, socketio.ASGIApp)

    def test_socket_app_is_asgi_callable(self) -> None:
        """socket_app is a callable ASGI application."""
        assert callable(socket_app)


class TestJWTSecretManagement:
    """Tests for JWT secret set/get."""

    def test_get_jwt_secret_initially_none(self) -> None:
        """get_jwt_secret returns None before set_jwt_secret called."""
        with patch('tron.realtime.socket_server._jwt_secret', None):
            result = get_jwt_secret()
            assert result is None

    def test_set_jwt_secret(self) -> None:
        """set_jwt_secret stores the secret."""
        secret = "test-secret-key"
        set_jwt_secret(secret)
        result = get_jwt_secret()
        assert result == secret

    def test_set_jwt_secret_multiple_times(self) -> None:
        """set_jwt_secret can be called multiple times."""
        set_jwt_secret("first-secret")
        assert get_jwt_secret() == "first-secret"

        set_jwt_secret("second-secret")
        assert get_jwt_secret() == "second-secret"

    def test_set_jwt_secret_with_empty_string(self) -> None:
        """set_jwt_secret accepts empty string."""
        set_jwt_secret("")
        assert get_jwt_secret() == ""


class TestBroadcastWorkflowEvent:
    """Tests for broadcast_workflow_event function."""

    @pytest.mark.asyncio
    async def test_broadcast_workflow_event_calls_emit(self) -> None:
        """broadcast_workflow_event calls sio.emit."""
        workflow_id = str(uuid4())
        event_type = "workflow_started"
        data = {"key": "value"}

        with patch.object(sio, 'emit', new_callable=AsyncMock) as mock_emit:
            await broadcast_workflow_event(workflow_id, event_type, data)

            mock_emit.assert_called_once()

    @pytest.mark.asyncio
    async def test_broadcast_workflow_event_correct_room(self) -> None:
        """broadcast_workflow_event sends to workflow:{workflow_id} room."""
        workflow_id = str(uuid4())
        event_type = "workflow_started"
        data = {"key": "value"}

        with patch.object(sio, 'emit', new_callable=AsyncMock) as mock_emit:
            await broadcast_workflow_event(workflow_id, event_type, data)

            call_args = mock_emit.call_args
            # Check room argument (keyword argument)
            assert call_args.kwargs.get('room') == f"workflow:{workflow_id}"

    @pytest.mark.asyncio
    async def test_broadcast_workflow_event_correct_event_name(self) -> None:
        """broadcast_workflow_event emits to 'workflow_event'."""
        workflow_id = str(uuid4())

        with patch.object(sio, 'emit', new_callable=AsyncMock) as mock_emit:
            await broadcast_workflow_event(workflow_id, "test_event", {})

            call_args = mock_emit.call_args
            # First argument is the event name
            assert call_args[0][0] == "workflow_event"

    @pytest.mark.asyncio
    async def test_broadcast_workflow_event_includes_event_type(self) -> None:
        """broadcast_workflow_event includes event_type in payload."""
        workflow_id = str(uuid4())
        event_type = "workflow_progress"
        data = {}

        with patch.object(sio, 'emit', new_callable=AsyncMock) as mock_emit:
            await broadcast_workflow_event(workflow_id, event_type, data)

            call_args = mock_emit.call_args
            payload = call_args[0][1]  # Second positional arg is payload
            assert payload["event_type"] == event_type

    @pytest.mark.asyncio
    async def test_broadcast_workflow_event_includes_workflow_id(self) -> None:
        """broadcast_workflow_event includes workflow_id in payload."""
        workflow_id = str(uuid4())

        with patch.object(sio, 'emit', new_callable=AsyncMock) as mock_emit:
            await broadcast_workflow_event(workflow_id, "test", {})

            call_args = mock_emit.call_args
            payload = call_args[0][1]
            assert payload["workflow_id"] == workflow_id

    @pytest.mark.asyncio
    async def test_broadcast_workflow_event_includes_timestamp(self) -> None:
        """broadcast_workflow_event includes ISO timestamp in payload."""
        workflow_id = str(uuid4())

        with patch.object(sio, 'emit', new_callable=AsyncMock) as mock_emit:
            before = datetime.utcnow()
            await broadcast_workflow_event(workflow_id, "test", {})
            after = datetime.utcnow()

            call_args = mock_emit.call_args
            payload = call_args[0][1]
            timestamp_str = payload["timestamp"]

            # Parse the ISO timestamp
            ts = datetime.fromisoformat(timestamp_str)
            assert before <= ts <= after

    @pytest.mark.asyncio
    async def test_broadcast_workflow_event_includes_data(self) -> None:
        """broadcast_workflow_event includes event data in payload."""
        workflow_id = str(uuid4())
        data = {"progress": 50, "status": "running"}

        with patch.object(sio, 'emit', new_callable=AsyncMock) as mock_emit:
            await broadcast_workflow_event(workflow_id, "test", data)

            call_args = mock_emit.call_args
            payload = call_args[0][1]
            assert payload["data"] == data

    @pytest.mark.asyncio
    async def test_broadcast_workflow_event_empty_data(self) -> None:
        """broadcast_workflow_event works with empty data."""
        workflow_id = str(uuid4())

        with patch.object(sio, 'emit', new_callable=AsyncMock) as mock_emit:
            await broadcast_workflow_event(workflow_id, "test", {})

            call_args = mock_emit.call_args
            payload = call_args[0][1]
            assert payload["data"] == {}


class TestBroadcastProjectEvent:
    """Tests for broadcast_project_event function."""

    @pytest.mark.asyncio
    async def test_broadcast_project_event_calls_emit(self) -> None:
        """broadcast_project_event calls sio.emit."""
        project_id = str(uuid4())
        event_type = "project_updated"
        data = {"name": "My Project"}

        with patch.object(sio, 'emit', new_callable=AsyncMock) as mock_emit:
            await broadcast_project_event(project_id, event_type, data)

            mock_emit.assert_called_once()

    @pytest.mark.asyncio
    async def test_broadcast_project_event_correct_room(self) -> None:
        """broadcast_project_event sends to project:{project_id} room."""
        project_id = str(uuid4())

        with patch.object(sio, 'emit', new_callable=AsyncMock) as mock_emit:
            await broadcast_project_event(project_id, "test", {})

            call_args = mock_emit.call_args
            assert call_args.kwargs.get('room') == f"project:{project_id}"

    @pytest.mark.asyncio
    async def test_broadcast_project_event_correct_event_name(self) -> None:
        """broadcast_project_event emits to 'project_event'."""
        project_id = str(uuid4())

        with patch.object(sio, 'emit', new_callable=AsyncMock) as mock_emit:
            await broadcast_project_event(project_id, "test", {})

            call_args = mock_emit.call_args
            assert call_args[0][0] == "project_event"

    @pytest.mark.asyncio
    async def test_broadcast_project_event_includes_event_type(self) -> None:
        """broadcast_project_event includes event_type in payload."""
        project_id = str(uuid4())
        event_type = "project_settings_changed"

        with patch.object(sio, 'emit', new_callable=AsyncMock) as mock_emit:
            await broadcast_project_event(project_id, event_type, {})

            call_args = mock_emit.call_args
            payload = call_args[0][1]
            assert payload["event_type"] == event_type

    @pytest.mark.asyncio
    async def test_broadcast_project_event_includes_project_id(self) -> None:
        """broadcast_project_event includes project_id in payload."""
        project_id = str(uuid4())

        with patch.object(sio, 'emit', new_callable=AsyncMock) as mock_emit:
            await broadcast_project_event(project_id, "test", {})

            call_args = mock_emit.call_args
            payload = call_args[0][1]
            assert payload["project_id"] == project_id

    @pytest.mark.asyncio
    async def test_broadcast_project_event_includes_timestamp(self) -> None:
        """broadcast_project_event includes ISO timestamp in payload."""
        project_id = str(uuid4())

        with patch.object(sio, 'emit', new_callable=AsyncMock) as mock_emit:
            before = datetime.utcnow()
            await broadcast_project_event(project_id, "test", {})
            after = datetime.utcnow()

            call_args = mock_emit.call_args
            payload = call_args[0][1]
            ts = datetime.fromisoformat(payload["timestamp"])
            assert before <= ts <= after

    @pytest.mark.asyncio
    async def test_broadcast_project_event_includes_data(self) -> None:
        """broadcast_project_event includes event data in payload."""
        project_id = str(uuid4())
        data = {"status": "active", "member_count": 5}

        with patch.object(sio, 'emit', new_callable=AsyncMock) as mock_emit:
            await broadcast_project_event(project_id, "test", data)

            call_args = mock_emit.call_args
            payload = call_args[0][1]
            assert payload["data"] == data


class TestBroadcastMetricUpdate:
    """Tests for broadcast_metric_update function."""

    @pytest.mark.asyncio
    async def test_broadcast_metric_update_calls_emit(self) -> None:
        """broadcast_metric_update calls sio.emit."""
        metric_type = "cost_update"
        data = {"total": 100.50}

        with patch.object(sio, 'emit', new_callable=AsyncMock) as mock_emit:
            await broadcast_metric_update(metric_type, data)

            mock_emit.assert_called_once()

    @pytest.mark.asyncio
    async def test_broadcast_metric_update_broadcasts_to_all(self) -> None:
        """broadcast_metric_update broadcasts to all clients (no room specified)."""
        metric_type = "cost_update"

        with patch.object(sio, 'emit', new_callable=AsyncMock) as mock_emit:
            await broadcast_metric_update(metric_type, {})

            call_args = mock_emit.call_args
            # Should not specify a room (broadcast to all)
            assert 'room' not in call_args.kwargs or call_args.kwargs.get('room') is None

    @pytest.mark.asyncio
    async def test_broadcast_metric_update_correct_event_name(self) -> None:
        """broadcast_metric_update emits to 'metric_update'."""
        with patch.object(sio, 'emit', new_callable=AsyncMock) as mock_emit:
            await broadcast_metric_update("cost_update", {})

            call_args = mock_emit.call_args
            assert call_args[0][0] == "metric_update"

    @pytest.mark.asyncio
    async def test_broadcast_metric_update_includes_metric_type(self) -> None:
        """broadcast_metric_update includes metric_type in payload."""
        metric_type = "system_health"

        with patch.object(sio, 'emit', new_callable=AsyncMock) as mock_emit:
            await broadcast_metric_update(metric_type, {})

            call_args = mock_emit.call_args
            payload = call_args[0][1]
            assert payload["metric_type"] == metric_type

    @pytest.mark.asyncio
    async def test_broadcast_metric_update_includes_timestamp(self) -> None:
        """broadcast_metric_update includes ISO timestamp in payload."""
        with patch.object(sio, 'emit', new_callable=AsyncMock) as mock_emit:
            before = datetime.utcnow()
            await broadcast_metric_update("test_metric", {})
            after = datetime.utcnow()

            call_args = mock_emit.call_args
            payload = call_args[0][1]
            ts = datetime.fromisoformat(payload["timestamp"])
            assert before <= ts <= after

    @pytest.mark.asyncio
    async def test_broadcast_metric_update_includes_data(self) -> None:
        """broadcast_metric_update includes event data in payload."""
        data = {"cpu": 45.2, "memory": 62.5, "disk": 78.1}

        with patch.object(sio, 'emit', new_callable=AsyncMock) as mock_emit:
            await broadcast_metric_update("system_metrics", data)

            call_args = mock_emit.call_args
            payload = call_args[0][1]
            assert payload["data"] == data

    @pytest.mark.asyncio
    async def test_broadcast_metric_update_empty_data(self) -> None:
        """broadcast_metric_update works with empty data."""
        with patch.object(sio, 'emit', new_callable=AsyncMock) as mock_emit:
            await broadcast_metric_update("ping", {})

            call_args = mock_emit.call_args
            payload = call_args[0][1]
            assert payload["data"] == {}


class TestRoomNameFormatting:
    """Tests for room name formatting in broadcast functions."""

    @pytest.mark.asyncio
    async def test_workflow_room_format(self) -> None:
        """Workflow room follows format: workflow:{id}."""
        workflow_id = str(uuid4())

        with patch.object(sio, 'emit', new_callable=AsyncMock):
            await broadcast_workflow_event(workflow_id, "test", {})
            # Just verify the format is used — tested in the broadcast test

    @pytest.mark.asyncio
    async def test_project_room_format(self) -> None:
        """Project room follows format: project:{id}."""
        project_id = str(uuid4())

        with patch.object(sio, 'emit', new_callable=AsyncMock):
            await broadcast_project_event(project_id, "test", {})
            # Just verify the format is used — tested in the broadcast test

    @pytest.mark.asyncio
    async def test_multiple_broadcast_with_different_ids(self) -> None:
        """Multiple broadcasts with different IDs target different rooms."""
        workflow_id_1 = str(uuid4())
        workflow_id_2 = str(uuid4())

        with patch.object(sio, 'emit', new_callable=AsyncMock) as mock_emit:
            await broadcast_workflow_event(workflow_id_1, "test", {})
            await broadcast_workflow_event(workflow_id_2, "test", {})

            assert mock_emit.call_count == 2
            rooms = [
                mock_emit.call_args_list[0].kwargs.get('room'),
                mock_emit.call_args_list[1].kwargs.get('room'),
            ]
            assert rooms[0] == f"workflow:{workflow_id_1}"
            assert rooms[1] == f"workflow:{workflow_id_2}"


class TestPayloadStructure:
    """Tests for consistency of payload structure across broadcast functions."""

    @pytest.mark.asyncio
    async def test_workflow_payload_has_required_fields(self) -> None:
        """Workflow event payload has required fields."""
        with patch.object(sio, 'emit', new_callable=AsyncMock) as mock_emit:
            await broadcast_workflow_event(str(uuid4()), "test", {"data": "value"})

            payload = mock_emit.call_args[0][1]
            assert "event_type" in payload
            assert "workflow_id" in payload
            assert "timestamp" in payload
            assert "data" in payload

    @pytest.mark.asyncio
    async def test_project_payload_has_required_fields(self) -> None:
        """Project event payload has required fields."""
        with patch.object(sio, 'emit', new_callable=AsyncMock) as mock_emit:
            await broadcast_project_event(str(uuid4()), "test", {"data": "value"})

            payload = mock_emit.call_args[0][1]
            assert "event_type" in payload
            assert "project_id" in payload
            assert "timestamp" in payload
            assert "data" in payload

    @pytest.mark.asyncio
    async def test_metric_payload_has_required_fields(self) -> None:
        """Metric update payload has required fields."""
        with patch.object(sio, 'emit', new_callable=AsyncMock) as mock_emit:
            await broadcast_metric_update("test_metric", {"data": "value"})

            payload = mock_emit.call_args[0][1]
            assert "metric_type" in payload
            assert "timestamp" in payload
            assert "data" in payload
