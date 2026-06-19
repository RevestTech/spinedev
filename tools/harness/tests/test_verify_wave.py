"""Tests for Harness Lite verify-wave."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

HARNESS_LIB = Path(__file__).resolve().parents[1] / "lib"
sys.path.insert(0, str(HARNESS_LIB))

from harness_state import init_harness, read_state  # noqa: E402
from verify_wave import (  # noqa: E402
    DEFAULT_LITE_ROLES,
    derive_gates,
    run_charter_role,
    QaRunResult,
    CharterRoleResult,
    SPINE_HOME,
)


@pytest.fixture()
def project_tmp(tmp_path: Path) -> Path:
    init_harness(tmp_path)
    return tmp_path


def test_default_lite_roles() -> None:
    assert "qa" in DEFAULT_LITE_ROLES
    assert "auditor" in DEFAULT_LITE_ROLES


def test_run_charter_role_qa_fixture() -> None:
    os.environ.setdefault("SPINE_HOME", str(SPINE_HOME))
    result = run_charter_role("qa", callable_name="fixture")
    assert result.eval_count >= 1
    assert result.overall_green is True
    assert result.exit_code == 0


def test_run_charter_role_qa_stub() -> None:
    os.environ.setdefault("SPINE_HOME", str(SPINE_HOME))
    result = run_charter_role("qa", callable_name="stub")
    assert result.eval_count >= 1
    assert "Charter eval report" in result.markdown


def test_derive_gates_from_charter_only() -> None:
    charter = [
        CharterRoleResult(
            role="qa",
            exit_code=0,
            overall_green=True,
            markdown="",
            eval_count=3,
        ),
        CharterRoleResult(
            role="auditor",
            exit_code=0,
            overall_green=True,
            markdown="",
            eval_count=3,
        ),
    ]
    gates = derive_gates(None, charter)
    assert gates["tests"] == "green"
    assert gates["security"] == "green"
    assert gates["compliance"] == "green"


def test_verify_wave_updates_state(project_tmp: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPINE_HOME", str(SPINE_HOME))
    from verify_wave import main

    code = main(["--project", str(project_tmp)])
    assert code in (0, 1)
    state = read_state(project_tmp)
    assert state["last_report"]
    assert Path(state["last_report"]).is_file()
    assert state["gates"]["tests"] in ("green", "red", "unknown")
