"""
shared.schemas.federation.consent_v1
====================================

v1 Pydantic models for federation MCP / REST traffic (#10 + #16).

`schema_version: 1` field tags every payload; future v2 reuses the
same module layout and the MCP tool dispatches on the field. (Pydantic
v2 disallows leading-underscore field names, so we use the explicit
``schema_version`` form rather than the more concise ``_v``.) Wire
compat:

* `ConsentGrantV1` / `ConsentRevokeV1` — child→parent consent grants
  per `consent_class`.
* `HubRegistrationV1` — payload for registering a child Hub.
* `HubConsentSummaryV1` — per-Hub consent posture for the Hub UI.
* `UpdateCascadePushV1` / `UpdateCascadePullV1` — #16 cascade
  request/response models.

All models use `extra='forbid'` (defensive — unknown fields are a sign
of version drift; surface them as 422 rather than silently ignore).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

_FORBID = ConfigDict(extra="forbid")

ConsentClass = Literal[
    "telemetry",
    "update_push",
    "learning_cross_org",
    "audit_export",
    "security_incident",
    "critical_compliance_evidence",
]
"""Mirrors `federation.consent.ConsentClass`. Keep both in sync."""

UpdateRolloutStatus = Literal[
    "pending", "in_progress", "completed", "failed", "rolled_back"
]
"""Mirrors V23 CHECK constraint on `update_distribution.rollout_status`."""

ConsentDecisionV1 = Literal["accepted", "rejected", "pending"]


class HubRegistrationV1(BaseModel):
    """Payload for `federation_register_child` MCP tool."""

    model_config = _FORBID

    schema_version: int = Field(default=1, frozen=True)
    child_hub_id: UUID = Field(..., description="UUIDv4 of the registering child")
    parent_hub_id: UUID = Field(..., description="UUIDv4 of the parent (this Hub)")
    name: str = Field(..., min_length=1, max_length=200)
    base_url: str = Field(..., min_length=1, max_length=2_000)
    public_key: str = Field(
        ...,
        min_length=1,
        max_length=8_000,
        description="PEM-encoded Ed25519 or RSA public key.",
    )
    rationale: str = Field(
        ...,
        min_length=1,
        max_length=4_000,
        description="Why this child is being registered (audit + #12 citation seed).",
    )


class ConsentGrantV1(BaseModel):
    """Payload for `federation_grant_consent` MCP tool."""

    model_config = _FORBID

    schema_version: int = Field(default=1, frozen=True)
    child_hub_id: UUID
    parent_hub_id: UUID
    consent_class: ConsentClass
    granted_by: str = Field(
        ..., min_length=1, max_length=200,
        description="Identity of the human (or service) that approved the grant.",
    )
    scope: dict[str, Any] = Field(
        default_factory=dict,
        description="consent_class-specific scope flags (free-form JSON).",
    )
    rationale: str = Field(
        ..., min_length=1, max_length=4_000,
        description="Why consent was granted (audit + #12).",
    )


class ConsentRevokeV1(BaseModel):
    """Payload for revoking a previously-granted consent record."""

    model_config = _FORBID

    schema_version: int = Field(default=1, frozen=True)
    child_hub_id: UUID
    parent_hub_id: UUID
    consent_class: ConsentClass
    revoked_by: str = Field(..., min_length=1, max_length=200)
    rationale: str = Field(..., min_length=1, max_length=4_000)


class HubConsentSummaryV1(BaseModel):
    """Per-Hub consent posture surfaced in the Hub UI."""

    model_config = _FORBID

    schema_version: int = Field(default=1, frozen=True)
    hub_id: UUID
    name: str
    consent_status: ConsentDecisionV1
    consent_classes: list[ConsentClass] = Field(
        default_factory=list,
        description="Consent classes currently granted for this Hub.",
    )
    mandatory_upward: list[ConsentClass] = Field(
        default_factory=list,
        description="Consent classes the bundle declares mandatory upward.",
    )


class UpdateCascadePushV1(BaseModel):
    """Payload for `federation_push_update` MCP tool.

    Tagged `requires_citation=True` on the tool side (#12).
    """

    model_config = _FORBID

    schema_version: int = Field(default=1, frozen=True)
    bundle_version: str = Field(..., min_length=1, max_length=200)
    signature_b64: str = Field(
        ..., min_length=1, max_length=8_000,
        description="Base64-encoded Ed25519/RSA signature over bundle payload.",
    )
    source_hub_id: UUID
    rationale: str = Field(..., min_length=1, max_length=4_000)


class UpdateCascadePullV1(BaseModel):
    """Payload for `federation_pull_updates` MCP tool.

    Listing pending updates does not require citation; applying one does.
    """

    model_config = _FORBID

    schema_version: int = Field(default=1, frozen=True)
    target_hub_id: UUID = Field(
        ...,
        description="The local Hub's hub_id — defensive in case the tool is "
                    "invoked across federation boundaries.",
    )
    include_completed: bool = Field(
        default=False,
        description="When true, include the recent completed/failed history "
                    "for operator review.",
    )


class PendingUpdateV1(BaseModel):
    """One pending update_distribution row surfaced to the caller."""

    model_config = _FORBID

    schema_version: int = Field(default=1, frozen=True)
    update_id: UUID
    source_hub_id: UUID
    target_hub_id: UUID
    bundle_version: str
    rollout_status: UpdateRolloutStatus
    approved_at: Optional[datetime] = None
    approved_by: Optional[str] = None


__all__ = [
    "ConsentClass",
    "ConsentDecisionV1",
    "ConsentGrantV1",
    "ConsentRevokeV1",
    "HubConsentSummaryV1",
    "HubRegistrationV1",
    "PendingUpdateV1",
    "UpdateCascadePullV1",
    "UpdateCascadePushV1",
    "UpdateRolloutStatus",
]
