"""Integration tests for Harness Lite loop-bridge."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

HARNESS_ROOT = Path(__file__).resolve().parents[1]
HARNESS_LIB = HARNESS_ROOT / "lib"
LOOP_BRIDGE = HARNESS_ROOT / "loop-bridge.sh"
SPINE_HARNESS = HARNESS_ROOT / "spine-harness"

sys.path.insert(0, str(HARNESS_LIB))

from harness_state import init_harness, read_state  # noqa: E402


@pytest.fixture()
def project_tmp(tmp_path: Path) -> Path:
    init_harness(tmp_path)
    return tmp_path


def _run(cmd: list[str], *, cwd: Path | None = None, timeout: float = 15) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "SPINE_HOME": str(Path(__file__).resolve().parents[3])}
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=cwd,
        env=env,
    )


def test_loop_bridge_start_emits_immediate_tick(project_tmp: Path) -> None:
    result = _run(
        [
            str(LOOP_BRIDGE),
            "start",
            "--project",
            str(project_tmp),
            "--mode",
            "release-gate",
            "--interval",
            "30s",
        ]
    )
    assert result.returncode == 0
    assert "loop-bridge: immediate tick" in result.stdout
    assert "AGENT_LOOP_WAKE_harness_release-gate" in result.stdout
    assert "harness-verify-wave" in result.stdout or "verify-wave" in result.stdout

    state = read_state(project_tmp)
    assert state["active_loops"]
    pid = state["active_loops"][0]["pid"]
    assert (project_tmp / ".spine" / "harness" / "loops" / f"{state['active_loops'][0]['purpose']}.pid").is_file()

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        pytest.fail(f"loop pid {pid} not running after start")

    stop = _run([str(LOOP_BRIDGE), "stop", "--project", str(project_tmp)])
    assert stop.returncode == 0
    assert "stopped pid" in stop.stdout


def test_loop_bridge_stop_clears_pid_files(project_tmp: Path) -> None:
    _run(
        [
            str(LOOP_BRIDGE),
            "start",
            "--project",
            str(project_tmp),
            "--mode",
            "watch",
            "--interval",
            "30s",
        ]
    )
    loops_dir = project_tmp / ".spine" / "harness" / "loops"
    assert any(loops_dir.glob("*.pid"))

    _run([str(LOOP_BRIDGE), "stop", "--project", str(project_tmp)])
    assert not any(loops_dir.glob("*.pid"))


def test_spine_harness_stop_kills_registered_loops(project_tmp: Path) -> None:
    _run(
        [
            str(LOOP_BRIDGE),
            "start",
            "--project",
            str(project_tmp),
            "--mode",
            "feature",
            "--event",
            "git",
            "--dynamic",
        ]
    )
    state = read_state(project_tmp)
    pids = [loop["pid"] for loop in state["active_loops"]]
    assert pids

    result = _run([str(SPINE_HARNESS), "stop", "--project", str(project_tmp)])
    assert result.returncode == 0

    for pid in pids:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            continue
        pytest.fail(f"pid {pid} still alive after spine-harness stop")

    state = read_state(project_tmp)
    assert state["active_loops"] == []


def test_init_refreshes_project_root(project_tmp: Path) -> None:
    stale = read_state(project_tmp)
    stale["project_root"] = "/stale/path"
    from harness_state import write_state

    write_state(project_tmp, stale)
    init_harness(project_tmp)
    assert read_state(project_tmp)["project_root"] == str(project_tmp.resolve())
