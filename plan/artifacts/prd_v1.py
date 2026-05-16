"""
Pydantic v2 schema for Spine's `prd-v1` artifact.

Implements STORY-1.1.3 from `docs/BACKLOG.md` and PRD §FR-2 from
`docs/PRD.md` (REQ-INIT-1). The `product` role emits this object after
running the 5-move dialogue protocol against the user.

The refuse-to-advance gate (FR-2) is enforced by:
  - per-field validators that reject TBD / empty strings on required fields
  - `_refuse_to_advance` model validator that blocks `status=approved`
    when any required collection is empty
"""

from __future__ import annotations

from typing import Annotated, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ._base import (
    AcceptanceCriterion,
    ArtifactMetadata,
    ArtifactStatus,
    Goal,
    OpenQuestion,
    ProjectType,
    is_empty_or_tbd,
)


# ============================================================================
# Sub-models specific to the PRD
# ============================================================================


class Stakeholder(BaseModel):
    """A user persona or stakeholder group with their needs from this feature."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: Annotated[str, Field(description="Persona / stakeholder name")]
    needs: Annotated[
        str,
        Field(description="What this stakeholder needs from the feature"),
    ]

    @field_validator("name", "needs")
    @classmethod
    def _not_empty(cls, v: str) -> str:
        if is_empty_or_tbd(v):
            raise ValueError("Stakeholder fields must not be empty or TBD")
        return v


class Goals(BaseModel):
    """MUST / SHOULD / COULD / WONT goal tiers per PRD §1.4 / FR-2."""

    must: List[Goal] = Field(default_factory=list)
    should: List[Goal] = Field(default_factory=list)
    could: List[Goal] = Field(default_factory=list)
    wont: List[Goal] = Field(default_factory=list)


# ============================================================================
# PRD v1
# ============================================================================


class PRDv1(BaseModel):
    """Spine Product Requirements Document, schema version `prd-v1`."""

    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True,
    )

    version: Literal["prd-v1"] = "prd-v1"
    project_id: Annotated[
        str, Field(description="Stable project id (e.g. 'spine', 'acme-timetracker')")
    ]
    project_name: Annotated[str, Field(description="Human-readable project name")]
    project_type: Annotated[
        ProjectType,
        Field(description="Drives swarm composition + intake template"),
    ]
    problem_statement: Annotated[
        str,
        Field(description="What pain are we solving and for whom"),
    ]
    users_stakeholders: List[Stakeholder] = Field(default_factory=list)
    goals: Goals = Field(default_factory=Goals)
    in_scope: List[str] = Field(default_factory=list)
    out_of_scope: List[str] = Field(default_factory=list)
    acceptance_criteria: List[AcceptanceCriterion] = Field(default_factory=list)
    open_questions: List[OpenQuestion] = Field(default_factory=list)
    metadata: ArtifactMetadata

    # ------------------------------------------------------------------
    # Validators — the "refuse-to-advance" gate
    # ------------------------------------------------------------------

    @field_validator("project_id", "project_name", "problem_statement")
    @classmethod
    def _required_text(cls, v: str) -> str:
        if is_empty_or_tbd(v):
            raise ValueError("Required PRD field must not be empty or TBD")
        return v

    @field_validator("in_scope", "out_of_scope")
    @classmethod
    def _no_tbd_lines(cls, v: List[str]) -> List[str]:
        for line in v:
            if is_empty_or_tbd(line):
                raise ValueError("Scope lines must not be empty or TBD")
        return v

    @model_validator(mode="after")
    def _refuse_to_advance(self) -> "PRDv1":
        """A PRD with `status=approved` must have all required content present."""
        if self.metadata.status != ArtifactStatus.APPROVED:
            return self
        problems: list[str] = []
        if not self.users_stakeholders:
            problems.append("users_stakeholders is empty")
        if not self.goals.must:
            problems.append("goals.must is empty")
        if not self.in_scope:
            problems.append("in_scope is empty")
        if not self.acceptance_criteria:
            problems.append("acceptance_criteria is empty")
        if problems:
            raise ValueError(
                "PRD cannot be marked approved while required sections are "
                "empty: " + ", ".join(problems)
            )
        return self

    # ------------------------------------------------------------------
    # Rendering — markdown skeleton that mirrors `docs/PRD.md` shape
    # ------------------------------------------------------------------

    def to_markdown(self) -> str:
        """Render this PRD as markdown matching the `docs/PRD.md` shape."""
        lines: list[str] = []
        lines.append(f"# {self.project_name} — PRD")
        lines.append("")
        lines.append(f"> Schema: `{self.version}`  ·  Project: `{self.project_id}`")
        lines.append(f"> Status: **{self.metadata.status.value}**")
        lines.append("")
        lines.append("## Problem")
        lines.append(self.problem_statement)
        lines.append("")
        lines.append("## Users & stakeholders")
        if self.users_stakeholders:
            lines.append("| Stakeholder | Needs |")
            lines.append("|---|---|")
            for s in self.users_stakeholders:
                lines.append(f"| **{s.name}** | {s.needs} |")
        lines.append("")
        lines.append("## Goals")
        for tier_name, items in [
            ("MUST", self.goals.must),
            ("SHOULD", self.goals.should),
            ("COULD", self.goals.could),
            ("WON'T", self.goals.wont),
        ]:
            lines.append(f"### {tier_name}")
            for g in items:
                lines.append(f"- **{g.id}** {g.statement}")
        lines.append("")
        lines.append("## In scope")
        for item in self.in_scope:
            lines.append(f"- {item}")
        lines.append("")
        lines.append("## Out of scope")
        for item in self.out_of_scope:
            lines.append(f"- {item}")
        lines.append("")
        lines.append("## Acceptance criteria")
        for ac in self.acceptance_criteria:
            prefix = f"- **{ac.id}**"
            if ac.given or ac.when:
                lines.append(
                    f"{prefix} Given {ac.given or '—'}, when {ac.when or '—'}, "
                    f"then {ac.then}"
                )
            else:
                lines.append(f"{prefix} {ac.then}")
        lines.append("")
        if self.open_questions:
            lines.append("## Open questions")
            for oq in self.open_questions:
                rec = f" _(rec: {oq.recommendation})_" if oq.recommendation else ""
                lines.append(f"- **{oq.id}** {oq.question}{rec}")
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"


__all__ = ["PRDv1", "Stakeholder", "Goals"]
