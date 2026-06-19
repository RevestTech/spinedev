"""Tests for Harness Lite audit-wave."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

HARNESS_LIB = Path(__file__).resolve().parents[1] / "lib"
sys.path.insert(0, str(HARNESS_LIB))

from harness_state import init_harness, read_state  # noqa: E402
from audit_wave import (  # noqa: E402
    gate_status_from_findings,
    gates_to_audit,
    scan_requirements,
    main,
)


def test_gates_to_audit_skips_green() -> None:
    state = {"gates": {"tests": "green", "docs": "unknown", "drift": "red"}}
    targets = gates_to_audit(state, audit_all=False)
    assert "tests" not in targets
    assert "docs" in targets
    assert "drift" in targets


def test_gate_status_from_findings() -> None:
    assert gate_status_from_findings([{"severity": "info"}]) == "green"
    assert gate_status_from_findings([{"severity": "high"}]) == "red"


def test_scan_requirements_on_spine_repo() -> None:
    root = Path(__file__).resolve().parents[3]
    findings = scan_requirements(root)
    assert findings
    assert all("location" in f for f in findings)


def test_audit_updates_state(tmp_path: Path) -> None:
    init_harness(tmp_path)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "PRD.md").write_text("# PRD\n")
    (tmp_path / "docs" / "SPINE_MASTER.md").write_text("# Master\n")
    (tmp_path / "todo").mkdir()
    (tmp_path / "todo" / "BACKLOG.md").write_text("# Backlog\n")
    code = main(["--project", str(tmp_path), "--gates", "requirements"])
    assert code in (0, 1)
    state = read_state(tmp_path)
    findings_dir = tmp_path / ".spine" / "harness" / "findings"
    assert any(findings_dir.glob("requirements-*.json"))
