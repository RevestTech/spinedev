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


def test_action_specs_include_manual_remediate_when_exhausted() -> None:
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
    assert "retry_engineer_remediate" in actions
    assert "retry_code_review" in actions


def test_pick_resume_prefers_code_review_when_exhausted() -> None:
    project = _build_project(
        metadata={
            "code_intro_md": "# Code",
            "code_review_md": "# Blocked",
            "code_review_blocked": True,
            "code_fix_iteration": 3,
        },
    )
    assert _project_recovery._pick_resume_action(project) == "retry_code_review"


def test_fix_loop_exhausted_allows_manual_remediate_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    project = _build_project(
        metadata={
            "code_intro_md": "# Code",
            "code_review_md": "# Blocked",
            "code_review_blocked": True,
            "code_fix_iteration": 3,
        },
    )
    persist = AsyncMock()
    created: list = []

    def fake_create_task(coro):  # noqa: ANN001
        created.append(coro)
        return AsyncMock()

    monkeypatch.setattr(
        _project_recovery,
        "_load_project_full",
        AsyncMock(return_value=project),
    )
    monkeypatch.setattr(_project_recovery, "_persist_metadata_patch", persist)
    monkeypatch.setattr(_project_recovery.asyncio, "create_task", fake_create_task)

    result = asyncio.run(
        _project_recovery.recovery_dispatch(
            "00000000-0000-0000-0000-00000000abcd",
            "retry_engineer_remediate",
            actor="founder",
        )
    )
    assert result["ok"] is True
    assert result["action"] == "retry_engineer_remediate"
    assert len(created) == 1


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
    assert (
        _project_recovery.retry_action_for_dispatch_kind("security_review_blocked")
        == "retry_engineer_remediate"
    )


def test_security_review_blocked_has_orchestrator_bridge() -> None:
    from shared.api.routes._role_dispatch_bridge import KIND_ROLE_DISPATCH

    assert "security_review_blocked" in KIND_ROLE_DISPATCH
    assert KIND_ROLE_DISPATCH["security_review_blocked"].directive == "REMEDIATE_FROM_REVIEW"


def test_auto_remediate_dedupes_concurrent_schedules(monkeypatch: pytest.MonkeyPatch) -> None:
    scheduled: list = []

    def fake_schedule(coro):  # noqa: ANN001
        scheduled.append(coro)
        return True

    monkeypatch.setattr(_project_recovery, "_schedule_hub_task", fake_schedule)
    _project_recovery._AUTO_REMEDIATE_SCHEDULED.clear()

    _project_recovery.schedule_auto_engineer_remediate("proj-a")
    _project_recovery.schedule_auto_engineer_remediate("proj-a")

    assert len(scheduled) == 1
    assert "proj-a" in _project_recovery._AUTO_REMEDIATE_SCHEDULED


def test_auto_remediate_retries_when_dispatch_in_flight(monkeypatch: pytest.MonkeyPatch) -> None:
    dispatch = AsyncMock(
        side_effect=[
            {"ok": False, "error": "dispatch_in_flight"},
            {"ok": True, "action": "retry_engineer_remediate"},
        ],
    )
    monkeypatch.setattr(_project_recovery, "recovery_dispatch", dispatch)
    monkeypatch.setattr(_project_recovery.asyncio, "sleep", AsyncMock())

    def run_immediately(coro):  # noqa: ANN001
        asyncio.run(coro)
        return True

    monkeypatch.setattr(_project_recovery, "_schedule_hub_task", run_immediately)
    _project_recovery._AUTO_REMEDIATE_SCHEDULED.clear()

    _project_recovery.schedule_auto_engineer_remediate(
        "00000000-0000-0000-0000-00000000abcd",
    )

    assert dispatch.await_count == 2
    assert "00000000-0000-0000-0000-00000000abcd" not in _project_recovery._AUTO_REMEDIATE_SCHEDULED


def test_recovery_dispatch_skips_duplicate_auto_remediate(monkeypatch: pytest.MonkeyPatch) -> None:
    from datetime import UTC, datetime

    project = _build_project(
        metadata={
            "code_intro_md": "# Code",
            "code_review_md": "# Blocked",
            "code_review_blocked": True,
            "recovery_dispatch_in_flight": {
                "action": "retry_engineer_remediate",
                "dispatch_kind": "code_review_blocked",
                "started_at": datetime.now(UTC).isoformat(),
            },
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
            actor="hub",
            auto_loop=True,
        )
    )

    assert result["ok"] is True
    assert result.get("skipped") is True


def test_recovery_status_clears_stale_inflight(monkeypatch: pytest.MonkeyPatch) -> None:
    from datetime import UTC, datetime, timedelta

    stale_start = (datetime.now(UTC) - timedelta(minutes=6)).isoformat()
    project = _build_project(
        metadata={
            "code_intro_md": "# Code",
            "code_review_md": "# Blocked",
            "code_review_blocked": True,
            "code_fix_iteration": 3,
            "recovery_dispatch_in_flight": {
                "action": "retry_code_review",
                "dispatch_kind": "code_approval",
                "started_at": stale_start,
            },
        },
    )
    persist = AsyncMock()
    pulse = AsyncMock()
    monkeypatch.setattr(
        _project_recovery,
        "_load_project_full",
        AsyncMock(return_value=project),
    )
    monkeypatch.setattr(_project_recovery, "_persist_metadata_patch", persist)
    monkeypatch.setattr(_project_recovery, "publish_recovery_pulse", pulse)

    result = asyncio.run(
        _project_recovery.recovery_status("00000000-0000-0000-0000-00000000abcd")
    )

    assert result["dispatch_in_flight"] is None
    persist.assert_awaited_once_with(
        "00000000-0000-0000-0000-00000000abcd",
        {"recovery_dispatch_in_flight": None},
    )
    pulse.assert_awaited()


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


def test_action_specs_include_reset_fix_loop_when_exhausted() -> None:
    project = _build_project(
        metadata={
            "code_intro_md": "# Code",
            "code_review_md": "# Blocked",
            "code_review_blocked": True,
            "code_fix_iteration": 3,
        },
    )
    actions = {s.action for s in _project_recovery._action_specs(project)}
    assert "reset_fix_loop" in actions


def test_reset_fix_loop_clears_counter(monkeypatch: pytest.MonkeyPatch) -> None:
    project = _build_project(
        metadata={
            "code_intro_md": "# Code",
            "code_review_md": "# Blocked",
            "code_review_blocked": True,
            "code_fix_iteration": 3,
        },
    )
    persist = AsyncMock()
    pulse = AsyncMock()
    monkeypatch.setattr(
        _project_recovery,
        "_load_project_full",
        AsyncMock(return_value=project),
    )
    monkeypatch.setattr(_project_recovery, "_persist_metadata_patch", persist)
    monkeypatch.setattr(_project_recovery, "publish_recovery_pulse", pulse)

    result = asyncio.run(
        _project_recovery.recovery_dispatch(
            "00000000-0000-0000-0000-00000000abcd",
            "reset_fix_loop",
            actor="founder",
        )
    )

    assert result["ok"] is True
    assert result["action"] == "reset_fix_loop"
    persist.assert_awaited_once_with(
        "00000000-0000-0000-0000-00000000abcd",
        {"code_review_blocked": False, "code_fix_iteration": 0},
    )
    pulse.assert_awaited_once()


def test_remediate_dispatch_does_not_increment_at_start(monkeypatch: pytest.MonkeyPatch) -> None:
    project = _build_project(
        metadata={
            "code_intro_md": "# Code",
            "code_review_md": "# Blocked",
            "code_review_blocked": True,
            "code_fix_iteration": 1,
        },
    )
    persist = AsyncMock()
    created: list = []

    def fake_create_task(coro):  # noqa: ANN001
        created.append(coro)
        return AsyncMock()

    monkeypatch.setattr(
        _project_recovery,
        "_load_project_full",
        AsyncMock(return_value=project),
    )
    monkeypatch.setattr(_project_recovery, "_persist_metadata_patch", persist)
    monkeypatch.setattr(_project_recovery.asyncio, "create_task", fake_create_task)

    result = asyncio.run(
        _project_recovery.recovery_dispatch(
            "00000000-0000-0000-0000-00000000abcd",
            "retry_engineer_remediate",
            actor="founder",
        )
    )

    assert result["ok"] is True
    for call in persist.await_args_list:
        patch = call.args[1]
        assert "code_fix_iteration" not in patch


def test_increment_code_fix_iteration_once(monkeypatch: pytest.MonkeyPatch) -> None:
    project = _build_project(metadata={"code_fix_iteration": 2})
    persist = AsyncMock()
    monkeypatch.setattr(
        _project_recovery,
        "_load_project_full",
        AsyncMock(return_value=project),
    )
    monkeypatch.setattr(_project_recovery, "_persist_metadata_patch", persist)

    n = asyncio.run(
        _project_recovery.increment_code_fix_iteration("00000000-0000-0000-0000-00000000abcd")
    )

    assert n == 3
    persist.assert_awaited_once_with(
        "00000000-0000-0000-0000-00000000abcd",
        {"code_fix_iteration": 3},
    )


def test_publish_recovery_pulse_emits_sse(monkeypatch: pytest.MonkeyPatch) -> None:
    published: list[dict] = []
    monkeypatch.setattr(
        _project_recovery,
        "recovery_status",
        AsyncMock(
            return_value={
                "ok": True,
                "stuck": False,
                "reasons": [],
                "pending_decisions": 1,
                "recommended_action": "retry_engineer_remediate",
                "last_role_failure": None,
                "dispatch_in_flight": None,
                "actions": [],
                "code_fix_iteration": 2,
                "max_code_fix_iterations": 3,
                "fix_loop_exhausted": False,
                "current_phase": "build_in_progress",
                "workspace_files_on_disk": 12,
            },
        ),
    )

    def fake_publish_event(payload: dict) -> None:
        published.append(payload)

    monkeypatch.setattr("shared.api.routes.decisions.publish_event", fake_publish_event)

    asyncio.run(
        _project_recovery.publish_recovery_pulse("00000000-0000-0000-0000-00000000abcd")
    )

    assert len(published) == 1
    assert published[0]["type"] == "recovery_pulse"
    assert published[0]["project_uuid"] == "00000000-0000-0000-0000-00000000abcd"
    assert published[0]["pending_decisions"] == 1
    assert published[0]["workspace_files_on_disk"] == 12


def test_complete_and_promote_feature_requests() -> None:
    md = {
        "feature_requests": [
            {"status": "completed", "feature": "cart", "priority": 0},
            {"status": "in_progress", "feature": "quiz", "priority": 1},
            {"status": "backlog", "feature": "mix bag", "priority": 2},
            {"status": "backlog", "feature": "gift", "priority": 3},
        ],
    }
    done = _project_recovery.complete_active_feature_request_patch(md)
    merged = {**md, **done}
    assert merged["feature_requests"][1]["status"] == "completed"
    promoted = _project_recovery.promote_next_feature_request_patch(merged)
    requests = promoted["feature_requests"]
    assert requests[2]["status"] == "requested"
    assert requests[3]["status"] == "backlog"


def test_feature_request_has_orchestrator_bridge() -> None:
    from shared.api.routes._role_dispatch_bridge import KIND_ROLE_DISPATCH

    assert "feature_request" in KIND_ROLE_DISPATCH
    assert KIND_ROLE_DISPATCH["feature_request"].role == "engineer"
