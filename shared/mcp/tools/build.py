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
    role: str = Field(default="build", min_length=1,
                      description="Target build role (router.sh sends engineer/devops/etc.).")
    directive: str = Field(default="SYNTHESIZE_BRIEF", min_length=1,
                           description="SYNTHESIZE_BRIEF for legacy brief handoff; PRODUCE_CODE/REMEDIATE for hub runners.")
    actor: str | None = Field(
        default=None,
        description="Audit attribution; defaults to ``role`` when omitted.",
    )
    extra_context: str | None = Field(
        default=None,
        description="Optional feedback block for engineer fix-loop dispatches.",
    )


class BuildDispatchResponse(BaseModel):
    """``ToolResponse.data`` payload for ``build_dispatch``."""

    model_config = ConfigDict(extra="forbid")

    project_id: str
    brief_id: str | None = None
    directive_id: str | None = None
    role: str | None = None
    result_kind: str | None = None
    artifact_key: str | None = None
    artifact_md: str | None = None
    engineering_goals_count: int = 0
    warnings: list[str] = Field(default_factory=list)
    audit_event_count: int = 0
    extra: dict[str, Any] = Field(default_factory=dict)


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

_HUB_BUILD_DIRECTIVES = (
    "PRODUCE_CODE", "REMEDIATE", "INSTALL", "CODE_REVIEW", "DEPLOY",
    "INSTALL_AND_SMOKE", "REMEDIATE_FROM_REVIEW", "DEPLOY_LOCAL",
    "EXECUTE_QA", "RUN_TESTS", "OPERATE",
)
_HUB_BUILD_ROLES = frozenset({
    "engineer", "devops", "devops_release", "security_engineer", "auditor", "qa",
})
_BRIEF_DIRECTIVES = frozenset({
    "SYNTHESIZE_BRIEF", "DISPATCH_BRIEF",
    # V3 B4: opt-in bounded-retrieval entry point. Routes through
    # build.runtime.build_dispatcher.dispatch_build_bounded, which
    # persists a minimal seed brief under METADATA_BRIEF_MINIMAL_KEY
    # instead of the fat brief. The fat-brief paths above are
    # unchanged so existing callers do not regress.
    "SYNTHESIZE_MINIMAL_BRIEF", "DISPATCH_MINIMAL_BRIEF",
})

_MINIMAL_BRIEF_DIRECTIVES = frozenset({
    "SYNTHESIZE_MINIMAL_BRIEF", "DISPATCH_MINIMAL_BRIEF",
})
"""Directives that route to the B4 bounded-retrieval path."""


def _uses_hub_build_runner(payload: BuildDispatchInput) -> bool:
    upper = payload.directive.upper()
    if upper in _BRIEF_DIRECTIVES:
        return False
    return payload.role in _HUB_BUILD_ROLES and any(tok in upper for tok in _HUB_BUILD_DIRECTIVES)


@register_tool(
    name="build_dispatch",
    input_model=BuildDispatchInput,
    story="STORY-7.2.2",
    description="Synthesize + persist a Build Brief for a project from its validated PRD.",
    tags=("build", "dispatch"),
)
def build_dispatch(payload: BuildDispatchInput) -> ToolResponse:
    """Hub role dispatch or legacy build-brief synthesis."""
    actor = payload.actor or payload.role
    logger.info("mcp_tool_call", extra={
        "tool": "build_dispatch", "project_id": payload.project_id,
        "role": payload.role, "actor": actor, "directive": payload.directive,
    })

    if _uses_hub_build_runner(payload):
        try:
            from build.runtime.hub_role_runner import run_build_hub_role  # noqa: PLC0415
        except Exception as exc:  # noqa: BLE001
            return _error("build_runtime_unavailable",
                          f"build.runtime.hub_role_runner import failed: {exc}")
        result = run_build_hub_role(
            project_id=payload.project_id,
            role=payload.role,
            directive=payload.directive,
            actor=actor,
            extra_context=payload.extra_context or "",
        )
        if not result.ok:
            return _error(
                result.error_class or "build_role_failed",
                result.error_message or f"{payload.role} dispatch failed",
            )
        return ToolResponse(status="ok", data=BuildDispatchResponse(
            project_id=payload.project_id,
            brief_id=None,
            directive_id=result.directive_id,
            role=result.role,
            result_kind=result.result_kind,
            artifact_key=result.artifact_key,
            artifact_md=result.artifact_md,
            extra=result.extra,
        ).model_dump(mode="json"))

    # Legacy build-brief path (plan_approved → engineer handoff document)
    # OR V3 B4 bounded-retrieval path when directive is in
    # _MINIMAL_BRIEF_DIRECTIVES. Both flow through the same response
    # shape so callers can swap directives without refactoring.
    try:
        from build.runtime.build_dispatcher import (  # noqa: PLC0415
            BuildDispatchError,
            dispatch_build,
            dispatch_build_bounded,
        )
    except Exception as exc:  # noqa: BLE001
        return _error("build_runtime_unavailable",
                      f"build.runtime.build_dispatcher import failed: {exc}")

    use_bounded = payload.directive.upper() in _MINIMAL_BRIEF_DIRECTIVES

    try:
        if use_bounded:
            result = dispatch_build_bounded(payload.project_id, actor=actor)
        else:
            result = dispatch_build(payload.project_id, actor=actor)
    except BuildDispatchError as exc:
        return _error(exc.reason, str(exc))
    except RuntimeError as exc:
        return _error("build_dispatch_failed", str(exc), retryable=True)
    except Exception as exc:  # noqa: BLE001
        return _error("build_dispatch_failed",
                      f"{exc.__class__.__name__}: {exc}", retryable=False)

    return ToolResponse(
        status="ok",
        # V3 #30a observation envelope: bounded path surfaces summary
        # and next_actions so callers (orchestrator / role daemons) can
        # branch on the dispatch mode without re-parsing data.
        summary=(
            f"minimal brief {result.brief_id} dispatched with "
            f"{result.engineering_goals_count} top engineering goal(s)"
            if use_bounded
            else f"build brief {result.brief_id} dispatched"
        ),
        next_actions=(
            [
                "build_completed when implementer reports back",
                # Roles signalling needs back must use the bounded-
                # retrieval need: prefix (see V3 B4).
                "engineer.read_minimal_brief",
            ]
            if use_bounded
            else ["build_completed when implementer reports back"]
        ),
        data=BuildDispatchResponse(
            project_id=payload.project_id,
            brief_id=result.brief_id,
            engineering_goals_count=result.engineering_goals_count,
            warnings=result.warnings,
            audit_event_count=result.audit_event_count,
        ).model_dump(mode="json"),
    )


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
