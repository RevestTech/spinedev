"""Plan subsystem MCP tools.

Today: a single front-door — ``plan_dispatch`` — that the orchestrator
calls when a project enters ``plan_in_progress``. It hands off to
``plan.runtime.intake_runner.run_intake`` which drives the interactive
intake template and synthesizes a draft PRD.

The MCP server is process-isolated from the user's shell. Without a tty
we can't run an `input()` loop, so the dispatch tool detects the
non-interactive case and returns a friendly error directing the user to
``spine intake <id>`` (which spawns the in-process Python transport with
the parent shell's stdin attached).

REQ-INIT-9 FR-5 / EPIC-9.4 / STORY-9.4.1.
"""

from __future__ import annotations

import logging
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from shared.mcp.schemas import ToolError, ToolResponse
from shared.mcp.tools import register_tool

logger = logging.getLogger(__name__)


class PlanDispatchInput(BaseModel):
    """Inputs for ``plan_dispatch`` (REQ-INIT-9 FR-5)."""

    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(..., min_length=1,
                            description="BIGINT project id or project name.")
    phase: str = Field(..., min_length=1,
                       description="Plan phase to enter (currently only 'plan_in_progress').")
    directive: str = Field(..., min_length=1,
                           description="Directive body handed to the Plan subsystem.")
    pipeline_version: str = Field(..., min_length=1,
                                  description="Locked sdlc-pipeline.yaml version (EPIC-1.7.5).")
    template: str | None = Field(
        default=None,
        description="Intake template name; if omitted the runner picks via project_type/metadata.",
    )
    actor: str = Field(default="product", min_length=1,
                       description="Role/user driving the dispatch (audit attribution).")


class PlanDispatchResponse(BaseModel):
    """``ToolResponse.data`` payload for ``plan_dispatch``."""

    model_config = ConfigDict(extra="forbid")

    project_id: str
    directive_id: str
    accepted: bool
    template: str | None = None
    answer_count: int = 0
    prd_valid: bool = False
    prd_fields_populated: int = 0
    audit_event_count: int = 0


def _error(code: str, message: str, *, retryable: bool = False) -> ToolResponse:
    return ToolResponse(status="error", data={}, error=ToolError(
        code=code, message=message, retryable=retryable,
    ))


@register_tool(
    name="plan_dispatch",
    input_model=PlanDispatchInput,
    story="STORY-9.4.1",
    description="Run the plan-phase intake loop for a project and persist a draft PRD.",
    tags=("plan", "dispatch", "intake"),
)
def plan_dispatch(payload: PlanDispatchInput) -> ToolResponse:
    """Drive intake_runner if a tty is available; otherwise surface a guidance error."""
    directive_id = f"dir_{uuid4().hex[:12]}"
    logger.info("mcp_tool_call", extra={
        "tool": "plan_dispatch", "project_id": payload.project_id,
        "actor": payload.actor,
    })

    # Late import — keeps the module importable when plan_runtime deps are
    # absent (e.g. PyYAML missing on a fresh checkout before `make install`).
    try:
        from plan.runtime.intake_runner import (
            IntakeNotInteractive, IntakeTemplateNotFound, run_intake,
        )
    except Exception as exc:  # noqa: BLE001
        return _error("plan_runtime_unavailable",
                      f"plan.runtime.intake_runner import failed: {exc}")

    try:
        result = run_intake(
            payload.project_id, template=payload.template, actor=payload.actor,
        )
    except IntakeNotInteractive as exc:
        return _error("intake_requires_tty", str(exc))
    except IntakeTemplateNotFound as exc:
        return _error("intake_template_not_found", str(exc))
    except Exception as exc:  # noqa: BLE001
        return _error("intake_failed",
                      f"{exc.__class__.__name__}: {exc}", retryable=False)

    return ToolResponse(status="ok", data=PlanDispatchResponse(
        project_id=payload.project_id,
        directive_id=directive_id,
        accepted=True,
        template=result.template,
        answer_count=len(result.answers),
        prd_valid=result.prd_valid,
        prd_fields_populated=result.prd_fields_populated,
        audit_event_count=result.audit_event_count,
    ).model_dump(mode="json"))


__all__: list[str] = ["PlanDispatchInput", "PlanDispatchResponse", "plan_dispatch"]
