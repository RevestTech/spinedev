"""Per-type pipeline routing tests for ``build/runtime/build_dispatcher.py``.

Wave-2 Squad-2 deliverable. Exercises:

* :func:`route_for_work_item_type` for each of 7 types, with DB lookup
  disabled (forces the in-process fallback path used by tests + offline).
* The new :class:`BuildBrief` Pydantic model + its ``implementer_kind`` /
  ``autonomy_tier`` defaults per #13.
* The synthesized brief from :func:`synthesize_build_brief` carries
  ``work_item_type`` + ``pipeline_id`` + ``role_set`` + the #13 fields.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from build.runtime.build_dispatcher import (
    DEFAULT_AUTONOMY_TIER,
    DEFAULT_IMPLEMENTER_KIND,
    BuildBrief,
    _TYPE_PIPELINE_FALLBACK,
    _TYPE_ROLE_FALLBACK,
    route_for_work_item_type,
    synthesize_build_brief,
)
from shared.schemas.build.work_item import WORK_ITEM_TYPES

# ── Fallback routing ─────────────────────────────────────────────────


@pytest.mark.parametrize("work_item_type", WORK_ITEM_TYPES)
def test_route_for_each_type_via_fallback(work_item_type: str) -> None:
    """With use_db=False, every type should resolve via the fallback dicts."""
    pipeline_id, role_set = route_for_work_item_type(work_item_type, use_db=False)
    assert pipeline_id == _TYPE_PIPELINE_FALLBACK[work_item_type]
    assert role_set == list(_TYPE_ROLE_FALLBACK[work_item_type])


def test_route_for_unknown_type_raises() -> None:
    with pytest.raises(ValueError):
        route_for_work_item_type("epic", use_db=False)


def test_route_falls_back_when_db_lookup_returns_none() -> None:
    """If _lookup_type_registry returns None, fallback must still resolve."""
    with patch("build.runtime.build_dispatcher._lookup_type_registry",
               return_value=None):
        pipeline_id, role_set = route_for_work_item_type("incident", use_db=True)
    assert pipeline_id == _TYPE_PIPELINE_FALLBACK["incident"]
    assert role_set == list(_TYPE_ROLE_FALLBACK["incident"])


def test_route_uses_db_value_when_present() -> None:
    """DB lookup wins over fallback when it returns a value."""
    with patch("build.runtime.build_dispatcher._lookup_type_registry",
               return_value=("custom_pipeline_v2", ["custom_role"])):
        pipeline_id, role_set = route_for_work_item_type("infra", use_db=True)
    assert pipeline_id == "custom_pipeline_v2"
    assert role_set == ["custom_role"]


# ── BuildBrief Pydantic ──────────────────────────────────────────────


def test_build_brief_defaults_match_13_decision() -> None:
    """#13: implementer_kind defaults to claude_code; autonomy_tier=low."""
    brief = BuildBrief(
        brief_id="b1", project_id="proj-uuid",
        project_name="P", pipeline_version="1.0.0",
    )
    assert brief.work_item_type == "feature"
    assert brief.pipeline_id == _TYPE_PIPELINE_FALLBACK["feature"]
    assert brief.role_set == list(_TYPE_ROLE_FALLBACK["feature"])
    assert brief.implementer_kind == DEFAULT_IMPLEMENTER_KIND == "claude_code"
    assert brief.autonomy_tier == DEFAULT_AUTONOMY_TIER == "low"


def test_build_brief_accepts_all_implementer_kinds() -> None:
    for kind in ("claude_code", "cursor", "aider", "openhands", "human"):
        brief = BuildBrief(
            brief_id="b", project_id="p", project_name="P",
            pipeline_version="1.0.0", implementer_kind=kind,  # type: ignore[arg-type]
        )
        assert brief.implementer_kind == kind


def test_build_brief_accepts_all_autonomy_tiers() -> None:
    for tier in ("low", "medium", "high"):
        brief = BuildBrief(
            brief_id="b", project_id="p", project_name="P",
            pipeline_version="1.0.0", autonomy_tier=tier,  # type: ignore[arg-type]
        )
        assert brief.autonomy_tier == tier


def test_build_brief_rejects_unknown_work_item_type() -> None:
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        BuildBrief(
            brief_id="b", project_id="p", project_name="P",
            pipeline_version="1.0.0", work_item_type="epic",  # type: ignore[arg-type]
        )


# ── synthesize_build_brief integration ────────────────────────────────


def _minimal_prd():
    """Construct a minimal PRDv1 just rich enough to feed synthesize_build_brief."""
    from plan.artifacts._base import (
        AcceptanceCriterion, ArtifactMetadata, Goal, OpenQuestion,
        ProjectType as PRDProjectType,
    )
    from plan.artifacts.prd_v1 import Goals, PRDv1, Stakeholder
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    return PRDv1(
        project_id="11111111-1111-1111-1111-111111111111",
        project_name="p",
        project_type=PRDProjectType.CLI_TOOL,
        problem_statement="A minimal PRD for routing tests with enough substance.",
        users_stakeholders=[Stakeholder(name="dev", needs="route by type")],
        goals=Goals(
            must=[Goal(id="G-M-1", statement="Route per work-item type cleanly.")],
            should=[], could=[],
        ),
        in_scope=["routing"], out_of_scope=["everything else"],
        acceptance_criteria=[AcceptanceCriterion(
            id="AC-MUST-1", given="a work item",
            when="dispatch fires",
            then="MUST item delivered: Route per work-item type cleanly.",
        )],
        open_questions=[OpenQuestion(
            id="OQ-1",
            question="Does the dispatcher need per-type role-set overrides?",
            recommendation="defer",
        )],
        metadata=ArtifactMetadata(created_by="test", created_at=now,
                                  last_modified=now),
    )


@pytest.mark.parametrize("work_item_type", WORK_ITEM_TYPES)
def test_synthesize_brief_carries_type_routing(work_item_type: str) -> None:
    project: dict[str, Any] = {
        "id": 1,
        "project_uuid": "11111111-1111-1111-1111-111111111111",
        "name": "p",
        "current_phase": "build_in_progress",
        "pipeline_version": "1.0.0",
        "work_item_type": work_item_type,
        "metadata": {"intake": {"answers": {}}},
    }
    brief = synthesize_build_brief(
        project=project, prd=_minimal_prd(),
        actor="test", use_db_routing=False,
    )
    assert brief["work_item_type"] == work_item_type
    assert brief["pipeline_id"] == _TYPE_PIPELINE_FALLBACK[work_item_type]
    assert brief["role_set"] == list(_TYPE_ROLE_FALLBACK[work_item_type])
    assert brief["implementer_kind"] == DEFAULT_IMPLEMENTER_KIND
    assert brief["autonomy_tier"] == DEFAULT_AUTONOMY_TIER
    # And it should typecheck through the BuildBrief model.
    BuildBrief.model_validate({
        "brief_id": brief["brief_id"], "project_id": brief["project_id"],
        "project_name": brief["project_name"],
        "pipeline_version": brief["pipeline_version"],
        "work_item_type": brief["work_item_type"],
        "pipeline_id": brief["pipeline_id"],
        "role_set": brief["role_set"],
        "implementer_kind": brief["implementer_kind"],
        "autonomy_tier": brief["autonomy_tier"],
    })


def test_synthesize_brief_picks_up_intake_implementer_overrides() -> None:
    project: dict[str, Any] = {
        "id": 1,
        "project_uuid": "11111111-1111-1111-1111-111111111111",
        "name": "p", "current_phase": "build_in_progress",
        "pipeline_version": "1.0.0",
        "work_item_type": "feature",
        "metadata": {"intake": {"answers": {
            "implementer_kind": "aider",
            "autonomy_tier": "medium",
        }}},
    }
    brief = synthesize_build_brief(
        project=project, prd=_minimal_prd(),
        actor="test", use_db_routing=False,
    )
    assert brief["implementer_kind"] == "aider"
    assert brief["autonomy_tier"] == "medium"


def test_synthesize_brief_defaults_to_feature_when_type_absent() -> None:
    project: dict[str, Any] = {
        "id": 1,
        "project_uuid": "11111111-1111-1111-1111-111111111111",
        "name": "p", "current_phase": "build_in_progress",
        "pipeline_version": "1.0.0",
        # work_item_type intentionally absent — must default to 'feature'.
        "metadata": {},
    }
    brief = synthesize_build_brief(
        project=project, prd=_minimal_prd(),
        actor="test", use_db_routing=False,
    )
    assert brief["work_item_type"] == "feature"
    assert brief["pipeline_id"] == _TYPE_PIPELINE_FALLBACK["feature"]
