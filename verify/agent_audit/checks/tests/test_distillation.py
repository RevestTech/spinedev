"""Tests for ``verify.agent_audit.checks.distillation`` (L04)."""
from __future__ import annotations

from pathlib import Path

import pytest

from verify.agent_audit.checks.distillation import check_distillation_layer


REPO_ROOT = Path(__file__).resolve().parents[4]


def _stub_audit_files(root: Path) -> None:
    audit_dir = root / "shared" / "audit"
    audit_dir.mkdir(parents=True)
    (audit_dir / "audit_record.py").write_text("# stub", encoding="utf-8")
    (audit_dir / "exporter.py").write_text("# stub", encoding="utf-8")


def test_pending_when_no_audit_summary_signal() -> None:
    finding = check_distillation_layer(REPO_ROOT, {})
    assert finding.layer == "L04_distillation"
    assert finding.status == "instrumentation_pending"
    assert finding.severity == "low"


def test_clean_when_ratio_under_threshold(tmp_path: Path) -> None:
    _stub_audit_files(tmp_path)
    signals = {
        "audit_summary": {
            "events_in_window": 100,
            "rollup_events": 10,
            "rollups": [
                {"source_audit_record_id": "evt-1"},
                {"source_audit_record_id": "evt-2"},
            ],
        }
    }
    finding = check_distillation_layer(tmp_path, signals)
    assert finding.status == "clean"
    assert finding.severity == "low"


def test_warning_when_rollup_ratio_exceeds_threshold(tmp_path: Path) -> None:
    _stub_audit_files(tmp_path)
    signals = {
        "audit_summary": {
            "events_in_window": 100,
            "rollup_events": 40,
            "rollups": [{"source_audit_record_id": "evt-1"}],
        }
    }
    finding = check_distillation_layer(tmp_path, signals)
    assert finding.status == "warning"
    assert finding.severity == "medium"
    assert "40%" in finding.summary or "40/100" in finding.summary


def test_regressed_when_rollup_missing_source_id(tmp_path: Path) -> None:
    _stub_audit_files(tmp_path)
    signals = {
        "audit_summary": {
            "events_in_window": 100,
            "rollup_events": 5,
            "rollups": [
                {"source_audit_record_id": "evt-1"},
                {"summary": "rollup with no provenance"},
            ],
        }
    }
    finding = check_distillation_layer(tmp_path, signals)
    assert finding.status == "regressed"
    assert finding.severity == "high"
    assert "rollup[1]" in finding.evidence


def test_regressed_when_audit_files_missing(tmp_path: Path) -> None:
    finding = check_distillation_layer(tmp_path, {})
    assert finding.status == "regressed"
    assert finding.severity == "critical"
    assert any("audit_record.py" in e for e in finding.evidence)
    assert any("exporter.py" in e for e in finding.evidence)


def test_regressed_when_audit_summary_wrong_type(tmp_path: Path) -> None:
    _stub_audit_files(tmp_path)
    finding = check_distillation_layer(
        tmp_path, {"audit_summary": "not-a-dict"}
    )
    assert finding.status == "regressed"
    assert finding.severity == "high"


def test_pending_when_events_in_window_zero(tmp_path: Path) -> None:
    _stub_audit_files(tmp_path)
    signals = {
        "audit_summary": {
            "events_in_window": 0,
            "rollup_events": 0,
            "rollups": [],
        }
    }
    finding = check_distillation_layer(tmp_path, signals)
    assert finding.status == "instrumentation_pending"


def test_clean_against_real_repo_with_signal() -> None:
    signals = {
        "audit_summary": {
            "events_in_window": 1000,
            "rollup_events": 12,
            "rollups": [
                {"source_audit_record_id": "evt-123"},
            ],
        }
    }
    finding = check_distillation_layer(REPO_ROOT, signals)
    assert finding.status == "clean"


@pytest.mark.parametrize(
    "ratio_events,ratio_rollups,expected",
    [
        (100, 25, "clean"),
        (100, 26, "warning"),
        (4, 1, "clean"),
        (4, 2, "warning"),
    ],
)
def test_ratio_boundary_behaviour(
    tmp_path: Path,
    ratio_events: int,
    ratio_rollups: int,
    expected: str,
) -> None:
    _stub_audit_files(tmp_path)
    signals = {
        "audit_summary": {
            "events_in_window": ratio_events,
            "rollup_events": ratio_rollups,
            "rollups": [{"source_audit_record_id": "evt-1"}],
        }
    }
    finding = check_distillation_layer(tmp_path, signals)
    assert finding.status == expected
