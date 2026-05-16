"""
Pydantic v2 schema for Spine's `trd-v1` artifact.

Implements STORY-1.2.3 from `docs/BACKLOG.md` and PRD §FR-3 from
`docs/PRD.md` (REQ-INIT-1). The `architect` role emits this object
after running the technical-review swarm and synthesizing per-lens
contributions into one Technical Requirements Document.

Same refuse-to-advance discipline as the PRD: required free-text
fields reject TBD / empty strings, and a final model-level validator
blocks `status=approved` when key sections are still empty.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ._base import (
    ArtifactMetadata,
    ArtifactStatus,
    OpenQuestion,
    Size,
    is_empty_or_tbd,
)


class IntegrationDirection(str, Enum):
    """Inbound, outbound, or bidirectional integration."""

    INBOUND = "inbound"
    OUTBOUND = "outbound"
    BIDIRECTIONAL = "bidirectional"


class Likelihood(str, Enum):
    """Likelihood band for risk register."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Impact(str, Enum):
    """Impact band for risk register."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


def _reject_tbd(values: List[str], label: str) -> List[str]:
    """Shared helper: raise if any string in `values` is empty/TBD."""
    for v in values:
        if is_empty_or_tbd(v):
            raise ValueError(f"{label} must not be empty or TBD")
    return values


class Component(BaseModel):
    """A logical component in the proposed architecture."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str
    responsibility: Annotated[str, Field(description="One-line responsibility")]
    technology: Annotated[
        Optional[str],
        Field(default=None, description="Concrete tech choice if decided"),
    ] = None

    @field_validator("name", "responsibility")
    @classmethod
    def _not_empty(cls, v: str) -> str:
        return _reject_tbd([v], "Component field")[0]


class ArchitectureSection(BaseModel):
    """The architecture lens of the TRD."""

    system_overview: Annotated[str, Field(description="Prose architecture summary")]
    components: List[Component] = Field(default_factory=list)
    data_flow: Annotated[str, Field(description="How data moves between components")]

    @field_validator("system_overview", "data_flow")
    @classmethod
    def _not_empty(cls, v: str) -> str:
        return _reject_tbd([v], "Architecture field")[0]


class Entity(BaseModel):
    """An entity in the data model."""

    model_config = ConfigDict(str_strip_whitespace=True)
    name: str
    attributes: List[str] = Field(default_factory=list)
    notes: Optional[str] = None


class Relationship(BaseModel):
    """A relationship between two entities (one-to-many, owns, references, etc.)."""

    model_config = ConfigDict(str_strip_whitespace=True)
    source: str
    target: str
    kind: str


class DataModel(BaseModel):
    """Entities + relationships. Optional — internal tools may have none."""

    entities: List[Entity] = Field(default_factory=list)
    relationships: List[Relationship] = Field(default_factory=list)


class Integration(BaseModel):
    """An external system the project talks to."""

    model_config = ConfigDict(str_strip_whitespace=True)
    name: str
    direction: IntegrationDirection
    protocol: Annotated[str, Field(description="REST, gRPC, SQS, webhook, ...")]
    auth: Annotated[str, Field(description="OAuth2, API key, mTLS, none, ...")]


class NonFunctionalRequirements(BaseModel):
    """One prose field per NFR concern; extensible per project."""

    performance: str = ""
    security: str = ""
    scalability: str = ""
    observability: str = ""
    cost: str = ""


class TechChoice(BaseModel):
    """A single architecture decision (lightweight ADR)."""

    model_config = ConfigDict(str_strip_whitespace=True)
    concern: Annotated[str, Field(description="e.g. 'message queue', 'auth provider'")]
    decision: Annotated[str, Field(description="Chosen technology")]
    rationale: str
    alternatives_considered: List[str] = Field(default_factory=list)

    @field_validator("concern", "decision", "rationale")
    @classmethod
    def _not_empty(cls, v: str) -> str:
        return _reject_tbd([v], "TechChoice field")[0]


class Risk(BaseModel):
    """An entry in the risk register."""

    model_config = ConfigDict(str_strip_whitespace=True)
    description: str
    likelihood: Likelihood
    impact: Impact
    mitigation: str

    @field_validator("description", "mitigation")
    @classmethod
    def _not_empty(cls, v: str) -> str:
        return _reject_tbd([v], "Risk field")[0]


class ScopeEstimate(BaseModel):
    """The decomposer's first-cut scope estimate (refined into the Roadmap)."""

    epics_count: Annotated[int, Field(ge=0)]
    stories_count: Annotated[int, Field(ge=0)]
    estimated_size: Annotated[Size, Field(description="Overall t-shirt size")]


class CostProjection(BaseModel):
    """Forecast spend per phase, in `currency` (default USD)."""

    build_phase_estimate: Annotated[float, Field(ge=0.0)]
    verify_phase_estimate: Annotated[float, Field(ge=0.0)]
    total_estimate: Annotated[float, Field(ge=0.0)]
    currency: str = "USD"

    @model_validator(mode="after")
    def _total_at_least_sum(self) -> "CostProjection":
        if self.total_estimate + 1e-6 < (
            self.build_phase_estimate + self.verify_phase_estimate
        ):
            raise ValueError(
                "total_estimate must be at least build + verify estimates"
            )
        return self


class TRDv1(BaseModel):
    """Spine Technical Requirements Document, schema version `trd-v1`."""

    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True)

    version: Literal["trd-v1"] = "trd-v1"
    project_id: str
    prd_ref: Annotated[str, Field(description="URL or anchor of the source PRD")]
    architecture: ArchitectureSection
    data_model: Optional[DataModel] = None
    integrations: List[Integration] = Field(default_factory=list)
    nfrs: NonFunctionalRequirements = Field(default_factory=NonFunctionalRequirements)
    tech_choices: List[TechChoice] = Field(default_factory=list)
    risks: List[Risk] = Field(default_factory=list)
    open_questions: List[OpenQuestion] = Field(default_factory=list)
    scope_estimate: ScopeEstimate
    cost_projection: CostProjection
    metadata: ArtifactMetadata

    @field_validator("project_id", "prd_ref")
    @classmethod
    def _required_text(cls, v: str) -> str:
        return _reject_tbd([v], "Required TRD field")[0]

    @model_validator(mode="after")
    def _refuse_to_advance(self) -> "TRDv1":
        """A TRD with `status=approved` must have all required content present."""
        if self.metadata.status != ArtifactStatus.APPROVED:
            return self
        problems: list[str] = []
        if not self.architecture.components:
            problems.append("architecture.components is empty")
        if not self.tech_choices:
            problems.append("tech_choices is empty")
        if problems:
            raise ValueError(
                "TRD cannot be marked approved while required sections are "
                "empty: " + ", ".join(problems)
            )
        return self

    def to_markdown(self) -> str:
        """Render this TRD as markdown. Skeleton — not a final formatter."""
        out: list[str] = [
            f"# TRD — {self.project_id}",
            "",
            f"> Schema: `{self.version}` · PRD: {self.prd_ref}",
            f"> Status: **{self.metadata.status.value}**",
            "",
            "## Architecture",
            self.architecture.system_overview,
            "",
            "### Components",
        ]
        for c in self.architecture.components:
            tech = f" _[{c.technology}]_" if c.technology else ""
            out.append(f"- **{c.name}**{tech} — {c.responsibility}")
        out += ["", "### Data flow", self.architecture.data_flow, ""]
        if self.integrations:
            out.append("## Integrations")
            for i in self.integrations:
                out.append(
                    f"- **{i.name}** · {i.direction.value} · {i.protocol} · "
                    f"auth={i.auth}"
                )
            out.append("")
        out.append("## Non-functional requirements")
        for key in ("performance", "security", "scalability", "observability", "cost"):
            val = getattr(self.nfrs, key)
            if val:
                out.append(f"- **{key}**: {val}")
        out += ["", "## Tech choices"]
        for t in self.tech_choices:
            alts = (
                f" (alternatives: {', '.join(t.alternatives_considered)})"
                if t.alternatives_considered
                else ""
            )
            out.append(f"- **{t.concern}** → `{t.decision}` — {t.rationale}{alts}")
        out.append("")
        if self.risks:
            out.append("## Risks")
            for r in self.risks:
                out.append(
                    f"- _{r.likelihood.value}/{r.impact.value}_ — {r.description} "
                    f"(mitigation: {r.mitigation})"
                )
            out.append("")
        if self.open_questions:
            out.append("## Open questions")
            for oq in self.open_questions:
                rec = f" _(rec: {oq.recommendation})_" if oq.recommendation else ""
                out.append(f"- **{oq.id}** {oq.question}{rec}")
            out.append("")
        cp = self.cost_projection
        out += [
            "## Scope estimate",
            f"- Epics: {self.scope_estimate.epics_count}, "
            f"Stories: {self.scope_estimate.stories_count}, "
            f"Size: {self.scope_estimate.estimated_size.value}",
            "",
            "## Cost projection",
            f"- Build: {cp.build_phase_estimate:.2f} {cp.currency}, "
            f"Verify: {cp.verify_phase_estimate:.2f} {cp.currency}, "
            f"Total: {cp.total_estimate:.2f} {cp.currency}",
        ]
        return "\n".join(out).rstrip() + "\n"


__all__ = [
    "TRDv1",
    "ArchitectureSection",
    "Component",
    "DataModel",
    "Entity",
    "Relationship",
    "Integration",
    "IntegrationDirection",
    "NonFunctionalRequirements",
    "TechChoice",
    "Risk",
    "Likelihood",
    "Impact",
    "ScopeEstimate",
    "CostProjection",
]
