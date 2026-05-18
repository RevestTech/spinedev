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

Wave 3.5 FIX3: the in-process ``_DecisionStore`` is now a thin write-
through cache over ``spine_lifecycle.decision_card`` (V36). The cache
keeps SSE pub/sub working without round-tripping LISTEN/NOTIFY through
Postgres on every event; the DB is the durability layer so a Hub
restart no longer drops the queue. When the asyncpg pool is
unreachable (tests, bootstrap window) the cache stands alone and
behaves exactly like the Wave 3 in-memory implementation — so the
existing 5/5 SPA panel tests + `test_routes_decisions.py` keep passing
without a DB fixture.

Per #12 every card carries a ``citations`` field; per #25 mutating
endpoints are auth-gated via ``shared.identity.current_user``.

Dependencies: ``fastapi``, ``pydantic`` (already required).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Annotated, Any, AsyncIterator, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from shared.api.dependencies import DbHandle, actor_label, current_user, get_db_pool
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
    #: Cite-or-Refuse evidence (#12) — list of {kg_node_id|file_line|...}
    citations: list[dict[str, Any]] = Field(default_factory=list)


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
# Persistent store (V36 spine_lifecycle.decision_card) + SSE cache.
# ---------------------------------------------------------------------------


def _row_to_card(row: dict[str, Any]) -> DecisionCard:
    """Translate a ``spine_lifecycle.decision_card`` row into a DecisionCard.

    Defensive: missing/extra columns are tolerated so the schema can
    evolve in Wave 4 without breaking the API contract.
    """
    pushed_at = row.get("pushed_at")
    if isinstance(pushed_at, datetime):
        created_at = pushed_at.timestamp()
    elif pushed_at is None:
        created_at = time.time()
    else:
        try:
            created_at = float(pushed_at)
        except (TypeError, ValueError):
            created_at = time.time()
    expires_at_raw = row.get("expires_at")
    expires_at: Optional[float] = None
    if isinstance(expires_at_raw, datetime):
        expires_at = expires_at_raw.timestamp()
    elif expires_at_raw is not None:
        try:
            expires_at = float(expires_at_raw)
        except (TypeError, ValueError):
            expires_at = None
    citations = row.get("citations") or []
    if isinstance(citations, str):
        try:
            citations = json.loads(citations)
        except json.JSONDecodeError:
            citations = []
    metadata = row.get("metadata") or {}
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except json.JSONDecodeError:
            metadata = {}
    project_id_raw = row.get("project_id")
    project_id_str: Optional[str] = None
    if project_id_raw is not None:
        project_id_str = str(project_id_raw)
    return DecisionCard(
        decision_id=str(row["id"]),
        decision_class=row.get("kind") or "approval",  # type: ignore[arg-type]
        project_id=project_id_str,
        title=row.get("title") or "",
        body=row.get("body") or "",
        severity=row.get("severity") or "info",  # type: ignore[arg-type]
        status=row.get("status") or "pending",  # type: ignore[arg-type]
        created_at=created_at,
        expires_at=expires_at,
        metadata=metadata if isinstance(metadata, dict) else {},
        citations=citations if isinstance(citations, list) else [],
    )


_INSERT_SQL = """
INSERT INTO spine_lifecycle.decision_card
    (id, project_id, kind, title, body, severity, status,
     pushed_at, expires_at, citations, metadata)
VALUES
    ($1::uuid, $2, $3, $4, $5, $6, $7,
     to_timestamp($8), CASE WHEN $9::double precision IS NULL THEN NULL ELSE to_timestamp($9) END,
     $10::jsonb, $11::jsonb)
ON CONFLICT (id) DO UPDATE SET
    title    = EXCLUDED.title,
    body     = EXCLUDED.body,
    severity = EXCLUDED.severity,
    status   = EXCLUDED.status,
    metadata = EXCLUDED.metadata,
    citations = EXCLUDED.citations;
"""

_SELECT_BY_ID_SQL = """
SELECT id::text AS id, project_id, kind, title, body, severity, status,
       pushed_at, decided_at, decided_by, expires_at, citations, metadata
FROM   spine_lifecycle.decision_card
WHERE  id = $1::uuid;
"""

_SELECT_LIST_SQL = """
SELECT id::text AS id, project_id, kind, title, body, severity, status,
       pushed_at, decided_at, decided_by, expires_at, citations, metadata
FROM   spine_lifecycle.decision_card
WHERE  ($1::text IS NULL OR status = $1)
ORDER  BY pushed_at DESC
LIMIT  500;
"""

_TRANSITION_SQL = """
UPDATE spine_lifecycle.decision_card
SET    status      = $2,
       decided_at  = NOW(),
       decided_by  = $3
WHERE  id          = $1::uuid
RETURNING id::text AS id, project_id, kind, title, body, severity, status,
          pushed_at, decided_at, decided_by, expires_at, citations, metadata;
"""


def _to_uuid_str(decision_id: str) -> Optional[str]:
    """Return a canonical UUID string, or ``None`` if not parseable.

    Wave 3 inserts hex IDs (``uuid.uuid4().hex``) — accept both 32-char
    hex and standard 36-char dashed form. Anything else is rejected so
    we never pass a malformed value into asyncpg's ``$1::uuid`` cast.
    """
    try:
        return str(uuid.UUID(decision_id))
    except (ValueError, TypeError, AttributeError):
        return None


class _DecisionStore:
    """Write-through cache over ``spine_lifecycle.decision_card`` (V36).

    Wave 3.5 FIX3: the cache is the SSE pub/sub layer (fanning out
    create/update events to every subscriber without a Postgres round-
    trip per event). The DB is the durability layer — every ``put`` /
    ``transition`` is mirrored to ``spine_lifecycle.decision_card`` so
    a Hub restart no longer drops the queue.

    When ``set_db_handle()`` has never been called (tests, bootstrap)
    the cache stands alone and behaves exactly like the Wave 3
    in-memory implementation. This keeps the 5/5 SPA panel tests +
    ``test_routes_decisions.py`` green without a DB fixture.
    """

    def __init__(self, *, sse_buffer: int = 256) -> None:
        self._cards: dict[str, DecisionCard] = {}
        self._events: deque[dict[str, Any]] = deque(maxlen=sse_buffer)
        self._subscribers: list[asyncio.Queue[dict[str, Any]]] = []
        self._db: Optional[DbHandle] = None

    # ── DB plumbing ────────────────────────────────────────────────
    def set_db(self, db: Optional[DbHandle]) -> None:
        """Inject a DB handle. Pass ``None`` to fall back to cache-only."""
        self._db = db

    async def _persist_put(self, card: DecisionCard) -> None:
        if self._db is None:
            return
        uuid_str = _to_uuid_str(card.decision_id)
        if uuid_str is None:
            # Non-UUID id (extremely rare; only via direct test seed) —
            # keep in cache, skip persistence.
            return
        project_id: Optional[int] = None
        if card.project_id and str(card.project_id).isdigit():
            project_id = int(card.project_id)
        try:
            await self._db.execute(
                _INSERT_SQL,
                uuid_str,
                project_id,
                card.decision_class,
                card.title,
                card.body,
                card.severity,
                card.status,
                float(card.created_at),
                float(card.expires_at) if card.expires_at is not None else None,
                json.dumps(card.citations),
                json.dumps(card.metadata),
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("decisions.persist_put.failed", extra={"err": str(exc)})

    async def _persist_transition(
        self, decision_id: str, new_status: DecisionStatus, actor: Optional[str],
    ) -> Optional[DecisionCard]:
        if self._db is None:
            return None
        uuid_str = _to_uuid_str(decision_id)
        if uuid_str is None:
            return None
        try:
            rows = await self._db.fetch_rows(
                _TRANSITION_SQL, uuid_str, new_status, actor or "system",
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("decisions.persist_transition.failed", extra={"err": str(exc)})
            return None
        if not rows:
            return None
        return _row_to_card(rows[0])

    async def _hydrate(self, decision_id: str) -> Optional[DecisionCard]:
        """Load from DB into cache if not already present."""
        if self._db is None:
            return None
        uuid_str = _to_uuid_str(decision_id)
        if uuid_str is None:
            return None
        try:
            rows = await self._db.fetch_rows(_SELECT_BY_ID_SQL, uuid_str)
        except Exception as exc:  # noqa: BLE001
            logger.debug("decisions.hydrate.failed", extra={"err": str(exc)})
            return None
        if not rows:
            return None
        card = _row_to_card(rows[0])
        self._cards[card.decision_id] = card
        return card

    async def _list_from_db(
        self, *, status_filter: Optional[DecisionStatus],
    ) -> list[DecisionCard]:
        if self._db is None:
            return []
        try:
            rows = await self._db.fetch_rows(_SELECT_LIST_SQL, status_filter)
        except Exception as exc:  # noqa: BLE001
            logger.debug("decisions.list_from_db.failed", extra={"err": str(exc)})
            return []
        return [_row_to_card(r) for r in rows]

    # ── Public API ────────────────────────────────────────────────
    def put(self, card: DecisionCard) -> None:
        """Cache + (best-effort) persist. Synchronous facade kept for
        the existing ``enqueue_decision`` helper; persistence is fired
        as a background task so the call site stays non-blocking.
        """
        self._cards[card.decision_id] = card
        self._publish({"type": "card_created", "card": card.model_dump()})
        if self._db is not None:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._persist_put(card))
            except RuntimeError:
                # No running loop (sync test context). Skip persistence.
                pass

    async def aput(self, card: DecisionCard) -> None:
        """Async variant — awaits persistence before returning."""
        self._cards[card.decision_id] = card
        self._publish({"type": "card_created", "card": card.model_dump()})
        await self._persist_put(card)

    def get(self, decision_id: str) -> Optional[DecisionCard]:
        return self._cards.get(decision_id)

    async def aget(self, decision_id: str) -> Optional[DecisionCard]:
        card = self._cards.get(decision_id)
        if card is not None:
            return card
        return await self._hydrate(decision_id)

    def list(self, *, status_filter: Optional[DecisionStatus] = None) -> list[DecisionCard]:
        items = list(self._cards.values())
        if status_filter is not None:
            items = [c for c in items if c.status == status_filter]
        return sorted(items, key=lambda c: c.created_at, reverse=True)

    async def alist(
        self, *, status_filter: Optional[DecisionStatus] = None,
    ) -> list[DecisionCard]:
        """DB-first list. Falls back to cache when DB is unavailable.

        Cache values for the same ID OVERWRITE the DB row so an in-flight
        unpersisted card (race window) is never missed.
        """
        db_cards = await self._list_from_db(status_filter=status_filter)
        cached = self.list(status_filter=status_filter)
        merged: dict[str, DecisionCard] = {c.decision_id: c for c in db_cards}
        for c in cached:
            merged[c.decision_id] = c
        return sorted(merged.values(), key=lambda c: c.created_at, reverse=True)

    def transition(self, decision_id: str, new_status: DecisionStatus) -> Optional[DecisionCard]:
        card = self._cards.get(decision_id)
        if card is None:
            return None
        card = card.model_copy(update={"status": new_status})
        self._cards[decision_id] = card
        self._publish({"type": "card_updated", "card": card.model_dump()})
        return card

    async def atransition(
        self, decision_id: str, new_status: DecisionStatus, *, actor: Optional[str] = None,
    ) -> Optional[DecisionCard]:
        """Async transition: tries DB first, then cache."""
        card = await self._persist_transition(decision_id, new_status, actor)
        if card is None:
            card = self.transition(decision_id, new_status)
        else:
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


def set_decisions_db(db: Optional[DbHandle]) -> None:
    """Wire (or clear) the asyncpg-backed durability layer.

    Called by the FastAPI lifespan in ``shared/api/app.py`` after the
    pool is initialized. Tests can pass ``None`` for cache-only mode.
    """
    _STORE.set_db(db)


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
    db: Annotated[DbHandle, Depends(get_db_pool)],
    status_filter: Optional[DecisionStatus] = Query(default="pending", alias="status"),
) -> DecisionList:
    """List decisions visible to the caller (Wave 3.5: DB + cache merge)."""
    # Wire the per-request DbHandle so the store can hydrate from DB.
    _STORE.set_db(db)
    items = await _STORE.alist(status_filter=status_filter)
    return DecisionList(items=items, total=len(items))


@router.get("/{decision_id}", response_model=DecisionCard)
async def get_decision(
    decision_id: str,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[DbHandle, Depends(get_db_pool)],
) -> DecisionCard:
    """Single decision card."""
    _STORE.set_db(db)
    card = await _STORE.aget(decision_id)
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
    db: Annotated[DbHandle, Depends(get_db_pool)],
) -> DecisionActionResponse:
    """Acknowledge / approve a decision card."""
    _STORE.set_db(db)
    actor = actor_label(user)
    updated = await _STORE.atransition(decision_id, "acked", actor=actor)
    if updated is None:
        raise HTTPException(404, detail={"error_code": "decision_not_found", "message": decision_id})
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
    db: Annotated[DbHandle, Depends(get_db_pool)],
) -> DecisionActionResponse:
    """Reject a decision card."""
    _STORE.set_db(db)
    actor = actor_label(user)
    updated = await _STORE.atransition(decision_id, "rejected", actor=actor)
    if updated is None:
        raise HTTPException(404, detail={"error_code": "decision_not_found", "message": decision_id})
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


async def aenqueue_decision(card: DecisionCard) -> DecisionCard:
    """Async variant — awaits DB persistence before returning."""
    if not card.decision_id:
        card = card.model_copy(update={"decision_id": uuid.uuid4().hex})
    await _STORE.aput(card)
    return card


__all__ = [
    "router",
    "DecisionCard",
    "DecisionList",
    "DecisionActionResponse",
    "DecisionStatus",
    "DecisionClass",
    "enqueue_decision",
    "aenqueue_decision",
    "get_store",
    "set_decisions_db",
]
