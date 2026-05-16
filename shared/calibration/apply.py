"""Per-role calibration wrappers (STORY-3.6.4).

Thin sugar over `calibrator.calibrate(role, output_type, raw)` for the four
LLM-only output families EPIC-3.6 calls out:

    architect    risk_score          0..1 raw
    decomposer   story_estimate      hours -> log-normalised 0..1
    qa           severity            label -> ordinal 0..1
    auditor      finding_confidence  0..1 raw

Keeping the role/output_type strings + the raw->[0,1] coercions in one
place means callers don't reinvent them inconsistently across daemons.
"""
from __future__ import annotations
from math import log
from typing import Optional
from .calibrator import CalibratedPrediction, calibrate

# Decomposer hour ceiling -- estimates above this map to raw=1.0.
DECOMPOSER_HOUR_CAP = 160.0

# QA severity -> ordinal raw value. Closed list keeps the corpus consistent.
QA_SEVERITY_MAP: dict[str, float] = {
    "critical": 1.0,
    "high":     0.8,
    "medium":   0.5,
    "low":      0.2,
    "info":     0.05,
}


def calibrate_architect_risk(risk_score: float, project_id: Optional[str] = None,
                             *, db_url: Optional[str] = None
                             ) -> CalibratedPrediction:
    """Architect risk_score already lives in [0,1]; pass straight through."""
    return calibrate("architect", "risk_score", float(risk_score), db_url=db_url)


def _normalise_estimate_hours(estimate_hours: float) -> float:
    """log(h+1)/log(cap) capped at 1. Compresses long tails so a 320h estimate
    doesn't sit at raw=2.0; banded calibration needs every raw in [0,1]."""
    h = max(0.0, float(estimate_hours))
    raw = log(h + 1.0) / log(DECOMPOSER_HOUR_CAP)
    return max(0.0, min(1.0, raw))


def calibrate_decomposer_estimate(estimate_hours: float,
                                  project_id: Optional[str] = None,
                                  *, db_url: Optional[str] = None
                                  ) -> CalibratedPrediction:
    """Normalise estimate to [0,1] via log-cap, then look up the active model."""
    return calibrate("decomposer", "story_estimate",
                     _normalise_estimate_hours(estimate_hours), db_url=db_url)


def calibrate_qa_severity(severity_label: str,
                          project_id: Optional[str] = None,
                          *, db_url: Optional[str] = None
                          ) -> CalibratedPrediction:
    """Convert closed-list severity to ordinal raw, then calibrate.

    Unknown labels collapse to 0.5 (medium) -- the corpus + model handles
    drift downstream; we don't want to drop a finding because of a typo.
    """
    raw = QA_SEVERITY_MAP.get((severity_label or "").lower().strip(), 0.5)
    return calibrate("qa", "severity", raw, db_url=db_url)


def calibrate_auditor_finding(confidence: float,
                              project_id: Optional[str] = None,
                              *, db_url: Optional[str] = None
                              ) -> CalibratedPrediction:
    """Auditor finding_confidence is already a [0,1] LLM self-report."""
    return calibrate("auditor", "finding_confidence",
                     float(confidence), db_url=db_url)


__all__ = ["calibrate_architect_risk", "calibrate_decomposer_estimate",
           "calibrate_qa_severity", "calibrate_auditor_finding",
           "QA_SEVERITY_MAP", "DECOMPOSER_HOUR_CAP"]
