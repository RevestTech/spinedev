"""
Per-scout contribution schema for the Technical Review Swarm.

Implements `STORY-1.2.4` (per-scout contribution format) from
`docs/BACKLOG.md`. Each swarm member (researcher / engineer / datawright /
operator / qa) emits a `ScoutContribution`; the architect's synthesis step
merges these into a `trd-v1` (see `plan/artifacts/trd_v1.py`).

Schema is lens-agnostic: every scout fills in the same shape, only the
`lens` and content of `findings`/`risks` differs. `synthesis.py` walks a
uniform structure.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ScoutRole(str, Enum):
    RESEARCHER = "researcher"
    ENGINEER = "engineer"
    DATAWRIGHT = "datawright"
    OPERATOR = "operator"
    QA = "qa"


class ScoutLens(str, Enum):
    CURRENT_STATE = "current_state"   # researcher
    FEASIBILITY = "feasibility"       # engineer
    DATA = "data"                     # datawright
    INFRA = "infra"                   # operator
    QUALITY = "quality"               # qa


DEFAULT_LENS_FOR_ROLE: dict[ScoutRole, ScoutLens] = {
    ScoutRole.RESEARCHER: ScoutLens.CURRENT_STATE,
    ScoutRole.ENGINEER: ScoutLens.FEASIBILITY,
    ScoutRole.DATAWRIGHT: ScoutLens.DATA,
    ScoutRole.OPERATOR: ScoutLens.INFRA,
    ScoutRole.QA: ScoutLens.QUALITY,
}


class Severity(str, Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class FindingKind(str, Enum):
    CONSTRAINT = "constraint"
    RECOMMENDATION = "recommendation"
    DEPENDENCY = "dependency"
    GAP = "gap"
    OPPORTUNITY = "opportunity"


class Likelihood(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Impact(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Finding(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    severity: Severity
    kind: FindingKind
    file_or_section: Annotated[str, Field(description="PRD section / file / 'global'")]
    description: Annotated[str, Field(min_length=1)]
    recommendation: Optional[str] = None


class RiskItem(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    description: Annotated[str, Field(min_length=1)]
    likelihood: Likelihood
    impact: Impact
    mitigation: Optional[str] = None


class OpenQuestion(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    id: Annotated[str, Field(description="Stable id, e.g. 'OQ-ENG-1'")]
    question: Annotated[str, Field(min_length=1)]
    recommendation: Optional[str] = None


class ScoutContribution(BaseModel):
    """One scout's per-lens report; many of these synthesize into a TRD."""

    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True)

    scout_role: ScoutRole
    lens: ScoutLens
    scope_received: Annotated[str, Field(description="PRD anchor / sub-question")]
    findings: List[Finding] = Field(default_factory=list)
    risks: List[RiskItem] = Field(default_factory=list)
    open_questions: List[OpenQuestion] = Field(default_factory=list)
    confidence: Annotated[float, Field(ge=0.0, le=1.0)] = 0.5
    cost_usd: Annotated[float, Field(ge=0.0)] = 0.0
    duration_ms: Annotated[int, Field(ge=0)] = 0
    model_used: Annotated[str, Field(min_length=1)] = "unknown"
    produced_at: datetime = Field(default_factory=datetime.utcnow)

    @field_validator("scope_received")
    @classmethod
    def _scope_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("scope_received must be non-empty")
        return v

    @model_validator(mode="after")
    def _lens_matches_role(self) -> "ScoutContribution":
        """Default role→lens binding; custom scouts opt out by overriding the map."""
        expected = DEFAULT_LENS_FOR_ROLE.get(self.scout_role)
        if expected is not None and self.lens != expected:
            raise ValueError(
                f"scout_role={self.scout_role.value} should produce "
                f"lens={expected.value}, got {self.lens.value}"
            )
        return self


__all__ = [
    "DEFAULT_LENS_FOR_ROLE", "Finding", "FindingKind", "Impact", "Likelihood",
    "OpenQuestion", "RiskItem", "ScoutContribution", "ScoutLens", "ScoutRole",
    "Severity",
]
