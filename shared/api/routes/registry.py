"""``/api/v2/registry`` — Master role + integration registry (#3 + #8).

Two surfaces collapsed under one prefix because they're both *catalog*
reads driven by the same bundle metadata:

* ``GET /api/v2/registry/roles``        — Master roles + project-level roles
* ``GET /api/v2/registry/integrations`` — External integrations (GitHub, Linear, …)

These are read-only; the SPA renders them in the Hub's "registry" tab.
Mutations live under ``vault_config`` / ``integrations`` / ``federation``.

Dependencies: ``fastapi``, ``pydantic`` (already required).
"""

from __future__ import annotations

from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from shared.api.dependencies import current_user
from shared.identity.models import User

router = APIRouter(prefix="/api/v2/registry", tags=["registry"])

RoleTier = Literal["master", "project"]


class RoleEntry(BaseModel):
    """One catalog entry — a role known to the Hub bundle."""

    model_config = ConfigDict(extra="forbid")
    name: str = Field(..., min_length=1)
    tier: RoleTier
    description: str = Field(default="", max_length=4_000)
    charter_ref: Optional[str] = None
    feature_flag: Optional[str] = None


class IntegrationEntry(BaseModel):
    """One catalog entry — an external integration the Hub can configure."""

    model_config = ConfigDict(extra="forbid")
    name: str = Field(..., min_length=1)
    kind: Literal["scm", "issue_tracker", "comms", "incident", "grc", "cloud"]
    description: str = Field(default="", max_length=4_000)
    feature_flag: Optional[str] = None
    requires_vault_path: Optional[str] = None


class RoleList(BaseModel):
    """``GET /registry/roles`` envelope."""

    model_config = ConfigDict(extra="forbid")
    ok: bool = True
    items: list[RoleEntry]


class IntegrationList(BaseModel):
    """``GET /registry/integrations`` envelope."""

    model_config = ConfigDict(extra="forbid")
    ok: bool = True
    items: list[IntegrationEntry]


# ---------------------------------------------------------------------------
# Static catalog — Wave 4 sources this from the active bundle
# ---------------------------------------------------------------------------

_MASTER_ROLES: tuple[RoleEntry, ...] = (
    RoleEntry(name="director_engineering", tier="master", description="Master eng director"),
    RoleEntry(name="director_product", tier="master", description="Master product director"),
    RoleEntry(name="director_devops", tier="master", description="Master DevOps director (#11)"),
    RoleEntry(name="director_security", tier="master", description="Master security director"),
)
_PROJECT_ROLES: tuple[RoleEntry, ...] = (
    RoleEntry(name="architect", tier="project", description="System architecture"),
    RoleEntry(name="product", tier="project", description="Product manager"),
    RoleEntry(name="engineer", tier="project", description="Generalist engineer"),
    RoleEntry(name="qa", tier="project", description="Quality assurance", charter_ref="lib/role-prompts/qa.md"),
    RoleEntry(name="ux", tier="project", description="UX / design"),
    RoleEntry(name="operator", tier="project", description="Spine-internal ops (#11 distinct from devops)"),
    RoleEntry(name="devops", tier="project", description="Customer-facing devops (#11)", feature_flag="role_devops"),
    RoleEntry(name="datawright", tier="project", description="Data engineering"),
    RoleEntry(name="planner", tier="project", description="Planning / scrum master"),
    RoleEntry(name="conductor", tier="project", description="Squad conductor"),
    RoleEntry(name="release_manager", tier="project", description="Release coordination", feature_flag="role_release_manager"),
    RoleEntry(name="tech_writer", tier="project", description="Technical writing", feature_flag="role_tech_writer"),
    RoleEntry(name="security_engineer", tier="project", description="Security engineer", feature_flag="role_security_engineer"),
    RoleEntry(name="compliance_officer", tier="project", description="Compliance officer", feature_flag="role_compliance_officer"),
    RoleEntry(name="customer_support", tier="project", description="Customer support", feature_flag="role_customer_support"),
)

_INTEGRATIONS: tuple[IntegrationEntry, ...] = (
    IntegrationEntry(name="github", kind="scm", description="GitHub repo + Actions",
                     feature_flag="integration_github", requires_vault_path="spine/integrations/github/token"),
    IntegrationEntry(name="linear", kind="issue_tracker", description="Linear issue tracker",
                     feature_flag="integration_linear", requires_vault_path="spine/integrations/linear/api_key"),
    IntegrationEntry(name="jira", kind="issue_tracker", description="Atlassian Jira",
                     feature_flag="integration_jira", requires_vault_path="spine/integrations/jira/api_key"),
    IntegrationEntry(name="slack", kind="comms", description="Slack notifications + slash cmds",
                     feature_flag="channel_slack", requires_vault_path="spine/integrations/slack/bot_token"),
    IntegrationEntry(name="pagerduty", kind="incident", description="PagerDuty incident events",
                     feature_flag="channel_pagerduty", requires_vault_path="spine/integrations/pagerduty/routing_key"),
    IntegrationEntry(name="vanta", kind="grc", description="Vanta SOC 2 evidence push",
                     feature_flag="integration_vanta", requires_vault_path="spine/integrations/vanta/api_key"),
    IntegrationEntry(name="drata", kind="grc", description="Drata SOC 2 evidence push",
                     feature_flag="integration_drata", requires_vault_path="spine/integrations/drata/api_key"),
)


@router.get("/roles", response_model=RoleList)
async def list_roles(user: Annotated[User, Depends(current_user)]) -> RoleList:
    """Return Master + project-level roles known to this Hub."""
    return RoleList(items=list(_MASTER_ROLES) + list(_PROJECT_ROLES))


@router.get("/integrations", response_model=IntegrationList)
async def list_integrations(
    user: Annotated[User, Depends(current_user)],
) -> IntegrationList:
    """Return the integration catalog."""
    return IntegrationList(items=list(_INTEGRATIONS))


__all__ = [
    "router",
    "RoleEntry",
    "IntegrationEntry",
    "RoleList",
    "IntegrationList",
]
