"""
Domain event definitions for real-time updates.

Events are the unit of communication between the backend and Socket.IO clients.
Each event has a type, optional resource IDs, timestamp, and event-specific data.
"""

from __future__ import annotations

import logging
from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class EventType(str, Enum):
    """Types of real-time events."""

    WORKFLOW_STARTED = "workflow_started"
    WORKFLOW_PROGRESS = "workflow_progress"
    WORKFLOW_COMPLETED = "workflow_completed"
    WORKFLOW_FAILED = "workflow_failed"
    FINDING_DISCOVERED = "finding_discovered"
    AGENT_STATUS_CHANGED = "agent_status_changed"
    COST_UPDATE = "cost_update"
    PROJECT_UPDATED = "project_updated"


class DomainEvent(BaseModel):
    """Domain event with type, resource IDs, timestamp, and data."""

    event_type: EventType
    workflow_id: Optional[UUID] = None
    project_id: Optional[UUID] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    data: dict[str, Any] = Field(default_factory=dict)

    class Config:
        use_enum_values = True
        json_encoders = {
            UUID: str,
            datetime: lambda v: v.isoformat(),
        }


async def publish_event(event: DomainEvent) -> None:
    """Publish a domain event via Socket.IO.

    Routes the event to the appropriate broadcast function based on event_type
    and available resource IDs (workflow_id, project_id).

    Logs warnings if event cannot be routed due to missing IDs.
    """
    from tron.realtime.socket_server import (
        broadcast_workflow_event,
        broadcast_project_event,
        broadcast_metric_update,
    )

    event_type = event.event_type if isinstance(event.event_type, str) else event.event_type.value

    # Route based on event type and available IDs
    if event.workflow_id:
        # Workflow-scoped events
        await broadcast_workflow_event(
            str(event.workflow_id),
            event_type,
            event.data,
        )
        logger.debug("Published workflow event: %s to workflow %s", event_type, event.workflow_id)

    elif event.project_id:
        # Project-scoped events
        await broadcast_project_event(
            str(event.project_id),
            event_type,
            event.data,
        )
        logger.debug("Published project event: %s to project %s", event_type, event.project_id)

    else:
        # Global events (metrics, system updates)
        await broadcast_metric_update(event_type, event.data)
        logger.debug("Published global event: %s", event_type)


__all__ = [
    'EventType',
    'DomainEvent',
    'publish_event',
]
