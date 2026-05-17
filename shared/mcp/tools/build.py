"""Build subsystem MCP tools.

Two front-door tools (REQ-INIT-7 FR-2 / FR-3, EPIC-7.2 / EPIC-7.4):

* ``build_dispatch``  — orchestrator hands a directive to Build with the
  locked pipeline version (STORY-7.2.2). Synthesizes a typed Build Brief
  from the project's validated PRD and persists it to
  ``project.metadata.build_brief``. The brief is the structured handoff
  to an external implementer (human or LLM) — Spine plans, the
  implementer builds, Spine ingests + verifies.
* ``build_completed`` — implementer reports completion with a typed
  ``BuildArtifact`` (STORY-7.2.3). Validates via the schema's own
  refuse-to-seal validator, persists to ``project.metadata.build_artifact``,
  and appends a ``build_history`` entry so multi-attempt builds leave a
  trail. Does NOT advance the phase — the orchestrator owns transitions.

Both tools are thin wrappers around ``build.runtime.build_dispatcher``;
this module is the MCP boundary (Pydantic input/output models + error
envelopes) and nothing else. Same pattern as
``shared/mcp/tools/plan.py:plan_dispatch``.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from shared.mcp.schemas import ToolError, ToolResponse
from shared.mcp.tools import register_tool

logger = logging.getLogger(__name__)


# ── Input / response models ────────────────────────────────────────────


class BuildDispatchInput(BaseModel):
    """Inputs for ``build_dispatch`` (REQ-INIT-7 FR-2)."""

    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(..., min_length=1,
                            description="BIGINT project id, project_uuid, or project name.")
    pipeline_version: str = Field(..., min_length=1,
                                  description="Locked sdlc-pipeline.yaml version (EPIC-1.7.5).")
    actor: str = Field(default="orchestrator", min_length=1,
                       description="Role/user driving the dispatch (audit attribution).")


class BuildDispatchResponse(BaseModel):
    """``ToolResponse.data`` payload for ``build_dispatch``."""

    model_config = ConfigDict(extra="forbid")

    project_id: str
    brief_id: str
    engineering_goals_count: int
    warnings: list[str] = Field(default_factory=list)
    audit_event_count: int = 0


class BuildCompletedInput(BaseModel):
    """Inputs for ``build_completed`` (REQ-INIT-7 FR-3, EPIC-7.4)."""

    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(..., min_length=1)
    artifact: dict[str, Any] = Field(
        ...,
        description="Serialized BuildArtifact JSON (validated via BuildArtifact.model_validate).",
    )
    actor: str = Field(default="build", min_length=1)


class BuildCompletedResponse(BaseModel):
    """``ToolResponse.data`` payload for ``build_completed``."""

    model_config = ConfigDict(extra="forbid")

    project_id: str
    artifact_uuid: str
    artifact_hash: str
    code_changes_count: int
    ready_for_verify: bool
    history_length: int
    audit_event_count: int = 0


def _error(code: str, message: str, *, retryable: bool = False) -> ToolResponse:
    return ToolResponse(status="error", data={}, error=ToolError(
        code=code, message=message, retryable=retryable,
    ))


# ── build_dispatch ─────────────────────────────────────────────────────


@register_tool(
    name="build_dispatch",
    input_model=BuildDispatchInput,
    story="STORY-7.2.2",
    description="Synthesize + persist a Build Brief for a project from its validated PRD.",
    tags=("build", "dispatch"),
)
def build_dispatch(payload: BuildDispatchInput) -> ToolResponse:
    """Run the dispatcher; surface structured errors when the PRD isn't ready."""
    logger.info("mcp_tool_call", extra={
        "tool": "build_dispatch", "project_id": payload.project_id,
        "actor": payload.actor,
    })

    # Late import — keeps the module importable when build_runtime deps are
    # absent (e.g. PRDv1 import path broken on a half-installed checkout).
    try:
        from build.runtime.build_dispatcher import (
            BuildDispatchError, dispatch_build,
        )
    except Exception as exc:  # noqa: BLE001
        return _error("build_runtime_unavailable",
                      f"build.runtime.build_dispatcher import failed: {exc}")

    try:
        result = dispatch_build(payload.project_id, actor=payload.actor)
    except BuildDispatchError as exc:
        return _error(exc.reason, str(exc))
    except RuntimeError as exc:
        # Project not found / DB issues land here.
        return _error("build_dispatch_failed", str(exc), retryable=True)
    except Exception as exc:  # noqa: BLE001
        return _error("build_dispatch_failed",
                      f"{exc.__class__.__name__}: {exc}", retryable=False)

    return ToolResponse(status="ok", data=BuildDispatchResponse(
        project_id=payload.project_id,
        brief_id=result.brief_id,
        engineering_goals_count=result.engineering_goals_count,
        warnings=result.warnings,
        audit_event_count=result.audit_event_count,
    ).model_dump(mode="json"))


# ── build_completed ────────────────────────────────────────────────────


@register_tool(
    name="build_completed",
    input_model=BuildCompletedInput,
    story="STORY-7.2.3",
    description="Ingest a typed BuildArtifact reported by an implementer; ready it for verify.",
    tags=("build", "completion"),
)
def build_completed(payload: BuildCompletedInput) -> ToolResponse:
    """Validate + persist the artifact; never advance the phase."""
    logger.info("mcp_tool_call", extra={
        "tool": "build_completed", "project_id": payload.project_id,
        "actor": payload.actor,
    })

    try:
        from build.runtime.build_dispatcher import (
            BuildCompletionError, ingest_build_artifact,
        )
    except Exception as exc:  # noqa: BLE001
        return _error("build_runtime_unavailable",
                      f"build.runtime.build_dispatcher import failed: {exc}")

    try:
        result = ingest_build_artifact(
            payload.project_id, payload.artifact, actor=payload.actor,
        )
    except BuildCompletionError as exc:
        return _error(exc.reason, str(exc))
    except RuntimeError as exc:
        return _error("build_completed_failed", str(exc), retryable=True)
    except Exception as exc:  # noqa: BLE001
        return _error("build_completed_failed",
                      f"{exc.__class__.__name__}: {exc}", retryable=False)

    return ToolResponse(status="ok", data=BuildCompletedResponse(
        project_id=payload.project_id,
        artifact_uuid=result.artifact_uuid,
        artifact_hash=result.artifact_hash,
        code_changes_count=result.code_changes_count,
        ready_for_verify=result.ready_for_verify,
        history_length=result.history_length,
        audit_event_count=result.audit_event_count,
    ).model_dump(mode="json"))


__all__: list[str] = [
    "BuildCompletedInput",
    "BuildCompletedResponse",
    "BuildDispatchInput",
    "BuildDispatchResponse",
    "build_completed",
    "build_dispatch",
]
