"""
shared.mcp.tools.federation
===========================

MCP tools for the Spine v3 federation subsystem (Wave 4 Squad A).

Tools registered (4):

* ``federation_register_child``  — register a downstream Hub
                                   (requires_citation=True, #12)
* ``federation_grant_consent``   — record a peer-consent grant
* ``federation_push_update``     — initiate a #16 cascade
                                   (requires_citation=True, #12)
* ``federation_pull_updates``    — list pending updates targeting us

All four are async-aware at the dispatch layer (the registry's `fn`
signature is sync, so each tool delegates to its async impl via
`asyncio.get_event_loop()` only when the test pool is present;
production routes call these from FastAPI dependencies that are
already on the event loop).

Per #12, the two high-impact tools — register-child and push-update —
require a Cite-or-Refuse `citation` in the response envelope; the
server middleware rejects responses without one with HTTP 422.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from shared.mcp.schemas import Citation, ToolError, ToolResponse
from shared.mcp.tools import register_tool
from shared.schemas.federation import (
    ConsentGrantV1,
    HubRegistrationV1,
    UpdateCascadePullV1,
    UpdateCascadePushV1,
)

logger = logging.getLogger("spine.mcp.tools.federation")

_FORBID = ConfigDict(extra="forbid")

#: Module-level injection seam — production wires this in the Hub
#: lifespan to point at the live `HubRegistry`, `ConsentEngine`,
#: `UpdateCascade`. Tests overwrite it directly. Each entry is the
#: subsystem object; missing entries → tool returns
#: ``status='stub_implementation'`` so smoke tests can detect un-wired
#: deployments without false-failing.
_DEPS: dict[str, Any] = {}


def set_federation_deps(
    *,
    hub_registry: Any = None,
    consent_engine: Any = None,
    update_cascade: Any = None,
    local_hub_id: Optional[UUID] = None,
) -> None:
    """Lifespan helper — wires the federation subsystem into MCP tools.

    Pass `None` for the values you want to leave un-wired. Tests pass
    mocks for every slot.
    """
    if hub_registry is not None:
        _DEPS["hub_registry"] = hub_registry
    if consent_engine is not None:
        _DEPS["consent_engine"] = consent_engine
    if update_cascade is not None:
        _DEPS["update_cascade"] = update_cascade
    if local_hub_id is not None:
        _DEPS["local_hub_id"] = local_hub_id


def clear_federation_deps() -> None:
    """Reset injected deps — primarily for test isolation."""
    _DEPS.clear()


def _stub_audit_id() -> UUID:
    return uuid4()


def _stub_response(tool: str) -> ToolResponse:
    """Return a `stub_implementation` response when deps are missing."""
    return ToolResponse(
        status="stub_implementation",
        audit_id=_stub_audit_id(),
        data={"tool": tool, "reason": "federation deps not wired"},
    )


def _run_async(coro: Any) -> Any:
    """Bridge sync-fn dispatcher → async impl.

    The MCP registry's `fn` signature is sync. Tests call these tools
    outside an event loop, so we drive the coroutine via
    `asyncio.run`. In production callers should invoke the underlying
    async helpers directly when already on the loop.
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Schedule on the running loop and block. This branch is
            # used by tests that create a loop manually; production
            # uses the helpers directly.
            future = asyncio.ensure_future(coro)
            return loop.run_until_complete(future)
    except RuntimeError:
        pass
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Tool input/output models — wrap v1 schemas in the MCP envelope inputs
# ---------------------------------------------------------------------------


class RegisterChildIn(BaseModel):
    """Inputs for ``federation_register_child``.

    Wraps `HubRegistrationV1` plus an `actor` claim for audit
    attribution. The MCP envelope `actor` field is propagated; this
    model also accepts it as a per-tool override.
    """

    model_config = _FORBID
    payload: HubRegistrationV1
    actor: str = Field(default="system", min_length=1)


class GrantConsentIn(BaseModel):
    """Inputs for ``federation_grant_consent``."""

    model_config = _FORBID
    payload: ConsentGrantV1
    actor: str = Field(default="system", min_length=1)


class PushUpdateIn(BaseModel):
    """Inputs for ``federation_push_update`` (Cite-or-Refuse)."""

    model_config = _FORBID
    payload: UpdateCascadePushV1
    actor: str = Field(default="system", min_length=1)
    approved_by: str = Field(..., min_length=1)


class PullUpdatesIn(BaseModel):
    """Inputs for ``federation_pull_updates``."""

    model_config = _FORBID
    payload: UpdateCascadePullV1
    actor: str = Field(default="system", min_length=1)


# ---------------------------------------------------------------------------
# Async implementations (testable in isolation)
# ---------------------------------------------------------------------------


async def _impl_register_child(inp: RegisterChildIn) -> ToolResponse:
    reg = _DEPS.get("hub_registry")
    if reg is None:
        return _stub_response("federation_register_child")
    p = inp.payload
    audit_id = uuid4()
    try:
        rec = await reg.register_child(
            child_hub_id=p.child_hub_id,
            name=p.name,
            base_url=p.base_url,
            public_key=p.public_key,
            parent_hub_id=p.parent_hub_id,
            initial_status="pending",
        )
    except Exception as exc:  # noqa: BLE001
        return ToolResponse(
            status="error",
            audit_id=audit_id,
            error=ToolError(
                code="federation_register_failed",
                message=str(exc),
                retryable=False,
            ),
        )
    return ToolResponse(
        status="ok",
        audit_id=audit_id,
        data={
            "hub_id": str(rec.hub_id),
            "parent_hub_id": str(rec.parent_hub_id) if rec.parent_hub_id else None,
            "consent_status": rec.consent_status,
        },
        citation=[
            Citation(
                type="audit_hash",
                ref=str(audit_id),
                excerpt=(
                    f"register_child({rec.hub_id}) by {inp.actor}: {p.rationale[:120]}"
                ),
            ),
        ],
    )


async def _impl_grant_consent(inp: GrantConsentIn) -> ToolResponse:
    eng = _DEPS.get("consent_engine")
    if eng is None:
        return _stub_response("federation_grant_consent")
    p = inp.payload
    audit_id = uuid4()
    try:
        await eng.grant(
            child_hub_id=p.child_hub_id,
            parent_hub_id=p.parent_hub_id,
            consent_class=p.consent_class,
            granted_by=p.granted_by,
            scope=p.scope,
        )
    except Exception as exc:  # noqa: BLE001
        return ToolResponse(
            status="error",
            audit_id=audit_id,
            error=ToolError(
                code="federation_grant_failed",
                message=str(exc),
                retryable=False,
            ),
        )
    return ToolResponse(
        status="ok",
        audit_id=audit_id,
        data={
            "child_hub_id": str(p.child_hub_id),
            "parent_hub_id": str(p.parent_hub_id),
            "consent_class": p.consent_class,
        },
    )


async def _impl_push_update(inp: PushUpdateIn) -> ToolResponse:
    cas = _DEPS.get("update_cascade")
    if cas is None:
        return _stub_response("federation_push_update")
    audit_id = uuid4()
    p = inp.payload
    # We approve-and-apply by treating the v1 payload as the local
    # already-pending record; the real lifecycle inserts the row first
    # (via the license/Squad B side or a child-pull) and then approves.
    try:
        # Convention: a pull_pending entry with matching bundle_version
        # is what we approve. The cascade refuses to auto-create rows.
        pending = await cas.pull_pending()
        match = next(
            (
                r
                for r in pending
                if r.bundle_version == p.bundle_version
                and r.source_hub_id == p.source_hub_id
            ),
            None,
        )
        if match is None:
            return ToolResponse(
                status="error",
                audit_id=audit_id,
                error=ToolError(
                    code="federation_no_pending_match",
                    message=(
                        f"no pending update for bundle_version={p.bundle_version!r} "
                        f"from source_hub_id={p.source_hub_id}"
                    ),
                    retryable=False,
                ),
            )
        outcome = await cas.approve_and_apply(
            match.id,
            approved_by=inp.approved_by,
            rationale=p.rationale,
        )
    except Exception as exc:  # noqa: BLE001
        return ToolResponse(
            status="error",
            audit_id=audit_id,
            error=ToolError(
                code="federation_cascade_failed",
                message=str(exc),
                retryable=False,
            ),
        )
    return ToolResponse(
        status="ok",
        audit_id=audit_id,
        data={
            "local_update_id": str(outcome.local_update_id),
            "local_status": outcome.local_status,
            "children_attempted": outcome.children_attempted,
            "children_succeeded": outcome.children_succeeded,
            "children_failed": outcome.children_failed,
            "notes": outcome.notes,
        },
        citation=[
            Citation(
                type="audit_hash",
                ref=str(audit_id),
                excerpt=(
                    f"approve_and_apply({outcome.local_update_id}) by "
                    f"{inp.approved_by}: {p.rationale[:120]}"
                ),
            ),
        ],
    )


async def _impl_pull_updates(inp: PullUpdatesIn) -> ToolResponse:
    cas = _DEPS.get("update_cascade")
    if cas is None:
        return _stub_response("federation_pull_updates")
    audit_id = uuid4()
    try:
        pending = await cas.pull_pending()
    except Exception as exc:  # noqa: BLE001
        return ToolResponse(
            status="error",
            audit_id=audit_id,
            error=ToolError(
                code="federation_pull_failed",
                message=str(exc),
                retryable=True,
            ),
        )
    return ToolResponse(
        status="ok",
        audit_id=audit_id,
        data={
            "target_hub_id": str(inp.payload.target_hub_id),
            "items": [
                {
                    "update_id": str(r.id),
                    "source_hub_id": str(r.source_hub_id),
                    "bundle_version": r.bundle_version,
                    "rollout_status": r.rollout_status,
                }
                for r in pending
            ],
        },
    )


# ---------------------------------------------------------------------------
# Registered tool entry points (sync — delegate to async impls)
# ---------------------------------------------------------------------------


@register_tool(
    name="federation_register_child",
    input_model=RegisterChildIn,
    story="WAVE-4.A.1",
    description="Register a downstream child Hub (#10).",
    tags=("federation",),
    requires_citation=True,  # #12 — high-impact action
)
def federation_register_child(payload: RegisterChildIn) -> ToolResponse:
    """Register a downstream child Hub in the federation registry."""
    return _run_async(_impl_register_child(payload))


@register_tool(
    name="federation_grant_consent",
    input_model=GrantConsentIn,
    story="WAVE-4.A.2",
    description="Record a peer-consent grant (#10).",
    tags=("federation",),
    requires_citation=False,
)
def federation_grant_consent(payload: GrantConsentIn) -> ToolResponse:
    """Grant a consent_class from child to parent Hub."""
    return _run_async(_impl_grant_consent(payload))


@register_tool(
    name="federation_push_update",
    input_model=PushUpdateIn,
    story="WAVE-4.A.3",
    description="Approve + cascade a signed bundle update (#16).",
    tags=("federation", "update_cascade"),
    requires_citation=True,  # #12 — high-impact action
)
def federation_push_update(payload: PushUpdateIn) -> ToolResponse:
    """Approve a pending update and cascade it to consenting children."""
    return _run_async(_impl_push_update(payload))


@register_tool(
    name="federation_pull_updates",
    input_model=PullUpdatesIn,
    story="WAVE-4.A.4",
    description="List pending updates targeting this Hub (#16).",
    tags=("federation", "update_cascade"),
    requires_citation=False,
)
def federation_pull_updates(payload: PullUpdatesIn) -> ToolResponse:
    """Return pending updates from `spine_federation.update_distribution`."""
    return _run_async(_impl_pull_updates(payload))


__all__ = [
    "set_federation_deps",
    "clear_federation_deps",
    "federation_register_child",
    "federation_grant_consent",
    "federation_push_update",
    "federation_pull_updates",
    "RegisterChildIn",
    "GrantConsentIn",
    "PushUpdateIn",
    "PullUpdatesIn",
]
