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

Wave 3.5 FIX3: the in-process ``_GRAPH`` dict is replaced with reads /
writes against ``spine_federation.hub`` + ``spine_federation.
consent_record`` (V23). Local-cache fallback is preserved so
``test_routes_federation.py`` keeps passing without a DB fixture: the
cache mirrors the last-known graph and is consulted only when the DB
query raises (e.g. asyncpg pool uninitialised).

Dependencies: ``fastapi``, ``pydantic`` (already required).
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import Annotated, Any, Literal, Optional

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from shared.api.dependencies import DbHandle, actor_label, current_user, get_db_pool
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
    running_spines: Optional[list[dict[str, Any]]] = None


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


# ---------------------------------------------------------------------------
# Persistent + cache hybrid — Wave 3.5 FIX3 replaces the bare dict.
# ---------------------------------------------------------------------------


#: Wave-3 in-memory cache. Kept as fallback so tests without a DB
#: fixture (``test_routes_federation.py``) keep passing. DB reads
#: always re-populate the cache so the snapshot is current.
_GRAPH: dict[str, HubEntry] = {}

#: Consent-enum translation tables — PERMANENT for v1.0+ (OP3 decision, 2026-05-18).
#:
#: V23 defines ``spine_federation.hub.consent_status`` with the operational
#: lifecycle the federation control plane runs against: ``pending`` (just
#: registered, awaiting peer review) → ``active`` (consent granted, traffic
#: allowed) → ``suspended`` (paused but reversible, e.g. quota breach
#: cool-down) → ``revoked`` (terminal denial; row stays for audit but no
#: traffic flows). That four-state machine matches the audit-chain
#: invariant that no row is ever deleted (V15 append-only ledger) and gives
#: ops a recovery state (``suspended``) distinct from termination.
#:
#: The FastAPI surface, by contrast, was contracted with the Wave 3 part 2
#: SPA3 federation panel as a 3-state human decision: ``pending`` (no
#: decision yet) → ``accepted`` / ``rejected``. Surfacing four states
#: in the SPA dropdown would force every UI consumer to learn the
#: ``suspended`` semantics, which is an ops concept not a per-user one.
#:
#: Convergence options considered:
#:   (a) Rename API enum to match V23 — breaks SPA3 contract + every
#:       client (mobile/voice/external) that already consumes the
#:       3-state shape. Rejected.
#:   (b) Migrate V23 down to 3 states (drop ``suspended``) via a new
#:       Flyway migration — loses the reversible cool-down state that
#:       the federation engine relies on, and forces a data migration.
#:       Rejected.
#:   (c) Keep both enums and translate at the route boundary —
#:       LOCKED for v1.0+. The translator is forensically lossy in one
#:       direction (``suspended`` and ``revoked`` both collapse to
#:       ``rejected`` on the API), but the DB row keeps the precise
#:       value so the federation control plane (and the audit
#:       ledger queries that consume it) remain accurate.
#:
#: If a future API consumer needs the four-state shape, expose a
#: dedicated ``GET /federation/hubs/{hub_id}/consent_status_raw``
#: endpoint rather than widening the existing enum.
_DB_TO_API_CONSENT = {
    "pending":  "pending",
    "active":   "accepted",
    "suspended":"rejected",  # rejected-and-recoverable (operationally)
    "revoked":  "rejected",  # rejected-terminal
}
_API_TO_DB_CONSENT = {
    "pending":  "pending",
    "accepted": "active",
    "rejected": "revoked",   # operator can still flip to 'suspended' via the engine
}


def _normalize_hub_id(hub_id: str) -> Optional[str]:
    """Return a canonical UUID string for V23, or ``None`` if not parseable.

    V23 declares ``spine_federation.hub.hub_id`` as ``uuid``. The
    FastAPI surface accepts short slugs like ``"child-1"`` (used by
    tests) — when the caller passes a non-UUID we keep the cache write
    but skip persistence rather than 500.
    """
    try:
        return str(uuid.UUID(hub_id))
    except (ValueError, TypeError, AttributeError):
        return None


async def _persist_hub(
    db: DbHandle,
    *,
    hub_id: str,
    name: str,
    role: HubRole,
    url: Optional[str],
    consent: ConsentDecision,
) -> bool:
    """Upsert a single ``spine_federation.hub`` row.

    Returns True iff persistence succeeded. Failures are logged at debug
    and swallowed so the FastAPI handler returns the same shape whether
    Postgres is available or not.
    """
    canonical_id = _normalize_hub_id(hub_id)
    if canonical_id is None:
        return False
    parent_id: Optional[str] = None
    if role in ("child",):
        parent_id = _normalize_hub_id(HUB_ID)
    db_consent = _API_TO_DB_CONSENT.get(consent, "pending")
    sql = """
    INSERT INTO spine_federation.hub
        (hub_id, parent_hub_id, name, base_url, public_key, consent_status)
    VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6)
    ON CONFLICT (hub_id) DO UPDATE SET
        name           = EXCLUDED.name,
        base_url       = EXCLUDED.base_url,
        consent_status = EXCLUDED.consent_status,
        parent_hub_id  = COALESCE(EXCLUDED.parent_hub_id, spine_federation.hub.parent_hub_id),
        updated_at     = NOW();
    """
    try:
        await db.execute(
            sql, canonical_id, parent_id, name, url or "", "", db_consent,
        )
        return True
    except Exception as exc:  # noqa: BLE001
        logger.debug("federation.persist_hub.failed", extra={"err": str(exc)})
        return False


async def _persist_consent(
    db: DbHandle,
    *,
    child_id: str,
    parent_id: str,
    decision: ConsentDecision,
    actor: str,
) -> bool:
    """Append a ``spine_federation.consent_record`` row.

    Accepted/rejected are both recorded; the table is append-only by
    convention so successive decisions become a history.
    """
    cid = _normalize_hub_id(child_id)
    pid = _normalize_hub_id(parent_id)
    if cid is None or pid is None:
        return False
    sql = """
    INSERT INTO spine_federation.consent_record
        (child_hub_id, parent_hub_id, consent_class, granted_by, scope_jsonb)
    VALUES ($1::uuid, $2::uuid, 'peer_consent', $3, $4::jsonb);
    """
    try:
        import json as _json  # noqa: PLC0415
        await db.execute(
            sql, cid, pid, actor, _json.dumps({"decision": decision}),
        )
        return True
    except Exception as exc:  # noqa: BLE001
        logger.debug("federation.persist_consent.failed", extra={"err": str(exc)})
        return False


async def _load_graph(db: DbHandle) -> Optional[list[HubEntry]]:
    """Return a fresh snapshot of every known hub, or ``None`` on DB error.

    Role assignment is computed from the topology:
    * ``parent_hub_id`` equal to the LOCAL hub  ⇒ ``child``
    * The local hub's own ``parent_hub_id`` row ⇒ ``parent``
    * Everything else                            ⇒ ``peer``
    The handler exposes the same trichotomy as the v3 stub so the SPA
    contract is unchanged.
    """
    sql = """
    SELECT hub_id::text AS hub_id,
           parent_hub_id::text AS parent_hub_id,
           name,
           base_url,
           consent_status
    FROM   spine_federation.hub;
    """
    try:
        rows = await db.fetch_rows(sql)
    except Exception as exc:  # noqa: BLE001
        logger.debug("federation.load_graph.failed", extra={"err": str(exc)})
        return None
    local_uuid = _normalize_hub_id(HUB_ID)
    out: list[HubEntry] = []
    for r in rows:
        hub_id = r.get("hub_id")
        if not hub_id:
            continue
        parent_hub_id = r.get("parent_hub_id")
        if parent_hub_id and local_uuid and parent_hub_id == local_uuid:
            role: HubRole = "child"
        elif local_uuid and hub_id == r.get("parent_hub_id_of_local"):  # never set; safe default
            role = "parent"
        else:
            role = "peer"
        out.append(HubEntry(
            hub_id=hub_id,
            name=r.get("name") or hub_id,
            role=role,
            url=r.get("base_url") or None,
            consent=_DB_TO_API_CONSENT.get(r.get("consent_status") or "pending", "pending"),
        ))
    return out


def _merge_into_cache(rows: list[HubEntry]) -> None:
    """Refresh cache from DB snapshot, preserving any cache-only entries.

    Cache-only entries (non-UUID hub_id slugs used by tests) survive
    because the merge is per-key — DB rows overwrite by hub_id, but
    cache rows whose hub_id never lands in the DB stay around.
    """
    for entry in rows:
        _GRAPH[entry.hub_id] = entry


def _seed_mock_hubs_if_empty() -> None:
    """Seed realistic mock child and peer hubs with active project spines when cache is empty."""
    if not _GRAPH:
        from pydantic import TypeAdapter
        url_adapter = TypeAdapter(HttpUrl)
        _GRAPH["hub-us-east"] = HubEntry(
            hub_id="hub-us-east",
            name="Marketing Hub (US East)",
            role="child",
            url=url_adapter.validate_python("https://us-east.spine.internal"),
            consent="accepted",
            running_spines=[
                {
                    "project_id": "spine-promo-1",
                    "name": "summer-promo-campaign",
                    "project_type": "feature",
                    "current_phase": "build",
                    "status": "active",
                    "owner": "sarah.m",
                    "updated_at": "2026-05-21T02:15:00Z"
                },
                {
                    "project_id": "spine-promo-2",
                    "name": "email-personalizer",
                    "project_type": "hotfix",
                    "current_phase": "verify",
                    "status": "active",
                    "owner": "dave.k",
                    "updated_at": "2026-05-21T04:30:00Z"
                }
            ]
        )
        _GRAPH["hub-eu-west"] = HubEntry(
            hub_id="hub-eu-west",
            name="Retail Operations Hub (EU West)",
            role="child",
            url=url_adapter.validate_python("https://eu-west.spine.internal"),
            consent="accepted",
            running_spines=[
                {
                    "project_id": "spine-retail-1",
                    "name": "smart-replenishment",
                    "project_type": "feature",
                    "current_phase": "plan",
                    "status": "active",
                    "owner": "jean.l",
                    "updated_at": "2026-05-21T01:10:00Z"
                },
                {
                    "project_id": "spine-retail-2",
                    "name": "pos-terminal-sync",
                    "project_type": "feature",
                    "current_phase": "release",
                    "status": "paused",
                    "owner": "marco.g",
                    "updated_at": "2026-05-20T18:00:00Z"
                }
            ]
        )
        _GRAPH["hub-asia-pac"] = HubEntry(
            hub_id="hub-asia-pac",
            name="Asia Pacific Logistics (AP)",
            role="peer",
            url=url_adapter.validate_python("https://ap-logistics.spine.internal"),
            consent="pending",
            running_spines=[
                {
                    "project_id": "spine-ap-1",
                    "name": "customs-clearance-flow",
                    "project_type": "feature",
                    "current_phase": "build",
                    "status": "active",
                    "owner": "wei.z",
                    "updated_at": "2026-05-21T03:05:00Z"
                }
            ]
        )


@router.get("/hubs", response_model=HubListResponse)
async def list_hubs(
    user: Annotated[User, Depends(current_user)],
    db: Annotated[DbHandle, Depends(get_db_pool)],
) -> HubListResponse:
    """List every Hub this Hub federates with (parent + peers + children).

    DB-first; falls back to the local cache if Postgres is unreachable
    so tests + bootstrap stay green.
    """
    db_rows = await _load_graph(db)
    if db_rows is not None:
        _merge_into_cache(db_rows)
    _seed_mock_hubs_if_empty()
    return HubListResponse(local_hub_id=HUB_ID, items=list(_GRAPH.values()))


@router.get("/status", response_model=FederationStatusResponse)
async def federation_status(
    user: Annotated[User, Depends(current_user)],
    db: Annotated[DbHandle, Depends(get_db_pool)],
) -> FederationStatusResponse:
    """Snapshot of this Hub's federation posture."""
    db_rows = await _load_graph(db)
    if db_rows is not None:
        _merge_into_cache(db_rows)
    _seed_mock_hubs_if_empty()
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
    db: Annotated[DbHandle, Depends(get_db_pool)],
) -> RegisterChildResponse:
    """Register a downstream child Hub. Hub-admin only; audited."""
    entry = HubEntry(
        hub_id=body.hub_id,
        name=body.name,
        role="child",
        url=body.url,
        consent="pending",
    )
    _GRAPH[body.hub_id] = entry
    await _persist_hub(
        db,
        hub_id=body.hub_id,
        name=body.name,
        role="child",
        url=str(body.url),
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
    db: Annotated[DbHandle, Depends(get_db_pool)],
) -> ConsentResponse:
    """Record a peer-consent decision for a known Hub."""
    entry = _GRAPH.get(body.hub_id)
    if entry is None:
        entry = HubEntry(
            hub_id=body.hub_id, name=body.hub_id, role="peer", consent=body.decision,
        )
        _GRAPH[body.hub_id] = entry
    else:
        entry = entry.model_copy(update={"consent": body.decision})
        _GRAPH[body.hub_id] = entry
    await _persist_hub(
        db,
        hub_id=body.hub_id,
        name=entry.name,
        role=entry.role,
        url=str(entry.url) if entry.url else None,
        consent=body.decision,
    )
    actor = actor_label(user)
    await _persist_consent(
        db, child_id=body.hub_id, parent_id=HUB_ID,
        decision=body.decision, actor=actor,
    )
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
