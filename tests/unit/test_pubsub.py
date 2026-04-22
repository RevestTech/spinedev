"""
Unit tests for Redis pub/sub event publishing.

Tests:
  - Event channel format
  - publish_progress builds correct payload
  - publish_finding builds correct payload
  - publish_audit_completed / publish_audit_failed
  - Best-effort: exceptions are swallowed
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from tron.infra.redis.pubsub import (
    AuditEvent,
    publish_audit_event,
    publish_progress,
    publish_finding,
    publish_audit_completed,
    publish_audit_failed,
)


@pytest.fixture
def audit_run_id():
    return uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")


class TestAuditEventEnum:

    def test_all_events_exist(self):
        events = [e.value for e in AuditEvent]
        assert "status_change" in events
        assert "progress_update" in events
        assert "finding_discovered" in events
        assert "agent_started" in events
        assert "agent_completed" in events
        assert "audit_completed" in events
        assert "audit_failed" in events


class TestPublishProgress:

    async def test_publish_progress_calls_redis(self, audit_run_id, mock_redis):
        """publish_progress sends to correct channel with correct payload."""
        with patch("tron.infra.redis.pubsub.get_redis", return_value=mock_redis):
            await publish_progress(audit_run_id, "running", 50, "Scanning files")

        mock_redis.publish.assert_called_once()
        call_args = mock_redis.publish.call_args
        channel = call_args[0][0]
        payload = json.loads(call_args[0][1])

        assert f"audit:{audit_run_id}:progress" == channel
        assert payload["event"] == "progress_update"
        assert payload["data"]["status"] == "running"
        assert payload["data"]["progress"] == 50
        assert payload["data"]["message"] == "Scanning files"

    async def test_publish_progress_swallows_errors(self, audit_run_id, mock_redis):
        """Redis errors don't propagate (best-effort)."""
        mock_redis.publish.side_effect = ConnectionError("Redis down")
        with patch("tron.infra.redis.pubsub.get_redis", return_value=mock_redis):
            # Should not raise
            await publish_progress(audit_run_id, "running", 50, "test")


class TestPublishAuditCompleted:

    async def test_publish_completed(self, audit_run_id, mock_redis):
        with patch("tron.infra.redis.pubsub.get_redis", return_value=mock_redis):
            await publish_audit_completed(
                audit_run_id,
                findings_total=10,
                findings_critical=1,
                findings_high=3,
                findings_medium=4,
                findings_low=2,
                duration_seconds=45.3,
            )

        call_args = mock_redis.publish.call_args
        payload = json.loads(call_args[0][1])
        assert payload["event"] == "audit_completed"
        assert payload["data"]["findings_total"] == 10
        assert payload["data"]["findings_critical"] == 1


class TestPublishAuditFailed:

    async def test_publish_failed(self, audit_run_id, mock_redis):
        with patch("tron.infra.redis.pubsub.get_redis", return_value=mock_redis):
            await publish_audit_failed(audit_run_id, "LLM timeout")

        call_args = mock_redis.publish.call_args
        payload = json.loads(call_args[0][1])
        assert payload["event"] == "audit_failed"
        assert "LLM timeout" in payload["data"]["error_message"]
