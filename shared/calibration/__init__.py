"""Spine confidence calibration runtime (INIT-3 / EPIC-3.6).

Platt scaling + banded fallback for LLM-only outputs, lifted from TRON's
Layer-6 calibration into a shared Plan/Build/Verify service. See
`calibration_README.md` and `db/flyway/sql/V18__calibration_corpus.sql`.
"""
from .calibrator import (CalibratedPrediction, calibrate, fit_platt,
                         fit_banded, refit_if_due)
from .outcome_corpus import (record_prediction, record_outcome,
                             pending_outcomes_count)
from .calibration_sink import (CalibrationOutputType, CalibrationRole,
                               capture, capture_many)

__all__ = ["CalibratedPrediction", "CalibrationOutputType",
           "CalibrationRole", "calibrate", "capture", "capture_many",
           "fit_platt", "fit_banded", "refit_if_due", "record_prediction",
           "record_outcome", "pending_outcomes_count"]
