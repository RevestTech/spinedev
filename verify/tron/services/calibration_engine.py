"""
Calibration & Drift Engine (L6/L7) — calibration service.

Now actually does Platt scaling when a labeled-outcomes corpus is provided
(closes the documented gap that this used to be "raw accuracy as a stand-in
for calibrated probability"). Falls back to per-band accuracy when the
corpus is too small for a stable logistic fit.

Two modes
---------
1. **Banded mode** (default, low N): per-confidence-band true-positive rate.
   Matches the legacy behaviour exactly — preserves backwards compatibility
   for callers without labeled outcomes.

2. **Platt mode** (N ≥ ``platt_min_samples``, default 500): fit a logistic
   ``calibrated = 1 / (1 + exp(A * raw + B))`` over the labeled corpus.
   Uses scikit-learn's ``LogisticRegression`` if available; otherwise falls
   back gracefully to banded mode and logs a warning.

The sklearn import is gated so this module imports cleanly in any
environment — tests, CI, even installs that haven't run
``pip install scikit-learn`` yet. When sklearn IS present the fit
produces a real Platt-scaled mapping; until you have real labels,
the corpus-loader CLI is the gating piece, not the math.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

from tron.schemas.verification import FindingOutput, CalibrationMetric


logger = logging.getLogger(__name__)


# ── Sklearn — optional ────────────────────────────────────────────────────


try:
    from sklearn.linear_model import LogisticRegression
    _HAS_SKLEARN = True
except Exception:  # pragma: no cover - exercised only without sklearn
    LogisticRegression = None  # type: ignore[assignment]
    _HAS_SKLEARN = False


# ── Labeled-outcome ingestion ─────────────────────────────────────────────


@dataclass
class LabeledOutcome:
    """One row of the labeled-outcomes corpus.

    A finding produced by the audit pipeline that has been adjudicated
    after the fact (true positive vs false positive). The corpus is
    assembled by ``scripts/calibration_corpus.py`` from triaged audit
    runs; this dataclass is the wire shape between that loader and the
    calibration engine.
    """

    raw_confidence: float
    is_true_positive: bool


# ── Calibration engine ────────────────────────────────────────────────────


class CalibrationEngine:
    """
    Engine for calibrating finding confidence scores based on historical performance.

    Calibration ensures that a confidence score of 0.9 actually corresponds to a 90%
    true positive rate in production.
    """

    # Minimum N before we attempt a Platt fit. Below this, the logistic
    # regression is overfit and noisier than per-band accuracy. The 500
    # threshold matches ``VERIFICATION_PLATT_SCALING_MIN_SAMPLES`` in
    # .env.example so ops can tune both with one knob.
    DEFAULT_PLATT_MIN_SAMPLES = 500

    def __init__(
        self,
        historical_data: Optional[Dict[str, Dict[str, int]]] = None,
        labeled_outcomes: Optional[Sequence[LabeledOutcome]] = None,
        platt_min_samples: int = DEFAULT_PLATT_MIN_SAMPLES,
    ):
        """
        Initialize with historical accuracy data and/or labeled outcomes.

        Args:
            historical_data: Per-band aggregates ({ "0.8-0.9": { "true_positives": 170,
                "total_findings": 200 } }). Used by the banded fallback path
                and for ``calculate_metrics()`` reporting.
            labeled_outcomes: Per-finding labels. When ``len(...) >=
                platt_min_samples`` and sklearn is available, a logistic
                Platt mapping is fit over these and used for
                ``apply_calibration``.
            platt_min_samples: Below this count, we do NOT attempt a
                Platt fit (logistic regression with too few samples
                overfits).
        """
        # Default mock data if none provided. Backwards compatible with
        # callers that don't pass labeled_outcomes.
        self.historical_data = historical_data or {
            "0.0-0.1": {"true_positives": 5, "total_findings": 100},
            "0.1-0.2": {"true_positives": 15, "total_findings": 100},
            "0.2-0.3": {"true_positives": 25, "total_findings": 100},
            "0.3-0.4": {"true_positives": 35, "total_findings": 100},
            "0.4-0.5": {"true_positives": 45, "total_findings": 100},
            "0.5-0.6": {"true_positives": 55, "total_findings": 100},
            "0.6-0.7": {"true_positives": 65, "total_findings": 100},
            "0.7-0.8": {"true_positives": 75, "total_findings": 100},
            "0.8-0.9": {"true_positives": 85, "total_findings": 100},
            "0.9-1.0": {"true_positives": 96, "total_findings": 100},
        }
        self.platt_min_samples = platt_min_samples
        self._platt_params: Optional[Tuple[float, float]] = None
        self._platt_n: int = 0

        if labeled_outcomes and len(labeled_outcomes) >= platt_min_samples:
            self._platt_params = self._fit_platt(labeled_outcomes)
            self._platt_n = len(labeled_outcomes)

    # ── Per-band helpers (unchanged from legacy) ──────────────────────

    def get_confidence_band(self, confidence: float) -> str:
        """Categorize a confidence score into a 10% band."""
        if confidence >= 1.0:
            return "0.9-1.0"
        lower = int(confidence * 10) / 10.0
        upper = lower + 0.1
        return f"{lower:.1f}-{upper:.1f}"

    def calculate_metrics(self) -> List[CalibrationMetric]:
        """Generate CalibrationMetric objects for all tracked confidence bands."""
        metrics = []
        for band, data in self.historical_data.items():
            tp = data["true_positives"]
            total = data["total_findings"]
            accuracy = tp / total if total > 0 else 0.0

            try:
                parts = band.split("-")
                lower = float(parts[0])
                upper = float(parts[1])
                midpoint = (lower + upper) / 2
            except (ValueError, IndexError):
                midpoint = 0.5

            error = accuracy - midpoint

            metrics.append(CalibrationMetric(
                confidence_band=band,
                total_findings=total,
                true_positives=tp,
                false_positives=total - tp,
                actual_accuracy=accuracy,
                calibration_error=error,
                sample_sufficient=total >= 200,
                measured_at=datetime.utcnow()
            ))
        return metrics

    # ── Platt-scaling fit ─────────────────────────────────────────────

    def _fit_platt(
        self, outcomes: Sequence[LabeledOutcome]
    ) -> Optional[Tuple[float, float]]:
        """Fit logistic ``P(true) = 1 / (1 + exp(A * raw + B))``.

        Returns ``(A, B)`` on success, ``None`` if the fit can't be made.
        """
        if not _HAS_SKLEARN:
            logger.warning(
                "Platt scaling requested with %d labeled outcomes but "
                "scikit-learn is not installed — falling back to banded "
                "calibration. Install scikit-learn to enable Platt fits.",
                len(outcomes),
            )
            return None

        # Need at least one of each class — sklearn's LogisticRegression
        # raises on a single-class label set.
        labels = [int(o.is_true_positive) for o in outcomes]
        if 0 not in labels or 1 not in labels:
            logger.warning(
                "Platt fit aborted: corpus has only one class "
                "(%d positives, %d negatives). Need both.",
                sum(labels), len(labels) - sum(labels),
            )
            return None

        X = [[o.raw_confidence] for o in outcomes]
        y = labels
        model = LogisticRegression(solver="lbfgs", max_iter=1000)
        try:
            model.fit(X, y)
        except Exception:  # pragma: no cover — sklearn internal failure
            logger.exception("Platt fit failed")
            return None

        # Sklearn parameterisation: log_odds = w*x + b. Convert to the
        # canonical Platt form ``1 / (1 + exp(A*raw + B))`` by negating:
        #   P = sigmoid(w*x + b) = 1 / (1 + exp(-(w*x + b)))
        #   so A = -w, B = -b.
        w = float(model.coef_[0][0])
        b = float(model.intercept_[0])
        return (-w, -b)

    @staticmethod
    def _apply_platt(raw: float, params: Tuple[float, float]) -> float:
        a, b = params
        # Clip the exponent to avoid float-overflow on extreme scores.
        z = max(min(a * raw + b, 50.0), -50.0)
        return 1.0 / (1.0 + math.exp(z))

    # ── Calibration application ───────────────────────────────────────

    def apply_calibration(self, finding: FindingOutput) -> FindingOutput:
        """
        Apply calibrated_confidence to a finding based on its raw confidence.

        Resolution order:
          1. Platt fit if active (sklearn + N ≥ platt_min_samples).
          2. Per-band historical accuracy otherwise.
          3. Pass-through if neither has data for this finding.
        """
        if self._platt_params is not None:
            calibrated = self._apply_platt(finding.confidence, self._platt_params)
            calibrated = max(0.0, min(1.0, calibrated))
            # ``use_platt_scaling`` lives on CalibrationMetric (the
            # operator-facing report row), not on FindingOutput. The
            # engine itself exposes ``is_platt_active`` for callers
            # that want to know which path produced a given calibration.
            return finding.model_copy(update={
                "calibrated_confidence": calibrated,
            })

        band = self.get_confidence_band(finding.confidence)
        data = self.historical_data.get(band)

        if data and data["total_findings"] > 0:
            # Banded calibration: this band's empirical TP rate.
            calibrated = data["true_positives"] / data["total_findings"]
            calibrated = max(0.0, min(1.0, calibrated))

            return finding.model_copy(update={
                "calibrated_confidence": calibrated,
            })

        return finding

    def batch_calibrate(self, findings: List[FindingOutput]) -> List[FindingOutput]:
        """Apply calibration to a batch of findings."""
        return [self.apply_calibration(f) for f in findings]

    # ── Introspection (used by admin metrics endpoint + tests) ────────

    @property
    def is_platt_active(self) -> bool:
        return self._platt_params is not None

    @property
    def platt_sample_count(self) -> int:
        return self._platt_n

    def platt_params(self) -> Optional[Dict[str, Any]]:
        if self._platt_params is None:
            return None
        a, b = self._platt_params
        return {"a": a, "b": b, "n_samples": self._platt_n}
