"""Smart Spine learning MCP tools — Wave 4 Squad D / V3 #27.

Four tools:

  * ``learning_contribute`` — record a lesson + run the 3-tier gate
  * ``learning_query`` — paginated read of lessons by scope
  * ``learning_grant_cross_org_consent`` — flip a customer's cross-org
    consent (REQUIRES CITATION per V3 #12 — high-stakes data-sharing
    decision)
  * ``learning_revoke_cross_org_consent`` — revoke same; not citation-
    required (revocation is always safe)

The grant tool is the ONLY tool in this module tagged ``requires_
citation=True``. The MCP server middleware enforces the Cite-or-Refuse
contract on it — granting cross-org learning without supporting
evidence (org consent record, signed bundle, admin email, etc.) is
auto-refused with a 422.
"""
from __future__ import annotations

import logging
from typing import Any, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from shared.mcp.schemas import ToolError, ToolResponse
from shared.mcp.tools import register_tool

from learning.consent import (
    ConsentRecord,
    grant_cross_org_consent,
    list_cross_org_consents,
    revoke_cross_org_consent,
)
from learning.contribute import LessonPayload, contribute_lesson
from learning.scope import (
    KNOWN_DATA_CATEGORIES,
    LearningScope,
    ScopeContext,
    ScopePolicy,
)

logger = logging.getLogger(__name__)

_FORBID = ConfigDict(extra="forbid")


# ─── learning_contribute ─────────────────────────────────────────────


class LearningContributeInput(BaseModel):
    """Inputs for ``learning_contribute`` (V3 #27 Wave 4)."""
    model_config = _FORBID
    project_id: str = Field(..., min_length=1)
    actor: str = Field(default="learning", min_length=1)
    lesson_text: str = Field(..., min_length=1)
    source_audit_record_id: Optional[str] = Field(default=None)
    requested_scope: str = Field(
        default="project",
        description="project | within_hub | cross_org",
    )
    data_category: Optional[str] = Field(default=None)
    hub_id: Optional[str] = Field(default=None)
    # Optional bundle overlays from the org-bundle YAML.
    within_hub_enabled: Optional[bool] = Field(default=None)
    cross_org_default: Optional[bool] = Field(default=None)


class LearningContributeOutput(BaseModel):
    model_config = _FORBID
    granted_scope: str
    requested_scope: str
    reason: str
    written: dict[str, str]
    failed: dict[str, str]
    skipped: dict[str, str]
    audit_id: UUID


def _scope_from_str(s: str) -> LearningScope:
    try:
        return LearningScope(s)
    except ValueError as exc:
        raise ValueError(
            f"requested_scope {s!r} not in "
            f"{[v.value for v in LearningScope]}"
        ) from exc


@register_tool(
    name="learning_contribute",
    input_model=LearningContributeInput,
    story="WAVE-4-SQUAD-D",
    description="Record a lesson; runs the 3-tier Smart Spine scope gate.",
    tags=("learning",),
)
def learning_contribute(payload: LearningContributeInput) -> ToolResponse:
    """Apply the 3-tier scope gate, then write one row per permitted tier."""
    audit_id = uuid4()
    try:
        scope = _scope_from_str(payload.requested_scope)
    except ValueError as exc:
        return ToolResponse(
            status="error", audit_id=audit_id,
            error=ToolError(
                code="invalid_scope", message=str(exc), retryable=False,
            ),
        )
    ctx = ScopeContext(
        hub_id=payload.hub_id,
        project_id=payload.project_id,
        requested_scope=scope,
        data_category=payload.data_category,
        bundle_within_hub_enabled=payload.within_hub_enabled,
        bundle_cross_org_default=payload.cross_org_default,
    )
    lp = LessonPayload(
        lesson_text=payload.lesson_text,
        source_audit_record_id=payload.source_audit_record_id,
    )
    outcome = contribute_lesson(lp, ctx)
    decision = outcome.decision
    out = LearningContributeOutput(
        granted_scope=decision.resolved.granted_scope.value,
        requested_scope=decision.resolved.requested_scope.value,
        reason=decision.resolved.reason,
        written=outcome.written,
        failed=outcome.failed,
        skipped=dict(decision.skipped_reasons),
        audit_id=audit_id,
    )
    return ToolResponse(
        status="ok", audit_id=audit_id, data=out.model_dump(mode="json"),
    )


# ─── learning_query ──────────────────────────────────────────────────


class LearningQueryInput(BaseModel):
    model_config = _FORBID
    project_id: str = Field(..., min_length=1)
    actor: str = Field(default="learning", min_length=1)
    scope: Optional[str] = Field(
        default=None,
        description="project | within_hub | cross_org. None = all permitted.",
    )
    hub_id: Optional[str] = Field(default=None)
    limit: int = Field(default=20, ge=1, le=200)


class LearningQueryRow(BaseModel):
    model_config = _FORBID
    scope: str
    lesson_text: str
    source_audit_record_id: Optional[str] = None


class LearningQueryOutput(BaseModel):
    model_config = _FORBID
    rows: list[LearningQueryRow]
    audit_id: UUID
    note: str = ""


def _query_reader(
    project_id: str, scope: Optional[str], hub_id: Optional[str], limit: int,
) -> list[LearningQueryRow]:
    """Default reader — DB-free stub; Wave 5 wires the real psql path.

    The stub returns an empty list so the tool is callable in any
    environment (smoke test, laptop without DB) without raising.
    """
    return []


@register_tool(
    name="learning_query",
    input_model=LearningQueryInput,
    story="WAVE-4-SQUAD-D",
    description="Read lessons from spine_learning.lesson with scope filter.",
    tags=("learning",),
)
def learning_query(payload: LearningQueryInput) -> ToolResponse:
    audit_id = uuid4()
    if payload.scope is not None:
        try:
            _scope_from_str(payload.scope)
        except ValueError as exc:
            return ToolResponse(
                status="error", audit_id=audit_id,
                error=ToolError(
                    code="invalid_scope", message=str(exc), retryable=False,
                ),
            )
    rows = _query_reader(
        payload.project_id, payload.scope, payload.hub_id, payload.limit,
    )
    out = LearningQueryOutput(rows=rows, audit_id=audit_id,
                              note="reader stub — Wave 5 wires psql")
    return ToolResponse(
        status="ok", audit_id=audit_id, data=out.model_dump(mode="json"),
    )


# ─── learning_grant_cross_org_consent (requires_citation) ────────────


class LearningGrantConsentInput(BaseModel):
    """High-stakes — requires citation (V3 #12)."""
    model_config = _FORBID
    project_id: str = Field(..., min_length=1)
    actor: str = Field(default="admin", min_length=1)
    hub_id: Optional[str] = Field(default=None)
    target_project_id: Optional[str] = Field(default=None)
    cross_org_consent: bool = Field(default=True)
    granular: dict[str, bool] = Field(default_factory=dict)
    rationale: str = Field(default="", description="Admin-provided rationale")


class LearningGrantConsentOutput(BaseModel):
    model_config = _FORBID
    hub_id: Optional[str]
    project_id: Optional[str]
    operation: str
    cross_org_consent: bool
    granular: dict[str, bool]
    actor: str
    audit_id: UUID


@register_tool(
    name="learning_grant_cross_org_consent",
    input_model=LearningGrantConsentInput,
    story="WAVE-4-SQUAD-D",
    description="Grant cross-org learning consent. Requires citation (V3 #12).",
    tags=("learning", "consent"),
    requires_citation=True,
)
def learning_grant_cross_org_consent(
    payload: LearningGrantConsentInput,
) -> ToolResponse:
    """Flip the customer's cross-org consent on.

    Tagged ``requires_citation=True`` — the MCP server rejects calls
    that don't ship a non-empty ``citation`` list per V3 #12. Cite
    the org's consent record / signed bundle / admin email / etc.
    """
    audit_id = uuid4()
    # Validate granular keys are recognized; unknown ones are logged.
    for k in payload.granular:
        if k not in KNOWN_DATA_CATEGORIES:
            logger.info("learning_consent: non-canonical category=%s", k)
    record = ConsentRecord(
        hub_id=payload.hub_id,
        project_id=payload.target_project_id,
        cross_org_consent=payload.cross_org_consent,
        granular=dict(payload.granular),
        granted_by=payload.actor,
        rationale=payload.rationale,
    )
    try:
        decision = grant_cross_org_consent(record)
    except Exception as exc:  # noqa: BLE001
        return ToolResponse(
            status="error", audit_id=audit_id,
            error=ToolError(
                code="consent_write_failed",
                message=str(exc)[:300],
                retryable=True,
            ),
        )
    out = LearningGrantConsentOutput(
        hub_id=decision.hub_id,
        project_id=decision.project_id,
        operation=decision.operation,
        cross_org_consent=decision.effective_policy.cross_org_consent,
        granular=dict(decision.effective_policy.granular_consent),
        actor=decision.actor,
        audit_id=audit_id,
    )
    return ToolResponse(
        status="ok", audit_id=audit_id, data=out.model_dump(mode="json"),
    )


# ─── learning_revoke_cross_org_consent ───────────────────────────────


class LearningRevokeConsentInput(BaseModel):
    model_config = _FORBID
    project_id: str = Field(..., min_length=1)
    actor: str = Field(default="admin", min_length=1)
    hub_id: Optional[str] = Field(default=None)
    target_project_id: Optional[str] = Field(default=None)
    category: Optional[str] = Field(
        default=None,
        description=(
            "Single category to revoke; None revokes the entire scope."
        ),
    )
    rationale: str = Field(default="")


class LearningRevokeConsentOutput(BaseModel):
    model_config = _FORBID
    hub_id: Optional[str]
    project_id: Optional[str]
    operation: str
    cross_org_consent: bool
    granular: dict[str, bool]
    actor: str
    audit_id: UUID


@register_tool(
    name="learning_revoke_cross_org_consent",
    input_model=LearningRevokeConsentInput,
    story="WAVE-4-SQUAD-D",
    description="Revoke cross-org learning consent (full or per category).",
    tags=("learning", "consent"),
)
def learning_revoke_cross_org_consent(
    payload: LearningRevokeConsentInput,
) -> ToolResponse:
    """Revoke consent. Always safe → not citation-required."""
    audit_id = uuid4()
    try:
        decision = revoke_cross_org_consent(
            hub_id=payload.hub_id,
            project_id=payload.target_project_id,
            category=payload.category,
            actor=payload.actor,
            rationale=payload.rationale,
        )
    except Exception as exc:  # noqa: BLE001
        return ToolResponse(
            status="error", audit_id=audit_id,
            error=ToolError(
                code="consent_revoke_failed",
                message=str(exc)[:300],
                retryable=True,
            ),
        )
    out = LearningRevokeConsentOutput(
        hub_id=decision.hub_id,
        project_id=decision.project_id,
        operation=decision.operation,
        cross_org_consent=decision.effective_policy.cross_org_consent,
        granular=dict(decision.effective_policy.granular_consent),
        actor=decision.actor,
        audit_id=audit_id,
    )
    return ToolResponse(
        status="ok", audit_id=audit_id, data=out.model_dump(mode="json"),
    )


__all__ = [
    "LearningContributeInput",
    "LearningContributeOutput",
    "LearningGrantConsentInput",
    "LearningGrantConsentOutput",
    "LearningQueryInput",
    "LearningQueryOutput",
    "LearningRevokeConsentInput",
    "LearningRevokeConsentOutput",
    "learning_contribute",
    "learning_grant_cross_org_consent",
    "learning_query",
    "learning_revoke_cross_org_consent",
]
