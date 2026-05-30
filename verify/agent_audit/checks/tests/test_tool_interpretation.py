"""Tests for ``verify.agent_audit.checks.tool_interpretation``."""
from __future__ import annotations

from pathlib import Path

import pytest

from verify.agent_audit.checks.tool_interpretation import (
    check_tool_interpretation_layer,
)


_BR_RELPATH = Path("shared") / "runtime" / "bounded_retrieval.py"


def _write_br(repo: Path) -> Path:
    target = repo / _BR_RELPATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "NEED_PREFIX = 'need:'\n"
        "def parse_needs(response):\n"
        "    return []\n",
        encoding="utf-8",
    )
    return target


def test_missing_bounded_retrieval_file_regresses(tmp_path: Path) -> None:
    finding = check_tool_interpretation_layer(tmp_path, {})
    assert finding.status == "regressed"
    assert finding.severity == "critical"
    assert "missing" in finding.summary.lower()
    assert finding.evidence == (str(_BR_RELPATH),)


def test_signals_absent_is_instrumentation_pending(tmp_path: Path) -> None:
    _write_br(tmp_path)
    finding = check_tool_interpretation_layer(tmp_path, {})
    assert finding.status == "instrumentation_pending"
    assert finding.severity == "low"
    assert "next_actions_stats" in finding.summary


def test_signals_wrong_type_regresses(tmp_path: Path) -> None:
    _write_br(tmp_path)
    finding = check_tool_interpretation_layer(
        tmp_path,
        {"next_actions_stats": ["not", "a", "dict"]},
    )
    assert finding.status == "regressed"
    assert finding.severity == "high"
    assert "not a dict" in finding.summary


def test_zero_total_actions_is_instrumentation_pending(tmp_path: Path) -> None:
    _write_br(tmp_path)
    finding = check_tool_interpretation_layer(
        tmp_path,
        {
            "next_actions_stats": {
                "total_next_actions": 0,
                "parsed_needs": 0,
                "malformed_need_attempts": 0,
            }
        },
    )
    assert finding.status == "instrumentation_pending"
    assert finding.severity == "low"
    assert "0" in finding.summary


def test_high_malformed_rate_warns(tmp_path: Path) -> None:
    _write_br(tmp_path)
    finding = check_tool_interpretation_layer(
        tmp_path,
        {
            "next_actions_stats": {
                "total_next_actions": 20,
                "parsed_needs": 5,
                "malformed_need_attempts": 8,
            }
        },
    )
    assert finding.status == "warning"
    assert finding.severity == "medium"
    assert "40%" in finding.summary
    assert "malformed_need_attempts=8" in finding.evidence
    assert "total_next_actions=20" in finding.evidence


def test_malformed_rate_at_threshold_is_clean(tmp_path: Path) -> None:
    # Exactly 25% (5/20) should NOT trip the warning — strict ">" check.
    _write_br(tmp_path)
    finding = check_tool_interpretation_layer(
        tmp_path,
        {
            "next_actions_stats": {
                "total_next_actions": 20,
                "parsed_needs": 10,
                "malformed_need_attempts": 5,
            }
        },
    )
    assert finding.status == "clean"


def test_zero_parsed_with_enough_actions_warns(tmp_path: Path) -> None:
    _write_br(tmp_path)
    finding = check_tool_interpretation_layer(
        tmp_path,
        {
            "next_actions_stats": {
                "total_next_actions": 15,
                "parsed_needs": 0,
                "malformed_need_attempts": 0,
            }
        },
    )
    assert finding.status == "warning"
    assert finding.severity == "medium"
    assert "underused" in finding.summary
    assert "parsed_needs=0" in finding.evidence


def test_zero_parsed_below_min_actions_is_clean(tmp_path: Path) -> None:
    _write_br(tmp_path)
    finding = check_tool_interpretation_layer(
        tmp_path,
        {
            "next_actions_stats": {
                "total_next_actions": 5,
                "parsed_needs": 0,
                "malformed_need_attempts": 0,
            }
        },
    )
    assert finding.status == "clean"


def test_malformed_takes_precedence_over_underuse(tmp_path: Path) -> None:
    # parsed=0 + total>=10 would warn for underuse; high malformed rate
    # should win since it's the more actionable signal.
    _write_br(tmp_path)
    finding = check_tool_interpretation_layer(
        tmp_path,
        {
            "next_actions_stats": {
                "total_next_actions": 12,
                "parsed_needs": 0,
                "malformed_need_attempts": 9,
            }
        },
    )
    assert finding.status == "warning"
    assert "malformed" in finding.summary.lower()


def test_clean_path(tmp_path: Path) -> None:
    _write_br(tmp_path)
    finding = check_tool_interpretation_layer(
        tmp_path,
        {
            "next_actions_stats": {
                "total_next_actions": 30,
                "parsed_needs": 12,
                "malformed_need_attempts": 1,
            }
        },
    )
    assert finding.status == "clean"
    assert "12/30" in finding.summary
    assert "1 malformed" in finding.summary


def test_layer_id_is_l08(tmp_path: Path) -> None:
    _write_br(tmp_path)
    finding = check_tool_interpretation_layer(tmp_path, {})
    assert finding.layer == "L08_tool_interpretation"


def test_missing_file_layer_id(tmp_path: Path) -> None:
    finding = check_tool_interpretation_layer(tmp_path, {})
    assert finding.layer == "L08_tool_interpretation"


@pytest.mark.parametrize(
    "stats",
    [
        {
            "total_next_actions": None,
            "parsed_needs": None,
            "malformed_need_attempts": None,
        },
        {},
    ],
)
def test_none_or_empty_numeric_signals_treated_as_zero(
    tmp_path: Path, stats: dict,
) -> None:
    _write_br(tmp_path)
    finding = check_tool_interpretation_layer(
        tmp_path,
        {"next_actions_stats": stats},
    )
    # total resolves to 0 → instrumentation_pending.
    assert finding.status == "instrumentation_pending"
