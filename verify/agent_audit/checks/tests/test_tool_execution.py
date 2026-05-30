"""Tests for ``verify.agent_audit.checks.tool_execution`` (L07)."""
from __future__ import annotations

from pathlib import Path

import pytest

from verify.agent_audit.checks.tool_execution import (
    check_tool_execution_layer,
)


REPO_ROOT = Path(__file__).resolve().parents[4]


def _seed_mcp_files(root: Path) -> None:
    mcp = root / "shared" / "mcp"
    mcp.mkdir(parents=True)
    (mcp / "server.py").write_text("# stub server\n", encoding="utf-8")
    (mcp / "cite_or_refuse.py").write_text(
        "# stub cite_or_refuse\n",
        encoding="utf-8",
    )


# ─── required files ───


def test_regressed_when_mcp_files_missing(tmp_path: Path) -> None:
    finding = check_tool_execution_layer(
        tmp_path,
        {"tool_exec_stats": {"ok": 10}},
    )
    assert finding.layer == "L07_tool_execution"
    assert finding.status == "regressed"
    assert finding.severity == "critical"
    assert any("server.py" in e for e in finding.evidence)
    assert any("cite_or_refuse.py" in e for e in finding.evidence)


def test_regressed_when_only_one_mcp_file_present(tmp_path: Path) -> None:
    mcp = tmp_path / "shared" / "mcp"
    mcp.mkdir(parents=True)
    (mcp / "server.py").write_text("# stub\n", encoding="utf-8")
    finding = check_tool_execution_layer(
        tmp_path,
        {"tool_exec_stats": {"ok": 5}},
    )
    assert finding.status == "regressed"
    assert any("cite_or_refuse.py" in e for e in finding.evidence)


# ─── instrumentation_pending paths ───


def test_pending_when_no_signal(tmp_path: Path) -> None:
    _seed_mcp_files(tmp_path)
    finding = check_tool_execution_layer(tmp_path, {})
    assert finding.status == "instrumentation_pending"
    assert "no tool_exec_stats" in finding.summary


def test_pending_when_window_empty(tmp_path: Path) -> None:
    _seed_mcp_files(tmp_path)
    finding = check_tool_execution_layer(
        tmp_path,
        {"tool_exec_stats": {
            "ok": 0, "warning": 0, "error": 0,
            "refusal": 0, "stub_implementation": 0,
        }},
    )
    assert finding.status == "instrumentation_pending"
    assert "0 calls" in finding.summary


def test_pending_when_signal_is_empty_dict(tmp_path: Path) -> None:
    _seed_mcp_files(tmp_path)
    finding = check_tool_execution_layer(
        tmp_path,
        {"tool_exec_stats": {}},
    )
    assert finding.status == "instrumentation_pending"


# ─── malformed signal ───


def test_regressed_when_stats_not_dict(tmp_path: Path) -> None:
    _seed_mcp_files(tmp_path)
    finding = check_tool_execution_layer(
        tmp_path,
        {"tool_exec_stats": [("ok", 5)]},
    )
    assert finding.status == "regressed"
    assert finding.severity == "high"
    assert "not a dict" in finding.summary


def test_non_numeric_counts_coerced_to_zero(tmp_path: Path) -> None:
    _seed_mcp_files(tmp_path)
    finding = check_tool_execution_layer(
        tmp_path,
        {"tool_exec_stats": {
            "ok": "not-a-number",
            "error": None,
            "refusal": -5,
            "stub_implementation": 0,
            "warning": 0,
        }},
    )
    # All coerced to 0 → empty window
    assert finding.status == "instrumentation_pending"


# ─── regressed (error+refusal > 0.5) ───


def test_regressed_when_error_refusal_dominate(tmp_path: Path) -> None:
    _seed_mcp_files(tmp_path)
    finding = check_tool_execution_layer(
        tmp_path,
        {"tool_exec_stats": {
            "ok": 10, "warning": 0,
            "error": 30, "refusal": 30,
            "stub_implementation": 0,
        }},
    )
    assert finding.status == "regressed"
    assert finding.severity == "high"
    assert "60/70" in finding.summary
    assert "error=30" in finding.evidence
    assert "refusal=30" in finding.evidence
    assert finding.next_actions  # populated


def test_regressed_pure_errors(tmp_path: Path) -> None:
    _seed_mcp_files(tmp_path)
    finding = check_tool_execution_layer(
        tmp_path,
        {"tool_exec_stats": {
            "ok": 1, "warning": 0,
            "error": 10, "refusal": 0,
            "stub_implementation": 0,
        }},
    )
    assert finding.status == "regressed"


# ─── warning (stub > 0.5) ───


def test_warning_when_stub_dominates(tmp_path: Path) -> None:
    _seed_mcp_files(tmp_path)
    finding = check_tool_execution_layer(
        tmp_path,
        {"tool_exec_stats": {
            "ok": 5, "warning": 0,
            "error": 1, "refusal": 0,
            "stub_implementation": 60,
        }},
    )
    assert finding.status == "warning"
    assert finding.severity == "medium"
    assert "stub_implementation" in finding.summary
    assert "60/66" in finding.summary


# ─── warning (refusal > 0.25) ───


def test_warning_when_refusal_elevated(tmp_path: Path) -> None:
    _seed_mcp_files(tmp_path)
    finding = check_tool_execution_layer(
        tmp_path,
        {"tool_exec_stats": {
            "ok": 60, "warning": 0,
            "error": 5, "refusal": 30,
            "stub_implementation": 5,
        }},
    )
    assert finding.status == "warning"
    assert finding.severity == "medium"
    assert "refused" in finding.summary
    assert "30/100" in finding.summary


# ─── clean ───


def test_clean_on_healthy_mix(tmp_path: Path) -> None:
    _seed_mcp_files(tmp_path)
    finding = check_tool_execution_layer(
        tmp_path,
        {"tool_exec_stats": {
            "ok": 90, "warning": 5,
            "error": 3, "refusal": 2,
            "stub_implementation": 0,
        }},
    )
    assert finding.status == "clean"
    assert "100 MCP call" in finding.summary
    assert "ok=90" in finding.summary


def test_clean_against_repo_when_no_signal_with_real_files() -> None:
    # Real repo has MCP files; missing signal → pending, not regressed.
    finding = check_tool_execution_layer(REPO_ROOT, {})
    assert finding.status == "instrumentation_pending"


# ─── boundary checks ───


def test_exact_50_percent_error_refusal_is_not_regressed(tmp_path: Path) -> None:
    _seed_mcp_files(tmp_path)
    # error+refusal exactly 50% — strict ``>`` threshold means not regressed.
    finding = check_tool_execution_layer(
        tmp_path,
        {"tool_exec_stats": {
            "ok": 50, "warning": 0,
            "error": 25, "refusal": 25,
            "stub_implementation": 0,
        }},
    )
    # refusal_rate = 25% — also not > 0.25 (strict).
    assert finding.status == "clean"


def test_just_above_refusal_threshold(tmp_path: Path) -> None:
    _seed_mcp_files(tmp_path)
    finding = check_tool_execution_layer(
        tmp_path,
        {"tool_exec_stats": {
            "ok": 73, "warning": 0,
            "error": 0, "refusal": 26,
            "stub_implementation": 1,
        }},
    )
    assert finding.status == "warning"
    assert "refused" in finding.summary


def test_extra_unknown_keys_ignored(tmp_path: Path) -> None:
    _seed_mcp_files(tmp_path)
    finding = check_tool_execution_layer(
        tmp_path,
        {"tool_exec_stats": {
            "ok": 10,
            "mystery_key": 9999,
        }},
    )
    assert finding.status == "clean"
    assert "10 MCP call" in finding.summary
