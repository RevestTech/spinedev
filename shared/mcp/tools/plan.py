"""Plan subsystem MCP tools.

One tool today per REQ-INIT-9 FR-5 / ``EPIC-9.4`` / ``STORY-9.4.1``:

* ``plan_dispatch`` — orchestrator hands a directive to Plan with the
  locked pipeline version.

Real implementation lands in ``STORY-9.4.1``; this is scaffolding only.
"""

from __future__ import annotations

import logging
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from shared.mcp.schemas import ToolResponse
from shared.mcp.tools import register_tool

logger = logging.getLogger(__name__)


class PlanDispatchInput(BaseModel):
    """Inputs for ``plan_dispatch`` (REQ-INIT-9 FR-5)."""

    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(..., min_length=1)
    phase: str = Field(..., min_length=1, description="Plan phase to enter (e.g. 'plan_in_progress').")
    directive: str = Field(..., min_length=1, description="Directive body handed to the Plan subsystem.")
    pipeline_version: str = Field(
        ...,
        min_length=1,
        description="Locked sdlc-pipeline.yaml version (EPIC-1.7.5) carried with the dispatch.",
    )


class PlanDispatchResponse(BaseModel):
    """Stub payload returned by ``plan_dispatch``."""

    model_config = ConfigDict(extra="forbid")

    project_id: str
    directive_id: str
    accepted: bool


@register_tool(
    name="plan_dispatch",
    input_model=PlanDispatchInput,
    story="STORY-9.4.1",
    description="Orchestrator hands a directive to the Plan subsystem via MCP.",
    tags=("plan", "dispatch"),
)
def plan_dispatch(payload: PlanDispatchInput) -> ToolResponse:
    """Stub: acknowledges the directive but does not enqueue. TODO STORY-9.4.1: real implementation."""
    directive_id = f"dir_{uuid4().hex[:12]}"
    logger.info(
        "mcp_tool_call",
        extra={"tool": "plan_dispatch", "project_id": payload.project_id, "actor": "orchestrator"},
    )
    result = PlanDispatchResponse(
        project_id=payload.project_id,
        directive_id=directive_id,
        accepted=False,
    )
    return ToolResponse(status="stub_implementation", data=result.model_dump(mode="json"))


__all__: list[str] = ["PlanDispatchInput", "PlanDispatchResponse", "plan_dispatch"]
