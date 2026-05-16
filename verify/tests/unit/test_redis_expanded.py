"""
Expanded unit tests for Redis client and pub/sub.

Tests:
  - Connection pool initialization and configuration
  - Pool closure
  - get_redis error handling
  - Pub/sub event publishing
  - Event serialization
  - Channel naming
  - Redis unavailability graceful handling
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import tron.infra.redis.client as redis_client
import tron.infra.redis.pubsub as pubsub_module


class TestInitRedis:
    """Tests for init_redis initialization."""

    async def test_init_redis_creates_pool(self):
        """init_redis creates aioredis connection pool."""
        original = redis_client._pool
        try:
            redis_client._pool = None
            
            with patch("redis.asyncio.from_url") as mock_from_url:
                mock_pool = AsyncMock()
                mock_pool.ping = AsyncMock(return_value=True)
                mock_from_url.return_value = mock_pool
                
                await redis_client.init_redis("redis://localhost:6379")
                
                mock_from_url.assert_called_once()
                assert redis_client._pool is mock_pool
        finally:
            redis_client._pool = original

    async def test_init_redis_with_custom_pool_size(self):
        """init_redis accepts custom pool_size parameter."""
        original = redis_client._pool
        try:
            redis_client._pool = None
            
            with patch("redis.asyncio.from_url") as mock_from_url:
                mock_pool = AsyncMock()
                mock_pool.ping = AsyncMock(return_value=True)
                mock_from_url.return_value = mock_pool
                
                await redis_client.init_redis("redis://localhost:6379", pool_size=100)
                
                # Verify pool_size was passed
                call_args = mock_from_url.call_args
                assert call_args[1]["max_connections"] == 100
        finally:
            redis_client._pool = original

    async def test_init_redis_configures_connection_params(self):
        """init_redis sets timeout and retry params."""
        original = redis_client._pool
        try:
            redis_client._pool = None
            
            with patch("redis.asyncio.from_url") as mock_from_url:
                mock_pool = AsyncMock()
                mock_pool.ping = AsyncMock(return_value=True)
                mock_from_url.return_value = mock_pool
                
                await redis_client.init_redis("redis://localhost:6379")
                
                call_args = mock_from_url.call_args[1]
                assert call_args["socket_connect_timeout"] == 5
                assert call_args["socket_timeout"] == 5
                assert call_args["retry_on_timeout"] is True
                assert call_args["decode_responses"] is True
        finally:
            redis_client._pool = original

    async def test_init_redis_verifies_connection(self):
        """init_redis calls ping() to verify connection."""
        original = redis_client._pool
        try:
            redis_client._pool = None
            
            with patch("redis.asyncio.from_url") as mock_from_url:
                mock_pool = AsyncMock()
                mock_pool.ping = AsyncMock(return_value=True)
                mock_from_url.return_value = mock_pool
                
                await redis_client.init_redis("redis://localhost:6379")
                
                mock_pool.ping.assert_called_once()
        finally:
            redis_client._pool = original

    async def test_init_redis_ping_failure_raises(self):
        """init_redis raises if ping fails."""
        original = redis_client._pool
        try:
            redis_client._pool = None
            
            with patch("redis.asyncio.from_url") as mock_from_url:
                mock_pool = AsyncMock()
                mock_pool.ping = AsyncMock(side_effect=Exception("Connection refused"))
                mock_from_url.return_value = mock_pool
                
                with pytest.raises(Exception):
                    await redis_client.init_redis("redis://localhost:6379")
        finally:
            redis_client._pool = original


class TestGetRedis:
    """Tests for get_redis retrieval."""

    def test_get_redis_returns_pool_when_initialized(self):
        """get_redis returns the initialized pool."""
        original = redis_client._pool
        try:
            fake_pool = AsyncMock()
            redis_client._pool = fake_pool
            
            result = redis_client.get_redis()
            
            assert result is fake_pool
        finally:
            redis_client._pool = original

    def test_get_redis_raises_when_not_initialized(self):
        """get_redis raises RuntimeError when pool is None."""
        original = redis_client._pool
        try:
            redis_client._pool = None
            
            with pytest.raises(RuntimeError, match="not initialized"):
                redis_client.get_redis()
        finally:
            redis_client._pool = original

    def test_get_redis_error_message_helpful(self):
        """RuntimeError message indicates calling init_redis first."""
        original = redis_client._pool
        try:
            redis_client._pool = None
            
            with pytest.raises(RuntimeError) as exc_info:
                redis_client.get_redis()
            
            assert "init_redis" in str(exc_info.value).lower()
        finally:
            redis_client._pool = original


class TestCloseRedis:
    """Tests for close_redis cleanup."""

    async def test_close_redis_closes_pool(self):
        """close_redis calls aclose() on pool."""
        original = redis_client._pool
        try:
            fake_pool = AsyncMock()
            redis_client._pool = fake_pool
            
            await redis_client.close_redis()
            
            fake_pool.aclose.assert_called_once()
        finally:
            redis_client._pool = original

    async def test_close_redis_clears_pool_reference(self):
        """close_redis sets _pool to None."""
        original = redis_client._pool
        try:
            fake_pool = AsyncMock()
            redis_client._pool = fake_pool
            
            await redis_client.close_redis()
            
            assert redis_client._pool is None
        finally:
            redis_client._pool = original

    async def test_close_redis_idempotent(self):
        """close_redis can be called multiple times safely."""
        original = redis_client._pool
        try:
            fake_pool = AsyncMock()
            redis_client._pool = fake_pool
            
            await redis_client.close_redis()
            await redis_client.close_redis()
            
            assert redis_client._pool is None
        finally:
            redis_client._pool = original


class TestPublishAuditEvent:
    """Tests for publish_audit_event function."""

    async def test_publish_audit_event_returns_subscriber_count(self, mock_redis):
        """publish_audit_event returns number of subscribers."""
        audit_id = uuid.uuid4()
        
        with patch("tron.infra.redis.pubsub.get_redis", return_value=mock_redis):
            count = await pubsub_module.publish_audit_event(
                audit_id,
                pubsub_module.AuditEvent.STATUS_CHANGE,
            )
        
        assert count == 1
        mock_redis.publish.assert_called_once()

    async def test_publish_audit_event_serializes_payload_as_json(self, mock_redis):
        """Event payload serialized as JSON."""
        audit_id = uuid.uuid4()

        with patch("tron.infra.redis.pubsub.get_redis", return_value=mock_redis):
            await pubsub_module.publish_audit_event(
                audit_id,
                pubsub_module.AuditEvent.PROGRESS_UPDATE,
                {"progress": 50, "message": "Processing"},
            )

        # Check the published message
        call_args = mock_redis.publish.call_args
        published_json = call_args[0][1]
        payload = json.loads(published_json)

        assert payload["event"] == "progress_update"
        assert payload["data"]["progress"] == 50
        assert payload["data"]["message"] == "Processing"

    async def test_publish_audit_event_includes_timestamp(self, mock_redis):
        """Event includes ISO 8601 timestamp."""
        audit_id = uuid.uuid4()
        
        with patch("tron.infra.redis.pubsub.get_redis", return_value=mock_redis):
            await pubsub_module.publish_audit_event(
                audit_id,
                pubsub_module.AuditEvent.AUDIT_COMPLETED,
            )
        
        call_args = mock_redis.publish.call_args
        published_json = call_args[0][1]
        payload = json.loads(published_json)
        
        assert "timestamp" in payload
        assert "T" in payload["timestamp"]  # ISO format

    async def test_publish_audit_event_includes_audit_run_id(self, mock_redis):
        """Event includes audit_run_id as string."""
        audit_id = uuid.uuid4()
        
        with patch("tron.infra.redis.pubsub.get_redis", return_value=mock_redis):
            await pubsub_module.publish_audit_event(
                audit_id,
                pubsub_module.AuditEvent.AGENT_STARTED,
            )
        
        call_args = mock_redis.publish.call_args
        published_json = call_args[0][1]
        payload = json.loads(published_json)
        
        assert payload["audit_run_id"] == str(audit_id)

    async def test_publish_audit_event_redis_unavailable_returns_zero(self):
        """Returns 0 if Redis unavailable, doesn't raise."""
        audit_id = uuid.uuid4()
        
        with patch("tron.infra.redis.pubsub.get_redis", side_effect=RuntimeError("not initialized")):
            count = await pubsub_module.publish_audit_event(
                audit_id,
                pubsub_module.AuditEvent.STATUS_CHANGE,
            )
        
        assert count == 0

    async def test_publish_audit_event_exception_handling(self, caplog):
        """Exceptions logged but not raised."""
        audit_id = uuid.uuid4()
        mock_redis = AsyncMock()
        mock_redis.publish = AsyncMock(side_effect=Exception("Redis error"))
        
        with patch("tron.infra.redis.pubsub.get_redis", return_value=mock_redis):
            count = await pubsub_module.publish_audit_event(
                audit_id,
                pubsub_module.AuditEvent.FINDING_DISCOVERED,
            )
        
        assert count == 0
        assert any("Failed to publish" in record.message for record in caplog.records)

    async def test_publish_audit_event_channel_naming(self, mock_redis):
        """Publishes to correctly formatted channel."""
        audit_id = uuid.uuid4()
        
        with patch("tron.infra.redis.pubsub.get_redis", return_value=mock_redis):
            await pubsub_module.publish_audit_event(
                audit_id,
                pubsub_module.AuditEvent.STATUS_CHANGE,
            )
        
        call_args = mock_redis.publish.call_args
        channel = call_args[0][0]
        
        expected_channel = f"audit:{audit_id}:progress"
        assert channel == expected_channel


class TestPublishProgress:
    """Tests for publish_progress convenience function."""

    async def test_publish_progress_calls_publish_audit_event(self, mock_redis):
        """publish_progress delegates to publish_audit_event."""
        audit_id = uuid.uuid4()
        
        with patch("tron.infra.redis.pubsub.get_redis", return_value=mock_redis):
            await pubsub_module.publish_progress(
                audit_id,
                "running",
                75,
                "Processing files",
            )
        
        call_args = mock_redis.publish.call_args
        published_json = call_args[0][1]
        payload = json.loads(published_json)
        
        assert payload["event"] == "progress_update"
        assert payload["data"]["status"] == "running"
        assert payload["data"]["progress"] == 75
        assert payload["data"]["message"] == "Processing files"

    async def test_publish_progress_default_message(self, mock_redis):
        """publish_progress uses empty message by default."""
        audit_id = uuid.uuid4()
        
        with patch("tron.infra.redis.pubsub.get_redis", return_value=mock_redis):
            await pubsub_module.publish_progress(
                audit_id,
                "completed",
                100,
            )
        
        call_args = mock_redis.publish.call_args
        published_json = call_args[0][1]
        payload = json.loads(published_json)
        
        assert payload["data"]["message"] == ""


class TestPublishFinding:
    """Tests for publish_finding convenience function."""

    async def test_publish_finding_structure(self, mock_redis):
        """publish_finding creates proper finding payload."""
        audit_id = uuid.uuid4()
        
        with patch("tron.infra.redis.pubsub.get_redis", return_value=mock_redis):
            await pubsub_module.publish_finding(
                audit_id,
                "critical",
                "SQL Injection",
                "app/db.py",
                42,
                tool_confirmed=True,
            )
        
        call_args = mock_redis.publish.call_args
        published_json = call_args[0][1]
        payload = json.loads(published_json)
        
        assert payload["event"] == "finding_discovered"
        assert payload["data"]["severity"] == "critical"
        assert payload["data"]["title"] == "SQL Injection"
        assert payload["data"]["file_path"] == "app/db.py"
        assert payload["data"]["line_number"] == 42
        assert payload["data"]["tool_confirmed"] is True

    async def test_publish_finding_default_tool_confirmed(self, mock_redis):
        """publish_finding defaults tool_confirmed to False."""
        audit_id = uuid.uuid4()
        
        with patch("tron.infra.redis.pubsub.get_redis", return_value=mock_redis):
            await pubsub_module.publish_finding(
                audit_id,
                "medium",
                "Some Issue",
                "file.py",
                10,
            )
        
        call_args = mock_redis.publish.call_args
        published_json = call_args[0][1]
        payload = json.loads(published_json)
        
        assert payload["data"]["tool_confirmed"] is False


class TestPublishAuditCompleted:
    """Tests for publish_audit_completed convenience function."""

    async def test_publish_audit_completed_payload(self, mock_redis):
        """publish_audit_completed creates final audit event."""
        audit_id = uuid.uuid4()
        
        with patch("tron.infra.redis.pubsub.get_redis", return_value=mock_redis):
            await pubsub_module.publish_audit_completed(
                audit_id,
                findings_total=5,
                findings_critical=1,
                findings_high=2,
                findings_medium=2,
                findings_low=0,
                duration_seconds=123.456,
            )
        
        call_args = mock_redis.publish.call_args
        published_json = call_args[0][1]
        payload = json.loads(published_json)
        
        assert payload["event"] == "audit_completed"
        assert payload["data"]["findings_total"] == 5
        assert payload["data"]["findings_critical"] == 1
        assert payload["data"]["findings_high"] == 2
        assert payload["data"]["findings_medium"] == 2
        assert payload["data"]["findings_low"] == 0
        assert payload["data"]["duration_seconds"] == 123.5  # Rounded to 1 decimal

    async def test_publish_audit_completed_duration_rounding(self, mock_redis):
        """Duration rounded to 1 decimal place."""
        audit_id = uuid.uuid4()
        
        with patch("tron.infra.redis.pubsub.get_redis", return_value=mock_redis):
            await pubsub_module.publish_audit_completed(
                audit_id,
                findings_total=0,
                findings_critical=0,
                findings_high=0,
                findings_medium=0,
                findings_low=0,
                duration_seconds=42.6789,
            )
        
        call_args = mock_redis.publish.call_args
        published_json = call_args[0][1]
        payload = json.loads(published_json)
        
        assert payload["data"]["duration_seconds"] == 42.7


class TestPublishAuditFailed:
    """Tests for publish_audit_failed convenience function."""

    async def test_publish_audit_failed_payload(self, mock_redis):
        """publish_audit_failed creates failure event."""
        audit_id = uuid.uuid4()
        
        with patch("tron.infra.redis.pubsub.get_redis", return_value=mock_redis):
            await pubsub_module.publish_audit_failed(
                audit_id,
                "Repository clone failed: timeout",
            )
        
        call_args = mock_redis.publish.call_args
        published_json = call_args[0][1]
        payload = json.loads(published_json)
        
        assert payload["event"] == "audit_failed"
        assert payload["data"]["error_message"] == "Repository clone failed: timeout"

    async def test_publish_audit_failed_truncates_long_message(self, mock_redis):
        """Error message truncated to 500 chars."""
        audit_id = uuid.uuid4()
        long_message = "x" * 1000
        
        with patch("tron.infra.redis.pubsub.get_redis", return_value=mock_redis):
            await pubsub_module.publish_audit_failed(
                audit_id,
                long_message,
            )
        
        call_args = mock_redis.publish.call_args
        published_json = call_args[0][1]
        payload = json.loads(published_json)
        
        assert len(payload["data"]["error_message"]) <= 500


class TestAuditEventEnum:
    """Tests for AuditEvent enumeration."""

    def test_audit_event_values(self):
        """AuditEvent has expected event type values."""
        assert pubsub_module.AuditEvent.STATUS_CHANGE.value == "status_change"
        assert pubsub_module.AuditEvent.PROGRESS_UPDATE.value == "progress_update"
        assert pubsub_module.AuditEvent.FINDING_DISCOVERED.value == "finding_discovered"
        assert pubsub_module.AuditEvent.AGENT_STARTED.value == "agent_started"
        assert pubsub_module.AuditEvent.AGENT_COMPLETED.value == "agent_completed"
        assert pubsub_module.AuditEvent.CROSS_VALIDATION.value == "cross_validation"
        assert pubsub_module.AuditEvent.AUDIT_COMPLETED.value == "audit_completed"
        assert pubsub_module.AuditEvent.AUDIT_FAILED.value == "audit_failed"

    def test_audit_event_count(self):
        """AuditEvent has 8 event types."""
        events = list(pubsub_module.AuditEvent)
        assert len(events) == 8
