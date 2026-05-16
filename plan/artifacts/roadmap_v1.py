"""
Pydantic v2 schema for Spine's `roadmap-v1` artifact.

Implements STORY-1.3.4 from `docs/BACKLOG.md` and PRD §FR-4 from
`docs/PRD.md` (REQ-INIT-1). The `planner` role (with `conductor` as
supporting role) emits this object from the signed PRD + TRD.

The INIT / EPIC / STORY hierarchy and id scheme mirror what
`docs/BACKLOG.md` already uses (`INIT-N` / `EPIC-N.M` / `STORY-N.M.K`).
"""

from __future__ import annotations

import csv
import io
import re
from typing import Annotated, List, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ._base import (
    ArtifactMetadata,
    ArtifactStatus,
    Priority,
    Size,
    Status,
    is_empty_or_tbd,
)


_INIT_RE = re.compile(r"^INIT-\d+$")
_EPIC_RE = re.compile(r"^EPIC-\d+\.\d+$")
_STORY_RE = re.compile(r"^STORY-\d+\.\d+\.\d+$")


def _check_id(value: str, pattern: re.Pattern[str], label: str) -> str:
    if not pattern.match(value):
        raise ValueError(f"{label} '{value}' does not match {pattern.pattern}")
    return value


def _check_text(value: str, label: str) -> str:
    if is_empty_or_tbd(value):
        raise ValueError(f"{label} must not be empty or TBD")
    return value


class Story(BaseModel):
    """A single STORY-N.M.K — the unit of work the executor consumes."""

    model_config = ConfigDict(str_strip_whitespace=True)

    id: Annotated[str, Field(description="Story id, e.g. 'STORY-1.1.3'")]
    title: str
    status: Status = Status.BACKLOG
    priority: Priority
    size: Size
    estimate_cost: Annotated[
        float, Field(ge=0.0, description="Forecast spend in USD")
    ]
    estimate_duration: Annotated[
        str, Field(description="Human duration, e.g. '1-3 days', '1 week'")
    ]
    dependencies: List[str] = Field(
        default_factory=list, description="Story IDs that must complete first"
    )

    @field_validator("id")
    @classmethod
    def _vid(cls, v: str) -> str:
        return _check_id(v, _STORY_RE, "Story.id")

    @field_validator("title", "estimate_duration")
    @classmethod
    def _vtext(cls, v: str) -> str:
        return _check_text(v, "Story field")

    @field_validator("dependencies")
    @classmethod
    def _vdeps(cls, v: List[str]) -> List[str]:
        for dep in v:
            _check_id(dep, _STORY_RE, "Story.dependencies entry")
        return v


class Epic(BaseModel):
    """A single EPIC-N.M, containing zero or more stories."""

    model_config = ConfigDict(str_strip_whitespace=True)

    id: Annotated[str, Field(description="Epic id, e.g. 'EPIC-1.1'")]
    title: str
    description: str
    stories: List[Story] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def _vid(cls, v: str) -> str:
        return _check_id(v, _EPIC_RE, "Epic.id")

    @field_validator("title", "description")
    @classmethod
    def _vtext(cls, v: str) -> str:
        return _check_text(v, "Epic field")


class Initiative(BaseModel):
    """A single INIT-N, containing zero or more epics."""

    model_config = ConfigDict(str_strip_whitespace=True)

    id: Annotated[str, Field(description="Initiative id, e.g. 'INIT-1'")]
    title: str
    tier: Annotated[int, Field(ge=1, le=4, description="Landscape tier 1-4")]
    priority: Priority
    why: Annotated[str, Field(description="One-paragraph rationale")]
    epics: List[Epic] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def _vid(cls, v: str) -> str:
        return _check_id(v, _INIT_RE, "Initiative.id")

    @field_validator("title", "why")
    @classmethod
    def _vtext(cls, v: str) -> str:
        return _check_text(v, "Initiative field")


class Sprint(BaseModel):
    """A planning bucket: which stories ship in which sprint."""

    model_config = ConfigDict(str_strip_whitespace=True)

    number: Annotated[int, Field(ge=1)]
    name: str
    goal: str
    stories: List[str] = Field(
        default_factory=list, description="Story IDs assigned to this sprint"
    )

    @field_validator("name", "goal")
    @classmethod
    def _vtext(cls, v: str) -> str:
        return _check_text(v, "Sprint field")

    @field_validator("stories")
    @classmethod
    def _vstories(cls, v: List[str]) -> List[str]:
        for sid in v:
            _check_id(sid, _STORY_RE, "Sprint.stories entry")
        return v


class RoadmapV1(BaseModel):
    """Spine Roadmap artifact, schema version `roadmap-v1`."""

    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True)

    version: Literal["roadmap-v1"] = "roadmap-v1"
    project_id: str
    prd_ref: Annotated[str, Field(description="URL/anchor for the source PRD")]
    trd_ref: Annotated[str, Field(description="URL/anchor for the source TRD")]
    initiatives: List[Initiative] = Field(default_factory=list)
    epics: List[Epic] = Field(
        default_factory=list,
        description="Optional flattened view across initiatives",
    )
    stories: List[Story] = Field(
        default_factory=list,
        description="Optional flattened view across initiatives + epics",
    )
    sprint_plan: List[Sprint] = Field(default_factory=list)
    metadata: ArtifactMetadata

    @field_validator("project_id", "prd_ref", "trd_ref")
    @classmethod
    def _vtext(cls, v: str) -> str:
        return _check_text(v, "Required Roadmap field")

    @model_validator(mode="after")
    def _refuse_to_advance(self) -> "RoadmapV1":
        """A roadmap with `status=approved` must contain at least one story."""
        if self.metadata.status != ArtifactStatus.APPROVED:
            return self
        if not self.initiatives:
            raise ValueError("Roadmap cannot be approved with zero initiatives")
        if not any(e.stories for i in self.initiatives for e in i.epics):
            raise ValueError("Roadmap cannot be approved with zero stories")
        return self

    def to_markdown(self) -> str:
        """Render as BACKLOG.md-style markdown. Skeleton — not byte-exact."""
        out: list[str] = [
            f"# {self.project_id} — Roadmap",
            "",
            f"> Schema: `{self.version}` · PRD: {self.prd_ref} · TRD: {self.trd_ref}",
            f"> Status: **{self.metadata.status.value}**",
            "",
        ]
        if self.sprint_plan:
            out.append("## Sprint plan")
            for sp in self.sprint_plan:
                out += [
                    f"### Sprint {sp.number} — {sp.name}",
                    f"**Goal:** {sp.goal}",
                ]
                out += [f"- `{sid}`" for sid in sp.stories]
                out.append("")
        for init in self.initiatives:
            out += [
                f"## {init.id} — {init.title}  (tier {init.tier}, {init.priority.value})",
                f"_{init.why}_",
                "",
            ]
            for epic in init.epics:
                out += [f"### {epic.id} — {epic.title}", epic.description]
                for s in epic.stories:
                    deps = f" · deps: {', '.join(s.dependencies)}" if s.dependencies else ""
                    out.append(
                        f"- `{s.id}` · `{s.status.value}` · `{s.priority.value}` · "
                        f"`{s.size.value}` — {s.title}{deps}"
                    )
                out.append("")
        return "\n".join(out).rstrip() + "\n"

    def to_jira_csv(self) -> str:
        """
        Emit a flat CSV for Jira / Linear / GitHub Projects import.

        Placeholder for STORY-5.3.1 — columns approximate Jira's "Issues"
        importer format. A future story will tune per importer dialect.
        """
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow([
            "Issue Type", "Issue Key", "Summary", "Status", "Priority",
            "Story Points", "Parent", "Initiative", "Depends On",
            "Estimate (USD)", "Estimate (Duration)",
        ])
        for init in self.initiatives:
            w.writerow(["Initiative", init.id, init.title, "Backlog",
                        init.priority.value, "", "", "", "", "", ""])
            for epic in init.epics:
                w.writerow(["Epic", epic.id, epic.title, "Backlog", "",
                            "", init.id, init.id, "", "", ""])
                for s in epic.stories:
                    w.writerow([
                        "Story", s.id, s.title, s.status.value, s.priority.value,
                        s.size.value, epic.id, init.id,
                        ";".join(s.dependencies),
                        f"{s.estimate_cost:.2f}", s.estimate_duration,
                    ])
        return buf.getvalue()


__all__ = ["RoadmapV1", "Initiative", "Epic", "Story", "Sprint"]
