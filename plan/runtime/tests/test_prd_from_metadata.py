"""Tests for PRD synthesis from Hub metadata."""

from __future__ import annotations

from plan.runtime.prd_from_metadata import prd_from_project, swarm_project_type


def test_swarm_project_type_maps_feature_to_web_app() -> None:
    assert swarm_project_type({"project_type": "feature"}) == "web_app"


def test_prd_from_project_builds_valid_draft() -> None:
    prd = prd_from_project({
        "project_uuid": "00000000-0000-0000-0000-000000000001",
        "name": "Demo",
        "project_type": "feature",
        "metadata": {
            "description": "Build a todo app for solo founders.",
            "prd_md": "# PRD\n\nUsers need task tracking.",
        },
    })
    assert prd.project_id.endswith("0001")
    assert prd.project_name == "Demo"
    assert prd.goals.must
    assert prd.in_scope
    assert prd.acceptance_criteria
