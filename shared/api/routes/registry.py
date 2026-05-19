"""``/api/v2/registry`` — Master role + integration registry (#3 + #8).

Two surfaces collapsed under one prefix because they're both *catalog*
reads driven by the same bundle metadata:

* ``GET /api/v2/registry/roles``        — Master roles + project-level roles
* ``GET /api/v2/registry/integrations`` — External integrations (GitHub, Linear, …)

These are read-only; the SPA renders them in the Hub's "registry" tab.
Mutations live under ``vault_config`` / ``integrations`` / ``federation``.

Wave 3.5 FIX3 (per W3-part-2 SPA `master-roles` panel feedback):
``RoleEntry`` is enriched with three runtime fields — ``status``,
``last_decision_card_pushed_at``, ``current_responsibility`` — joined
from ``spine_audit.audit_event`` (latest event per role) and
``spine_lifecycle.route_history`` (open directives per role). The join
is read-only; no schema changes. The SPA stops rendering placeholders
and starts showing real values.

Dependencies: ``fastapi``, ``pydantic`` (already required).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated, Any, Literal, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from shared.api.dependencies import DbHandle, current_user, get_db_pool
from shared.identity.models import User

logger = logging.getLogger("spine.api.registry")
router = APIRouter(prefix="/api/v2/registry", tags=["registry"])

RoleTier = Literal["master", "project"]
RoleStatus = Literal["active", "idle", "paused"]


class RoleEntry(BaseModel):
    """One catalog entry — a role known to the Hub bundle.

    Wave 3.5 FIX3 added the runtime trio so the SPA's master-roles panel
    can stop rendering placeholders. ``status``, ``last_decision_card_
    pushed_at`` and ``current_responsibility`` are derived from
    ``spine_audit.audit_event`` + ``spine_lifecycle.route_history`` —
    no extra schema. They are ``None`` when the join returns nothing
    (e.g. brand-new Hub with zero audit events) so the field stays
    backward-compatible.
    """

    model_config = ConfigDict(extra="forbid")
    name: str = Field(..., min_length=1)
    tier: RoleTier
    description: str = Field(default="", max_length=4_000)
    charter_ref: Optional[str] = None
    feature_flag: Optional[str] = None
    # Runtime fields (FIX3) ----------------------------------------------
    status: Optional[RoleStatus] = None
    last_decision_card_pushed_at: Optional[datetime] = None
    current_responsibility: Optional[str] = None


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


# ---------------------------------------------------------------------------
# Runtime enrichment (FIX3)
# ---------------------------------------------------------------------------


#: SQL the SPA's master-roles panel ultimately drives. Joins:
#:   * latest ``spine_audit.audit_event`` per role → pushed_at + status
#:     proxy (action ``decision_card_pushed`` ⇒ ``last_decision_card_
#:     pushed_at``; presence of a recent event ⇒ ``active``)
#:   * latest OPEN ``spine_lifecycle.route_history`` per role →
#:     ``current_responsibility`` (the directive_ref the role is mid-flight on)
#:
#: We do two cheap aggregations rather than one heavy CTE so each part
#: degrades independently if its source schema is empty (fresh install).
_LATEST_AUDIT_PER_ROLE_SQL = """
SELECT role,
       MAX(ts) AS last_ts,
       MAX(ts) FILTER (WHERE action = 'decision_card_pushed') AS last_pushed_at
FROM   spine_audit.audit_event
WHERE  role IS NOT NULL
GROUP  BY role;
"""

_OPEN_DIRECTIVE_PER_ROLE_SQL = """
SELECT DISTINCT ON (role) role, directive_ref, dispatched_at
FROM   spine_lifecycle.route_history
WHERE  completed_at IS NULL
ORDER  BY role, dispatched_at DESC;
"""

#: A role is treated as ``active`` if its newest audit event is within the
#: last hour; ``idle`` otherwise. ``paused`` is reserved for an explicit
#: pause event the bundle policy may emit in Wave 4. The SPA only cares
#: about the trichotomy so the threshold lives here, not in SQL.
_ACTIVE_WINDOW_SECONDS = 60 * 60


def _derive_status(last_ts: Optional[datetime]) -> Optional[RoleStatus]:
    """Map ``last_ts`` to the active/idle/paused trichotomy."""
    if last_ts is None:
        return None
    from datetime import datetime as _dt, timezone as _tz  # noqa: PLC0415

    now = _dt.now(tz=_tz.utc)
    # ``last_ts`` is asyncpg → already TZ-aware (TIMESTAMPTZ). Coerce defensively.
    if last_ts.tzinfo is None:
        last_ts = last_ts.replace(tzinfo=_tz.utc)
    delta = (now - last_ts).total_seconds()
    if delta < 0 or delta <= _ACTIVE_WINDOW_SECONDS:
        return "active"
    return "idle"


async def _fetch_runtime_by_role(db: DbHandle) -> dict[str, dict[str, Any]]:
    """Return a ``{role_name: {status, last_pushed_at, responsibility}}`` map.

    Falls back to ``{}`` on any DB error so the route degrades to the
    static catalog when Postgres is unreachable (test envs, bootstrap,
    DR window). Per #25 the route still requires a valid OIDC user; we
    just stop adding the enrichment fields.
    """
    out: dict[str, dict[str, Any]] = {}
    try:
        rows_audit = await db.fetch_rows(_LATEST_AUDIT_PER_ROLE_SQL)
    except Exception as exc:  # noqa: BLE001 — fail-soft
        logger.debug("registry.runtime.audit_unavailable", extra={"err": str(exc)})
        rows_audit = []
    for r in rows_audit:
        role = str(r.get("role") or "")
        if not role:
            continue
        out.setdefault(role, {})
        out[role]["status"] = _derive_status(r.get("last_ts"))
        out[role]["last_decision_card_pushed_at"] = r.get("last_pushed_at")
    try:
        rows_directive = await db.fetch_rows(_OPEN_DIRECTIVE_PER_ROLE_SQL)
    except Exception as exc:  # noqa: BLE001 — fail-soft
        logger.debug("registry.runtime.directive_unavailable", extra={"err": str(exc)})
        rows_directive = []
    for r in rows_directive:
        role = str(r.get("role") or "")
        if not role:
            continue
        out.setdefault(role, {})
        out[role]["current_responsibility"] = r.get("directive_ref")
    return out


def _enrich(entries: tuple[RoleEntry, ...], runtime: dict[str, dict[str, Any]]) -> list[RoleEntry]:
    """Stamp the runtime trio onto every static role catalog entry."""
    enriched: list[RoleEntry] = []
    for entry in entries:
        extra = runtime.get(entry.name)
        if not extra:
            enriched.append(entry)
            continue
        enriched.append(entry.model_copy(update={
            "status": extra.get("status"),
            "last_decision_card_pushed_at": extra.get("last_decision_card_pushed_at"),
            "current_responsibility": extra.get("current_responsibility"),
        }))
    return enriched


@router.get("/roles", response_model=RoleList)
async def list_roles(
    user: Annotated[User, Depends(current_user)],
    db: Annotated[DbHandle, Depends(get_db_pool)],
) -> RoleList:
    """Return Master + project-level roles known to this Hub.

    Wave 3.5 FIX3: each entry carries a runtime trio sourced from
    ``spine_audit.audit_event`` + ``spine_lifecycle.route_history``.
    Read-only; fail-soft (returns the static catalog if the DB is
    unreachable).
    """
    runtime = await _fetch_runtime_by_role(db)
    items = _enrich(_MASTER_ROLES, runtime) + _enrich(_PROJECT_ROLES, runtime)
    return RoleList(items=items)


@router.get("/integrations", response_model=IntegrationList)
async def list_integrations(
    user: Annotated[User, Depends(current_user)],
) -> IntegrationList:
    """Return the integration catalog."""
    return IntegrationList(items=list(_INTEGRATIONS))


class WhoamiResponse(BaseModel):
    """SPA session probe payload."""
    ok: bool
    user: dict[str, Any]


@router.get("/me", response_model=WhoamiResponse)
async def whoami(
    user: Annotated[User, Depends(current_user)],
) -> WhoamiResponse:
    """Session probe consumed by the SPA's +layout.ts. Returns the
    authenticated user; in dev mode this is the synthetic dev user from
    ``shared.identity.middleware.current_user``."""
    return WhoamiResponse(
        ok=True,
        user={
            "sub": user.id,
            "username": user.username or user.id,
            "email": user.email,
            "roles": user.roles,
            "hub_id": None,
        },
    )


__all__ = [
    "router",
    "RoleEntry",
    "RoleStatus",
    "IntegrationEntry",
    "RoleList",
    "IntegrationList",
]
