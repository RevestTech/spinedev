"""
Tests for real-time domain events.

Tests:
- EventType enum values
- DomainEvent creation and validation
- DomainEvent serialization
- publish_event routing to broadcast functions
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from tron.realtime.events import EventType, DomainEvent, publish_event


class TestEventTypeEnum:
    """Tests for EventType enum."""

    def test_event_type_workflow_started(self) -> None:
        """EventType.WORKFLOW_STARTED has correct value."""
        assert EventType.WORKFLOW_STARTED.value == "workflow_started"

    def test_event_type_workflow_progress(self) -> None:
        """EventType.WORKFLOW_PROGRESS has correct value."""
        assert EventType.WORKFLOW_PROGRESS.value == "workflow_progress"

    def test_event_type_workflow_completed(self) -> None:
        """EventType.WORKFLOW_COMPLETED has correct value."""
        assert EventType.WORKFLOW_COMPLETED.value == "workflow_completed"

    def test_event_type_workflow_failed(self) -> None:
        """EventType.WORKFLOW_FAILED has correct value."""
        assert EventType.WORKFLOW_FAILED.value == "workflow_failed"

    def test_event_type_finding_discovered(self) -> None:
        """EventType.FINDING_DISCOVERED has correct value."""
        assert EventType.FINDING_DISCOVERED.value == "finding_discovered"

    def test_event_type_agent_status_changed(self) -> None:
        """EventType.AGENT_STATUS_CHANGED has correct value."""
        assert EventType.AGENT_STATUS_CHANGED.value == "agent_status_changed"

    def test_event_type_cost_update(self) -> None:
        """EventType.COST_UPDATE has correct value."""
        assert EventType.COST_UPDATE.value == "cost_update"

    def test_event_type_project_updated(self) -> None:
        """EventType.PROJECT_UPDATED has correct value."""
        assert EventType.PROJECT_UPDATED.value == "project_updated"

    def test_event_type_all_values(self) -> None:
        """All EventType values are strings."""
        for event_type in EventType:
            assert isinstance(event_type.value, str)


class TestDomainEventCreation:
    """Tests for DomainEvent creation."""

    def test_domain_event_minimal(self) -> None:
        """DomainEvent can be created with just event_type."""
        event = DomainEvent(event_type=EventType.WORKFLOW_STARTED)
        assert event.event_type == EventType.WORKFLOW_STARTED
        assert event.workflow_id is None
        assert event.project_id is None
        assert event.data == {}
        assert isinstance(event.timestamp, datetime)

    def test_domain_event_with_workflow_id(self) -> None:
        """DomainEvent can include workflow_id."""
        workflow_id = uuid4()
        event = DomainEvent(
            event_type=EventType.WORKFLOW_PROGRESS,
            workflow_id=workflow_id,
        )
        assert event.workflow_id == workflow_id

    def test_domain_event_with_project_id(self) -> None:
        """DomainEvent can include project_id."""
        project_id = uuid4()
        event = DomainEvent(
            event_type=EventType.PROJECT_UPDATED,
            project_id=project_id,
        )
        assert event.project_id == project_id

    def test_domain_event_with_data(self) -> None:
        """DomainEvent can include arbitrary data."""
        data = {"key": "value", "count": 42}
        event = DomainEvent(
            event_type=EventType.WORKFLOW_PROGRESS,
            data=data,
        )
        assert event.data == data

    def test_domain_event_with_custom_timestamp(self) -> None:
        """DomainEvent accepts custom timestamp."""
        ts = datetime(2025, 1, 1, 12, 0, 0)
        event = DomainEvent(
            event_type=EventType.WORKFLOW_STARTED,
            timestamp=ts,
        )
        assert event.timestamp == ts

    def test_domain_event_default_timestamp(self) -> None:
        """DomainEvent generates default timestamp."""
        before = datetime.utcnow()
        event = DomainEvent(event_type=EventType.WORKFLOW_STARTED)
        after = datetime.utcnow()
        assert before <= event.timestamp <= after

    def test_domain_event_full(self) -> None:
        """DomainEvent with all fields."""
        workflow_id = uuid4()
        project_id = uuid4()
        data = {"progress": 50}
        ts = datetime(2025, 1, 1, 12, 0, 0)

        event = DomainEvent(
            event_type=EventType.WORKFLOW_PROGRESS,
            workflow_id=workflow_id,
            project_id=project_id,
            timestamp=ts,
            data=data,
        )

        assert event.event_type == EventType.WORKFLOW_PROGRESS
        assert event.workflow_id == workflow_id
        assert event.project_id == project_id
        assert event.timestamp == ts
        assert event.data == data


class TestDomainEventValidation:
    """Tests for DomainEvent validation."""

    def test_domain_event_invalid_event_type(self) -> None:
        """DomainEvent requires valid event_type."""
        with pytest.raises(ValueError):
            DomainEvent(event_type="invalid_event")

    def test_domain_event_workflow_id_must_be_uuid(self) -> None:
        """DomainEvent workflow_id must be UUID."""
        with pytest.raises(ValueError):
            DomainEvent(
                event_type=EventType.WORKFLOW_STARTED,
                workflow_id="not-a-uuid",
            )

    def test_domain_event_project_id_must_be_uuid(self) -> None:
        """DomainEvent project_id must be UUID."""
        with pytest.raises(ValueError):
            DomainEvent(
                event_type=EventType.PROJECT_UPDATED,
                project_id="not-a-uuid",
            )

    def test_domain_event_data_must_be_dict(self) -> None:
        """DomainEvent data must be dict."""
        with pytest.raises(ValueError):
            DomainEvent(
                event_type=EventType.WORKFLOW_STARTED,
                data="not-a-dict",
            )


class TestDomainEventSerialization:
    """Tests for DomainEvent serialization."""

    def test_domain_event_dict(self) -> None:
        """DomainEvent can be converted to dict."""
        workflow_id = uuid4()
        event = DomainEvent(
            event_type=EventType.WORKFLOW_STARTED,
            workflow_id=workflow_id,
            data={"key": "value"},
        )

        event_dict = event.dict()
        assert event_dict["event_type"] == "workflow_started"
        assert str(event_dict["workflow_id"]) == str(workflow_id)
        assert event_dict["data"] == {"key": "value"}

    def test_domain_event_json(self) -> None:
        """DomainEvent can be serialized to JSON."""
        workflow_id = uuid4()
        event = DomainEvent(
            event_type=EventType.WORKFLOW_STARTED,
            workflow_id=workflow_id,
            data={"key": "value"},
        )

        json_str = event.json()
        assert "workflow_started" in json_str
        assert str(workflow_id) in json_str
        assert '"key"' in json_str and '"value"' in json_str

    def test_domain_event_json_with_timestamp(self) -> None:
        """DomainEvent JSON includes ISO timestamp."""
        ts = datetime(2025, 1, 1, 12, 0, 0)
        event = DomainEvent(
            event_type=EventType.WORKFLOW_STARTED,
            timestamp=ts,
        )

        json_str = event.json()
        assert "2025-01-01T12:00:00" in json_str

    def test_domain_event_json_uuid_serialization(self) -> None:
        """DomainEvent JSON serializes UUIDs as strings."""
        workflow_id = uuid4()
        event = DomainEvent(
            event_type=EventType.WORKFLOW_STARTED,
            workflow_id=workflow_id,
        )

        json_str = event.json()
        # UUID should be serialized as string in JSON
        assert str(workflow_id) in json_str


class TestPublishEvent:
    """Tests for publish_event function."""

    @pytest.mark.asyncio
    async def test_publish_event_with_workflow_id(self) -> None:
        """publish_event routes to broadcast_workflow_event when workflow_id set."""
        workflow_id = uuid4()
        event = DomainEvent(
            event_type=EventType.WORKFLOW_STARTED,
            workflow_id=workflow_id,
            data={"key": "value"},
        )

        with patch(
            'tron.realtime.socket_server.broadcast_workflow_event',
            new_callable=AsyncMock,
        ) as mock_broadcast:
            await publish_event(event)

            mock_broadcast.assert_called_once()
            call_args = mock_broadcast.call_args
            assert str(workflow_id) in call_args[0]  # workflow_id in args
            assert "workflow_started" in call_args[0]  # event_type in args
            assert call_args[0][2] == {"key": "value"}  # data in args

    @pytest.mark.asyncio
    async def test_publish_event_with_project_id(self) -> None:
        """publish_event routes to broadcast_project_event when project_id set."""
        project_id = uuid4()
        event = DomainEvent(
            event_type=EventType.PROJECT_UPDATED,
            project_id=project_id,
            data={"status": "updated"},
        )

        with patch(
            'tron.realtime.socket_server.broadcast_project_event',
            new_callable=AsyncMock,
        ) as mock_broadcast:
            await publish_event(event)

            mock_broadcast.assert_called_once()
            call_args = mock_broadcast.call_args
            assert str(project_id) in call_args[0]  # project_id in args
            assert "project_updated" in call_args[0]  # event_type in args

    @pytest.mark.asyncio
    async def test_publish_event_without_ids(self) -> None:
        """publish_event routes to broadcast_metric_update when no IDs set."""
        event = DomainEvent(
            event_type=EventType.COST_UPDATE,
            data={"total_cost": 100.50},
        )

        with patch(
            'tron.realtime.socket_server.broadcast_metric_update',
            new_callable=AsyncMock,
        ) as mock_broadcast:
            await publish_event(event)

            mock_broadcast.assert_called_once()
            call_args = mock_broadcast.call_args
            assert "cost_update" in call_args[0]  # event_type in args

    @pytest.mark.asyncio
    async def test_publish_event_prefers_workflow_over_project(self) -> None:
        """publish_event prefers workflow_id if both workflow_id and project_id set."""
        workflow_id = uuid4()
        project_id = uuid4()
        event = DomainEvent(
            event_type=EventType.WORKFLOW_PROGRESS,
            workflow_id=workflow_id,
            project_id=project_id,
            data={"progress": 50},
        )

        with patch(
            'tron.realtime.socket_server.broadcast_workflow_event',
            new_callable=AsyncMock,
        ) as mock_wf:
            with patch(
                'tron.realtime.socket_server.broadcast_project_event',
                new_callable=AsyncMock,
            ) as mock_proj:
                await publish_event(event)

                # Should call workflow broadcast, not project
                mock_wf.assert_called_once()
                mock_proj.assert_not_called()

    @pytest.mark.asyncio
    async def test_publish_event_includes_data(self) -> None:
        """publish_event includes event data in broadcast."""
        workflow_id = uuid4()
        data = {
            "progress": 75,
            "current_step": "analyzing",
            "agent": "security-agent",
        }
        event = DomainEvent(
            event_type=EventType.WORKFLOW_PROGRESS,
            workflow_id=workflow_id,
            data=data,
        )

        with patch(
            'tron.realtime.socket_server.broadcast_workflow_event',
            new_callable=AsyncMock,
        ) as mock_broadcast:
            await publish_event(event)

            call_args = mock_broadcast.call_args
            # data should be passed as third argument
            assert call_args[0][2] == data

    @pytest.mark.asyncio
    async def test_publish_event_multiple_calls(self) -> None:
        """publish_event can be called multiple times."""
        workflow_id = uuid4()

        with patch(
            'tron.realtime.socket_server.broadcast_workflow_event',
            new_callable=AsyncMock,
        ) as mock_broadcast:
            for i in range(3):
                event = DomainEvent(
                    event_type=EventType.WORKFLOW_PROGRESS,
                    workflow_id=workflow_id,
                    data={"step": i},
                )
                await publish_event(event)

            assert mock_broadcast.call_count == 3
