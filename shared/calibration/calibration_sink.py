"""Calibration sink — Wave 1 substrate wiring (V3 #27, decision 1.4 #10).

Every audit-class invoke (verify / iso / auditor) produces a prediction
(risk band, severity, confidence, estimate) that today gets discarded.
This helper persists each (predicted, observed?) pair into
``spine_calibration.{prediction, outcome}`` so the existing Platt /
banded refit loop in ``shared.calibration.calibrator`` has corpus to
learn from.

Single async entry point:

    await capture(
        role='verify' | 'iso' | 'auditor',
        output_type='risk_band' | 'estimate' | 'severity' | 'confidence',
        predicted=<any>,
        outcome=<any | None>,                # None = unresolved
        audit_record_id=<int | None>,
        project_id=<int | None>,
        metadata={...},
    )

Design choices:

  * Async surface — matches every other Wave 0+ shared library (#9).
  * Numeric coercion handled internally: severity strings ('critical',
    'high', ...) map to ordinal floats; raw booleans map to {0.0, 1.0};
    free-form risk_band strings (e.g. 'high_precision') are accepted
    via a documented coercion table.
  * Writer uses ``record_prediction`` + (optionally) ``record_outcome``
    from ``shared.calibration.outcome_corpus`` — no new SQL paths.
  * NO secrets read from env. All DB access goes through the existing
    psql subprocess plumbing in ``outcome_corpus`` which derives its
    URL from ``SPINE_DB_URL``/``DATABASE_URL`` — once Wave 0
    ``shared.secrets`` is wired everywhere, the DB URL itself routes
    through ``shared.secrets.get_secret``.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Iterable, Literal, Optional

from shared.calibration.outcome_corpus import (
    record_outcome as _record_outcome,
    record_prediction as _record_prediction,
)

logger = logging.getLogger(__name__)

CalibrationRole = Literal["verify", "iso", "auditor"]
CalibrationOutputType = Literal["risk_band", "estimate", "severity", "confidence"]

# Five accepted outcome sources (matches the V18 CHECK constraint).
_DEFAULT_OUTCOME_SOURCE = "verify_pass"
_ALLOWED_ROLES: frozenset[str] = frozenset({"verify", "iso", "auditor"})
_ALLOWED_OUTPUT_TYPES: frozenset[str] = frozenset(
    {"risk_band", "estimate", "severity", "confidence"}
)

# Severity-string → ordinal float coercion. Mirrors apply.py qa map.
_SEVERITY_ORDINAL: dict[str, float] = {
    "critical": 1.0,
    "high": 0.75,
    "medium": 0.50,
    "low": 0.25,
    "info": 0.05,
}

# Calibration band string → representative float. The "actual" calibration
# corpus is bucketed downstream; what matters here is monotonic ordering.
_RISK_BAND_ORDINAL: dict[str, float] = {
    "untrusted":     0.10,
    "low":           0.25,
    "medium":        0.50,
    "medium_high":   0.65,
    "high":          0.80,
    "high_precision": 0.90,
    "very_high":     0.95,
}


def _coerce_predicted(output_type: str, value: Any) -> Optional[float]:
    """Convert a heterogeneous predicted value to a [0,1] float."""
    if value is None:
        return None
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return _clip(float(value))
    if isinstance(value, str):
        v = value.strip().lower()
        if output_type == "severity" and v in _SEVERITY_ORDINAL:
            return _SEVERITY_ORDINAL[v]
        if output_type == "risk_band" and v in _RISK_BAND_ORDINAL:
            return _RISK_BAND_ORDINAL[v]
        # Try numeric string.
        try:
            return _clip(float(v))
        except ValueError:
            return None
    return None


def _coerce_outcome(output_type: str, value: Any) -> Optional[float]:
    """Outcome coercion follows the same table as predicted."""
    return _coerce_predicted(output_type, value)


def _clip(v: float) -> float:
    return max(0.0, min(1.0, v))


# ─── Public surface ─────────────────────────────────────────────────


async def capture(
    *,
    role: CalibrationRole,
    output_type: CalibrationOutputType,
    predicted: Any,
    outcome: Any = None,
    audit_record_id: Optional[int] = None,
    project_id: Optional[int] = None,
    metadata: Optional[dict[str, Any]] = None,
    outcome_source: str = _DEFAULT_OUTCOME_SOURCE,
    subject_id: Optional[str] = None,
) -> Optional[int]:
    """Persist a prediction (and optionally its outcome) for calibration.

    Returns the ``spine_calibration.prediction.id`` if the prediction
    row was written successfully, else ``None`` (DB miss / coercion
    failed — failures are logged + swallowed so the audit hot-path is
    never broken).

    Per V3 #27 risk: this helper is called from every audit-class
    invoke; it must be both async (to match the rest of Wave 0+ libs)
    and bullet-proof against partial DB outages.
    """
    if role not in _ALLOWED_ROLES:
        raise ValueError(
            f"role {role!r} not in {sorted(_ALLOWED_ROLES)}"
        )
    if output_type not in _ALLOWED_OUTPUT_TYPES:
        raise ValueError(
            f"output_type {output_type!r} not in {sorted(_ALLOWED_OUTPUT_TYPES)}"
        )

    raw_predicted = _coerce_predicted(output_type, predicted)
    if raw_predicted is None:
        logger.warning(
            "calibration_sink: cannot coerce predicted %r for output_type=%s; skip",
            predicted, output_type,
        )
        return None

    features: dict[str, Any] = {"original_predicted": predicted}
    if metadata:
        features.update(metadata)

    prediction_id = await asyncio.to_thread(
        _record_prediction,
        role, output_type, raw_predicted,
        project_id=project_id,
        subject_id=subject_id,
        features=features,
        audit_event_id=audit_record_id,
    )
    if prediction_id is None:
        logger.warning(
            "calibration_sink: prediction insert failed (role=%s, output_type=%s)",
            role, output_type,
        )
        return None

    if outcome is not None:
        raw_outcome = _coerce_outcome(output_type, outcome)
        if raw_outcome is None:
            logger.info(
                "calibration_sink: outcome %r coercion failed; prediction "
                "row %d left unresolved", outcome, prediction_id,
            )
        else:
            try:
                await asyncio.to_thread(
                    _record_outcome,
                    prediction_id, raw_outcome, outcome_source,
                )
            except ValueError:
                logger.exception(
                    "calibration_sink: invalid outcome_source %r", outcome_source,
                )
    return prediction_id


async def capture_many(events: Iterable[dict[str, Any]]) -> list[Optional[int]]:
    """Batch helper: fire :func:`capture` for each event dict.

    Each dict must carry the kwargs to ``capture``. Returns a list of
    prediction ids (or None per row on failure). Useful for the per-
    audit batch produced by ``verify_audit`` (one prediction per finding
    + one prediction per layer band).
    """
    return list(await asyncio.gather(*(capture(**e) for e in events)))


__all__ = [
    "CalibrationOutputType",
    "CalibrationRole",
    "capture",
    "capture_many",
]
