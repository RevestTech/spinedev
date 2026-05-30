"""Realtime event publishing for the SpineHub Live activity feed.

Wires every backend channel that produces project-scoped events
(decision ledger, audit, instincts, auditor verdicts, charter
evals, operate) through a single in-process pub/sub so the SPA can
render the operating loop's activity in real time.

See ``docs/REALTIME_HUB_TODO.md`` for the master task list.
"""
from shared.api.realtime.event_schema import (
    ProjectEvent,
    ProjectEventType,
    PROJECT_EVENT_TYPES,
)

__all__ = [
    "PROJECT_EVENT_TYPES",
    "ProjectEvent",
    "ProjectEventType",
]
