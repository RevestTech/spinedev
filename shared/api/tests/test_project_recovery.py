"""Tests for manual pipeline recovery actions."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from shared.api.routes import _project_recovery


def _build_project(**overrides) -> dict:
    base = {
        "project_uuid": "00000000-0000-0000-0000-00000000abcd",
        "name": "Test",
        "project_type": "feature",
        "current_phase": "build_in_progress",
        "metadata": {
            "prd_md": "# PRD",
            "roadmap_md": "# Roadmap",
            "trd_md": "# TRD",
            "sprint_plan_md": "# Sprint",
            "code_intro_md": "# Code",
            "code_review_md": "# Blocked",
            "code_review_blocked": True,
        },
    }
    base.update(overrides)
    if "metadata" in overrides:
        base["metadata"] = overrides["metadata"]
    return base


def test_action_specs_include_remediate_when_blocked() -> None:
    specs = _project_recovery._action_specs(_build_project())
    actions = {s.action for s in specs}
    assert "retry_engineer_remediate" in actions
    assert "retry_code_review" in actions
    assert "resume" in actions


def test_pick_resume_prefers_remediate_when_blocked() -> None:
    assert _project_recovery._pick_resume_action(_build_project()) == "retry_engineer_remediate"


def test_action_specs_omit_remediate_when_exhausted() -> None:
    project = _build_project(
        metadata={
            "code_intro_md": "# Code",
            "code_review_md": "# Blocked",
            "code_review_blocked": True,
            "code_fix_iteration": 3,
        },
    )
    specs = _project_recovery._action_specs(project)
    actions = {s.action for s in specs}
    assert "retry_engineer_remediate" not in actions
    assert "retry_code_review" in actions


def test_fix_loop_exhausted_blocks_manual_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    project = _build_project(
        metadata={
            "code_intro_md": "# Code",
            "code_review_md": "# Blocked",
            "code_review_blocked": True,
            "code_fix_iteration": 3,
        },
    )
    monkeypatch.setattr(
        _project_recovery,
        "_load_project_full",
        AsyncMock(return_value=project),
    )
    result = asyncio.run(
        _project_recovery.recovery_dispatch(
            "00000000-0000-0000-0000-00000000abcd",
            "retry_engineer_remediate",
            actor="founder",
        )
    )
    assert result["ok"] is False
    assert result["error"] == "fix_loop_exhausted"


def test_stuck_reasons_include_fix_loop_exhausted() -> None:
    project = _build_project(
        metadata={
            "code_intro_md": "# Code",
            "code_review_md": "# Blocked",
            "code_review_blocked": True,
            "code_fix_iteration": 3,
        },
    )
    reasons = _project_recovery._stuck_reasons(project, pending=0)
    assert "fix_loop_exhausted" in reasons
    assert "code_review_blocked" not in reasons


def test_retry_action_for_failed_engineer_remediate() -> None:
    assert (
        _project_recovery.retry_action_for_dispatch_kind("code_review_blocked")
        == "retry_engineer_remediate"
    )


def test_recovery_dispatch_rejects_unknown_action(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        _project_recovery,
        "_load_project_full",
        AsyncMock(return_value=_build_project(current_phase="released", metadata={})),
    )
    result = asyncio.run(
        _project_recovery.recovery_dispatch(
            "00000000-0000-0000-0000-00000000abcd",
            "retry_engineer",
            actor="founder",
        )
    )
    assert result["ok"] is False
    assert result["error"] == "action_not_allowed"


def test_recovery_dispatch_resume_picks_remediate(monkeypatch: pytest.MonkeyPatch) -> None:
    orchestrate = AsyncMock(return_value=True)
    persist = AsyncMock()
    created: list = []

    def fake_create_task(coro):  # noqa: ANN001
        created.append(coro)
        return AsyncMock()

    monkeypatch.setattr(
        _project_recovery,
        "_load_project_full",
        AsyncMock(return_value=_build_project()),
    )
    monkeypatch.setattr(_project_recovery, "_orchestrate_hub_role", orchestrate)
    monkeypatch.setattr(_project_recovery, "_persist_metadata_patch", persist)
    monkeypatch.setattr(_project_recovery.asyncio, "create_task", fake_create_task)

    result = asyncio.run(
        _project_recovery.recovery_dispatch(
            "00000000-0000-0000-0000-00000000abcd",
            "resume",
            actor="founder",
            note="fix jest",
        )
    )

    assert result["ok"] is True
    assert result["async"] is True
    assert result["action"] == "retry_engineer_remediate"
    assert len(created) == 1
    persist.assert_awaited()
    asyncio.run(created[0])
    orchestrate.assert_awaited_once()
    call = orchestrate.await_args.kwargs
    assert call["kind"] == "code_review_blocked"
    assert "fix jest" in call["extra"]["extra_context"]
