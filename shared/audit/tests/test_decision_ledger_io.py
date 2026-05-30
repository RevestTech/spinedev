"""Tests for ``shared.audit.decision_ledger_io`` (D2 slate #2)."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from shared.audit.decision_ledger import (
    Candidate,
    DecisionLedger,
    LedgerEntry,
    PromotionGate,
)
from shared.audit.decision_ledger_io import (
    SafePromotionInputs,
    append_promotion_decision,
    latest_promotion_verdict,
    make_candidate,
)


def _inputs(**overrides) -> SafePromotionInputs:
    base = dict(
        project_id="proj-a",
        run_id="run-1",
        role="conductor",
        rollout_index=0,
        tier="internal",
        freshness_passed=True,
        replay_passed=False,
    )
    base.update(overrides)
    return SafePromotionInputs(**base)


# ─── append_promotion_decision ───


def test_append_writes_entry_with_synthesized_candidate(tmp_path: Path) -> None:
    entry = append_promotion_decision(_inputs(), root=tmp_path)
    assert entry is not None
    assert entry.project_id == "proj-a"
    assert entry.run_id == "run-1"
    assert entry.actor == "conductor"
    assert len(entry.candidates) == 1
    assert entry.candidates[0].candidate_id == "conductor:rollout-0"
    assert entry.content_hash is not None


def test_append_preserves_caller_candidates(tmp_path: Path) -> None:
    candidate = make_candidate(
        "engineer:choice-A",
        mark="accept",
        rationale="best-fit per #7b matrix",
    )
    entry = append_promotion_decision(
        _inputs(role="engineer", candidates=(candidate,)),
        root=tmp_path,
    )
    assert entry is not None
    assert entry.candidates[0].candidate_id == "engineer:choice-A"
    assert entry.candidates[0].rationale == "best-fit per #7b matrix"


def test_append_default_gate_tier_internal_denies_live_without_freshness(
    tmp_path: Path,
) -> None:
    entry = append_promotion_decision(
        _inputs(freshness_passed=False),
        root=tmp_path,
    )
    assert entry is not None
    assert entry.promotion_gate.verdict == "denied"
    assert "freshness_stale" in entry.promotion_gate.reasons


def test_append_production_tier_with_both_gates_allows(tmp_path: Path) -> None:
    entry = append_promotion_decision(
        _inputs(
            tier="production",
            freshness_passed=True,
            replay_passed=True,
        ),
        root=tmp_path,
    )
    assert entry is not None
    assert entry.promotion_gate.verdict == "allowed"


def test_append_fail_soft_returns_none_on_invalid_inputs(
    tmp_path: Path,
) -> None:
    # Empty project_id triggers a ValueError in DecisionLedger init.
    result = append_promotion_decision(
        _inputs(project_id=""),
        root=tmp_path,
    )
    assert result is None


# ─── latest_promotion_verdict ───


def test_latest_returns_none_when_no_dir(tmp_path: Path) -> None:
    assert latest_promotion_verdict("proj-a", root=tmp_path) is None


def test_latest_returns_most_recent_verdict(tmp_path: Path) -> None:
    append_promotion_decision(
        _inputs(run_id="run-old", freshness_passed=False),
        root=tmp_path,
    )
    # Bump mtime so the newest run is unambiguous.
    import time

    time.sleep(0.01)
    append_promotion_decision(
        _inputs(
            run_id="run-new",
            tier="production",
            freshness_passed=True,
            replay_passed=True,
        ),
        root=tmp_path,
    )

    verdict = latest_promotion_verdict("proj-a", root=tmp_path)
    assert verdict is not None
    assert verdict[0] == "allowed"
    assert verdict[1] == ()


def test_latest_distinguishes_denied(tmp_path: Path) -> None:
    append_promotion_decision(
        _inputs(
            run_id="run-d",
            tier="production",
            freshness_passed=False,
        ),
        root=tmp_path,
    )
    verdict = latest_promotion_verdict("proj-a", root=tmp_path)
    assert verdict is not None
    assert verdict[0] == "denied"
    assert "freshness_stale" in verdict[1]


# ─── make_candidate ───


def test_make_candidate_defaults() -> None:
    c = make_candidate("x")
    assert c.candidate_id == "x"
    assert c.mark == "accept"
    assert c.rationale is None


def test_make_candidate_full() -> None:
    c = make_candidate("x", mark="watch", rationale="why", score=0.5)
    assert c.mark == "watch"
    assert c.rationale == "why"
    assert c.score == 0.5
