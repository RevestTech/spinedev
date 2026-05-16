"""Build subsystem MCP tools.

Two tools today per REQ-INIT-7 FR-2 / FR-3 and ``EPIC-7.2``:

* ``build_dispatch``  — orchestrator hands a directive to Build with the
  locked pipeline version (``STORY-7.2.2``).
* ``build_completed`` — Build reports completion with a typed ``BuildArtifact``
  (``STORY-7.2.3`` / ``EPIC-7.4``).

``build_dispatch`` now delegates to ``build/bridge/v1_dispatcher.sh`` so v2
orchestrator directives reach the existing v1 bash daemons (STORY-7.5.1,
PRD §7.5 FR-5). ``build_completed`` remains a stub pending STORY-7.2.3.
"""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from shared.mcp.schemas import ToolResponse
from shared.mcp.tools import register_tool

logger = logging.getLogger(__name__)

# v1 daemon set the bridge can dispatch to. Mirrors lib/roles.sh::
# SPINE_TEAM_ROLES; keep in sync when a role lands or retires.
_V1_BRIDGED_ROLES = frozenset({
    "product", "planner", "architect", "conductor", "researcher", "engineer",
    "ux", "qa", "operator", "datawright", "seer", "auditor", "memory",
})
_BRIDGE_DISPATCHER = Path(__file__).resolve().parents[3] / "build" / "bridge" / "v1_dispatcher.sh"


class BuildDispatchInput(BaseModel):
    """Inputs for ``build_dispatch`` (REQ-INIT-7 FR-2)."""

    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(..., min_length=1)
    role: str = Field(default="engineer", min_length=1, description="Target v1 role daemon.")
    directive: str = Field(..., min_length=1, description="Directive body for the Build subsystem.")
    story_id: str | None = Field(default=None, description="Optional STORY-X.Y.Z this directive realizes.")
    pipeline_version: str = Field(..., min_length=1, description="Locked sdlc-pipeline.yaml version.")
    parent_directive_id: str | None = Field(default=None, description="Set on verify-fail re-dispatch.")
    budget_remaining_usd: float | None = Field(default=None, ge=0)
    prior_findings: list[str] | None = Field(
        default=None,
        description="Optional verify findings being remediated on a re-route (EPIC-9.8).",
    )


class BuildDispatchResponse(BaseModel):
    """Payload returned by ``build_dispatch``."""

    model_config = ConfigDict(extra="forbid")

    project_id: str
    directive_id: str
    accepted: bool
    bridge: str = Field(default="v1", description="Which dispatch path was used (v1=bridge, v2=native).")


def _dispatch_via_v1_bridge(payload: BuildDispatchInput) -> tuple[str, bool]:
    """Shell out to ``build/bridge/v1_dispatcher.sh dispatch``. Returns
    ``(directive_id, accepted)``. Logs and returns ``("", False)`` on error."""
    cmd = [
        "bash", str(_BRIDGE_DISPATCHER), "dispatch",
        payload.role, payload.directive, payload.project_id, payload.pipeline_version,
    ]
    if payload.parent_directive_id:
        cmd.append(payload.parent_directive_id)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15, check=False)
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        logger.error("v1_bridge_unavailable", extra={"error": str(exc), "role": payload.role})
        return "", False
    if proc.returncode != 0:
        logger.error("v1_bridge_dispatch_failed",
                     extra={"rc": proc.returncode, "stderr": proc.stderr[-500:]})
        return "", False
    try:
        body = json.loads(proc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        logger.error("v1_bridge_bad_json", extra={"stdout": proc.stdout[-500:]})
        return "", False
    return str(body.get("directive_id", "")), bool(body.get("ok", False))


@register_tool(
    name="build_dispatch",
    input_model=BuildDispatchInput,
    story="STORY-7.2.2",
    description="Orchestrator dispatches a directive to Build via MCP, carrying the locked pipeline version.",
    tags=("build", "dispatch"),
)
def build_dispatch(payload: BuildDispatchInput) -> ToolResponse:
    """Route the directive to a v1 daemon via the bridge (STORY-7.5.1)."""
    logger.info("mcp_tool_call", extra={
        "tool": "build_dispatch", "project_id": payload.project_id,
        "actor": "orchestrator", "role": payload.role})
    if payload.role in _V1_BRIDGED_ROLES:
        directive_id, accepted = _dispatch_via_v1_bridge(payload)
        if not directive_id:  # bridge unreachable — synthesise an id so the caller can retry
            directive_id = f"dir_{uuid4().hex[:12]}"
        result = BuildDispatchResponse(
            project_id=payload.project_id, directive_id=directive_id,
            accepted=accepted, bridge="v1")
        return ToolResponse(status="ok" if accepted else "error",
                            data=result.model_dump(mode="json"))
    # Future: v2-native daemons land here when STORY-7.5.x retires bridged roles.
    directive_id = f"dir_{uuid4().hex[:12]}"
    result = BuildDispatchResponse(
        project_id=payload.project_id, directive_id=directive_id,
        accepted=False, bridge="v2")
    return ToolResponse(status="stub_implementation", data=result.model_dump(mode="json"))


class BuildCompletedInput(BaseModel):
    """Inputs for ``build_completed`` (REQ-INIT-7 FR-3, EPIC-7.4).

    ``artifact`` is a free-form dict here; the canonical Pydantic ``BuildArtifact``
    model lives in ``build/`` per ``STORY-7.4.1`` and will be referenced once the
    Build subsystem package ships.
    """

    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(..., min_length=1)
    directive_id: str = Field(..., min_length=1)
    artifact: dict = Field(
        default_factory=dict,
        description="Serialized BuildArtifact (code_changes, tests, kg_impact, cost, rationale).",
    )


class BuildCompletedResponse(BaseModel):
    """Stub payload returned by ``build_completed``."""

    model_config = ConfigDict(extra="forbid")

    project_id: str
    directive_id: str
    persisted: bool
    next_phase: str | None


@register_tool(
    name="build_completed",
    input_model=BuildCompletedInput,
    story="STORY-7.2.3",
    description="Build subsystem reports completion to the orchestrator with a typed BuildArtifact.",
    tags=("build", "completion"),
)
def build_completed(payload: BuildCompletedInput) -> ToolResponse:
    """Stub: acknowledges but does not persist. TODO STORY-7.2.3: real implementation."""
    logger.info(
        "mcp_tool_call",
        extra={"tool": "build_completed", "project_id": payload.project_id, "actor": "build"},
    )
    result = BuildCompletedResponse(
        project_id=payload.project_id,
        directive_id=payload.directive_id,
        persisted=False,
        next_phase=None,
    )
    return ToolResponse(status="stub_implementation", data=result.model_dump(mode="json"))


__all__: list[str] = [
    "BuildCompletedInput",
    "BuildCompletedResponse",
    "BuildDispatchInput",
    "BuildDispatchResponse",
    "build_completed",
    "build_dispatch",
]
