"""Tests for background role worker (SPINE-005)."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from shared.runtime.role_runtime import enqueue_directive
from shared.runtime.role_worker import (
    QueuedDirective,
    dispatch_queued_directive,
    role_worker_tick,
    scan_file_directives,
    worker_enabled,
)


@pytest.fixture
def work_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / ".spine" / "work"
    root.mkdir(parents=True)
    monkeypatch.setattr("shared.runtime.role_runtime._REPO_ROOT", tmp_path)
    return root


def test_worker_enabled_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SPINE_ROLE_WORKER", raising=False)
    assert worker_enabled() is False
    monkeypatch.setenv("SPINE_ROLE_WORKER", "1")
    assert worker_enabled() is True
    monkeypatch.setenv("SPINE_ROLE_WORKER", "off")
    assert worker_enabled() is False


def test_scan_file_directives_finds_pending(work_root: Path) -> None:
    handle = enqueue_directive("proj-a", "planner", "PRODUCE_ROADMAP", "test")
    found = scan_file_directives(work_root)
    assert len(found) == 1
    assert found[0].project_id == "proj-a"
    assert found[0].role == "planner"
    assert found[0].directive == "PRODUCE_ROADMAP"
    assert found[0].subsystem == "plan"
    assert found[0].workspace == handle.workspace


def test_scan_file_directives_ignores_done(work_root: Path) -> None:
    handle = enqueue_directive("proj-a", "planner", "PRODUCE_ROADMAP")
    meta = json.loads((handle.workspace / "status.json").read_text(encoding="utf-8"))
    meta["status"] = "done"
    (handle.workspace / "status.json").write_text(json.dumps(meta), encoding="utf-8")
    assert scan_file_directives(work_root) == []


def test_scan_file_directives_finds_stale_running(work_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shared.runtime.role_worker._STALE_RUNNING_SECS", 1.0)
    ws = work_root / "proj-b" / "directives" / "dir_stale01"
    ws.mkdir(parents=True)
    old = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
    meta = {
        "directive_id": "dir_stale01",
        "project_uuid": "proj-b",
        "role": "engineer",
        "directive": "PRODUCE_CODE",
        "status": "running",
        "started_at": old,
    }
    (ws / "status.json").write_text(json.dumps(meta), encoding="utf-8")

    found = scan_file_directives(work_root)
    assert len(found) == 1
    assert found[0].role == "engineer"
    assert found[0].subsystem == "build"


def test_dispatch_queued_directive_file_bus(
    work_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handle = enqueue_directive("proj-c", "conductor", "PRODUCE_SPRINT_PLAN")

    async def fake_pipeline(_pid: str) -> str:
        return "1"

    def fake_invoke(tool: str, payload: dict) -> dict:
        assert tool == "plan_dispatch"
        assert payload["role"] == "conductor"
        assert payload["project_id"] == "proj-c"
        return {"status": "ok", "data": {"directive_id": "dir_exec01"}}

    monkeypatch.setattr("shared.runtime.role_worker._load_pipeline_version", fake_pipeline)
    monkeypatch.setattr("shared.runtime.mcp_invoke.invoke_mcp_tool", fake_invoke)

    item = QueuedDirective(
        source="file",
        project_id="proj-c",
        role="conductor",
        directive="PRODUCE_SPRINT_PLAN",
        subsystem="plan",
        workspace=handle.workspace,
    )
    ok = asyncio.run(dispatch_queued_directive(item))
    assert ok is True

    meta = json.loads((handle.workspace / "status.json").read_text(encoding="utf-8"))
    assert meta["status"] == "done"
    assert meta["claimed_by"] == "role_worker"
    assert (handle.workspace / "report.md").is_file()


def test_role_worker_tick_dispatches_pending(
    work_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enqueue_directive("proj-d", "qa", "PRODUCE_TEST_PLAN")

    monkeypatch.setattr("shared.runtime.role_worker.scan_db_directives", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        "shared.runtime.role_worker._load_pipeline_version",
        AsyncMock(return_value="1"),
    )
    monkeypatch.setattr(
        "shared.runtime.mcp_invoke.invoke_mcp_tool",
        lambda tool, payload: {"status": "ok", "data": {"directive_id": "dir_x"}},
    )

    count = asyncio.run(role_worker_tick())
    assert count == 1


def test_dispatch_db_queue_marks_dispatched(monkeypatch: pytest.MonkeyPatch) -> None:
    marked: list[int] = []

    async def fake_can_dispatch(_pid: str) -> bool:
        return True

    async def fake_mark(qid: int) -> None:
        marked.append(qid)

    monkeypatch.setattr("shared.runtime.role_worker._can_dispatch_project", fake_can_dispatch)
    monkeypatch.setattr("shared.runtime.role_worker._mark_db_dispatched", fake_mark)
    monkeypatch.setattr(
        "shared.runtime.role_worker._load_pipeline_version",
        AsyncMock(return_value="2"),
    )
    monkeypatch.setattr(
        "shared.runtime.mcp_invoke.invoke_mcp_tool",
        lambda tool, payload: {"status": "ok", "data": {}},
    )

    item = QueuedDirective(
        source="db",
        project_id="uuid-123",
        role="engineer",
        directive="PRODUCE_CODE",
        subsystem="build",
        queue_id=42,
    )
    ok = asyncio.run(dispatch_queued_directive(item))
    assert ok is True
    assert marked == [42]


def test_dispatch_db_skips_when_at_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "shared.runtime.role_worker._can_dispatch_project",
        AsyncMock(return_value=False),
    )
    invoked = {"count": 0}

    def fake_invoke(tool: str, payload: dict) -> dict:
        invoked["count"] += 1
        return {"status": "ok", "data": {}}

    monkeypatch.setattr("shared.runtime.mcp_invoke.invoke_mcp_tool", fake_invoke)

    item = QueuedDirective(
        source="db",
        project_id="uuid-999",
        role="engineer",
        directive="PRODUCE_CODE",
        subsystem="build",
        queue_id=7,
    )
    ok = asyncio.run(dispatch_queued_directive(item))
    assert ok is False
    assert invoked["count"] == 0
