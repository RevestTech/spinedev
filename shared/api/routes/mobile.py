"""``/api/v2/mobile`` — mobile-optimised REST surface (#28 — mobile SCAFFOLD).

Per V3 design decision #28 (Mobile), v1.0 ships:

* a **mobile-API surface** — compact JSON, fewer fields, optimised for
  thin/intermittent connectivity (this module), and
* a **mobile-responsive web Hub** — handled by ``shared/ui/`` CSS, not
  here.

Native iOS/Android apps are deferred to v1.1+ (see ``mobile/README.md``
+ the ``mobile/ios/`` + ``mobile/android/`` placeholder projects). What
ships in v1.0 is the **contract** that those native shells will eventually
consume so the contract is not invented at v1.1 time.

Three resources, three GETs, one POST. Every endpoint:

* requires a Keycloak Bearer token (per #25 — auth via
  ``shared.identity.current_user``);
* returns **compact JSON** — short field names, no debug envelopes, no
  long-form HTML bodies. The full-fidelity surface lives at
  ``/api/v2/approvals``, ``/api/v2/decisions``, ``/healthz``;
* is **thin** — it delegates to the existing Hub routes (no new business
  logic) so the two surfaces never drift.

Endpoints
---------

* ``GET  /api/v2/mobile/approvals``                — compact pending approvals
* ``GET  /api/v2/mobile/briefings``                — compact decision-card / briefing feed
* ``GET  /api/v2/mobile/status``                   — Hub liveness summary for the lock-screen widget
* ``POST /api/v2/mobile/approvals/{id}/action``    — one-shot approve / reject

Compact JSON convention (per the mobile-bandwidth budget):

* Use short keys (``id`` not ``approval_id``; ``ts`` not ``created_at``).
* Drop optional fields if they are empty/None (``model_dump(exclude_none=True)``).
* Cap list endpoints at ``DEFAULT_LIMIT``; native client may pass
  ``?limit=N`` up to ``MAX_LIMIT``.
* Timestamps are unix seconds (int) — cheaper than ISO-8601 over the wire
  and easier for native shells to ``Date(timeIntervalSince1970:)``.

Auth contract (per #25): mobile clients exchange the user's Keycloak
refresh token for a short-lived access token *outside* this module
(handled by the Keycloak realm directly); each request carries the
access token as ``Authorization: Bearer <jwt>``. There is no separate
"mobile auth" flow — that is the entire point of #25 (single identity
provider).
"""

from __future__ import annotations

import logging
import time
from typing import Annotated, Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field

from shared.api.dependencies import actor_label, current_user
from shared.api.routes.decisions import get_store as get_decision_store
from shared.identity.models import User

logger = logging.getLogger("spine.api.mobile")
router = APIRouter(prefix="/api/v2/mobile", tags=["mobile"])

#: Default page size for mobile list endpoints. Tuned for a 200-300ms
#: round-trip on 4G/5G — keeps the payload <8KB at typical decision-card
#: sizes so an iPhone widget refresh stays inside a single TCP RTT.
DEFAULT_LIMIT = 25

#: Hard upper bound the server will accept on ``?limit=``. Anything above
#: this hits the full ``/api/v2/decisions`` surface instead.
MAX_LIMIT = 100

MobileAction = Literal["approve", "reject"]


# ---------------------------------------------------------------------------
# Compact JSON schemas — short keys, exclude_none, unix seconds for ts
# ---------------------------------------------------------------------------


class CompactApproval(BaseModel):
    """Mobile-optimised approval row (matches ``ApprovalDecision`` upstream)."""

    model_config = ConfigDict(extra="forbid")
    id: str = Field(..., description="approval_id (string for JS safety)")
    proj: str = Field(..., description="project_id")
    phase: Optional[str] = None
    sev: Literal["info", "warning", "critical"] = "info"
    ts: int = Field(..., description="created_at, unix seconds")


class CompactBriefing(BaseModel):
    """Mobile-optimised decision-card / briefing row."""

    model_config = ConfigDict(extra="forbid")
    id: str
    kind: str = Field(..., description="decision_class (compact key)")
    title: str = Field(..., max_length=120)
    sev: Literal["info", "warning", "critical"] = "info"
    ts: int


class CompactStatus(BaseModel):
    """Lock-screen widget status. Booleans + a single int — fits in <200B."""

    model_config = ConfigDict(extra="forbid")
    ok: bool
    pending: int = Field(0, description="count of pending approvals + decisions")
    hub: str = Field(..., description="hub_id (per #4 federation)")


class MobileActionResponse(BaseModel):
    """Response from POST /mobile/approvals/{id}/action."""

    model_config = ConfigDict(extra="forbid")
    ok: bool = True
    id: str
    action: MobileAction
    actor: str


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


def _clamp_limit(limit: int | None) -> int:
    """Clamp the caller-supplied limit into ``[1, MAX_LIMIT]``."""
    if not limit or limit < 1:
        return DEFAULT_LIMIT
    return min(limit, MAX_LIMIT)


@router.get("/approvals")
async def list_mobile_approvals(
    user: Annotated[User, Depends(current_user)],
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
) -> dict[str, Any]:
    """Compact list of pending approvals — mobile native-shell entry point.

    Wave 6 ships the static-shape contract; the implementation reads from
    the in-process decision store + a placeholder approval surface. Wave 4
    will pipe the persisted ``spine_lifecycle.approval`` rows through here
    once the asyncpg pool is available in test contexts.
    """
    n = _clamp_limit(limit)
    store = get_decision_store()
    # Approvals = the subset of pending decisions whose class is ``approval``.
    rows = [
        c for c in store.list(status_filter="pending") if c.decision_class == "approval"
    ][:n]
    items = [
        CompactApproval(
            id=c.decision_id,
            proj=c.project_id or "-",
            phase=(c.metadata or {}).get("phase"),
            sev=c.severity,
            ts=int(c.created_at),
        ).model_dump(exclude_none=True)
        for c in rows
    ]
    return {"ok": True, "items": items, "n": len(items)}


@router.get("/briefings")
async def list_mobile_briefings(
    user: Annotated[User, Depends(current_user)],
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
) -> dict[str, Any]:
    """Compact list of decision-cards / briefings (#5 active push).

    Includes ``briefing``, ``incident``, ``release``, ``budget``,
    ``policy_change`` classes — i.e. every class the native shell wants
    to surface in its inbox. Pure-approval class is reachable via
    ``/mobile/approvals`` instead.
    """
    n = _clamp_limit(limit)
    store = get_decision_store()
    rows = [
        c for c in store.list(status_filter="pending") if c.decision_class != "approval"
    ][:n]
    items = [
        CompactBriefing(
            id=c.decision_id,
            kind=c.decision_class,
            title=c.title[:120],
            sev=c.severity,
            ts=int(c.created_at),
        ).model_dump(exclude_none=True)
        for c in rows
    ]
    return {"ok": True, "items": items, "n": len(items)}


@router.get("/status")
async def mobile_status(
    user: Annotated[User, Depends(current_user)],
) -> dict[str, Any]:
    """Lock-screen widget payload — booleans + counters, <200 bytes.

    Native shells poll this once per app-foreground (or via APNs/FCM
    push) to update their badge count without paying for the full
    ``/healthz`` JSON.
    """
    # Hub ID — re-use the same env var the federation middleware uses so
    # we never get out of step (per #4 propagation header).
    from shared.api.app import HUB_ID  # noqa: PLC0415

    store = get_decision_store()
    pending = len(store.list(status_filter="pending"))
    return CompactStatus(ok=True, pending=pending, hub=HUB_ID).model_dump(
        exclude_none=True
    )


@router.post(
    "/approvals/{decision_id}/action",
    status_code=status.HTTP_200_OK,
)
async def post_mobile_action(
    decision_id: str,
    action: MobileAction,
    user: Annotated[User, Depends(current_user)],
) -> dict[str, Any]:
    """One-shot approve / reject from a native push-notification action.

    Native push frameworks (APNs / FCM) attach action buttons to the
    notification; tapping ``Approve`` posts here directly without
    opening the full Hub SPA. The full-fidelity flow with notes /
    request-changes lives at ``POST /api/v2/approvals`` — this endpoint
    is deliberately one-button-one-effect.
    """
    store = get_decision_store()
    card = store.get(decision_id)
    if card is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "decision_not_found", "message": decision_id},
        )
    new_status = "acked" if action == "approve" else "rejected"
    store.transition(decision_id, new_status)
    actor = actor_label(user)
    logger.info(
        "mobile_action",
        extra={"id": decision_id, "action": action, "actor": actor, "ts": int(time.time())},
    )
    return MobileActionResponse(id=decision_id, action=action, actor=actor).model_dump(
        exclude_none=True
    )


__all__ = [
    "router",
    "CompactApproval",
    "CompactBriefing",
    "CompactStatus",
    "MobileActionResponse",
    "MobileAction",
    "DEFAULT_LIMIT",
    "MAX_LIMIT",
]
