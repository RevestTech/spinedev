"""
Redis Pub/Sub for real-time audit progress streaming.

Publishes structured JSON events to per-audit channels.
WebSocket consumers subscribe to these channels to push
live updates to the frontend.

Channel format: audit:{audit_run_id}:progress
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional
from uuid import UUID

from tron.infra.redis.client import get_redis

logger = logging.getLogger(__name__)


class AuditEvent(str, Enum):
    """Event types published during an audit run."""

    STATUS_CHANGE = "status_change"
    PROGRESS_UPDATE = "progress_update"
    FINDING_DISCOVERED = "finding_discovered"
    AGENT_STARTED = "agent_started"
    AGENT_COMPLETED = "agent_completed"
    CROSS_VALIDATION = "cross_validation"
    AUDIT_COMPLETED = "audit_completed"
    AUDIT_FAILED = "audit_failed"


def _channel_name(audit_run_id: UUID) -> str:
    """Build the Redis pub/sub channel name for an audit run."""
    return f"audit:{audit_run_id}:progress"


async def publish_audit_event(
    audit_run_id: UUID,
    event: AuditEvent,
    data: Optional[Dict[str, Any]] = None,
) -> int:
    """Publish an event to the audit's progress channel.

    Returns the number of subscribers that received the message.
    Silently returns 0 if Redis is unavailable (non-critical path).
    """
    try:
        redis = get_redis()
    except RuntimeError:
        logger.debug("Redis not available for pub/sub — skipping event")
        return 0

    payload = {
        "event": event.value,
        "audit_run_id": str(audit_run_id),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": data or {},
    }

    try:
        channel = _channel_name(audit_run_id)
        count = await redis.publish(channel, json.dumps(payload))
        logger.debug(
            "Published %s to %s (%d subscribers)",
            event.value,
            channel,
            count,
        )
        return count
    except Exception as exc:
        # Pub/sub is best-effort — never fail the audit pipeline
        logger.warning("Failed to publish audit event: %s", exc)
        return 0


async def publish_progress(
    audit_run_id: UUID,
    status: str,
    progress: int,
    message: str = "",
) -> int:
    """Convenience: publish a progress update with status and percentage."""
    return await publish_audit_event(
        audit_run_id,
        AuditEvent.PROGRESS_UPDATE,
        {
            "status": status,
            "progress": progress,
            "message": message,
        },
    )


async def publish_finding(
    audit_run_id: UUID,
    severity: str,
    title: str,
    file_path: str,
    line_number: int,
    tool_confirmed: bool = False,
) -> int:
    """Convenience: publish a finding discovery event."""
    return await publish_audit_event(
        audit_run_id,
        AuditEvent.FINDING_DISCOVERED,
        {
            "severity": severity,
            "title": title,
            "file_path": file_path,
            "line_number": line_number,
            "tool_confirmed": tool_confirmed,
        },
    )


async def publish_audit_completed(
    audit_run_id: UUID,
    findings_total: int,
    findings_critical: int,
    findings_high: int,
    findings_medium: int,
    findings_low: int,
    duration_seconds: float,
) -> int:
    """Convenience: publish the final audit completed event."""
    return await publish_audit_event(
        audit_run_id,
        AuditEvent.AUDIT_COMPLETED,
        {
            "findings_total": findings_total,
            "findings_critical": findings_critical,
            "findings_high": findings_high,
            "findings_medium": findings_medium,
            "findings_low": findings_low,
            "duration_seconds": round(duration_seconds, 1),
        },
    )


async def publish_audit_failed(
    audit_run_id: UUID,
    error_message: str,
) -> int:
    """Convenience: publish an audit failure event."""
    return await publish_audit_event(
        audit_run_id,
        AuditEvent.AUDIT_FAILED,
        {"error_message": error_message[:500]},
    )
