"""Build subsystem MCP tools.

Two tools today per REQ-INIT-7 FR-2 / FR-3 and ``EPIC-7.2``:

* ``build_dispatch``  — orchestrator hands a directive to Build with the
  locked pipeline version (``STORY-7.2.2``).
* ``build_completed`` — Build reports completion with a typed ``BuildArtifact``
  (``STORY-7.2.3`` / ``EPIC-7.4``).

Real implementations land in the linked stories; this is scaffolding only.
"""

from __future__ import annotations

import logging
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from shared.mcp.schemas import ToolResponse
from shared.mcp.tools import register_tool

logger = logging.getLogger(__name__)


class BuildDispatchInput(BaseModel):
    """Inputs for ``build_dispatch`` (REQ-INIT-7 FR-2)."""

    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(..., min_length=1)
    directive: str = Field(..., min_length=1, description="Directive body for the Build subsystem.")
    story_id: str | None = Field(default=None, description="Optional STORY-X.Y.Z this directive realizes.")
    pipeline_version: str = Field(..., min_length=1, description="Locked sdlc-pipeline.yaml version.")
    prior_findings: list[str] | None = Field(
        default=None,
        description="Optional verify findings being remediated on a re-route (EPIC-9.8).",
    )


class BuildDispatchResponse(BaseModel):
    """Stub payload returned by ``build_dispatch``."""

    model_config = ConfigDict(extra="forbid")

    project_id: str
    directive_id: str
    accepted: bool


@register_tool(
    name="build_dispatch",
    input_model=BuildDispatchInput,
    story="STORY-7.2.2",
    description="Orchestrator dispatches a directive to Build via MCP, carrying the locked pipeline version.",
    tags=("build", "dispatch"),
)
def build_dispatch(payload: BuildDispatchInput) -> ToolResponse:
    """Stub: acknowledges the directive but does not enqueue. TODO STORY-7.2.2: real implementation."""
    directive_id = f"dir_{uuid4().hex[:12]}"
    logger.info(
        "mcp_tool_call",
        extra={"tool": "build_dispatch", "project_id": payload.project_id, "actor": "orchestrator"},
    )
    result = BuildDispatchResponse(
        project_id=payload.project_id,
        directive_id=directive_id,
        accepted=False,
    )
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
