"""Tests for ``learning.instinct`` (V3 B3 borrow).

Covers:
  * ``Instinct`` confidence bounded to [floor, ceiling].
  * Fingerprint stable under whitespace / case / rationale changes.
  * ``InstinctStore`` records observations and round-trips JSONL.
  * ``check_promotion`` aggregates across projects + applies thresholds.
  * ``promote_to_lesson_payload`` produces a usable LessonPayload only
    when the promotion decision is eligible.
  * Project / run mismatch rejected.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from learning.instinct import (
    CONFIDENCE_CEILING,
    CONFIDENCE_FLOOR,
    PROMOTION_MIN_CONFIDENCE,
    PROMOTION_THRESHOLD_PROJECTS,
    Instinct,
    InstinctRecord,
    InstinctStore,
    check_promotion,
    promote_to_lesson_payload,
)


def _record(
    *,
    project_id: str = "proj-a",
    run_id: str = "run-1",
    pattern: str = "use fixture X for Y",
    trigger: str = "writing pytest for KG queries",
    confidence: float = 0.5,
) -> InstinctRecord:
    return InstinctRecord(
        instinct=Instinct(
            pattern=pattern,
            trigger=trigger,
            rationale="reduces test flakiness on shared connections",
            confidence=confidence,
        ),
        project_id=project_id,
        run_id=run_id,
        actor="engineer",
    )


# ─── Instinct model ───


def test_instinct_default_confidence_is_floor() -> None:
    i = Instinct(pattern="p", trigger="t", rationale="r")
    assert i.confidence == CONFIDENCE_FLOOR


def test_instinct_confidence_bounded() -> None:
    # Below floor rejected.
    with pytest.raises(Exception):
        Instinct(pattern="p", trigger="t", rationale="r", confidence=0.1)
    # Above ceiling rejected.
    with pytest.raises(Exception):
        Instinct(pattern="p", trigger="t", rationale="r", confidence=1.0)
    # Boundaries accepted.
    Instinct(
        pattern="p", trigger="t", rationale="r",
        confidence=CONFIDENCE_FLOOR,
    )
    Instinct(
        pattern="p", trigger="t", rationale="r",
        confidence=CONFIDENCE_CEILING,
    )


def test_fingerprint_stable_under_whitespace_and_case() -> None:
    a = Instinct(
        pattern="Run flyway migrate before pytest",
        trigger="touching shared/db",
        rationale="…",
    )
    b = Instinct(
        pattern="   run   FLYWAY   migrate   before pytest  ",
        trigger="TOUCHING shared/db",
        rationale="different rationale",
    )
    assert a.fingerprint == b.fingerprint


def test_fingerprint_changes_with_trigger() -> None:
    a = Instinct(pattern="p", trigger="trigger-A", rationale="r")
    b = Instinct(pattern="p", trigger="trigger-B", rationale="r")
    assert a.fingerprint != b.fingerprint


# ─── Store ───


def test_store_records_and_iterates(tmp_path: Path) -> None:
    store = InstinctStore(
        project_id="proj-a", run_id="run-1", root=tmp_path,
    )
    store.record(_record())
    store.record(_record(confidence=0.6))
    records = list(store.iter_records())
    assert len(records) == 2
    assert records[0].instinct.confidence == 0.5
    assert records[1].instinct.confidence == 0.6


def test_store_rejects_project_mismatch(tmp_path: Path) -> None:
    store = InstinctStore(
        project_id="proj-a", run_id="run-1", root=tmp_path,
    )
    with pytest.raises(ValueError, match="project_id"):
        store.record(_record(project_id="other"))


def test_store_rejects_run_mismatch(tmp_path: Path) -> None:
    store = InstinctStore(
        project_id="proj-a", run_id="run-1", root=tmp_path,
    )
    with pytest.raises(ValueError, match="run_id"):
        store.record(_record(run_id="other"))


# ─── Promotion ───


def test_promotion_not_eligible_below_project_threshold(tmp_path: Path) -> None:
    InstinctStore(
        project_id="proj-a", run_id="run-1", root=tmp_path,
    ).record(_record(run_id="run-1", confidence=0.8))
    InstinctStore(
        project_id="proj-a", run_id="run-2", root=tmp_path,
    ).record(_record(run_id="run-2", confidence=0.8))
    # Two runs but one project — not eligible.
    fp = _record().instinct.fingerprint
    decision = check_promotion(fp, root=tmp_path)
    assert decision.eligible_for_promotion is False
    assert "threshold_not_met" in decision.reasons
    assert decision.observations == 2
    assert decision.projects_seen == ("proj-a",)


def test_promotion_not_eligible_when_confidence_low(tmp_path: Path) -> None:
    InstinctStore(
        project_id="proj-a", run_id="run-1", root=tmp_path,
    ).record(_record(run_id="run-1", confidence=CONFIDENCE_FLOOR))
    InstinctStore(
        project_id="proj-b", run_id="run-1", root=tmp_path,
    ).record(
        _record(
            project_id="proj-b", run_id="run-1",
            confidence=CONFIDENCE_FLOOR,
        )
    )
    fp = _record().instinct.fingerprint
    decision = check_promotion(fp, root=tmp_path)
    assert decision.eligible_for_promotion is False
    assert "confidence_below_floor" in decision.reasons
    assert sorted(decision.projects_seen) == ["proj-a", "proj-b"]


def test_promotion_eligible_above_thresholds(tmp_path: Path) -> None:
    InstinctStore(
        project_id="proj-a", run_id="r1", root=tmp_path,
    ).record(_record(run_id="r1", confidence=0.6))
    InstinctStore(
        project_id="proj-b", run_id="r1", root=tmp_path,
    ).record(_record(project_id="proj-b", run_id="r1", confidence=0.7))
    fp = _record().instinct.fingerprint
    decision = check_promotion(fp, root=tmp_path)
    assert decision.eligible_for_promotion is True
    assert decision.reasons == ()
    assert decision.observations == 2
    assert decision.avg_confidence == pytest.approx(0.65)


def test_promote_to_lesson_payload_returns_none_when_not_eligible(
    tmp_path: Path,
) -> None:
    InstinctStore(
        project_id="proj-a", run_id="r1", root=tmp_path,
    ).record(_record(run_id="r1", confidence=CONFIDENCE_FLOOR))
    fp = _record().instinct.fingerprint
    decision = check_promotion(fp, root=tmp_path)
    assert promote_to_lesson_payload(fp, decision, root=tmp_path) is None


def test_promote_to_lesson_payload_emits_when_eligible(tmp_path: Path) -> None:
    InstinctStore(
        project_id="proj-a", run_id="r1", root=tmp_path,
    ).record(_record(run_id="r1", confidence=0.6))
    InstinctStore(
        project_id="proj-b", run_id="r1", root=tmp_path,
    ).record(_record(project_id="proj-b", run_id="r1", confidence=0.8))
    fp = _record().instinct.fingerprint
    decision = check_promotion(fp, root=tmp_path)
    payload = promote_to_lesson_payload(fp, decision, root=tmp_path)
    assert payload is not None
    text = payload["lesson_text"]
    assert "Pattern: use fixture X for Y" in text
    assert "2 observation(s) across 2 project(s)" in text


def test_check_promotion_returns_no_observations_when_missing(
    tmp_path: Path,
) -> None:
    decision = check_promotion("0" * 64, root=tmp_path)
    assert decision.eligible_for_promotion is False
    assert decision.reasons == ("no_observations",)
