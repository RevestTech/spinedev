"""Post-ack orchestrator wiring tests — golden path ack kinds."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from pathlib import Path

import pytest

from shared.api.routes import _post_ack


def _card(kind: str, project_uuid: str = "00000000-0000-0000-0000-00000000abcd") -> SimpleNamespace:
    return SimpleNamespace(
        decision_id="dec-test",
        project_id=None,
        metadata={"kind": kind, "project_uuid": project_uuid, "project_name": "Overnight"},
    )


def _project(project_uuid: str = "00000000-0000-0000-0000-00000000abcd") -> dict:
    return {
        "project_uuid": project_uuid,
        "name": "Overnight",
        "project_type": "feature",
        "metadata": {},
    }


def test_prd_approval_routes_through_orchestrator(monkeypatch: pytest.MonkeyPatch) -> None:
    kinds: list[str] = []

    async def fake_require(**kwargs):  # noqa: ANN003
        kinds.append(kwargs["kind"])

    async def fake_advance(*args, **kwargs):  # noqa: ANN003
        return None

    async def fake_load(pid: str):  # noqa: ANN001
        return _project(pid)

    monkeypatch.setattr(_post_ack, "_require_orchestrate_hub_role", fake_require)
    monkeypatch.setattr(_post_ack, "advance_lifecycle_phase", fake_advance)
    monkeypatch.setattr(_post_ack, "_load_project_full", fake_load)

    asyncio.run(_post_ack.on_decision_acked(_card("prd_approval"), actor="founder"))

    assert kinds == ["prd_approval"]


def test_orchestrator_gap_enqueued_when_bridge_misses(monkeypatch: pytest.MonkeyPatch) -> None:
    enqueued: list[dict] = []

    async def fake_orchestrate(**kwargs):  # noqa: ANN003
        return False

    def fake_enqueue(card: dict) -> None:
        enqueued.append(card)

    monkeypatch.setattr(_post_ack, "_orchestrate_hub_role", fake_orchestrate)
    monkeypatch.setattr(_post_ack, "_enqueue", fake_enqueue)
    monkeypatch.setattr(_post_ack, "_emit", lambda *a, **k: None)

    asyncio.run(
        _post_ack._enqueue_orchestrator_gap(
            kind="code_approval",
            project=_project(),
            expected_role="verify",
        )
    )

    assert enqueued
    assert enqueued[0]["metadata"]["kind"] == "orchestrator_gap"


def test_golden_path_ack_kinds_all_call_require(monkeypatch: pytest.MonkeyPatch) -> None:
    from shared.api.tests.test_golden_path_e2e import GOLDEN_PATH_ORCHESTRATOR_KINDS

    seen: list[str] = []

    async def fake_require(**kwargs):  # noqa: ANN003
        seen.append(kwargs["kind"])

    async def fake_advance(*args, **kwargs):  # noqa: ANN003
        return None

    async def fake_sequence(*args, **kwargs):  # noqa: ANN003
        return None

    async def fake_load(pid: str):  # noqa: ANN001
        return _project(pid)

    monkeypatch.setattr(_post_ack, "_require_orchestrate_hub_role", fake_require)
    monkeypatch.setattr(_post_ack, "advance_lifecycle_phase", fake_advance)
    monkeypatch.setattr(_post_ack, "advance_sequence", fake_sequence)
    monkeypatch.setattr(_post_ack, "_load_project_full", fake_load)

    for kind in GOLDEN_PATH_ORCHESTRATOR_KINDS:
        asyncio.run(_post_ack.on_decision_acked(_card(kind), actor="founder"))

    assert seen == list(GOLDEN_PATH_ORCHESTRATOR_KINDS)


def test_write_workspace_files_respects_spine_on_spine(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import shared.runtime.project_workspace as pw

    uid = "00000000-0000-0000-0000-000000000099"
    md = {"spine_on_spine": True}
    monkeypatch.setattr(pw, "_REPO_ROOT", tmp_path)

    written = _post_ack._write_workspace_files(uid, [("hello.txt", "hi")], md)

    assert written == 1
    target = tmp_path / ".spine" / "dogfood" / uid / "hello.txt"
    assert target.is_file()
    assert target.read_text(encoding="utf-8") == "hi"


def test_fit_card_body_truncates(monkeypatch: pytest.MonkeyPatch) -> None:
    long_body = "x" * 70000
    fitted = _post_ack._fit_card_body(long_body)
    assert len(fitted) <= 64000
    assert "truncated" in fitted


def test_detect_cli_container_cmd_prefers_smoke_script(tmp_path: Path) -> None:
    (tmp_path / "smoke_test.sh").write_text("#!/bin/bash\necho ok\n", encoding="utf-8")
    cmd = _post_ack._detect_cli_container_cmd(tmp_path, {})
    assert cmd == "bash smoke_test.sh"


def test_detect_cli_container_cmd_todo_demo(tmp_path: Path) -> None:
    (tmp_path / "todo.py").write_text("print('cli')\n", encoding="utf-8")
    cmd = _post_ack._detect_cli_container_cmd(tmp_path, {})
    assert cmd is not None
    assert "todo.py add" in cmd
