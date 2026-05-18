"""Spine v3 work-item type schemas — Design Decision #19.

Seven canonical work-item types ship Day 1: ``feature``, ``bug``,
``incident``, ``support``, ``refactor``, ``infra``, ``compliance``. Each
gets its own intake template + phase pipeline + role-charter
responsibilities + UX surface + integration set; this module provides the
typed *runtime* representation shared by intake, dispatcher and verify.

The base class :class:`WorkItem` carries the fields every type needs;
seven subclasses add the type-specific payload. ``work_item_type`` is a
discriminator so a generic ``BaseModel`` reader can route to the right
subclass via :func:`work_item_from_dict`.

Wave-2 Squad-2 deliverable. Companion to
``db/flyway/sql/V28__work_item_types.sql`` (which seeds the same seven
types in the registry) and the intake template YAMLs under
``plan/templates/intake/``.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Annotated, Any, Literal, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ── Canonical type enum (seed order matches V28) ───────────────────────

#: V28 seed order — must stay aligned with
#: ``spine_workitem.item_type`` ENUM in ``V28__work_item_types.sql``.
WorkItemType = Literal[
    "feature",
    "bug",
    "incident",
    "support",
    "refactor",
    "infra",
    "compliance",
]

#: Tuple form for iteration / contains-checks. Kept in sync with WorkItemType.
WORK_ITEM_TYPES: tuple[str, ...] = (
    "feature", "bug", "incident", "support", "refactor", "infra", "compliance",
)

Priority = Literal["P0", "P1", "P2", "P3"]
Severity = Literal["sev1", "sev2", "sev3", "sev4"]

_FORBID = ConfigDict(extra="forbid", str_strip_whitespace=True)


# ── Base class ─────────────────────────────────────────────────────────


class WorkItem(BaseModel):
    """Base class for all 7 work-item types.

    Carries the common fields every type needs. Subclasses set the
    ``work_item_type`` Literal to a single value and add type-specific
    payload fields.
    """

    model_config = _FORBID

    id: UUID = Field(default_factory=uuid4, description="Stable identifier for this work item.")
    work_item_type: WorkItemType = Field(..., description="One of the 7 canonical types.")
    title: Annotated[str, Field(min_length=1, max_length=300)]
    description: Annotated[str, Field(min_length=1, max_length=20_000)]
    priority: Priority = Field(default="P2", description="P0=critical … P3=nice-to-have.")
    created_by: Annotated[str, Field(min_length=1, description="Username or email of the creator.")]
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    project_id: Optional[str] = Field(
        default=None,
        description="Spine project UUID this work item belongs to (set on intake completion).",
    )
    labels: list[str] = Field(default_factory=list, description="Free-form classification tags.")
    source_ref: Optional[str] = Field(
        default=None,
        description="External system ref (GitHub issue URL, PagerDuty incident id, Zendesk ticket, etc.).",
    )

    @field_validator("created_at")
    @classmethod
    def _tz_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("WorkItem.created_at must be timezone-aware")
        return v


# ── Subclass 1/7 — feature ────────────────────────────────────────────


class FeatureWorkItem(WorkItem):
    """A new user-facing capability. Default pipeline = ``default_feature_pipeline``."""

    work_item_type: Literal["feature"] = "feature"

    target_users: Optional[str] = Field(
        default=None, description="Primary persona who hires this feature."
    )
    success_metric: Optional[str] = Field(
        default=None, description="How the team will know the feature is working post-launch."
    )
    must_should_could: Optional[str] = Field(
        default=None, description="Tiered scope description (MUST / SHOULD / COULD)."
    )


# ── Subclass 2/7 — bug ────────────────────────────────────────────────


class BugWorkItem(WorkItem):
    """A defect in shipped behaviour. Default pipeline = ``default_bug_pipeline``."""

    work_item_type: Literal["bug"] = "bug"

    severity: Severity = Field(..., description="sev1=outage/data-loss … sev4=cosmetic.")
    reproduction_steps: Annotated[str, Field(min_length=1, description="Numbered steps to reproduce.")]
    affected_versions: list[str] = Field(
        default_factory=list, description="Semver / build ids where this bug reproduces."
    )
    regression_of: Optional[str] = Field(
        default=None,
        description="If a regression, the prior issue id / PR / commit that introduced it.",
    )


# ── Subclass 3/7 — incident ───────────────────────────────────────────


class IncidentWorkItem(WorkItem):
    """A production outage / impairment. Default pipeline = ``default_incident_pipeline``."""

    work_item_type: Literal["incident"] = "incident"

    severity: Severity = Field(..., description="sev1=full outage … sev4=non-customer-visible.")
    blast_radius: Annotated[str, Field(min_length=1, description="Scope of impact (users / regions / surfaces).")]
    time_to_acknowledge: Optional[int] = Field(
        default=None, ge=0, description="Seconds from detect to ack; populated by paging integration."
    )
    root_cause_status: Literal["unknown", "suspected", "confirmed", "ruled_out"] = Field(
        default="unknown", description="Where the post-mortem currently stands."
    )


# ── Subclass 4/7 — support ────────────────────────────────────────────


class SupportWorkItem(WorkItem):
    """A customer-support request. Default pipeline = ``default_support_pipeline``."""

    work_item_type: Literal["support"] = "support"

    customer_id: Annotated[str, Field(min_length=1, description="Stable customer / account identifier.")]
    sla_target: Optional[str] = Field(
        default=None,
        description="Free-form SLA target the support tier promised (e.g. 'P1 1h ack / 8h resolve').",
    )
    escalated_from: Optional[str] = Field(
        default=None,
        description="Source channel / tier this ticket escalated from (e.g. 'tier1', 'zendesk').",
    )


# ── Subclass 5/7 — refactor ───────────────────────────────────────────


class RefactorWorkItem(WorkItem):
    """A non-functional code/structure improvement. Default pipeline = ``default_refactor_pipeline``."""

    work_item_type: Literal["refactor"] = "refactor"

    rationale: Annotated[str, Field(min_length=1, description="Why this refactor pays for itself.")]
    scope_summary: Annotated[str, Field(min_length=1, description="What is being changed (subsystem / pattern).")]
    performance_baseline: Optional[str] = Field(
        default=None,
        description="Current measured metric the refactor targets (latency p95, allocation rate, …).",
    )
    expected_improvement: Optional[str] = Field(
        default=None, description="Predicted post-refactor delta on the baseline metric."
    )


# ── Subclass 6/7 — infra ──────────────────────────────────────────────


class InfraWorkItem(WorkItem):
    """An infrastructure change (provisioning, capacity, networking, IAM).

    Default pipeline = ``default_infra_pipeline``."""

    work_item_type: Literal["infra"] = "infra"

    cloud_target: Annotated[str, Field(
        min_length=1,
        description="Cloud / region / cluster target (e.g. 'aws/us-east-1', 'gcp/europe-west2/prod-1').",
    )]
    cost_estimate: Optional[str] = Field(
        default=None, description="Monthly cost delta the change is expected to introduce (USD)."
    )
    blast_radius: Annotated[str, Field(min_length=1, description="What customer-visible surfaces this could affect.")]


# ── Subclass 7/7 — compliance ─────────────────────────────────────────


class ComplianceWorkItem(WorkItem):
    """A control / evidence / audit obligation. Default pipeline = ``default_compliance_pipeline``."""

    work_item_type: Literal["compliance"] = "compliance"

    framework: Annotated[str, Field(
        min_length=1, description="Compliance framework (SOC2, ISO27001, HIPAA, PCI-DSS, GDPR, …)."
    )]
    control_id: Annotated[str, Field(min_length=1, description="Framework-specific control identifier.")]
    evidence_required: list[str] = Field(
        default_factory=list, description="List of evidence artefacts to collect / attach."
    )
    audit_deadline: Optional[date] = Field(
        default=None, description="Hard date by which the control must show compliant."
    )


# ── Discriminator helper ───────────────────────────────────────────────


_TYPE_TO_CLASS: dict[str, type[WorkItem]] = {
    "feature": FeatureWorkItem,
    "bug": BugWorkItem,
    "incident": IncidentWorkItem,
    "support": SupportWorkItem,
    "refactor": RefactorWorkItem,
    "infra": InfraWorkItem,
    "compliance": ComplianceWorkItem,
}


def work_item_from_dict(payload: dict[str, Any]) -> WorkItem:
    """Route ``payload`` to the right subclass based on its ``work_item_type``.

    Raises ``KeyError`` if ``work_item_type`` is missing,
    ``ValueError`` (via Pydantic) if the value is not one of the 7.
    """
    t = payload.get("work_item_type")
    if t is None:
        raise KeyError("payload missing required field 'work_item_type'")
    try:
        cls = _TYPE_TO_CLASS[t]
    except KeyError as exc:
        raise ValueError(
            f"unknown work_item_type={t!r}; expected one of {list(_TYPE_TO_CLASS)}"
        ) from exc
    return cls.model_validate(payload)


__all__ = [
    "BugWorkItem",
    "ComplianceWorkItem",
    "FeatureWorkItem",
    "IncidentWorkItem",
    "InfraWorkItem",
    "Priority",
    "RefactorWorkItem",
    "Severity",
    "SupportWorkItem",
    "WORK_ITEM_TYPES",
    "WorkItem",
    "WorkItemType",
    "work_item_from_dict",
]
