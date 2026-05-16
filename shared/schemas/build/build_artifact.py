"""
Pydantic v2 schema for Spine's `build-artifact-v1`.

Implements STORY-7.4.1 (BACKLOG) and PRD §FR-3 (REQ-INIT-7). Build emits
this typed contract for every completed directive; Verify (REQ-INIT-8
FR-4 `verify_audit`) consumes it. Replaces free-form markdown reports.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Annotated, Any, Literal, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from plan.artifacts._base import ArtifactMetadata, is_empty_or_tbd

_STRIP = ConfigDict(str_strip_whitespace=True)
_CHANGE_BUCKET = {"create": "files_created", "modify": "files_modified", "delete": "files_deleted"}


class CodeChange(BaseModel):
    """A single file mutation produced by a Build role."""

    model_config = _STRIP
    path: Annotated[str, Field(description="Repo-relative changed file path")]
    change_type: Literal["create", "modify", "delete"]
    diff_hash: Annotated[str, Field(description="SHA-256 of the unified diff")]
    lines_added: int = Field(ge=0)
    lines_removed: int = Field(ge=0)
    language: Optional[str] = None


class TestRecord(BaseModel):
    """A test added, modified, or executed during the directive."""

    model_config = _STRIP
    test_id: str
    path: str
    status: Literal["added", "modified", "passed", "failed", "skipped", "errored"]
    duration_ms: int = Field(ge=0)
    failure_message: Optional[str] = None


class KGImpactNode(BaseModel):
    """KG node touched by this directive (MCP `impact_radius` output)."""

    model_config = _STRIP
    node_id: Annotated[str, Field(description="Stable external KG id")]
    node_type: Annotated[str, Field(description="Function|Method|Class|Module|File ...")]
    impact_distance: int = Field(ge=0, description="0=direct, 1=caller, 2+=transitive")


class BuildCost(BaseModel):
    """Token + dollar cost accounting for the directive run."""

    model_config = _STRIP
    tokens_input: int = Field(ge=0)
    tokens_output: int = Field(ge=0)
    model: Annotated[str, Field(description="Model id, e.g. 'claude-opus-4-7'")]
    cost_usd: Decimal = Field(ge=Decimal("0"))
    tier: Literal["low", "medium", "high"]


class BuildRuntime(BaseModel):
    """Wall-clock timing + worker provenance."""

    started_at: datetime
    completed_at: datetime
    duration_seconds: int = Field(ge=0)
    worker_id: Optional[str] = None

    @field_validator("started_at", "completed_at")
    @classmethod
    def _tz_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("BuildRuntime datetimes must be timezone-aware")
        return v


class BuildArtifact(BaseModel):
    """Typed contract Build emits for every completed orchestrator directive."""

    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True)

    version: Literal["build-artifact-v1"] = "build-artifact-v1"
    artifact_uuid: UUID = Field(default_factory=uuid4)
    directive_id: Annotated[str, Field(description="Orchestrator-issued directive id")]
    project_id: str
    phase: Annotated[str, Field(description="SDLC phase, e.g. 'build_in_progress'")]
    role: Literal["engineer", "operator", "datawright"]
    pipeline_version: Annotated[str, Field(description="Locked SDLC pipeline manifest version")]
    parent_directive_id: Optional[str] = Field(default=None, description="Set on verify-fail re-dispatch")
    code_changes: list[CodeChange] = Field(default_factory=list)
    tests_added: list[TestRecord] = Field(default_factory=list)
    tests_run: list[TestRecord] = Field(default_factory=list)
    kg_impact: list[KGImpactNode] = Field(default_factory=list)
    cost: BuildCost
    runtime: BuildRuntime
    rationale: Annotated[str, Field(max_length=500, description="What was done and why (<=500 chars)")]
    status: Literal["sealed", "draft", "rejected"] = "draft"
    auditor_verdict: Optional[Literal["pending", "approved", "kg_impact_mismatch", "scope_violation"]] = None
    metadata: ArtifactMetadata

    @model_validator(mode="after")
    def _refuse_seal_without_kg_impact(self) -> "BuildArtifact":
        if self.status == "sealed" and self.role == "engineer" and self.code_changes and not self.kg_impact:
            raise ValueError(
                "Engineer BuildArtifact cannot be sealed with empty kg_impact when "
                "code_changes present — call MCP impact_radius before sealing"
            )
        return self

    @model_validator(mode="after")
    def _rationale_required_when_sealed(self) -> "BuildArtifact":
        if self.status == "sealed" and is_empty_or_tbd(self.rationale):
            raise ValueError("Sealed BuildArtifact requires a non-empty, non-TBD rationale")
        return self

    @model_validator(mode="after")
    def _cost_non_negative(self) -> "BuildArtifact":
        c = self.cost
        if c.cost_usd < 0 or c.tokens_input < 0 or c.tokens_output < 0:
            raise ValueError("BuildArtifact.cost fields must be non-negative")
        return self

    @model_validator(mode="after")
    def _runtime_consistency(self) -> "BuildArtifact":
        r = self.runtime
        if r.completed_at < r.started_at:
            raise ValueError("BuildRuntime.completed_at must be >= started_at")
        delta = int((r.completed_at - r.started_at).total_seconds())
        if abs(delta - r.duration_seconds) > 1:
            raise ValueError(
                f"BuildRuntime.duration_seconds ({r.duration_seconds}) does not "
                f"match completed_at-started_at delta ({delta})"
            )
        return self

    def compute_diff_summary(self) -> dict[str, int]:
        """Totals: files by change_type, total lines added/removed, tests by status."""
        s: dict[str, int] = {
            "files_created": 0, "files_modified": 0, "files_deleted": 0,
            "lines_added": 0, "lines_removed": 0, "tests_added": len(self.tests_added),
            "tests_passed": 0, "tests_failed": 0, "tests_skipped": 0, "tests_errored": 0,
        }
        for ch in self.code_changes:
            s[_CHANGE_BUCKET[ch.change_type]] += 1
            s["lines_added"] += ch.lines_added
            s["lines_removed"] += ch.lines_removed
        for t in self.tests_run:
            key = f"tests_{t.status}"
            if key in s:
                s[key] += 1
        return s

    def to_audit_metadata(self) -> dict[str, Any]:
        """JSONB blob subset suitable for the audit_event row."""
        return {
            "artifact_uuid": str(self.artifact_uuid), "directive_id": self.directive_id,
            "project_id": self.project_id, "role": self.role, "phase": self.phase,
            "pipeline_version": self.pipeline_version, "status": self.status,
            "auditor_verdict": self.auditor_verdict, "cost_usd": str(self.cost.cost_usd),
            "tokens_input": self.cost.tokens_input, "tokens_output": self.cost.tokens_output,
            "model": self.cost.model, "duration_seconds": self.runtime.duration_seconds,
            "kg_impact_count": len(self.kg_impact), "summary": self.compute_diff_summary(),
        }

    def to_markdown(self) -> str:
        """Render as Markdown report (header, TL;DR, changes, tests, KG, cost, metadata)."""
        s, r, c = self.compute_diff_summary(), self.runtime, self.cost
        tests = self.tests_added + self.tests_run
        changes_md = ("| Path | Type | +/- | Lang |\n|---|---|---|---|\n" + "\n".join(
            f"| `{x.path}` | {x.change_type} | +{x.lines_added}/-{x.lines_removed} | {x.language or '—'} |"
            for x in self.code_changes)) if self.code_changes else "_No code changes._"
        tests_md = ("| Test | Path | Status | Duration (ms) |\n|---|---|---|---|\n" + "\n".join(
            f"| `{t.test_id}` | `{t.path}` | {t.status} | {t.duration_ms} |" for t in tests)
        ) if tests else "_No tests recorded._"
        kg_md = "\n".join(
            f"- `{n.node_id}` ({n.node_type}, distance {n.impact_distance})" for n in self.kg_impact
        ) if self.kg_impact else "_Empty — sealing blocked for engineer role with code_changes._"
        verdict = f"\n> Auditor verdict: **{self.auditor_verdict}**" if self.auditor_verdict else ""
        worker = f"\n- Worker: `{r.worker_id}`" if r.worker_id else ""
        parent = f"\n- Parent directive: `{self.parent_directive_id}` (re-dispatch)" if self.parent_directive_id else ""
        return (
            f"# BuildArtifact `{self.directive_id}`\n\n"
            f"> Schema: `{self.version}` · Project: `{self.project_id}` · Role: `{self.role}` · "
            f"Status: **{self.status}** · Pipeline: `{self.pipeline_version}`{verdict}\n\n"
            f"## TL;DR\n{self.rationale}\n\n"
            f"## Code changes\n{changes_md}\n\n## Tests\n{tests_md}\n\n## KG impact\n{kg_md}\n\n"
            f"## Cost & runtime\n- Cost: **${c.cost_usd}** ({c.tier} tier, {c.model})\n"
            f"- Tokens: {c.tokens_input} in / {c.tokens_output} out\n"
            f"- Runtime: {r.duration_seconds}s ({r.started_at.isoformat()} → {r.completed_at.isoformat()}){worker}\n\n"
            f"## Metadata\n- Artifact UUID: `{self.artifact_uuid}`\n"
            f"- Created by: `{self.metadata.created_by}` at {self.metadata.created_at.isoformat()}{parent}\n"
            f"- Summary: {s['files_created']} created / {s['files_modified']} modified / "
            f"{s['files_deleted']} deleted; +{s['lines_added']}/-{s['lines_removed']} lines\n"
        )

    @classmethod
    def from_engineer_report(cls, **kw: Any) -> "BuildArtifact":
        """Convenience constructor for the engineer daemon (defaults status='draft')."""
        now = datetime.now(timezone.utc)
        kw.setdefault("phase", "build_in_progress")
        kw.setdefault("role", "engineer")
        kw.setdefault("status", "draft")
        for k in ("code_changes", "tests_added", "tests_run", "kg_impact"):
            kw.setdefault(k, [])
        kw.setdefault("metadata", ArtifactMetadata(
            created_by=kw.pop("created_by", "engineer"), created_at=now, last_modified=now))
        return cls(**kw)


__all__ = ["BuildArtifact", "BuildCost", "BuildRuntime", "CodeChange", "KGImpactNode", "TestRecord"]
