"""Tests for QA execution runtime (SPINE-004 / Operating-loop Stage 6)."""
from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

from verify.runtime.qa_execution_runner import (
    CommandRunOutcome,
    classify_test_commands,
    extract_acceptance_criteria,
    run_qa_execution,
)


def _project(**overrides: Any) -> dict[str, Any]:
    base = {
        "project_uuid": "22222222-2222-2222-2222-222222222222",
        "name": "qa-test-project",
        "metadata": {
            "sprint_plan_md": (
                "# Sprint plan — qa-test-project\n\n"
                "- **T-1** Auth endpoint — implement login.\n"
                "  Acceptance: POST /login returns 200 with token\n"
                "- **T-2** List endpoint — implement list.\n"
                "  Acceptance: GET /items returns JSON array\n"
            ),
            "code_run_block": (
                "npm install\n"
                "npm test\n"
                "npm start\n"
            ),
        },
    }
    base.update(overrides)
    if "metadata" in overrides:
        base["metadata"] = overrides["metadata"]
    return base


def test_extract_acceptance_criteria_from_task_cards() -> None:
    criteria = extract_acceptance_criteria(_project()["metadata"]["sprint_plan_md"])
    assert len(criteria) == 2
    assert criteria[0].task_id == "T-1"
    assert "POST /login" in criteria[0].description
    assert criteria[1].task_id == "T-2"


def test_extract_acceptance_criteria_fallback_lines() -> None:
    md = "Some plan\nAcceptance: user can sign in\nAcceptance: list loads"
    criteria = extract_acceptance_criteria(md)
    assert len(criteria) == 2
    assert criteria[0].task_id == "AC-1"
    assert "sign in" in criteria[0].description


def test_classify_test_commands_skips_install_and_start() -> None:
    commands = classify_test_commands(_project()["metadata"]["code_run_block"])
    assert commands == ["npm test"]


def test_classify_test_commands_keeps_verification_commands() -> None:
    run_block = "pip install -r requirements.txt\npytest -q\npython -m pytest tests/"
    commands = classify_test_commands(run_block)
    assert "pytest -q" in commands
    assert "python -m pytest tests/" in commands
    assert not any("pip install" in c for c in commands)


def test_missing_project_uuid_fails() -> None:
    result = run_qa_execution(_project(project_uuid=""))
    assert result.ok is False
    assert result.error_class == "missing_project_uuid"


def test_run_qa_execution_persists_metadata_on_pass() -> None:
    def fake_runner(_workspace: Path, commands: list[str]) -> list[CommandRunOutcome]:
        assert commands == ["npm test"]
        return [CommandRunOutcome(command="npm test", exit_code=0, output="ok")]

    persisted: dict[str, Any] = {}

    def fake_persist(_project_id: str, patch: dict[str, Any]) -> None:
        persisted.update(patch)

    with patch(
        "shared.runtime.project_workspace.resolve_code_dir",
        return_value=Path("/tmp/ws"),
    ), patch(
        "verify.runtime.qa_execution_runner._persist_metadata",
        side_effect=fake_persist,
    ), patch(
        "shared.runtime.role_activity.role_log",
    ), patch(
        "verify.runtime.qa_execution_runner._record_ledger_outcome",
    ), patch(
        "verify.runtime.qa_execution_runner._publish_qa_execution_event",
    ):
        result = run_qa_execution(_project(), command_runner=fake_runner)

    assert result.ok is True
    assert result.all_passed is True
    assert "QA PASS" in result.execution_md
    assert persisted["qa_execution_ok"] is True
    assert "qa_execution_md" in persisted
    assert persisted["qa_execution_commands"] == ["npm test"]


def test_run_qa_execution_marks_fail_when_command_fails() -> None:
    def fake_runner(_workspace: Path, _commands: list[str]) -> list[CommandRunOutcome]:
        return [CommandRunOutcome(command="npm test", exit_code=1, output="FAILURES")]

    with patch(
        "shared.runtime.project_workspace.resolve_code_dir",
        return_value=Path("/tmp/ws"),
    ), patch(
        "verify.runtime.qa_execution_runner._persist_metadata",
    ), patch(
        "shared.runtime.role_activity.role_log",
    ), patch(
        "verify.runtime.qa_execution_runner._record_ledger_outcome",
    ), patch(
        "verify.runtime.qa_execution_runner._publish_qa_execution_event",
    ):
        result = run_qa_execution(_project(), command_runner=fake_runner)

    assert result.ok is True
    assert result.all_passed is False
    assert result.commands_failed == 1
    assert "QA FAIL" in result.execution_md


def test_run_qa_execution_no_commands_with_criteria_fails() -> None:
    project = _project(metadata={
        "sprint_plan_md": "- **T-1** Task\n  Acceptance: something works",
        "code_run_block": "",
    })

    with patch(
        "shared.runtime.project_workspace.resolve_code_dir",
        return_value=Path("/tmp/ws"),
    ), patch(
        "verify.runtime.qa_execution_runner._persist_metadata",
    ), patch(
        "shared.runtime.role_activity.role_log",
    ), patch(
        "verify.runtime.qa_execution_runner._record_ledger_outcome",
    ), patch(
        "verify.runtime.qa_execution_runner._publish_qa_execution_event",
    ):
        result = run_qa_execution(project, command_runner=lambda _w, _c: [])

    assert result.all_passed is False
    assert "No test commands" in result.execution_md


def test_command_runner_exception_surfaces_as_error() -> None:
    def boom(_workspace: Path, _commands: list[str]) -> list[CommandRunOutcome]:
        raise RuntimeError("shell unavailable")

    with patch(
        "shared.runtime.project_workspace.resolve_code_dir",
        return_value=Path("/tmp/ws"),
    ), patch(
        "shared.runtime.role_activity.role_log",
    ):
        result = run_qa_execution(_project(), command_runner=boom)

    assert result.ok is False
    assert result.error_class == "RuntimeError"


async def _drain_for(q, expected_type: str, max_events: int = 4):
    import asyncio

    for _ in range(max_events):
        evt = await asyncio.wait_for(q.get(), timeout=1.0)
        if evt.event_type == expected_type:
            return evt
    raise AssertionError(f"never received event_type={expected_type!r}")


def test_realtime_qa_execution_event_publishes() -> None:
    import asyncio

    from shared.api.realtime.event_publisher import subscribe, unsubscribe

    def fake_runner(_workspace: Path, _commands: list[str]) -> list[CommandRunOutcome]:
        return [CommandRunOutcome(command="npm test", exit_code=0, output="ok")]

    async def body():
        q = subscribe("22222222-2222-2222-2222-222222222222")
        try:
            with patch(
                "shared.runtime.project_workspace.resolve_code_dir",
                return_value=Path("/tmp/ws"),
            ), patch(
                "verify.runtime.qa_execution_runner._persist_metadata",
            ), patch(
                "shared.runtime.role_activity.role_log",
            ), patch(
                "verify.runtime.qa_execution_runner._record_ledger_outcome",
            ):
                run_qa_execution(_project(), command_runner=fake_runner)
            await asyncio.sleep(0)
            evt = await _drain_for(q, "qa_execution_finished")
            assert evt.verdict == "ok"
            assert evt.payload["all_passed"] is True
        finally:
            unsubscribe(q)

    asyncio.run(body())
