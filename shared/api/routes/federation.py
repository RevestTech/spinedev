"""``/api/v2/federation`` — Hub-to-Hub config + status (#4, #10, #16).

Per #10 "a Hub is a Hub is a Hub": every Hub can register child Hubs,
declare an upstream parent, and surface aggregated state.

Endpoints (Wave 3 part 1 minimum surface):

* ``GET  /api/v2/federation/hubs``             — list known peer Hubs
* ``GET  /api/v2/federation/status``           — local Hub's federation posture
* ``POST /api/v2/federation/register-child``   — register a downstream Hub
* ``POST /api/v2/federation/consent``          — record peer-consent decision

All federation routes are gated by ``require_feature_flag('federation')``
because federation is a paid-tier capability per #23.

Dependencies: ``fastapi``, ``pydantic`` (already required).
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from shared.api.dependencies import actor_label, current_user
from shared.api.middleware.feature_flag import require_feature_flag
from shared.audit.audit_record import AuditRecord, chain_to_previous
from shared.identity.models import User
from shared.identity.rbac import require_role

logger = logging.getLogger("spine.api.federation")
router = APIRouter(
    prefix="/api/v2/federation",
    tags=["federation"],
    dependencies=[Depends(require_feature_flag("federation"))],
)

#: Local Hub ID — propagated on every outbound federation header.
#: Lives in env-as-metadata (NOT a secret value), so it's allowed under #9.
HUB_ID = os.environ.get("SPINE_HUB_ID", "hub-local")


HubRole = Literal["root", "parent", "peer", "child"]
ConsentDecision = Literal["accepted", "rejected", "pending"]


class HubEntry(BaseModel):
    """One known Hub in the federation graph."""

    model_config = ConfigDict(extra="forbid")
    hub_id: str = Field(..., min_length=1)
    name: str
    role: HubRole
    url: Optional[HttpUrl] = None
    consent: ConsentDecision = "pending"


class HubListResponse(BaseModel):
    """``GET /federation/hubs`` envelope."""

    model_config = ConfigDict(extra="forbid")
    ok: bool = True
    local_hub_id: str
    items: list[HubEntry]


class FederationStatusResponse(BaseModel):
    """``GET /federation/status`` envelope."""

    model_config = ConfigDict(extra="forbid")
    ok: bool = True
    local_hub_id: str
    parent_hub_id: Optional[str] = None
    children_count: int
    peers_count: int


class RegisterChildRequest(BaseModel):
    """``POST /federation/register-child`` body."""

    model_config = ConfigDict(extra="forbid")
    hub_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    url: HttpUrl
    rationale: str = Field(..., min_length=1, max_length=4_000)


class RegisterChildResponse(BaseModel):
    """``POST /federation/register-child`` response."""

    model_config = ConfigDict(extra="forbid")
    ok: bool
    hub_id: str
    actor: str
    audit_event_uuid: str


class ConsentRequest(BaseModel):
    """``POST /federation/consent`` body."""

    model_config = ConfigDict(extra="forbid")
    hub_id: str = Field(..., min_length=1)
    decision: ConsentDecision
    rationale: str = Field(..., min_length=1, max_length=4_000)


class ConsentResponse(BaseModel):
    """``POST /federation/consent`` response."""

    model_config = ConfigDict(extra="forbid")
    ok: bool
    hub_id: str
    decision: ConsentDecision
    actor: str
    audit_event_uuid: str


# In-memory federation graph — Wave 4 moves to spine_federation tables.
_GRAPH: dict[str, HubEntry] = {}


@router.get("/hubs", response_model=HubListResponse)
async def list_hubs(user: Annotated[User, Depends(current_user)]) -> HubListResponse:
    """List every Hub this Hub federates with (parent + peers + children)."""
    return HubListResponse(local_hub_id=HUB_ID, items=list(_GRAPH.values()))


@router.get("/status", response_model=FederationStatusResponse)
async def federation_status(
    user: Annotated[User, Depends(current_user)],
) -> FederationStatusResponse:
    """Snapshot of this Hub's federation posture."""
    parent = next((h.hub_id for h in _GRAPH.values() if h.role == "parent"), None)
    children = sum(1 for h in _GRAPH.values() if h.role == "child")
    peers = sum(1 for h in _GRAPH.values() if h.role == "peer")
    return FederationStatusResponse(
        local_hub_id=HUB_ID, parent_hub_id=parent, children_count=children, peers_count=peers
    )


@router.post("/register-child", response_model=RegisterChildResponse,
             status_code=status.HTTP_201_CREATED)
async def register_child(
    body: RegisterChildRequest,
    user: Annotated[User, Depends(require_role("hub-admin"))],
) -> RegisterChildResponse:
    """Register a downstream child Hub. Hub-admin only; audited."""
    _GRAPH[body.hub_id] = HubEntry(
        hub_id=body.hub_id,
        name=body.name,
        role="child",
        url=body.url,
        consent="pending",
    )
    actor = actor_label(user)
    rec = AuditRecord(
        role="hub_admin",
        subsystem="federation",
        action="register_child",
        actor=actor,
        subject_type="hub",
        subject_id=body.hub_id,
        rationale=body.rationale,
        correlation_id=uuid.uuid4(),
        metadata={"local_hub_id": HUB_ID, "child_name": body.name},
    )
    rec = chain_to_previous(rec, prev_hash=None)
    return RegisterChildResponse(
        ok=True, hub_id=body.hub_id, actor=actor, audit_event_uuid=str(rec.event_uuid)
    )


@router.post("/consent", response_model=ConsentResponse)
async def record_consent(
    body: ConsentRequest,
    user: Annotated[User, Depends(require_role("hub-admin"))],
) -> ConsentResponse:
    """Record a peer-consent decision for a known Hub."""
    entry = _GRAPH.get(body.hub_id)
    if entry is None:
        _GRAPH[body.hub_id] = HubEntry(
            hub_id=body.hub_id, name=body.hub_id, role="peer", consent=body.decision
        )
    else:
        _GRAPH[body.hub_id] = entry.model_copy(update={"consent": body.decision})
    actor = actor_label(user)
    rec = AuditRecord(
        role="hub_admin",
        subsystem="federation",
        action="consent_decision",
        actor=actor,
        subject_type="hub",
        subject_id=body.hub_id,
        rationale=body.rationale,
        metadata={"decision": body.decision, "local_hub_id": HUB_ID},
    )
    rec = chain_to_previous(rec, prev_hash=None)
    return ConsentResponse(
        ok=True,
        hub_id=body.hub_id,
        decision=body.decision,
        actor=actor,
        audit_event_uuid=str(rec.event_uuid),
    )


__all__ = [
    "router",
    "HUB_ID",
    "HubEntry",
    "HubListResponse",
    "FederationStatusResponse",
    "RegisterChildRequest",
    "RegisterChildResponse",
    "ConsentRequest",
    "ConsentResponse",
]
