"""Tests for ``verify.agent_audit.twelve_layer`` (V3 B10).

Covers:
  * Each native check returns the right status on synthetic input
    (clean / regressed / warning / instrumentation_pending).
  * ``scan_agent_stack`` aggregates 12 findings and computes
    overall_status correctly.
  * Live repo scan returns ``clean`` or ``warning`` for the native
    checks (the rest are instrumentation_pending by design).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from verify.agent_audit.twelve_layer import (
    AgentAuditReport,
    DEFAULT_CHECKS,
    check_answer_shaping_layer,
    check_evals_layer,
    check_long_term_memory_layer,
    check_promotion_gate_layer,
    check_system_prompt_layer,
    check_tool_selection_layer,
    scan_agent_stack,
)


REPO_ROOT = Path(__file__).resolve().parents[3]


# ─── L01 system_prompt ───


def test_l01_clean_against_repo() -> None:
    finding = check_system_prompt_layer(REPO_ROOT, {})
    assert finding.layer == "L01_system_prompt"
    assert finding.status == "clean"


def test_l01_regressed_when_charters_dir_missing(tmp_path: Path) -> None:
    finding = check_system_prompt_layer(tmp_path, {})
    assert finding.status == "regressed"
    assert finding.severity == "critical"


def test_l01_warning_on_truncated_charter(tmp_path: Path) -> None:
    charters = tmp_path / "shared" / "charters"
    charters.mkdir(parents=True)
    (charters / "tiny.md").write_text("# almost empty\n", encoding="utf-8")
    finding = check_system_prompt_layer(tmp_path, {})
    assert finding.status == "warning"
    assert "tiny.md" in finding.evidence


# ─── L03 long_term_memory ───


def test_l03_clean_against_repo() -> None:
    finding = check_long_term_memory_layer(REPO_ROOT, {})
    assert finding.status == "clean"


def test_l03_regressed_when_instinct_missing(tmp_path: Path) -> None:
    (tmp_path / "learning").mkdir()
    finding = check_long_term_memory_layer(tmp_path, {})
    assert finding.status == "regressed"
    assert any("instinct.py" in e for e in finding.evidence)


# ─── L06 tool_selection ───


def test_l06_pending_when_no_signal() -> None:
    finding = check_tool_selection_layer(REPO_ROOT, {})
    assert finding.status == "instrumentation_pending"


def test_l06_clean_with_nonempty_registry() -> None:
    finding = check_tool_selection_layer(
        REPO_ROOT, {"tool_registry": {"a": 1, "b": 2}},
    )
    assert finding.status == "clean"
    assert "2 tool" in finding.summary


def test_l06_regressed_when_registry_empty() -> None:
    finding = check_tool_selection_layer(
        REPO_ROOT, {"tool_registry": {}},
    )
    assert finding.status == "regressed"


def test_l06_regressed_when_registry_wrong_type() -> None:
    finding = check_tool_selection_layer(
        REPO_ROOT, {"tool_registry": ["a", "b"]},
    )
    assert finding.status == "regressed"


# ─── L09 answer_shaping ───


def test_l09_clean_against_repo() -> None:
    finding = check_answer_shaping_layer(REPO_ROOT, {})
    assert finding.status == "clean"


def test_l09_regressed_when_envelope_missing_b2_fields(tmp_path: Path) -> None:
    pkg = tmp_path / "shared" / "mcp" / "schemas"
    pkg.mkdir(parents=True)
    # Stub that contains zero references to the B2 field names —
    # the check works by substring presence so even the word in a
    # comment counts.
    (pkg / "envelopes.py").write_text(
        "class ToolResponse:\n"
        "    status: str\n"
        "    data: dict\n",
        encoding="utf-8",
    )
    finding = check_answer_shaping_layer(tmp_path, {})
    assert finding.status == "regressed"
    assert "summary" in finding.evidence


# ─── L11 evals ───


def test_l11_clean_against_repo() -> None:
    finding = check_evals_layer(REPO_ROOT, {})
    assert finding.status == "clean"


def test_l11_warning_when_role_dir_missing(tmp_path: Path) -> None:
    (tmp_path / "verify" / "charter_evals" / "engineer").mkdir(parents=True)
    # architect/ deliberately not created
    finding = check_evals_layer(tmp_path, {})
    assert finding.status == "warning"
    assert any("architect" in e for e in finding.evidence)


def test_l11_regressed_when_charter_evals_missing(tmp_path: Path) -> None:
    finding = check_evals_layer(tmp_path, {})
    assert finding.status == "regressed"


# ─── L12 promotion_gate ───


def test_l12_pending_without_signal() -> None:
    finding = check_promotion_gate_layer(REPO_ROOT, {})
    assert finding.status == "instrumentation_pending"


def test_l12_clean_with_low_denial_rate() -> None:
    finding = check_promotion_gate_layer(
        REPO_ROOT,
        {"ledger_summary": {"denials_in_window": 1, "window_size": 10}},
    )
    assert finding.status == "clean"


def test_l12_warning_at_elevated_denial_rate() -> None:
    finding = check_promotion_gate_layer(
        REPO_ROOT,
        {"ledger_summary": {"denials_in_window": 3, "window_size": 10}},
    )
    assert finding.status == "warning"


def test_l12_regressed_at_majority_denial_rate() -> None:
    finding = check_promotion_gate_layer(
        REPO_ROOT,
        {"ledger_summary": {"denials_in_window": 6, "window_size": 10}},
    )
    assert finding.status == "regressed"


# ─── scan_agent_stack ───


def test_scan_returns_12_findings_in_order() -> None:
    report = scan_agent_stack(repo_root=REPO_ROOT)
    assert len(report.findings) == 12
    expected = [c.layer for c in DEFAULT_CHECKS]
    actual = [f.layer for f in report.findings]
    assert actual == expected


def test_scan_overall_status_against_live_repo() -> None:
    report = scan_agent_stack(repo_root=REPO_ROOT)
    # Native checks pass; un-instrumented layers are pending. None
    # regressed.
    assert report.overall_status in ("clean", "warning")
    assert report.regressed_layers == ()


def test_scan_with_signals_promotes_layers_to_clean() -> None:
    signals = {
        "tool_registry": {"a": 1},
        "ledger_summary": {"denials_in_window": 0, "window_size": 5},
    }
    report = scan_agent_stack(repo_root=REPO_ROOT, signals=signals)
    findings_by_layer = {f.layer: f for f in report.findings}
    assert findings_by_layer["L06_tool_selection"].status == "clean"
    assert findings_by_layer["L12_promotion_gate"].status == "clean"


def test_scan_with_broken_repo_root_surfaces_regressions(
    tmp_path: Path,
) -> None:
    report = scan_agent_stack(repo_root=tmp_path)
    # L01, L03, L09, L11 should all regress under an empty repo.
    assert any(f.status == "regressed" for f in report.findings)
    assert report.overall_status == "regressed"
