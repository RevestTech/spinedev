"""Standards / org-bundle MCP tools.

One tool today per ``EPIC-2.2`` / ``STORY-2.2.5`` — agents can query the active
org bundle mid-task to make policy-aware decisions:

* ``org_standards_get`` — return the standards slice for a given domain
  (e.g. ``"security"``, ``"banned_patterns"``, ``"approved_libs"``).

Real implementation reads from ``shared/standards/`` (lifted from TRON's
Standards Hierarchy by ``EPIC-2.4``); this is scaffolding only.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, ConfigDict, Field

from shared.mcp.schemas import ToolResponse
from shared.mcp.tools import register_tool

logger = logging.getLogger(__name__)


class OrgStandardsGetInput(BaseModel):
    """Inputs for ``org_standards_get``."""

    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(..., min_length=1)
    domain: str | None = Field(
        default=None,
        description="Optional slice: 'security' | 'standards' | 'banned_patterns' | 'approved_libs' | 'cost_caps' | etc.",
    )


class OrgStandardsResponse(BaseModel):
    """Stub payload returned by ``org_standards_get``."""

    model_config = ConfigDict(extra="forbid")

    project_id: str
    domain: str | None
    bundle_version: str
    standards: dict


@register_tool(
    name="org_standards_get",
    input_model=OrgStandardsGetInput,
    story="STORY-2.2.5",
    description="Return the active org-bundle standards slice for the given domain.",
    tags=("standards",),
)
def org_standards_get(payload: OrgStandardsGetInput) -> ToolResponse:
    """Stub: returns an empty standards bundle. TODO STORY-2.2.5: real implementation."""
    logger.info(
        "mcp_tool_call",
        extra={"tool": "org_standards_get", "project_id": payload.project_id, "actor": "agent"},
    )
    result = OrgStandardsResponse(
        project_id=payload.project_id,
        domain=payload.domain,
        bundle_version="0.0.0-stub",
        standards={},
    )
    return ToolResponse(status="stub_implementation", data=result.model_dump(mode="json"))


__all__: list[str] = ["OrgStandardsGetInput", "OrgStandardsResponse", "org_standards_get"]
