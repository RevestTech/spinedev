"""Tests for per-role directive runtime."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shared.runtime.role_runtime import (
    append_directive_context,
    begin_directive,
    complete_directive,
    fail_directive,
)


@pytest.fixture
def repo_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    # role_runtime resolves .spine/work relative to repo root (parents[2]).
    # Patch by monkeypatching the module constant via chdir isn't ideal;
    # we only assert files appear under the real repo .spine/work tree.
    return tmp_path


def test_directive_lifecycle() -> None:
    uid = "test-proj-001"
    handle = begin_directive(uid, "planner", "PRODUCE_ROADMAP", "test@example.com")
    append_directive_context(handle, "## KG\n\n- node `a`")

    status_path = handle.workspace / "status.json"
    assert status_path.is_file()
    meta = json.loads(status_path.read_text(encoding="utf-8"))
    assert meta["status"] == "running"
    assert meta["role"] == "planner"

    complete_directive(handle, "# Roadmap\n\nDone.", ok=True)
    meta = json.loads(status_path.read_text(encoding="utf-8"))
    assert meta["status"] == "done"
    assert (handle.workspace / "report.md").read_text(encoding="utf-8").startswith("# Roadmap")

    handle2 = begin_directive(uid, "engineer", "PRODUCE_CODE")
    fail_directive(handle2, "LLM timeout")
    meta2 = json.loads((handle2.workspace / "status.json").read_text(encoding="utf-8"))
    assert meta2["status"] == "failed"
