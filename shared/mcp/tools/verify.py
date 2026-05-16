"""Verify subsystem MCP tools.

Two tools today per REQ-INIT-8 FR-4 / FR-5 and ``EPIC-8.4`` / ``EPIC-8.5``:

* ``verify_audit`` — orchestrator hands a ``BuildArtifact`` + ``Blueprint`` to
  Verify; returns ``VerifyFindings`` (``STORY-8.5.1``).
* ``iso_invoke``   — individually-addressable ISO agent for early-detect during
  Build (``STORY-8.6.1``).

Real implementations delegate to TRON's ``AuditManager`` per FR-4; this is
scaffolding only.
"""

from __future__ import annotations

import logging
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from shared.mcp.schemas import ToolResponse
from shared.mcp.tools import register_tool

logger = logging.getLogger(__name__)


class VerifyAuditInput(BaseModel):
    """Inputs for ``verify_audit`` (REQ-INIT-8 FR-4)."""

    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(..., min_length=1)
    artifact_ref: str = Field(..., min_length=1, description="Pointer / ID of the BuildArtifact under verification.")
    scope: dict = Field(
        default_factory=dict,
        description="Blueprint scope: file patterns, check types, ISO agent selection, NOT_IN_SCOPE.",
    )
    pipeline_version: str = Field(..., min_length=1)


class VerifyAuditResponse(BaseModel):
    """Stub payload returned by ``verify_audit``."""

    model_config = ConfigDict(extra="forbid")

    project_id: str
    audit_run_id: str
    findings_count: int
    overall_pass: bool | None


@register_tool(
    name="verify_audit",
    input_model=VerifyAuditInput,
    story="STORY-8.5.1",
    description="Orchestrator invokes Verify on a BuildArtifact; returns VerifyFindings.",
    tags=("verify", "audit"),
)
def verify_audit(payload: VerifyAuditInput) -> ToolResponse:
    """Stub: returns an empty findings envelope. TODO STORY-8.5.1: delegate to TRON AuditManager."""
    audit_run_id = f"audit_{uuid4().hex[:12]}"
    logger.info(
        "mcp_tool_call",
        extra={"tool": "verify_audit", "project_id": payload.project_id, "actor": "orchestrator"},
    )
    result = VerifyAuditResponse(
        project_id=payload.project_id,
        audit_run_id=audit_run_id,
        findings_count=0,
        overall_pass=None,
    )
    return ToolResponse(status="stub_implementation", data=result.model_dump(mode="json"))


class IsoInvokeInput(BaseModel):
    """Inputs for ``iso_invoke`` (REQ-INIT-8 FR-5)."""

    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(..., min_length=1)
    agent_name: str = Field(..., min_length=1, description="ISO agent name, e.g. 'SecurityISO', 'QAISO'.")
    code_region: str = Field(..., min_length=1, description="file:lines or symbol scoping the invocation.")
    blueprint: dict = Field(default_factory=dict, description="Optional blueprint overrides for this single agent.")


class IsoInvokeResponse(BaseModel):
    """Stub payload returned by ``iso_invoke``."""

    model_config = ConfigDict(extra="forbid")

    project_id: str
    agent_name: str
    findings: list[dict]


@register_tool(
    name="iso_invoke",
    input_model=IsoInvokeInput,
    story="STORY-8.6.1",
    description="Invoke a single TRON ISO agent (e.g. SecurityISO) from Build for early-detect.",
    tags=("verify", "iso"),
)
def iso_invoke(payload: IsoInvokeInput) -> ToolResponse:
    """Stub: returns an empty findings list. TODO STORY-8.6.1: real implementation."""
    logger.info(
        "mcp_tool_call",
        extra={"tool": "iso_invoke", "project_id": payload.project_id, "actor": "build"},
    )
    result = IsoInvokeResponse(
        project_id=payload.project_id,
        agent_name=payload.agent_name,
        findings=[],
    )
    return ToolResponse(status="stub_implementation", data=result.model_dump(mode="json"))


__all__: list[str] = [
    "IsoInvokeInput",
    "IsoInvokeResponse",
    "VerifyAuditInput",
    "VerifyAuditResponse",
    "iso_invoke",
    "verify_audit",
]
