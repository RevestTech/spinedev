"""Labeled outcome corpus helpers (STORY-3.6.2).

Thin recorders that let roles + the orchestrator drop predictions and
outcomes into `spine_calibration.{prediction, outcome}` without thinking
about the SQL or the schema. All DB access via subprocess psql, matching
shared/cost/router.py + shared/calibration/calibrator.py.

Usage from a role daemon:

    pid = record_prediction("architect", "risk_score", 0.82,
                            project_id=42, subject_id="story-uuid",
                            features={"model": "claude-opus-4-7"})
    # ... time passes, outcome observed (verify pass, user approval, ...)
    record_outcome(pid, observed_value=1.0, source="user_approval")
"""
from __future__ import annotations
import json, os, subprocess
from typing import Any, Literal, Optional

DEFAULT_DB_URL = "postgresql://spine:spine@localhost:33000/spine"
OutcomeSource = Literal["user_approval", "verify_pass", "prod_incident",
                        "time_elapsed", "manual_review"]
_VALID_SOURCES = {"user_approval", "verify_pass", "prod_incident",
                  "time_elapsed", "manual_review"}


def _psql(sql: str, db_url: Optional[str]) -> Optional[str]:
    """One-shot psql; stdout or None on failure (matches calibrator._psql)."""
    url = db_url or os.environ.get("SPINE_DB_URL", DEFAULT_DB_URL)
    try:
        r = subprocess.run(["psql", url, "-A", "-t", "-X", "-q",
                            "-v", "ON_ERROR_STOP=1", "-c", sql],
                           capture_output=True, text=True, timeout=10, check=True)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
            FileNotFoundError):
        return None
    return r.stdout.strip() or None


_q = lambda s: s.replace("'", "''")


def _clip01(v: float) -> float:
    """Clip a numeric value into [0,1] -- the CHECK constraints' domain."""
    return max(0.0, min(1.0, float(v)))


def _opt_int(v: Optional[int]) -> str:
    return "NULL" if v is None else str(int(v))


def _opt_str(v: Optional[str]) -> str:
    return "NULL" if v is None else f"'{_q(v)}'"


def record_prediction(role: str, output_type: str, raw_value: float, *,
                      project_id: Optional[int] = None,
                      subject_id: Optional[str] = None,
                      features: Optional[dict[str, Any]] = None,
                      audit_event_id: Optional[int] = None,
                      db_url: Optional[str] = None) -> Optional[int]:
    """Insert one row into spine_calibration.prediction. Returns its id."""
    if not role or not output_type:
        raise ValueError("role and output_type must be non-empty")
    v = _clip01(raw_value)
    payload = json.dumps(features or {}, sort_keys=True, separators=(",", ":"))
    sql = (
        "INSERT INTO spine_calibration.prediction "
        "(role, output_type, project_id, subject_id, predicted_value, "
        "raw_features, audit_event_id) VALUES "
        f"('{_q(role)}', '{_q(output_type)}', {_opt_int(project_id)}, "
        f"{_opt_str(subject_id)}, {v:.4f}, '{_q(payload)}'::jsonb, "
        f"{_opt_int(audit_event_id)}) RETURNING id;")
    raw = _psql(sql, db_url)
    if not raw:
        return None
    try:
        return int(raw.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return None


def record_outcome(prediction_id: int, observed_value: float,
                   source: OutcomeSource, *, notes: Optional[str] = None,
                   db_url: Optional[str] = None) -> Optional[int]:
    """Insert one row into spine_calibration.outcome. Returns its id."""
    if source not in _VALID_SOURCES:
        raise ValueError(f"outcome source {source!r} not in {sorted(_VALID_SOURCES)}")
    v = _clip01(observed_value)
    sql = (
        "INSERT INTO spine_calibration.outcome "
        "(prediction_id, observed_value, outcome_source, notes) VALUES "
        f"({int(prediction_id)}, {v:.4f}, '{_q(source)}', {_opt_str(notes)}) "
        "RETURNING id;")
    raw = _psql(sql, db_url)
    if not raw:
        return None
    try:
        return int(raw.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return None


def pending_outcomes_count(role: Optional[str] = None,
                           output_type: Optional[str] = None,
                           db_url: Optional[str] = None) -> int:
    """Count predictions still missing an outcome row. 0 on DB miss."""
    where = ["o.id IS NULL"]
    if role:
        where.append(f"p.role = '{_q(role)}'")
    if output_type:
        where.append(f"p.output_type = '{_q(output_type)}'")
    raw = _psql(
        "SELECT COUNT(*)::bigint FROM spine_calibration.prediction p "
        "LEFT JOIN spine_calibration.outcome o ON o.prediction_id = p.id "
        f"WHERE {' AND '.join(where)};", db_url)
    try:
        return int(raw) if raw else 0
    except ValueError:
        return 0


def labeled_corpus_size(role: str, output_type: str, *,
                        db_url: Optional[str] = None) -> int:
    """Labeled (prediction + outcome) pair count for the pair. 0 on DB miss."""
    raw = _psql(
        "SELECT COUNT(*)::bigint FROM spine_calibration.prediction p "
        "JOIN spine_calibration.outcome o ON o.prediction_id = p.id "
        f"WHERE p.role = '{_q(role)}' AND p.output_type = '{_q(output_type)}';",
        db_url)
    try:
        return int(raw) if raw else 0
    except ValueError:
        return 0


__all__ = ["record_prediction", "record_outcome", "pending_outcomes_count",
           "labeled_corpus_size", "OutcomeSource"]
