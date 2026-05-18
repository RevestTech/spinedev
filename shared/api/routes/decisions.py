"""``/api/v2/decisions`` — active-push decision queue (per #5 + #6).

The "AI Scrum Master / PM / Release Manager actively communicates" loop
(#5) needs a REST + SSE surface so the Hub SPA can show a live decision
queue + render decision-card details + accept ack/reject in one click.
Channels (#6) consume the same queue: notifications dropped into the
queue here are also fanned out via ``shared.notify`` to whatever
mediums the user opted into (web / Slack / email / SMS / WhatsApp /
Teams / PagerDuty).

Endpoints:

* ``GET  /api/v2/decisions``                   — list pending decisions
* ``GET  /api/v2/decisions/{id}``              — fetch one by ID
* ``POST /api/v2/decisions/{id}/ack``          — user accepted the card
* ``POST /api/v2/decisions/{id}/reject``       — user rejected the card
* ``POST /api/v2/decisions/subscribe`` (SSE)   — live push (text/event-stream)

Dependencies: ``fastapi``, ``pydantic`` (already required).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections import deque
from typing import Annotated, Any, AsyncIterator, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from shared.api.dependencies import actor_label, current_user
from shared.audit.audit_record import AuditRecord, chain_to_previous
from shared.identity.models import User

logger = logging.getLogger("spine.api.decisions")
router = APIRouter(prefix="/api/v2/decisions", tags=["decisions"])

DecisionStatus = Literal["pending", "acked", "rejected", "expired"]
DecisionClass = Literal[
    "approval", "incident", "release", "briefing", "budget", "policy_change",
]


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class DecisionCard(BaseModel):
    """One pending decision (the "card" the SPA renders)."""

    model_config = ConfigDict(extra="forbid")
    decision_id: str
    decision_class: DecisionClass
    project_id: Optional[str] = None
    title: str = Field(..., min_length=1, max_length=200)
    body: str = Field(default="", max_length=8_000)
    severity: Literal["info", "warning", "critical"] = "info"
    actions: list[str] = Field(default_factory=lambda: ["ack", "reject"])
    status: DecisionStatus = "pending"
    created_at: float = Field(default_factory=time.time)
    expires_at: Optional[float] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class DecisionList(BaseModel):
    """``GET /api/v2/decisions`` envelope."""

    model_config = ConfigDict(extra="forbid")
    ok: bool = True
    items: list[DecisionCard]
    total: int


class DecisionActionResponse(BaseModel):
    """Response from ack/reject."""

    model_config = ConfigDict(extra="forbid")
    ok: bool = True
    decision_id: str
    status: DecisionStatus
    actor: str
    audit_event_uuid: str


# ---------------------------------------------------------------------------
# In-process queue — Wave 4 replaces with Postgres-backed store
# ---------------------------------------------------------------------------


class _DecisionStore:
    """Hot in-memory store + a ring of recent events for SSE replay.

    Wave 3 part 1 ships the in-memory shape to unblock the SPA; Wave 4
    moves persistence into ``spine_lifecycle.decision_card`` so the
    queue survives restart + federation.
    """

    def __init__(self, *, sse_buffer: int = 256) -> None:
        self._cards: dict[str, DecisionCard] = {}
        self._events: deque[dict[str, Any]] = deque(maxlen=sse_buffer)
        self._subscribers: list[asyncio.Queue[dict[str, Any]]] = []

    def put(self, card: DecisionCard) -> None:
        self._cards[card.decision_id] = card
        self._publish({"type": "card_created", "card": card.model_dump()})

    def get(self, decision_id: str) -> Optional[DecisionCard]:
        return self._cards.get(decision_id)

    def list(self, *, status_filter: Optional[DecisionStatus] = None) -> list[DecisionCard]:
        items = list(self._cards.values())
        if status_filter is not None:
            items = [c for c in items if c.status == status_filter]
        return sorted(items, key=lambda c: c.created_at, reverse=True)

    def transition(self, decision_id: str, new_status: DecisionStatus) -> Optional[DecisionCard]:
        card = self._cards.get(decision_id)
        if card is None:
            return None
        card = card.model_copy(update={"status": new_status})
        self._cards[decision_id] = card
        self._publish({"type": "card_updated", "card": card.model_dump()})
        return card

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=64)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[dict[str, Any]]) -> None:
        try:
            self._subscribers.remove(q)
        except ValueError:
            pass

    def _publish(self, event: dict[str, Any]) -> None:
        self._events.append(event)
        for q in list(self._subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # Slow consumer — drop silently rather than block fanout.
                pass


_STORE = _DecisionStore()


def get_store() -> _DecisionStore:
    """Test seam — returns the process-local store."""
    return _STORE


# ---------------------------------------------------------------------------
# Audit helper — every state change writes an AuditRecord (per req)
# ---------------------------------------------------------------------------


def _audit_decision_event(
    *, action: str, decision_id: str, actor: str, project_id: Optional[str]
) -> AuditRecord:
    """Build a chained AuditRecord for a decision-queue mutation."""
    rec = AuditRecord(
        role="hub",
        subsystem="hub",
        action=action,
        actor=actor,
        subject_type="decision_card",
        subject_id=decision_id,
        project_id=int(project_id) if project_id and project_id.isdigit() else None,
        metadata={"surface": "decisions"},
    )
    return chain_to_previous(rec, prev_hash=None)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("", response_model=DecisionList)
async def list_decisions(
    user: Annotated[User, Depends(current_user)],
    status_filter: Optional[DecisionStatus] = Query(default="pending", alias="status"),
) -> DecisionList:
    """List decisions visible to the caller (Wave 3: no per-user scoping)."""
    items = _STORE.list(status_filter=status_filter)
    return DecisionList(items=items, total=len(items))


@router.get("/{decision_id}", response_model=DecisionCard)
async def get_decision(
    decision_id: str,
    user: Annotated[User, Depends(current_user)],
) -> DecisionCard:
    """Single decision card."""
    card = _STORE.get(decision_id)
    if card is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "decision_not_found", "message": decision_id},
        )
    return card


@router.post("/{decision_id}/ack", response_model=DecisionActionResponse)
async def ack_decision(
    decision_id: str,
    user: Annotated[User, Depends(current_user)],
) -> DecisionActionResponse:
    """Acknowledge / approve a decision card."""
    updated = _STORE.transition(decision_id, "acked")
    if updated is None:
        raise HTTPException(404, detail={"error_code": "decision_not_found", "message": decision_id})
    actor = actor_label(user)
    rec = _audit_decision_event(
        action="decision_acked", decision_id=decision_id, actor=actor, project_id=updated.project_id
    )
    return DecisionActionResponse(
        decision_id=decision_id,
        status=updated.status,
        actor=actor,
        audit_event_uuid=str(rec.event_uuid),
    )


@router.post("/{decision_id}/reject", response_model=DecisionActionResponse)
async def reject_decision(
    decision_id: str,
    user: Annotated[User, Depends(current_user)],
) -> DecisionActionResponse:
    """Reject a decision card."""
    updated = _STORE.transition(decision_id, "rejected")
    if updated is None:
        raise HTTPException(404, detail={"error_code": "decision_not_found", "message": decision_id})
    actor = actor_label(user)
    rec = _audit_decision_event(
        action="decision_rejected", decision_id=decision_id, actor=actor, project_id=updated.project_id
    )
    return DecisionActionResponse(
        decision_id=decision_id,
        status=updated.status,
        actor=actor,
        audit_event_uuid=str(rec.event_uuid),
    )


@router.post("/subscribe")
async def subscribe(
    user: Annotated[User, Depends(current_user)],
) -> StreamingResponse:
    """SSE stream of live decision events (text/event-stream).

    The SPA opens this once and receives ``card_created`` /
    ``card_updated`` events until the connection drops. Each event is
    a JSON object in an ``event:`` + ``data:`` frame.
    """
    queue = _STORE.subscribe()

    async def _iter() -> AsyncIterator[bytes]:
        try:
            # Initial keep-alive comment per SSE spec.
            yield b": connected\n\n"
            while True:
                try:
                    evt = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    yield b": keepalive\n\n"
                    continue
                payload = json.dumps(evt, default=str)
                yield f"event: {evt.get('type', 'message')}\n".encode("utf-8")
                yield f"data: {payload}\n\n".encode("utf-8")
        finally:
            _STORE.unsubscribe(queue)

    return StreamingResponse(_iter(), media_type="text/event-stream")


# ---------------------------------------------------------------------------
# Test/helper API — used by other routes to *post* decisions for delivery.
# ---------------------------------------------------------------------------


def enqueue_decision(card: DecisionCard) -> DecisionCard:
    """Programmatic API for callers (notifier, gate, etc.) to post a card.

    Not exposed via REST — internal callers only. Returns the stored card
    so callers can attach the ID to their own audit row.
    """
    if not card.decision_id:
        card = card.model_copy(update={"decision_id": uuid.uuid4().hex})
    _STORE.put(card)
    return card


__all__ = [
    "router",
    "DecisionCard",
    "DecisionList",
    "DecisionActionResponse",
    "DecisionStatus",
    "DecisionClass",
    "enqueue_decision",
    "get_store",
]
