"""Tests for ``build_dispatcher`` B4 bounded-retrieval opt-in.

Covers:
  * ``synthesize_minimal_build_brief`` ships only the top-N goals + a
    derived_from total so the role knows when to ask for more.
  * The minimal brief carries ``brief_mode=bounded_retrieval`` so
    downstream wrappers can branch.
  * ``resolve_build_brief_needs`` resolves ``project_metadata`` needs
    and returns graceful failures for KG / file / audit / ledger needs.
  * ``dispatch_build_bounded`` persists the minimal brief under
    ``METADATA_BRIEF_MINIMAL_KEY`` (distinct from the fat-brief key)
    and writes the right audit actions.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import patch

import pytest

from build.runtime.build_dispatcher import (
    DEFAULT_MINIMAL_BRIEF_TOP_GOALS,
    METADATA_BRIEF_KEY,
    METADATA_BRIEF_MINIMAL_KEY,
    METADATA_PRD_KEY,
    MINIMAL_BRIEF_VERSION,
    dispatch_build_bounded,
    resolve_build_brief_needs,
    synthesize_minimal_build_brief,
)
from plan.artifacts._base import (
    AcceptanceCriterion,
    ArtifactMetadata,
    Goal,
    OpenQuestion,
    ProjectType as PRDProjectType,
)
from plan.artifacts.prd_v1 import Goals, PRDv1, Stakeholder
from shared.runtime.bounded_retrieval import Need


# ─── shared fixture helpers ──────────────────────────────────────────


def _five_goal_prd() -> PRDv1:
    """Construct a PRDv1 with 5 engineering goals so truncation triggers."""
    now = datetime.now(timezone.utc)
    must = [
        Goal(id=f"G-M-{i}", statement=f"Implement MUST feature {i}.")
        for i in range(1, 6)
    ]
    return PRDv1(
        project_id="11111111-1111-1111-1111-111111111111",
        project_name="p",
        project_type=PRDProjectType.CLI_TOOL,
        problem_statement="A minimal PRD for B4 bounded-retrieval tests.",
        users_stakeholders=[Stakeholder(name="dev", needs="route by type")],
        goals=Goals(must=must, should=[], could=[]),
        in_scope=["routing"],
        out_of_scope=["everything else"],
        acceptance_criteria=[
            AcceptanceCriterion(
                id=f"AC-MUST-{i}",
                given="a work item",
                when="dispatch fires",
                then=f"MUST item delivered: Implement MUST feature {i}.",
            )
            for i in range(1, 6)
        ],
        open_questions=[
            OpenQuestion(
                id="OQ-1",
                question="defer",
                recommendation="defer",
            ),
        ],
        metadata=ArtifactMetadata(
            created_by="test", created_at=now, last_modified=now,
        ),
    )


def _project_row(prd: PRDv1) -> dict[str, Any]:
    """A project row in the shape ``_load_project`` returns."""
    return {
        "id": 42,
        "project_uuid": "11111111-1111-1111-1111-111111111111",
        "name": "auth-overhaul",
        "current_phase": "build_in_progress",
        "pipeline_version": "1.0.0",
        "work_item_type": "feature",
        "metadata": {
            METADATA_PRD_KEY: prd.model_dump(mode="json"),
            "intake": {
                "answers": {},
                "work_item_type": "feature",
            },
        },
    }


# ─── synthesize_minimal_build_brief ──────────────────────────────────


def test_minimal_brief_includes_only_top_goals() -> None:
    prd = _five_goal_prd()
    proj = _project_row(prd)

    brief = synthesize_minimal_build_brief(
        project=proj, prd=prd, actor="orchestrator",
        use_db_routing=False,
    )

    assert brief["version"] == MINIMAL_BRIEF_VERSION
    assert brief["metadata"]["brief_mode"] == "bounded_retrieval"
    assert len(brief["top_engineering_goals"]) == DEFAULT_MINIMAL_BRIEF_TOP_GOALS
    assert brief["derived_from"]["engineering_goals_total"] == 5
    assert brief["derived_from"]["engineering_goals_included"] == 3
    assert "need_channel_hint" in brief


def test_minimal_brief_respects_top_goals_override() -> None:
    prd = _five_goal_prd()
    proj = _project_row(prd)

    brief = synthesize_minimal_build_brief(
        project=proj, prd=prd, actor="orchestrator",
        top_goals=1, use_db_routing=False,
    )
    assert len(brief["top_engineering_goals"]) == 1


def test_minimal_brief_carries_prior_winner() -> None:
    prd = _five_goal_prd()
    proj = _project_row(prd)

    brief = synthesize_minimal_build_brief(
        project=proj, prd=prd, actor="orchestrator",
        prior_winner="EG-1:accepted", use_db_routing=False,
    )
    assert brief["prior_winner"] == "EG-1:accepted"


# ─── resolve_build_brief_needs ───────────────────────────────────────


def test_resolver_finds_project_metadata_path() -> None:
    prd = _five_goal_prd()
    proj = _project_row(prd)
    need = Need(type="project_metadata", ref="intake.work_item_type")

    resolved = resolve_build_brief_needs([need], project=proj)

    assert len(resolved) == 1
    assert resolved[0].success is True
    assert resolved[0].content == "feature"
    assert resolved[0].artifact is not None


def test_resolver_reports_missing_metadata_path() -> None:
    prd = _five_goal_prd()
    proj = _project_row(prd)
    need = Need(type="project_metadata", ref="intake.does.not.exist")

    resolved = resolve_build_brief_needs([need], project=proj)

    assert resolved[0].success is False
    assert "metadata path not found" in (resolved[0].error or "")


def test_resolver_returns_failure_for_kg_need() -> None:
    prd = _five_goal_prd()
    proj = _project_row(prd)
    need = Need(type="kg_node", ref="node-123")

    resolved = resolve_build_brief_needs([need], project=proj)

    assert resolved[0].success is False
    assert "side-channel resolver" in (resolved[0].error or "")


def test_resolver_handles_mixed_needs() -> None:
    prd = _five_goal_prd()
    proj = _project_row(prd)
    needs = [
        Need(type="project_metadata", ref="intake.work_item_type"),
        Need(type="kg_node", ref="node-x"),
        Need(type="audit_hash", ref="abcd"),
    ]

    resolved = resolve_build_brief_needs(needs, project=proj)

    assert [r.success for r in resolved] == [True, False, False]


def test_resolver_ignores_non_need_objects() -> None:
    prd = _five_goal_prd()
    proj = _project_row(prd)
    needs = ["not a need", Need(type="project_metadata", ref="intake")]

    resolved = resolve_build_brief_needs(needs, project=proj)

    # Only the Need is processed; the string is silently skipped.
    assert len(resolved) == 1
    assert resolved[0].success is True


# ─── dispatch_build_bounded ──────────────────────────────────────────


def test_dispatch_bounded_persists_minimal_brief() -> None:
    prd = _five_goal_prd()
    proj = _project_row(prd)
    merged: dict[str, Any] = {}

    def fake_merge(pid: int, patch: dict[str, Any]) -> None:
        merged.update(patch)

    def fake_audit(**_kwargs: Any) -> bool:
        return True

    with patch(
        "build.runtime.build_dispatcher._load_project", return_value=proj,
    ), patch(
        "build.runtime.build_dispatcher._merge_metadata", side_effect=fake_merge,
    ), patch(
        "build.runtime.build_dispatcher._write_audit", side_effect=fake_audit,
    ), patch(
        "build.runtime.build_dispatcher.route_for_work_item_type",
        return_value=("default_feature_pipeline", ["engineer", "qa"]),
    ):
        result = dispatch_build_bounded(42, actor="orchestrator")

    assert METADATA_BRIEF_MINIMAL_KEY in merged
    # Fat brief untouched in this path.
    assert METADATA_BRIEF_KEY not in merged
    brief = merged[METADATA_BRIEF_MINIMAL_KEY]
    assert brief["version"] == MINIMAL_BRIEF_VERSION
    assert result.engineering_goals_count == DEFAULT_MINIMAL_BRIEF_TOP_GOALS
    # 2 audit events: dispatched + brief_persisted.
    assert result.audit_event_count == 2


def test_dispatch_bounded_emits_warning_when_goals_truncated() -> None:
    prd = _five_goal_prd()
    proj = _project_row(prd)

    with patch(
        "build.runtime.build_dispatcher._load_project", return_value=proj,
    ), patch(
        "build.runtime.build_dispatcher._merge_metadata",
    ), patch(
        "build.runtime.build_dispatcher._write_audit", return_value=True,
    ), patch(
        "build.runtime.build_dispatcher.route_for_work_item_type",
        return_value=("default_feature_pipeline", ["engineer", "qa"]),
    ):
        result = dispatch_build_bounded(42, actor="orchestrator")

    assert any("minimal_brief" in w for w in result.warnings)
    assert any("need:project_metadata" in w for w in result.warnings)


def test_dispatch_bounded_no_warning_when_all_goals_fit() -> None:
    prd = _five_goal_prd()
    proj = _project_row(prd)

    with patch(
        "build.runtime.build_dispatcher._load_project", return_value=proj,
    ), patch(
        "build.runtime.build_dispatcher._merge_metadata",
    ), patch(
        "build.runtime.build_dispatcher._write_audit", return_value=True,
    ), patch(
        "build.runtime.build_dispatcher.route_for_work_item_type",
        return_value=("default_feature_pipeline", ["engineer", "qa"]),
    ):
        result = dispatch_build_bounded(
            42, actor="orchestrator", top_goals=10,
        )

    assert result.warnings == []
    assert result.engineering_goals_count == 5
