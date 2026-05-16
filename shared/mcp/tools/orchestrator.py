"""Orchestrator MCP tools — project lifecycle primitives (EPIC-9.9).

Stubs for the four tools that make up the orchestrator's MCP API surface:

* ``project_create``  — STORY-9.9.1: create a new project in phase ``intake``.
* ``project_status``  — STORY-9.9.1: read current phase, owners, open gates.
* ``phase_advance``   — STORY-9.2.1: transition to a target phase (HMAC token).
* ``approval_grant``  — STORY-9.3.2: record an approval, return a token.

All four validate input, log the call, and return a fixture with
``status="stub_implementation"``. Wiring to ``orchestrator/lib/transition.sh``
and the ``spine_lifecycle`` schema lands in the linked stories.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from shared.mcp.schemas import ToolResponse
from shared.mcp.tools import register_tool

logger = logging.getLogger(__name__)

_FORBID = ConfigDict(extra="forbid")

# Canonical project_type values mirror docs/PRD.md REQ-INIT-1. Kept narrow on
# purpose; org bundles extend via the manifest, not by widening this Literal.
ProjectType = Literal["greenfield", "evolve", "audit_only", "operate"]


def _log(tool: str, project_id: str, actor: str) -> None:
    logger.info("mcp_tool_call", extra={"tool": tool, "project_id": project_id, "actor": actor})


def _stub(payload: BaseModel) -> ToolResponse:
    return ToolResponse(status="stub_implementation", data=payload.model_dump(mode="json"))


class ProjectCreateInput(BaseModel):
    """Inputs for ``project_create``."""

    model_config = _FORBID
    name: str = Field(..., min_length=1, max_length=200, description="Human-readable project name.")
    project_type: ProjectType = Field(..., description="Lifecycle template to apply.")
    owner: str = Field(..., min_length=1, description="Email or username of the responsible owner.")


class ProjectCreatedResponse(BaseModel):
    """``ToolResponse.data`` payload for ``project_create``."""

    model_config = _FORBID
    project_id: str
    name: str
    project_type: ProjectType
    owner: str
    initial_phase: str
    created_at: datetime


class ProjectStatusInput(BaseModel):
    """Inputs for ``project_status``."""

    model_config = _FORBID
    project_id: str = Field(..., min_length=1, description="Spine project ID.")


class ProjectStatusResponse(BaseModel):
    """``ToolResponse.data`` payload for ``project_status``."""

    model_config = _FORBID
    project_id: str
    current_phase: str
    pending_approvals: list[str]
    pipeline_version: str
    last_transition_at: datetime | None


class PhaseAdvanceInput(BaseModel):
    """Inputs for ``phase_advance``."""

    model_config = _FORBID
    project_id: str = Field(..., min_length=1)
    target_phase: str = Field(..., min_length=1, description="Phase to advance to per sdlc-pipeline.yaml.")
    approval_token: str | None = Field(
        default=None, description="HMAC-signed token for gated phases (FR-4); None for system transitions."
    )


class PhaseAdvanceResponse(BaseModel):
    """``ToolResponse.data`` payload for ``phase_advance``."""

    model_config = _FORBID
    project_id: str
    from_phase: str
    to_phase: str
    transition_id: str
    accepted: bool


class ApprovalGrantInput(BaseModel):
    """Inputs for ``approval_grant``."""

    model_config = _FORBID
    project_id: str = Field(..., min_length=1)
    phase: str = Field(..., min_length=1, description="Phase being approved (e.g. 'plan_approved').")
    approver: str = Field(..., min_length=1, description="Username/email of the approver.")
    notes: str | None = Field(default=None, max_length=4_000, description="Optional rationale recorded with the approval.")


class ApprovalGrantedResponse(BaseModel):
    """``ToolResponse.data`` payload for ``approval_grant``."""

    model_config = _FORBID
    project_id: str
    phase: str
    approver: str
    approval_id: str
    token: str
    granted_at: datetime


@register_tool(
    name="project_create",
    input_model=ProjectCreateInput,
    story="STORY-9.9.1",
    description="Create a new Spine project in the initial 'intake' phase.",
    tags=("orchestrator", "lifecycle"),
)
def project_create(payload: ProjectCreateInput) -> ToolResponse:
    """Stub. TODO STORY-9.9.1: persist to spine_lifecycle.project + audit row."""
    project_id = f"proj_{uuid4().hex[:12]}"
    _log("project_create", project_id, payload.owner)
    return _stub(ProjectCreatedResponse(
        project_id=project_id, name=payload.name, project_type=payload.project_type,
        owner=payload.owner, initial_phase="intake", created_at=datetime.now(timezone.utc),
    ))


@register_tool(
    name="project_status",
    input_model=ProjectStatusInput,
    story="STORY-9.9.1",
    description="Return the current phase, pending approvals, and pipeline version for a project.",
    tags=("orchestrator", "lifecycle"),
)
def project_status(payload: ProjectStatusInput) -> ToolResponse:
    """Stub. TODO STORY-9.9.1: read from spine_lifecycle.project + phase_history."""
    _log("project_status", payload.project_id, "system")
    return _stub(ProjectStatusResponse(
        project_id=payload.project_id, current_phase="intake", pending_approvals=[],
        pipeline_version="0.0.0-stub", last_transition_at=None,
    ))


@register_tool(
    name="phase_advance",
    input_model=PhaseAdvanceInput,
    story="STORY-9.2.1",
    description="Advance a project to a target lifecycle phase; verifies HMAC approval token if required.",
    tags=("orchestrator", "lifecycle", "gate"),
)
def phase_advance(payload: PhaseAdvanceInput) -> ToolResponse:
    """Stub. TODO STORY-9.2.1: invoke orchestrator/lib/transition.sh + verify HMAC + audit."""
    _log("phase_advance", payload.project_id, "orchestrator")
    return _stub(PhaseAdvanceResponse(
        project_id=payload.project_id, from_phase="intake", to_phase=payload.target_phase,
        transition_id=f"tx_{uuid4().hex[:12]}", accepted=False,
    ))


@register_tool(
    name="approval_grant",
    input_model=ApprovalGrantInput,
    story="STORY-9.3.2",
    description="Record an approval for a phase gate; returns an HMAC-signed token consumable by phase_advance.",
    tags=("orchestrator", "lifecycle", "gate"),
)
def approval_grant(payload: ApprovalGrantInput) -> ToolResponse:
    """Stub. TODO STORY-9.3.2: HMAC-sign (project_id, phase, approver, ts); persist."""
    _log("approval_grant", payload.project_id, payload.approver)
    return _stub(ApprovalGrantedResponse(
        project_id=payload.project_id, phase=payload.phase, approver=payload.approver,
        approval_id=f"app_{uuid4().hex[:12]}", token="stub-token-not-hmac-signed",
        granted_at=datetime.now(timezone.utc),
    ))


__all__: list[str] = [
    "ApprovalGrantInput", "ApprovalGrantedResponse", "PhaseAdvanceInput", "PhaseAdvanceResponse",
    "ProjectCreateInput", "ProjectCreatedResponse", "ProjectStatusInput", "ProjectStatusResponse",
    "approval_grant", "phase_advance", "project_create", "project_status",
]
