"""Tests for ``shared.api.realtime.event_publisher``.

Uses ``asyncio.run`` directly per the project's existing test
conventions (no pytest-asyncio dependency).
"""
from __future__ import annotations

import asyncio

import pytest

from shared.api.realtime.event_publisher import (
    MAX_QUEUE,
    publish,
    snapshot_subscribers,
    subscribe,
    unsubscribe,
)
from shared.api.realtime.event_schema import ProjectEvent


def _event(project_id: str = "proj-a", **overrides) -> ProjectEvent:
    defaults = dict(
        event_type="ledger_append",
        project_id=project_id,
        actor="conductor",
    )
    defaults.update(overrides)
    return ProjectEvent(**defaults)


def _run(coro):
    return asyncio.run(coro)


# ─── Subscribe / unsubscribe lifecycle ───


def test_subscribe_returns_a_queue() -> None:
    async def body():
        q = subscribe("proj-a")
        try:
            assert isinstance(q, asyncio.Queue)
            snap = snapshot_subscribers()
            assert snap.get("proj-a", 0) >= 1
        finally:
            unsubscribe(q)

    _run(body())


def test_unsubscribe_removes_subscriber() -> None:
    async def body():
        q = subscribe("proj-clean")
        unsubscribe(q)
        snap = snapshot_subscribers()
        assert "proj-clean" not in snap

    _run(body())


def test_unsubscribe_is_idempotent() -> None:
    async def body():
        q = subscribe("proj-idem")
        unsubscribe(q)
        unsubscribe(q)
        snap = snapshot_subscribers()
        assert "proj-idem" not in snap

    _run(body())


# ─── Project-id filtered routing ───


def test_publish_routes_to_matching_project_only() -> None:
    async def body():
        qa = subscribe("proj-a")
        qb = subscribe("proj-b")
        try:
            publish(_event(project_id="proj-a"))
            await asyncio.sleep(0)  # flush call_soon_threadsafe
            a_event = await asyncio.wait_for(qa.get(), timeout=1.0)
            assert a_event.project_id == "proj-a"
            assert qb.empty()
        finally:
            unsubscribe(qa)
            unsubscribe(qb)

    _run(body())


def test_publish_to_any_subscriber_receives_every_event() -> None:
    async def body():
        q_any = subscribe(None)
        q_a = subscribe("proj-a")
        try:
            publish(_event(project_id="proj-a"))
            publish(_event(project_id="proj-b"))
            await asyncio.sleep(0)
            evt1 = await asyncio.wait_for(q_any.get(), timeout=1.0)
            evt2 = await asyncio.wait_for(q_any.get(), timeout=1.0)
            seen = {evt1.project_id, evt2.project_id}
            assert seen == {"proj-a", "proj-b"}
            evt_a = await asyncio.wait_for(q_a.get(), timeout=1.0)
            assert evt_a.project_id == "proj-a"
            assert q_a.empty()
        finally:
            unsubscribe(q_any)
            unsubscribe(q_a)

    _run(body())


# ─── Concurrent subscribers ───


def test_three_subscribers_each_receive_their_share() -> None:
    async def body():
        queues = [subscribe("proj-multi") for _ in range(3)]
        try:
            publish(_event(project_id="proj-multi", summary="one"))
            publish(_event(project_id="proj-multi", summary="two"))
            await asyncio.sleep(0)
            for q in queues:
                received = []
                for _ in range(2):
                    received.append(
                        await asyncio.wait_for(q.get(), timeout=1.0)
                    )
                summaries = {e.summary for e in received}
                assert summaries == {"one", "two"}
        finally:
            for q in queues:
                unsubscribe(q)

    _run(body())


# ─── Overflow behaviour ───


def test_overflow_drops_oldest_event() -> None:
    async def body():
        q = subscribe("proj-overflow")
        try:
            # Publish MAX_QUEUE + 5 events; ensure the latest are
            # retained and the earliest get evicted.
            for idx in range(MAX_QUEUE + 5):
                publish(_event(project_id="proj-overflow", summary=str(idx)))
            await asyncio.sleep(0)

            received = []
            while True:
                try:
                    received.append(
                        await asyncio.wait_for(q.get(), timeout=0.1)
                    )
                except asyncio.TimeoutError:
                    break

            assert len(received) == MAX_QUEUE
            summaries = {e.summary for e in received}
            # The last event must still be there.
            assert str(MAX_QUEUE + 4) in summaries
            # The very first event was evicted.
            assert "0" not in summaries
        finally:
            unsubscribe(q)

    _run(body())


# ─── Fail-soft contract ───


def test_publish_with_no_subscribers_does_not_raise() -> None:
    publish(_event(project_id="proj-empty"))


def test_unsubscribe_unknown_queue_does_not_raise() -> None:
    foreign = asyncio.Queue()
    unsubscribe(foreign)


# ─── Snapshot diagnostic ───


def test_snapshot_counts_subscribers() -> None:
    async def body():
        q1 = subscribe("proj-snap")
        q2 = subscribe("proj-snap")
        q3 = subscribe(None)
        try:
            snap = snapshot_subscribers()
            assert snap.get("proj-snap", 0) == 2
            assert snap.get("__any__", 0) >= 1
        finally:
            unsubscribe(q1)
            unsubscribe(q2)
            unsubscribe(q3)

    _run(body())
