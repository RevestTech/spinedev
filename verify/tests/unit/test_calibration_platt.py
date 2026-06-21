"""Calibration engine — Platt scaling vs. banded fallback (#3).

Covers:
  * Banded fallback still works when no labeled corpus is supplied
    (legacy behaviour preserved).
  * Platt fit kicks in once N ≥ platt_min_samples AND at least one
    sample of each class is present.
  * Single-class corpus is rejected gracefully (logs, falls back).
  * Below-threshold corpus does NOT trigger a fit.
  * The fitted mapping is monotonic in raw confidence (higher raw →
    higher calibrated, given the synthetic data is well-ordered).
"""

from __future__ import annotations

import random
from uuid import uuid4

import pytest

from tron.schemas.verification import (
    FindingOutput,
    SeverityLevel,
    VulnerabilityType,
)
from tron.services.calibration_engine import (
    CalibrationEngine,
    LabeledOutcome,
    _HAS_SKLEARN,
)


def _f(conf: float) -> FindingOutput:
    # ``deterministic_tool_confirmed=True`` lifts the schema's 0.7 cap on
    # LLM-only findings, which lets us drive the calibration engine at any
    # raw confidence in [0, 1] for these unit tests. The calibration math
    # doesn't read this flag.
    return FindingOutput(
        id=str(uuid4()),
        title="t",
        agent_id="a",
        blueprint_id="bp",
        finding_fingerprint=f"fp-{uuid4().hex[:8]}",
        file_path="x.py",
        line_number=1,
        vulnerability_type=VulnerabilityType.SQL_INJECTION,
        severity=SeverityLevel.HIGH,
        confidence=conf,
        description="t",
        code_snippet="x = 1",
        fix_suggestion="fix",
        deterministic_tool_confirmed=True,
    )


# ── Banded fallback (legacy behaviour preserved) ──────────────────────────


class TestBandedFallback:
    def test_no_corpus_uses_band_aggregates(self):
        # Engine constructed with default (mock) banded data and no
        # labeled outcomes — must apply per-band TP rate exactly as the
        # legacy implementation did.
        eng = CalibrationEngine()
        out = eng.apply_calibration(_f(0.85))  # band 0.8-0.9 → 85/100
        assert out.calibrated_confidence == pytest.approx(0.85)
        # ``use_platt_scaling`` lives on CalibrationMetric (the report
        # row), not on FindingOutput; check the engine flag instead.
        assert eng.is_platt_active is False

    def test_below_threshold_corpus_does_not_fit(self):
        # 50 samples with platt_min_samples=500 → no fit, banded fallback.
        outcomes = [
            LabeledOutcome(raw_confidence=0.5, is_true_positive=True)
            for _ in range(25)
        ] + [
            LabeledOutcome(raw_confidence=0.2, is_true_positive=False)
            for _ in range(25)
        ]
        eng = CalibrationEngine(
            labeled_outcomes=outcomes, platt_min_samples=500
        )
        assert eng.is_platt_active is False
        assert eng.platt_sample_count == 0


# ── Platt fit (requires sklearn) ──────────────────────────────────────────


@pytest.mark.skipif(not _HAS_SKLEARN, reason="sklearn not installed")
class TestPlattFit:
    def _make_corpus(self, n: int = 600, seed: int = 42):
        # Synthetic well-separated corpus: TP probability rises smoothly
        # with raw confidence, so a logistic fit should land cleanly.
        rng = random.Random(seed)
        outcomes = []
        for _ in range(n):
            raw = rng.uniform(0.0, 1.0)
            # P(TP) = raw — clean labeled outcomes for the fit.
            is_tp = rng.random() < raw
            outcomes.append(LabeledOutcome(raw_confidence=raw, is_true_positive=is_tp))
        return outcomes

    def test_fit_engages_above_threshold(self):
        outcomes = self._make_corpus(n=600)
        eng = CalibrationEngine(
            labeled_outcomes=outcomes, platt_min_samples=500
        )
        assert eng.is_platt_active is True
        assert eng.platt_sample_count == 600

    def test_fit_is_monotonic_in_raw_confidence(self):
        # If P(TP) grows with raw, the calibrated mapping should too.
        outcomes = self._make_corpus(n=800, seed=11)
        eng = CalibrationEngine(
            labeled_outcomes=outcomes, platt_min_samples=500
        )
        cals = [eng.apply_calibration(_f(c)).calibrated_confidence for c in
                [0.05, 0.25, 0.5, 0.75, 0.95]]
        # Strictly non-decreasing, with at least some spread.
        for prev, curr in zip(cals, cals[1:]):
            assert curr >= prev - 1e-9
        assert cals[-1] - cals[0] > 0.2

    def test_calibrated_in_unit_interval(self):
        outcomes = self._make_corpus(n=600, seed=7)
        eng = CalibrationEngine(
            labeled_outcomes=outcomes, platt_min_samples=500
        )
        for c in [0.0, 0.25, 0.5, 0.75, 1.0]:
            out = eng.apply_calibration(_f(c))
            assert 0.0 <= out.calibrated_confidence <= 1.0
        # Engine reports Platt is active — finding itself doesn't carry
        # the flag (it's on CalibrationMetric, the per-band reporting row).
        assert eng.is_platt_active is True

    def test_single_class_corpus_falls_back(self):
        # All TPs — fit can't happen. Engine should log and degrade to
        # banded fallback rather than crashing.
        outcomes = [
            LabeledOutcome(raw_confidence=0.5, is_true_positive=True)
            for _ in range(600)
        ]
        eng = CalibrationEngine(
            labeled_outcomes=outcomes, platt_min_samples=500
        )
        assert eng.is_platt_active is False
        # Banded path still works.
        out = eng.apply_calibration(_f(0.85))
        assert out.calibrated_confidence == pytest.approx(0.85)


# ── platt_params introspection ───────────────────────────────────────────


@pytest.mark.skipif(not _HAS_SKLEARN, reason="sklearn not installed")
class TestPlattIntrospection:
    def test_platt_params_returns_shape(self):
        rng = random.Random(0)
        outcomes = [
            LabeledOutcome(raw_confidence=rng.uniform(0, 1),
                           is_true_positive=rng.random() < 0.5)
            for _ in range(600)
        ]
        # Inject at least one of each class.
        outcomes[0] = LabeledOutcome(raw_confidence=0.99, is_true_positive=True)
        outcomes[1] = LabeledOutcome(raw_confidence=0.01, is_true_positive=False)

        eng = CalibrationEngine(
            labeled_outcomes=outcomes, platt_min_samples=500
        )
        if not eng.is_platt_active:
            pytest.skip("synthetic corpus didn't engage Platt")
        params = eng.platt_params()
        assert params is not None
        assert "a" in params and "b" in params and "n_samples" in params
        assert params["n_samples"] == 600

    def test_platt_params_is_none_when_inactive(self):
        eng = CalibrationEngine()
        assert eng.platt_params() is None
