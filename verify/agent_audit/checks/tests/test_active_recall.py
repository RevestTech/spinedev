"""Tests for ``verify.agent_audit.checks.active_recall``."""
from __future__ import annotations

from pathlib import Path

import pytest

from verify.agent_audit.checks.active_recall import check_active_recall_layer


_KG_RELPATH = Path("shared") / "runtime" / "kg_role_context.py"


def _write_kg(repo: Path, *, with_cap: bool = True) -> Path:
    target = repo / _KG_RELPATH
    target.parent.mkdir(parents=True, exist_ok=True)
    if with_cap:
        body = (
            "def format_hybrid_search_block(data):\n"
            "    results = data.get('results') or []\n"
            "    for row in results[:15]:\n"
            "        pass\n"
            "    return ''\n"
        )
    else:
        body = (
            "def format_hybrid_search_block(data):\n"
            "    results = data.get('results') or []\n"
            "    for row in results:\n"
            "        pass\n"
            "    return ''\n"
        )
    target.write_text(body, encoding="utf-8")
    return target


def test_missing_kg_role_context_file_regresses(tmp_path: Path) -> None:
    finding = check_active_recall_layer(tmp_path, {})
    assert finding.status == "regressed"
    assert finding.severity == "high"
    assert "missing" in finding.summary.lower()
    assert finding.evidence == (str(_KG_RELPATH),)


def test_missing_cap_marker_regresses(tmp_path: Path) -> None:
    _write_kg(tmp_path, with_cap=False)
    finding = check_active_recall_layer(tmp_path, {})
    assert finding.status == "regressed"
    assert finding.severity == "high"
    assert finding.evidence == ("missing 15-row cap",)


def test_signals_absent_is_instrumentation_pending(tmp_path: Path) -> None:
    _write_kg(tmp_path)
    finding = check_active_recall_layer(tmp_path, {})
    assert finding.status == "instrumentation_pending"
    assert finding.severity == "low"


def test_signals_wrong_type_regresses(tmp_path: Path) -> None:
    _write_kg(tmp_path)
    finding = check_active_recall_layer(
        tmp_path,
        {"kg_retrieval_stats": ["not", "a", "dict"]},
    )
    assert finding.status == "regressed"
    assert finding.severity == "high"
    assert "not a dict" in finding.summary


def test_low_hit_rate_warns(tmp_path: Path) -> None:
    _write_kg(tmp_path)
    finding = check_active_recall_layer(
        tmp_path,
        {
            "kg_retrieval_stats": {
                "recent_queries": 20,
                "recent_hits": 4,
                "avg_results_per_hit": 5.0,
            }
        },
    )
    assert finding.status == "warning"
    assert finding.severity == "medium"
    assert "20%" in finding.summary
    assert "recent_queries=20" in finding.evidence


def test_low_hit_rate_skipped_below_min_queries(tmp_path: Path) -> None:
    _write_kg(tmp_path)
    finding = check_active_recall_layer(
        tmp_path,
        {
            "kg_retrieval_stats": {
                "recent_queries": 5,
                "recent_hits": 0,
                "avg_results_per_hit": 4.0,
            }
        },
    )
    assert finding.status == "clean"


def test_bloated_result_set_warns(tmp_path: Path) -> None:
    _write_kg(tmp_path)
    finding = check_active_recall_layer(
        tmp_path,
        {
            "kg_retrieval_stats": {
                "recent_queries": 50,
                "recent_hits": 48,
                "avg_results_per_hit": 42.5,
            }
        },
    )
    assert finding.status == "warning"
    assert finding.severity == "medium"
    assert "42.5" in finding.summary
    assert finding.evidence == ("avg_results_per_hit=42.5",)


def test_clean_path(tmp_path: Path) -> None:
    _write_kg(tmp_path)
    finding = check_active_recall_layer(
        tmp_path,
        {
            "kg_retrieval_stats": {
                "recent_queries": 25,
                "recent_hits": 22,
                "avg_results_per_hit": 8.0,
            }
        },
    )
    assert finding.status == "clean"
    assert "22/25" in finding.summary


def test_hit_rate_takes_precedence_over_bloat(tmp_path: Path) -> None:
    _write_kg(tmp_path)
    finding = check_active_recall_layer(
        tmp_path,
        {
            "kg_retrieval_stats": {
                "recent_queries": 30,
                "recent_hits": 5,
                "avg_results_per_hit": 99.0,
            }
        },
    )
    assert finding.status == "warning"
    assert "hit rate" in finding.summary.lower()


def test_zero_queries_handled_cleanly(tmp_path: Path) -> None:
    _write_kg(tmp_path)
    finding = check_active_recall_layer(
        tmp_path,
        {
            "kg_retrieval_stats": {
                "recent_queries": 0,
                "recent_hits": 0,
                "avg_results_per_hit": 0.0,
            }
        },
    )
    assert finding.status == "clean"


def test_layer_id_is_l05(tmp_path: Path) -> None:
    _write_kg(tmp_path)
    finding = check_active_recall_layer(tmp_path, {})
    assert finding.layer == "L05_active_recall"


@pytest.mark.parametrize(
    "stats",
    [
        {"recent_queries": None, "recent_hits": None, "avg_results_per_hit": None},
        {},
    ],
)
def test_none_or_empty_numeric_signals_handled(tmp_path: Path, stats: dict) -> None:
    _write_kg(tmp_path)
    finding = check_active_recall_layer(
        tmp_path,
        {"kg_retrieval_stats": stats},
    )
    assert finding.status == "clean"
