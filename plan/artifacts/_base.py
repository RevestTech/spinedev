"""
Shared base models for Spine SDLC artifact schemas (PRD / TRD / Roadmap).

These types are reused across `prd_v1`, `trd_v1`, and `roadmap_v1` so that
metadata, approval records, and common value-objects stay consistent.

Pattern lifted from TRON `tron/schemas/verification.py`.

Spec source: `docs/PRD.md` REQ-INIT-1 (FR-2 / FR-3 / FR-4).
Stories: STORY-1.1.3, STORY-1.2.3, STORY-1.3.4 in `docs/BACKLOG.md`.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ============================================================================
# Sentinel values that the "refuse-to-advance" gate rejects (FR-2)
# ============================================================================

# Any required free-text field equal (case-insensitive, stripped) to one of
# these placeholders is treated as "not filled in" and blocks artifact
# completion. Source: PRD §FR-2 "Refuse-to-advance rule".
EMPTY_SENTINELS: frozenset[str] = frozenset(
    {"", "tbd", "todo", "fixme", "n/a", "na", "?", "..."}
)


def is_empty_or_tbd(value: str | None) -> bool:
    """Return True when `value` is missing or one of the placeholder sentinels."""
    if value is None:
        return True
    return value.strip().lower() in EMPTY_SENTINELS


# ============================================================================
# Enumerations shared across artifacts
# ============================================================================


class ProjectType(str, Enum):
    """Project archetype — drives swarm composition + intake template choice."""

    WEB_APP = "web_app"
    INTERNAL_TOOL = "internal_tool"
    DATA_PIPELINE = "data_pipeline"
    MOBILE = "mobile"
    API_SERVICE = "api_service"
    CLI_TOOL = "cli_tool"
    CUSTOM = "custom"


class Priority(str, Enum):
    """Story / epic priority. Matches `docs/BACKLOG.md` legend."""

    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class Size(str, Enum):
    """T-shirt sizing. Matches `docs/BACKLOG.md` legend."""

    XS = "XS"
    S = "S"
    M = "M"
    L = "L"
    XL = "XL"


class Status(str, Enum):
    """Story workflow status. Matches `docs/BACKLOG.md` legend."""

    BACKLOG = "Backlog"
    IN_DESIGN = "InDesign"
    IN_PROGRESS = "InProgress"
    DONE = "Done"
    WONT_DO = "WontDo"


class ArtifactStatus(str, Enum):
    """Lifecycle status of a PRD / TRD / Roadmap artifact."""

    DRAFT = "draft"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


# ============================================================================
# Shared value-objects
# ============================================================================


class Goal(BaseModel):
    """A single MUST / SHOULD / COULD / WONT goal entry."""

    model_config = ConfigDict(str_strip_whitespace=True)

    id: Annotated[str, Field(description="Stable goal id, e.g. 'G-1'")]
    statement: Annotated[str, Field(description="One-sentence goal statement")]
    rationale: Annotated[
        Optional[str],
        Field(default=None, description="Optional 'why this matters' detail"),
    ] = None

    @field_validator("statement")
    @classmethod
    def _not_empty(cls, v: str) -> str:
        if is_empty_or_tbd(v):
            raise ValueError("Goal.statement must not be empty or TBD")
        return v


class OpenQuestion(BaseModel):
    """An unresolved question + the role's recommended default."""

    model_config = ConfigDict(str_strip_whitespace=True)

    id: Annotated[str, Field(description="Stable id, e.g. 'OQ-1'")]
    question: str
    recommendation: Annotated[
        Optional[str],
        Field(
            default=None,
            description="Producing role's best-guess answer until the user resolves it",
        ),
    ] = None

    @field_validator("question")
    @classmethod
    def _not_empty(cls, v: str) -> str:
        if is_empty_or_tbd(v):
            raise ValueError("OpenQuestion.question must not be empty or TBD")
        return v


class AcceptanceCriterion(BaseModel):
    """A single, testable acceptance criterion."""

    model_config = ConfigDict(str_strip_whitespace=True)

    id: Annotated[str, Field(description="Stable id, e.g. 'AC-1'")]
    given: Annotated[Optional[str], Field(default=None)] = None
    when: Annotated[Optional[str], Field(default=None)] = None
    then: Annotated[str, Field(description="Observable expected outcome")]

    @field_validator("then")
    @classmethod
    def _not_empty(cls, v: str) -> str:
        if is_empty_or_tbd(v):
            raise ValueError("AcceptanceCriterion.then must not be empty or TBD")
        return v


class ApprovalRecord(BaseModel):
    """Captures who approved/rejected an artifact and when."""

    model_config = ConfigDict(str_strip_whitespace=True)

    approver: Annotated[str, Field(description="User id or role that signed off")]
    decision: Annotated[
        ArtifactStatus,
        Field(description="One of approved / rejected / superseded"),
    ]
    decided_at: datetime = Field(default_factory=datetime.utcnow)
    notes: Annotated[
        Optional[str],
        Field(default=None, description="Free-text rationale, change requests, etc."),
    ] = None

    @field_validator("decision")
    @classmethod
    def _terminal_only(cls, v: ArtifactStatus) -> ArtifactStatus:
        if v == ArtifactStatus.DRAFT:
            raise ValueError("ApprovalRecord.decision cannot be 'draft'")
        return v


class ArtifactMetadata(BaseModel):
    """Common provenance + lifecycle metadata for every Spine artifact."""

    model_config = ConfigDict(str_strip_whitespace=True)

    created_at: datetime = Field(default_factory=datetime.utcnow)
    created_by: Annotated[str, Field(description="Role or user id that produced it")]
    last_modified: datetime = Field(default_factory=datetime.utcnow)
    status: ArtifactStatus = ArtifactStatus.DRAFT
    approval: Annotated[
        Optional[ApprovalRecord],
        Field(
            default=None,
            description="Populated once the artifact has been signed off or rejected",
        ),
    ] = None
