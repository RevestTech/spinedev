"""SSE endpoint for project-scoped realtime events.

``GET /api/v2/projects/{project_id}/events`` — Server-Sent Events
stream. Each event arrives as ``event: <type>`` + ``data: <json>``
frames. The SPA's ``projectEvents`` store subscribes once per
project workspace.

Mirrors the pattern in :mod:`shared.api.routes.decisions.subscribe`
(15s keepalive, unsubscribe on disconnect). Adds explicit project
filter so a client only sees events for the project it's viewing.

Operator / observer endpoint
----------------------------

``GET /api/v2/projects/events`` (no project_id) subscribes to every
project's events — used by the global Hub dashboard.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Annotated, AsyncIterator, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from shared.api.dependencies import User, current_user
from shared.api.realtime.event_publisher import subscribe, unsubscribe

logger = logging.getLogger("spine.api.routes.project_events")


router = APIRouter(prefix="/api/v2/projects", tags=["realtime"])


KEEPALIVE_SECS = 15.0
"""Seconds between SSE comment frames when the queue is idle.

Matches the decisions.subscribe keepalive so connection-loss heuristics
on the client are uniform.
"""


async def _iter_events(project_id: Optional[str]) -> AsyncIterator[bytes]:
    """Yield SSE-formatted bytes for one subscriber until disconnect."""
    queue = subscribe(project_id)
    try:
        yield b": connected\n\n"
        while True:
            try:
                evt = await asyncio.wait_for(queue.get(), timeout=KEEPALIVE_SECS)
            except asyncio.TimeoutError:
                yield b": keepalive\n\n"
                continue
            try:
                payload = evt.model_dump_json()
            except Exception:  # noqa: BLE001
                logger.warning("project_events: drop unserializable event")
                continue
            yield f"event: {evt.event_type}\n".encode("utf-8")
            yield f"data: {payload}\n\n".encode("utf-8")
    finally:
        unsubscribe(queue)


@router.get("/events")
async def stream_all_events(
    user: Annotated[User, Depends(current_user)],
) -> StreamingResponse:
    """Operator / observer view — every project's events."""
    return StreamingResponse(
        _iter_events(None), media_type="text/event-stream",
    )


@router.get("/{project_id}/events")
async def stream_project_events(
    project_id: str,
    user: Annotated[User, Depends(current_user)],
) -> StreamingResponse:
    """Per-project SSE stream of realtime events."""
    return StreamingResponse(
        _iter_events(project_id), media_type="text/event-stream",
    )


__all__ = ["router", "stream_all_events", "stream_project_events"]
