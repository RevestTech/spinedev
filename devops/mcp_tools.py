"""MCP tool surface for the Operate / devops subsystem (V3 #11).

Three tools auto-registered via the :func:`shared.mcp.tools.register_tool`
decorator (per the existing pattern in
``shared/mcp/tools/__init__.py``):

* ``devops_invoke`` — dispatch ``(plane, action, payload)`` to the right
  control plane. Tagged ``requires_citation=True`` per #12: any change
  action must cite (KG node / file:line / audit hash for "previous
  state"). The MCP Cite-or-Refuse middleware enforces this on the wire;
  the dispatcher additionally enforces on intrinsically HIGH_IMPACT
  actions even when called outside MCP.
* ``devops_status`` — read-only status snapshot for ``(plane, project_id)``.
* ``devops_planes_list`` — enumerate the 8 registered planes + their
  supported actions.

Caller pattern (mirrors existing tool modules in
:mod:`shared.mcp.tools`)::

    from shared.mcp.tools import TOOL_REGISTRY, discover_tools
    import devops.mcp_tools  # noqa: F401 — import-time registration
    discover_tools("shared.mcp.tools")
    TOOL_REGISTRY["devops_invoke"]  # ToolSpec

Wave 3 housekeeping: when the unified MCP server walks tool modules it
currently only inspects ``shared.mcp.tools.*``. Squad 4 should extend
``server.load_tools`` to also import ``devops.mcp_tools`` (or move this
module under ``shared/mcp/tools/devops.py``). For now, downstream
callers import this module directly; the decorator still populates
``TOOL_REGISTRY`` exactly as expected.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from shared.mcp.schemas import Citation, ToolError, ToolResponse
from shared.mcp.tools import register_tool

from devops.dispatcher import DevOpsDispatcher

logger = logging.getLogger(__name__)


# ─── One process-wide dispatcher (cheap to construct, idempotent). ─────


_DISPATCHER: DevOpsDispatcher | None = None


def _get_dispatcher() -> DevOpsDispatcher:
    """Lazy-init a single dispatcher per process."""
    global _DISPATCHER
    if _DISPATCHER is None:
        _DISPATCHER = DevOpsDispatcher()
    return _DISPATCHER


def _run_async(coro: Any) -> Any:
    """Sync→async bridge for the MCP entrypoint (mirrors verify.py)."""
    try:
        return asyncio.run(coro)
    except RuntimeError:  # pragma: no cover - nested loop
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()


# ─── Input models ──────────────────────────────────────────────────────


class DevopsInvokeInput(BaseModel):
    """Inputs for ``devops_invoke``."""

    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(..., min_length=1,
        description="Spine project; required for audit attribution.")
    plane: str = Field(..., min_length=1,
        description="One of 8 ENUM values from spine_devops.control_plane_name.")
    action: str = Field(..., min_length=1,
        description="Action name; must be in the plane's supported_actions.")
    payload: dict[str, Any] = Field(default_factory=dict,
        description=(
            "Action-specific payload. Cite-or-Refuse tools must include "
            "a non-empty 'citation' field (list of {type, ref, excerpt})."
        ))
    actor: str = Field(default="devops", min_length=1,
        description="Caller identity for the audit trail.")


class DevopsStatusInput(BaseModel):
    """Inputs for ``devops_status``."""

    model_config = ConfigDict(extra="forbid")

    plane: str = Field(..., min_length=1)
    project_id: str | None = Field(default=None,
        description="None = hub-global plane status.")


class DevopsPlanesListInput(BaseModel):
    """Inputs for ``devops_planes_list`` — no parameters."""

    model_config = ConfigDict(extra="forbid")


# ─── Tools ─────────────────────────────────────────────────────────────


@register_tool(
    name="devops_invoke",
    input_model=DevopsInvokeInput,
    story="STORY-11.1.1",  # placeholder until Wave 3 wires the backlog
    description="Dispatch a (plane, action, payload) call to a DevOps control plane.",
    tags=("devops", "operate"),
    requires_citation=True,  # V3 #12 — any change action must cite.
)
def devops_invoke(payload: DevopsInvokeInput) -> ToolResponse:
    """Route an Operate action through :class:`DevOpsDispatcher`.

    The dispatcher enforces Cite-or-Refuse for intrinsically HIGH_IMPACT
    actions. The MCP middleware additionally enforces that any response
    from a ``requires_citation=True`` tool carries a non-empty citation
    list — so we always include the action_log + audit_chain_anchor
    citations on ``ok`` and ``stub_implementation`` envelopes.
    """
    dispatcher = _get_dispatcher()
    try:
        result = _run_async(
            dispatcher.invoke(payload.plane, payload.action,
                              {**payload.payload, "project_id": payload.project_id})
        )
    except KeyError as exc:
        return ToolResponse(
            status="error", data={},
            error=ToolError(code="unknown_plane",
                            message=str(exc), retryable=False),
            audit_id=uuid4(), citation=[],
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("devops_invoke failed")
        return ToolResponse(
            status="error", data={},
            error=ToolError(code="dispatcher_failed",
                            message=f"{type(exc).__name__}: {exc!s}",
                            retryable=True),
            audit_id=uuid4(), citation=[],
        )

    if result.status == "error":
        # Cite-or-Refuse refusal lands here when the dispatcher refused
        # a HIGH_IMPACT action without citation — pass it through.
        return ToolResponse(
            status="error", data=result.model_dump(mode="json"),
            error=ToolError(
                code="devops_action_error",
                message=result.error or "unknown error",
                retryable=False,
            ),
            audit_id=uuid4(), citation=[],
        )

    # ok / stub_implementation: build citations from the action_log +
    # audit anchor so the Cite-or-Refuse middleware accepts the response.
    citations: list[Citation] = [
        Citation(
            type="audit_hash",
            ref=result.audit_chain_anchor or str(result.action_log_id),
            excerpt=f"devops.{payload.plane}.{payload.action} action_log",
        ),
    ]
    return ToolResponse(
        status="ok" if result.status == "ok" else "stub_implementation",
        data=result.model_dump(mode="json"),
        audit_id=uuid4(), citation=citations,
    )


@register_tool(
    name="devops_status",
    input_model=DevopsStatusInput,
    story="STORY-11.1.2",
    description="Read-only status snapshot for a (plane, project_id) pair.",
    tags=("devops", "operate"),
)
def devops_status(payload: DevopsStatusInput) -> ToolResponse:
    """Return :class:`PlaneStatus` for ``(plane, project_id)``."""
    dispatcher = _get_dispatcher()
    try:
        status = _run_async(
            dispatcher.status(payload.plane, payload.project_id)
        )
    except KeyError as exc:
        return ToolResponse(
            status="error", data={},
            error=ToolError(code="unknown_plane",
                            message=str(exc), retryable=False),
            audit_id=uuid4(), citation=[],
        )
    return ToolResponse(
        status="ok", data=status.model_dump(mode="json"),
        audit_id=uuid4(), citation=[],
    )


@register_tool(
    name="devops_planes_list",
    input_model=DevopsPlanesListInput,
    story="STORY-11.1.3",
    description="Enumerate the 8 registered control planes + supported actions.",
    tags=("devops", "operate"),
)
def devops_planes_list(payload: DevopsPlanesListInput) -> ToolResponse:
    """Return ``{planes: [{name, supported_actions}]}``."""
    dispatcher = _get_dispatcher()
    planes = [
        {"name": name, "supported_actions": dispatcher.supported_actions(name)}
        for name in dispatcher.registered_planes()
    ]
    return ToolResponse(
        status="ok",
        data={"planes": planes, "count": len(planes)},
        audit_id=uuid4(), citation=[],
    )


__all__: list[str] = [
    "DevopsInvokeInput",
    "DevopsStatusInput",
    "DevopsPlanesListInput",
    "devops_invoke",
    "devops_status",
    "devops_planes_list",
]
