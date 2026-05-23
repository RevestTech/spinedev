"""Tests for canonical SDLC pipeline bridge helpers."""

from __future__ import annotations

from shared.api.routes._pipeline_bridge import (
    PHASE_BUILD_IN_PROGRESS,
    PHASE_PLAN_IN_PROGRESS,
    PHASE_RELEASED,
    PHASE_VERIFY_IN_PROGRESS,
    default_workspace_root,
    phase_bucket,
)


def test_phase_bucket_canonical_ids() -> None:
    assert phase_bucket("intake") == "intake"
    assert phase_bucket(PHASE_PLAN_IN_PROGRESS) == "plan"
    assert phase_bucket("plan_approved") == "plan"
    assert phase_bucket(PHASE_BUILD_IN_PROGRESS) == "build"
    assert phase_bucket("build_complete") == "build"
    assert phase_bucket(PHASE_VERIFY_IN_PROGRESS) == "verify"
    assert phase_bucket("verify_approved") == "verify"
    assert phase_bucket(PHASE_RELEASED) == "release"
    assert phase_bucket("operate") == "release"


def test_phase_bucket_legacy_shortcut_names() -> None:
    assert phase_bucket("plan") == "plan"
    assert phase_bucket("build") == "build"
    assert phase_bucket("verify") == "verify"
    assert phase_bucket("release") == "release"


def test_default_workspace_root_under_spine_work() -> None:
    root = default_workspace_root()
    # Without Hub mount or SPINE_PROJECTS_ROOT, falls back to repo .spine/work.
    assert root.name == "work"
    assert root.parent.name == ".spine"
