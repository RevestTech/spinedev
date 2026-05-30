"""Tests for ``shared.audit.decision_ledger`` (V3 #12a).

Covers:
  * Append + hash chaining (prev_hash and content_hash populated, chain valid).
  * Tamper detection (mutating an on-disk entry breaks the chain).
  * Promotion gate default-deny behaviour and per-tier checks.
  * Project / run ID mismatch is rejected.
  * Empty candidates list is rejected.
  * ``SPINE_DECISION_LEDGER_ROOT`` env override honoured.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from shared.audit.decision_ledger import (
    Candidate,
    DecisionLedger,
    LedgerEntry,
    PromotionGate,
    default_ledger_root,
)


_DEFAULT_CANDIDATES = [Candidate(candidate_id="cand-a", mark="accept", score=0.9)]


def _make_entry(
    project_id: str = "proj-a",
    run_id: str = "run-1",
    rollout_index: int = 0,
    *,
    candidates: list[Candidate] | None = None,
    gate: PromotionGate | None = None,
) -> LedgerEntry:
    return LedgerEntry(
        project_id=project_id,
        run_id=run_id,
        actor="conductor",
        rollout_index=rollout_index,
        candidates=list(_DEFAULT_CANDIDATES) if candidates is None else candidates,
        promotion_gate=gate
        if gate is not None
        else PromotionGate.evaluate(
            tier="preview",
            freshness_passed=True,
            replay_passed=True,
        ),
    )


# ─── Append + hash chain ───


def test_first_append_populates_hash_and_no_prev(tmp_path: Path) -> None:
    ledger = DecisionLedger(project_id="proj-a", run_id="run-1", root=tmp_path)
    appended = ledger.append(_make_entry())
    assert appended.prev_hash is None
    assert appended.content_hash is not None
    assert len(appended.content_hash) == 64  # sha256 hex


def test_second_append_chains_prev_hash(tmp_path: Path) -> None:
    ledger = DecisionLedger(project_id="proj-a", run_id="run-1", root=tmp_path)
    first = ledger.append(_make_entry(rollout_index=0))
    second = ledger.append(_make_entry(rollout_index=1))
    assert second.prev_hash == first.content_hash
    assert second.content_hash != first.content_hash


def test_verify_chain_ok_for_clean_ledger(tmp_path: Path) -> None:
    ledger = DecisionLedger(project_id="proj-a", run_id="run-1", root=tmp_path)
    for idx in range(3):
        ledger.append(_make_entry(rollout_index=idx))
    ok, reason = ledger.verify_chain()
    assert ok is True
    assert reason is None


def test_verify_chain_detects_tamper(tmp_path: Path) -> None:
    ledger = DecisionLedger(project_id="proj-a", run_id="run-1", root=tmp_path)
    ledger.append(_make_entry(rollout_index=0))
    ledger.append(_make_entry(rollout_index=1))

    # Mutate the first entry on disk.
    raw_lines = ledger.path.read_text(encoding="utf-8").splitlines()
    first = json.loads(raw_lines[0])
    first["actor"] = "tampered"
    raw_lines[0] = json.dumps(first, sort_keys=True, separators=(",", ":"))
    ledger.path.write_text("\n".join(raw_lines) + "\n", encoding="utf-8")

    ok, reason = ledger.verify_chain()
    assert ok is False
    assert reason is not None
    assert "content_hash mismatch" in reason


def test_tail_returns_last_n_in_order(tmp_path: Path) -> None:
    ledger = DecisionLedger(project_id="proj-a", run_id="run-1", root=tmp_path)
    for idx in range(5):
        ledger.append(_make_entry(rollout_index=idx))
    last_two = ledger.tail(2)
    assert [e.rollout_index for e in last_two] == [3, 4]


# ─── Promotion gate ───


def test_promotion_gate_paper_always_allowed() -> None:
    gate = PromotionGate.evaluate(
        tier="paper", freshness_passed=False, replay_passed=False,
    )
    assert gate.verdict == "allowed"
    assert gate.reasons == []


def test_promotion_gate_production_requires_both() -> None:
    only_fresh = PromotionGate.evaluate(
        tier="production", freshness_passed=True, replay_passed=False,
    )
    assert only_fresh.verdict == "denied"
    assert "replay_failed" in only_fresh.reasons
    assert "freshness_stale" not in only_fresh.reasons

    only_replay = PromotionGate.evaluate(
        tier="production", freshness_passed=False, replay_passed=True,
    )
    assert only_replay.verdict == "denied"
    assert "freshness_stale" in only_replay.reasons

    both = PromotionGate.evaluate(
        tier="production", freshness_passed=True, replay_passed=True,
    )
    assert both.verdict == "allowed"


def test_promotion_gate_destructive_requires_operator() -> None:
    no_operator = PromotionGate.evaluate(
        tier="destructive",
        freshness_passed=True,
        replay_passed=True,
        operator_confirmed=False,
    )
    assert no_operator.verdict == "denied"
    assert "operator_not_confirmed" in no_operator.reasons

    with_operator = PromotionGate.evaluate(
        tier="destructive",
        freshness_passed=True,
        replay_passed=True,
        operator_confirmed=True,
    )
    assert with_operator.verdict == "allowed"
    assert with_operator.reasons == []


def test_promotion_gate_default_state_is_denied() -> None:
    gate = PromotionGate(tier="production")
    assert gate.verdict == "denied"
    assert gate.freshness_passed is False
    assert gate.replay_passed is False


# ─── Validation ───


def test_project_id_mismatch_rejected(tmp_path: Path) -> None:
    ledger = DecisionLedger(project_id="proj-a", run_id="run-1", root=tmp_path)
    bad = _make_entry(project_id="proj-other")
    with pytest.raises(ValueError, match="project_id"):
        ledger.append(bad)


def test_run_id_mismatch_rejected(tmp_path: Path) -> None:
    ledger = DecisionLedger(project_id="proj-a", run_id="run-1", root=tmp_path)
    bad = _make_entry(run_id="run-other")
    with pytest.raises(ValueError, match="run_id"):
        ledger.append(bad)


def test_empty_candidates_rejected(tmp_path: Path) -> None:
    ledger = DecisionLedger(project_id="proj-a", run_id="run-1", root=tmp_path)
    with pytest.raises(ValueError, match="candidates"):
        ledger.append(_make_entry(candidates=[]))


# ─── Env override ───


def test_env_override_honoured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "custom-root"
    monkeypatch.setenv("SPINE_DECISION_LEDGER_ROOT", str(target))
    resolved = default_ledger_root()
    assert resolved == target.resolve()


def test_env_override_used_by_default_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "default-root"
    monkeypatch.setenv("SPINE_DECISION_LEDGER_ROOT", str(target))
    ledger = DecisionLedger(project_id="proj-a", run_id="run-1")
    assert str(ledger.path).startswith(str(target.resolve()))
