"""
Unit tests for Redis pub/sub audit event publishing.

Tests:
  - publish_audit_event with Redis available
  - publish_audit_event with Redis unavailable (graceful degradation)
  - publish_progress, publish_finding, publish_audit_completed convenience functions
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch
from uuid import uuid4


from tron.infra.redis.pubsub import (
    AuditEvent,
    publish_audit_event,
    publish_progress,
    publish_finding,
    publish_audit_completed,
    _channel_name,
)


class TestPublishAuditEvent:
    """Test audit event publishing."""

    async def test_publish_event_success(self):
        """publish_audit_event should publish to Redis and return subscriber count."""
        audit_id = uuid4()
        mock_redis = AsyncMock()
        mock_redis.publish = AsyncMock(return_value=2)  # 2 subscribers

        with patch("tron.infra.redis.pubsub.get_redis", return_value=mock_redis):
            count = await publish_audit_event(
                audit_id,
                AuditEvent.PROGRESS_UPDATE,
                {"progress": 50},
            )

        assert count == 2
        mock_redis.publish.assert_called_once()
        call_args = mock_redis.publish.call_args[0]
        channel = call_args[0]
        payload = json.loads(call_args[1])
        assert payload["event"] == "progress_update"
        assert payload["audit_run_id"] == str(audit_id)
        assert payload["data"]["progress"] == 50

    async def test_publish_event_redis_unavailable(self):
        """publish_audit_event should gracefully handle Redis unavailability."""
        audit_id = uuid4()

        with patch("tron.infra.redis.pubsub.get_redis", side_effect=RuntimeError("Redis not available")):
            count = await publish_audit_event(
                audit_id,
                AuditEvent.FINDING_DISCOVERED,
                {"severity": "high"},
            )

        assert count == 0

    async def test_publish_event_redis_error(self):
        """publish_audit_event should return 0 on Redis publish error."""
        audit_id = uuid4()
        mock_redis = AsyncMock()
        mock_redis.publish = AsyncMock(side_effect=Exception("Redis error"))

        with patch("tron.infra.redis.pubsub.get_redis", return_value=mock_redis):
            count = await publish_audit_event(
                audit_id,
                AuditEvent.STATUS_CHANGE,
                {"status": "running"},
            )

        assert count == 0


class TestChannelName:
    """Test channel name generation."""

    def test_channel_name_format(self):
        """_channel_name should format audit:id:progress."""
        audit_id = uuid4()
        channel = _channel_name(audit_id)
        assert channel == f"audit:{audit_id}:progress"


class TestPublishProgress:
    """Test progress update convenience function."""

    async def test_publish_progress_sends_correct_event(self):
        """publish_progress should send PROGRESS_UPDATE event."""
        audit_id = uuid4()
        mock_redis = AsyncMock()
        mock_redis.publish = AsyncMock(return_value=1)

        with patch("tron.infra.redis.pubsub.get_redis", return_value=mock_redis):
            await publish_progress(
                audit_id,
                "running",
                75,
                "Scanning files...",
            )

        call_args = mock_redis.publish.call_args[0]
        payload = json.loads(call_args[1])
        assert payload["event"] == "progress_update"
        assert payload["data"]["status"] == "running"
        assert payload["data"]["progress"] == 75
        assert payload["data"]["message"] == "Scanning files..."


class TestPublishFinding:
    """Test finding discovery convenience function."""

    async def test_publish_finding_sends_correct_event(self):
        """publish_finding should send FINDING_DISCOVERED event."""
        audit_id = uuid4()
        mock_redis = AsyncMock()
        mock_redis.publish = AsyncMock(return_value=1)

        with patch("tron.infra.redis.pubsub.get_redis", return_value=mock_redis):
            await publish_finding(
                audit_id,
                "critical",
                "SQL Injection Vulnerability",
                "src/db/query.py",
                42,
                tool_confirmed=True,
            )

        call_args = mock_redis.publish.call_args[0]
        payload = json.loads(call_args[1])
        assert payload["event"] == "finding_discovered"
        assert payload["data"]["severity"] == "critical"
        assert payload["data"]["title"] == "SQL Injection Vulnerability"
        assert payload["data"]["file_path"] == "src/db/query.py"
        assert payload["data"]["line_number"] == 42
        assert payload["data"]["tool_confirmed"] is True


class TestPublishAuditCompleted:
    """Test audit completion convenience function."""

    async def test_publish_audit_completed(self):
        """publish_audit_completed should send final stats."""
        audit_id = uuid4()
        mock_redis = AsyncMock()
        mock_redis.publish = AsyncMock(return_value=1)

        with patch("tron.infra.redis.pubsub.get_redis", return_value=mock_redis):
            await publish_audit_completed(
                audit_id,
                findings_total=5,
                findings_critical=1,
                findings_high=2,
                findings_medium=1,
                findings_low=1,
                duration_seconds=123.456,
            )

        call_args = mock_redis.publish.call_args[0]
        payload = json.loads(call_args[1])
        assert payload["event"] == "audit_completed"
        assert payload["data"]["findings_total"] == 5
        assert payload["data"]["findings_critical"] == 1
        assert payload["data"]["findings_high"] == 2
        assert payload["data"]["findings_medium"] == 1
        assert payload["data"]["findings_low"] == 1
        # Duration should be rounded to 1 decimal
        assert abs(payload["data"]["duration_seconds"] - 123.5) < 0.1


class TestAuditEventEnum:
    """Test AuditEvent enum values."""

    def test_audit_event_values(self):
        """AuditEvent should have standard event types."""
        assert AuditEvent.STATUS_CHANGE.value == "status_change"
        assert AuditEvent.PROGRESS_UPDATE.value == "progress_update"
        assert AuditEvent.FINDING_DISCOVERED.value == "finding_discovered"
        assert AuditEvent.AGENT_STARTED.value == "agent_started"
        assert AuditEvent.AGENT_COMPLETED.value == "agent_completed"
        assert AuditEvent.AUDIT_COMPLETED.value == "audit_completed"
        assert AuditEvent.AUDIT_FAILED.value == "audit_failed"
