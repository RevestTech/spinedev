"""Tests for the ``/api/v2/projects/{id}/events`` SSE endpoint (T9).

Uses the iterator factory directly rather than spinning up the full
FastAPI app — keeps tests fast + isolated from the dev-mode auth
plumbing which requires DB + cookies.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from shared.api.realtime.event_publisher import publish
from shared.api.realtime.event_schema import ProjectEvent
from shared.api.routes.project_events import _iter_events


def _run(coro):
    return asyncio.run(coro)


# ─── _iter_events behaviour ───


def test_first_chunk_is_connected_keepalive() -> None:
    async def body():
        gen = _iter_events("proj-sse")
        chunk = await asyncio.wait_for(gen.__anext__(), timeout=1.0)
        assert chunk == b": connected\n\n"
        await gen.aclose()

    _run(body())


def test_published_event_arrives_as_sse_frame() -> None:
    async def body():
        gen = _iter_events("proj-sse2")
        # Drain the initial connected frame.
        await asyncio.wait_for(gen.__anext__(), timeout=1.0)

        # Schedule a publish AFTER the subscriber is registered.
        async def _later():
            await asyncio.sleep(0.05)
            publish(
                ProjectEvent(
                    event_type="ledger_append",
                    project_id="proj-sse2",
                    actor="conductor",
                    verdict="allowed",
                    summary="test",
                )
            )

        asyncio.create_task(_later())

        # Read the event-type frame and the data frame.
        event_frame = await asyncio.wait_for(gen.__anext__(), timeout=2.0)
        data_frame = await asyncio.wait_for(gen.__anext__(), timeout=2.0)
        assert event_frame.startswith(b"event: ledger_append")
        assert data_frame.startswith(b"data: ")

        # Parse the JSON body of the data frame.
        body_text = data_frame.decode("utf-8")[len("data: "):].rstrip("\n")
        payload = json.loads(body_text)
        assert payload["event_type"] == "ledger_append"
        assert payload["project_id"] == "proj-sse2"
        assert payload["summary"] == "test"

        await gen.aclose()

    _run(body())


def test_idle_subscriber_receives_keepalives() -> None:
    """Lower KEEPALIVE_SECS in this test so we don't wait 15s."""
    async def body():
        from shared.api.routes import project_events as mod

        mod.KEEPALIVE_SECS = 0.05  # type: ignore[attr-defined]
        try:
            gen = _iter_events("proj-quiet")
            # Drain the initial connected frame.
            await asyncio.wait_for(gen.__anext__(), timeout=1.0)
            # Next chunk with no publishes must be a keepalive.
            chunk = await asyncio.wait_for(gen.__anext__(), timeout=1.0)
            assert chunk == b": keepalive\n\n"
            await gen.aclose()
        finally:
            mod.KEEPALIVE_SECS = 15.0  # restore

    _run(body())


def test_per_project_filter_isolates_streams() -> None:
    async def body():
        gen_a = _iter_events("proj-a-only")
        await asyncio.wait_for(gen_a.__anext__(), timeout=1.0)

        # Publish to a DIFFERENT project — should not arrive at gen_a.
        async def _later():
            await asyncio.sleep(0.05)
            publish(
                ProjectEvent(
                    event_type="ledger_append",
                    project_id="proj-other",
                    actor="conductor",
                    verdict="allowed",
                )
            )

        asyncio.create_task(_later())

        # Wait briefly; gen_a should NOT receive the foreign event.
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(gen_a.__anext__(), timeout=0.4)

        await gen_a.aclose()

    _run(body())
