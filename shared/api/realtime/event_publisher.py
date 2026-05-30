"""In-process pub/sub hub for :class:`ProjectEvent` streaming.

Backend channels (decision ledger, audit, instincts, auditor verdicts,
charter evals, operate) call :func:`publish` from anywhere — sync or
async. The SSE endpoint in :mod:`shared.api.routes.project_events`
subscribes once per connected client and consumes events filtered to
the project the client cares about.

Design choices
--------------

* **In-process only.** No Redis, no NATS, no AMQP. The Hub is a single
  container per V3 #3; horizontal scale lands later via the federation
  layer (#10), not here.
* **Bounded queues.** Each subscriber gets ``asyncio.Queue(maxsize=256)``.
  When a slow consumer fills the queue, the publisher drops the
  *oldest* event for that subscriber so the live feed stays current.
  The audit + decision ledger remain the durable source of truth — no
  caller depends on the SSE stream for correctness.
* **Fail-soft.** :func:`publish` never raises. Any error inside the
  delivery loop is logged; the caller continues.
* **No event loop required at publish time.** Callers may be inside a
  running loop or not (e.g. a synchronous ``run_auditor`` call from a
  test). The publisher uses :func:`asyncio.get_running_loop` when it
  can, falls back to a direct queue write when it can't.

Public API
----------

::

    publish(event: ProjectEvent) -> None
    subscribe(project_id: str | None) -> asyncio.Queue[ProjectEvent]
    unsubscribe(queue: asyncio.Queue[ProjectEvent]) -> None
    snapshot_subscribers() -> dict[str | None, int]
"""
from __future__ import annotations

import asyncio
import logging
import threading
from collections import defaultdict
from typing import DefaultDict

from shared.api.realtime.event_schema import ProjectEvent

logger = logging.getLogger("spine.api.realtime.event_publisher")


MAX_QUEUE = 256
"""Per-subscriber bounded queue size. See module docstring rationale."""


_ANY = "__any__"
"""Sentinel for subscribers that want every project's events
(operator / observer view)."""


class _Hub:
    """Process-wide registry of subscriber queues keyed by project id.

    Holds a thread-safe registry — publishers may run in any thread.
    Delivery into a subscriber queue is async (``asyncio.Queue.put_nowait``
    is sync but only safe from the loop that owns the queue; we
    therefore schedule the put via ``loop.call_soon_threadsafe`` when
    publishing from a non-owning thread).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subscribers: DefaultDict[str, list[tuple[asyncio.Queue, asyncio.AbstractEventLoop | None]]] = defaultdict(
            list
        )

    def subscribe(self, project_id: str | None) -> asyncio.Queue:
        key = project_id or _ANY
        queue: asyncio.Queue[ProjectEvent] = asyncio.Queue(maxsize=MAX_QUEUE)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        with self._lock:
            self._subscribers[key].append((queue, loop))
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        with self._lock:
            for key, items in list(self._subscribers.items()):
                kept = [item for item in items if item[0] is not queue]
                if kept:
                    self._subscribers[key] = kept
                else:
                    self._subscribers.pop(key, None)

    def publish(self, event: ProjectEvent) -> None:
        # Snapshot subscribers under the lock; deliver outside it so
        # slow consumers can't stall publishers.
        with self._lock:
            targets = list(self._subscribers.get(event.project_id, []))
            targets += list(self._subscribers.get(_ANY, []))
        for queue, loop in targets:
            self._deliver(queue, loop, event)

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return {key: len(items) for key, items in self._subscribers.items()}

    # ── internal ──────────────────────────────────────────────

    def _deliver(
        self,
        queue: asyncio.Queue,
        loop: asyncio.AbstractEventLoop | None,
        event: ProjectEvent,
    ) -> None:
        if loop is None or loop.is_closed():
            # Subscriber was created without an active loop (rare —
            # mostly tests). Best-effort: try a direct put; if it
            # fails, log and move on.
            self._direct_put(queue, event)
            return
        try:
            loop.call_soon_threadsafe(self._put_with_overflow, queue, event)
        except RuntimeError:
            # Loop closed between snapshot and delivery; drop.
            logger.debug("publisher: loop closed mid-delivery; dropping event")

    @staticmethod
    def _put_with_overflow(queue: asyncio.Queue, event: ProjectEvent) -> None:
        """Drop oldest on overflow so the live feed stays current."""
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                # Queue suddenly empty — try again, give up if still full.
                pass
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning("publisher: drop event after overflow retry")

    @staticmethod
    def _direct_put(queue: asyncio.Queue, event: ProjectEvent) -> None:
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning("publisher: direct put dropped event")


_HUB = _Hub()


def publish(event: ProjectEvent) -> None:
    """Publish ``event`` to every subscriber for its project + any-projects.

    Never raises. Returns immediately; delivery is best-effort.
    """
    try:
        _HUB.publish(event)
    except Exception:  # noqa: BLE001
        logger.exception("event_publisher: publish raised; swallowed")


def subscribe(project_id: str | None) -> asyncio.Queue:
    """Create a new bounded subscription queue.

    ``project_id=None`` subscribes to every project (operator view).
    Caller MUST eventually call :func:`unsubscribe` to release the
    slot.
    """
    return _HUB.subscribe(project_id)


def unsubscribe(queue: asyncio.Queue) -> None:
    """Release the subscription. Idempotent."""
    _HUB.unsubscribe(queue)


def snapshot_subscribers() -> dict[str, int]:
    """Diagnostic: returns ``{project_id_or_sentinel: subscriber_count}``."""
    return _HUB.snapshot()


__all__ = [
    "MAX_QUEUE",
    "publish",
    "snapshot_subscribers",
    "subscribe",
    "unsubscribe",
]
