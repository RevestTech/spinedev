"""Spine calibration runtime: Platt + banded fallback + identity.

Implements STORY-3.6.1 (TRON lift), STORY-3.6.3 (Platt N>=500 else banded).
Lifts `verify/tron/services/calibration_engine.py` and generalises it across
(role, output_type) for Plan, Build and Verify.

Algorithm:
  N < 50         -> identity (untrusted)
  50 <= N < 500  -> banded (per-decile TP rate; sklearn-free)
  N >= 500       -> platt (sigmoid(A*x+B); numpy if present, stdlib GD else)

Active model = `calibration_model` row with `valid_to IS NULL` per pair.
Refit writes a new row and marks the prior active one `valid_to=NOW()` in
one transaction (see _persist_model). DB access mirrors shared/cost/router.
"""
from __future__ import annotations
import json, math, os, subprocess
from typing import Any, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field

DEFAULT_DB_URL = "postgresql://spine:spine@localhost:33000/spine"
IDENTITY_THRESHOLD = 50      # below: identity
PLATT_THRESHOLD = 500        # at/above: platt
DEFAULT_BANDS = 10
_MODEL_TYPES = ("platt", "banded", "identity")
Band = Literal["high", "medium-high", "medium", "low-medium", "low", "untrusted"]


class CalibratedPrediction(BaseModel):
    """Result of calibrate(); public contract for callers."""
    model_config = ConfigDict(protected_namespaces=())
    raw_value: float = Field(ge=0.0, le=1.0)
    calibrated_value: float = Field(ge=0.0, le=1.0)
    band: Band
    model_used: Literal["platt", "banded", "identity"]
    n_samples_basis: int = Field(ge=0)
    rationale: str


# ---- psql plumbing (mirrors shared/cost/router.py) ------------------

def _psql(sql: str, db_url: Optional[str]) -> Optional[str]:
    """One-shot psql; stdout or None on any failure (fail-closed)."""
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


# ---- math helpers ---------------------------------------------------

def _sigmoid(z: float) -> float:
    """Numerically-stable logistic."""
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    ez = math.exp(z)
    return ez / (1.0 + ez)


def _band_key(x: float, n_bands: int = DEFAULT_BANDS) -> str:
    """Decile band string e.g. '0.7-0.8'. >=1.0 lumps into the top band.
    Uses integer indexing on `x*n_bands` so floats like 0.7 don't slip a band."""
    w = 1.0 / n_bands
    if x >= 1.0:
        return f"{1.0 - w:.1f}-1.0"
    idx = min(n_bands - 1, max(0, int(x * n_bands + 1e-9)))
    return f"{idx * w:.1f}-{(idx + 1) * w:.1f}"


def _trust_band(model_type: str, n: int, calibrated: float) -> Band:
    """Combine model strength and prediction magnitude into a Band."""
    if model_type == "identity":
        return "untrusted"
    if model_type == "banded":
        # banded never claims 'high'; cap at medium-high.
        if calibrated >= 0.75: return "medium-high"
        if calibrated >= 0.5:  return "medium"
        if calibrated >= 0.25: return "low-medium"
        return "low"
    if n >= 1000 and calibrated >= 0.85: return "high"
    if calibrated >= 0.7:  return "medium-high"
    if calibrated >= 0.4:  return "medium"
    if calibrated >= 0.2:  return "low-medium"
    return "low"


# ---- fitters --------------------------------------------------------

def fit_platt(predictions: list[tuple[float, float]]) -> tuple[float, float]:
    """Platt scaling: fit (A,B) so sigmoid(A*x+B) approximates y.

    numpy-accelerated when available; pure-stdlib batch GD on log-loss else.
    """
    if not predictions:
        return (1.0, 0.0)
    xs = [float(x) for x, _ in predictions]
    ys = [float(y) for _, y in predictions]
    try:
        import numpy as np  # type: ignore[import-not-found]
    except ImportError:
        np = None
    a, b, lr = 1.0, 0.0, 0.5
    if np is not None:
        ax, ay = np.asarray(xs, dtype="float64"), np.asarray(ys, dtype="float64")
        for _ in range(400):
            err = 1.0 / (1.0 + np.exp(-(a * ax + b))) - ay
            a -= lr * float(np.mean(err * ax))
            b -= lr * float(np.mean(err))
        return (float(a), float(b))
    n = len(xs)
    for _ in range(400):
        ga = gb = 0.0
        for x, y in zip(xs, ys):
            err = _sigmoid(a * x + b) - y
            ga += err * x; gb += err
        a -= lr * (ga / n); b -= lr * (gb / n)
    return (a, b)


def fit_banded(predictions: list[tuple[float, float]],
               n_bands: int = DEFAULT_BANDS) -> dict[str, Any]:
    """Per-decile mean outcome. Empty bands are omitted; apply_banded
    falls back to the nearest non-empty band by midpoint."""
    buckets: dict[str, list[float]] = {}
    for x, y in predictions:
        buckets.setdefault(_band_key(x, n_bands), []).append(float(y))
    return {"bands": {k: round(sum(v) / len(v), 6) for k, v in buckets.items() if v},
            "n_bands": n_bands}


# ---- appliers -------------------------------------------------------

def _apply_platt(params: dict[str, Any], x: float) -> float:
    a, b = float(params.get("A", 1.0)), float(params.get("B", 0.0))
    return max(0.0, min(1.0, _sigmoid(a * x + b)))


def _apply_banded(params: dict[str, Any], x: float) -> float:
    """Lookup x's band; on miss, nearest non-empty by midpoint distance."""
    bands: dict[str, float] = params.get("bands") or {}
    nb = int(params.get("n_bands", DEFAULT_BANDS))
    key = _band_key(x, nb)
    if key in bands:
        return max(0.0, min(1.0, float(bands[key])))
    if not bands:
        return x
    def _mid(k: str) -> float:
        lo, hi = k.split("-"); return (float(lo) + float(hi)) / 2
    nearest = min(bands.keys(), key=lambda k: abs(_mid(k) - x))
    return max(0.0, min(1.0, float(bands[nearest])))


# ---- persistence ----------------------------------------------------

def _fetch_active_model(role: str, output_type: str, db_url: Optional[str]
                        ) -> Optional[dict[str, Any]]:
    """Active (valid_to IS NULL) model row for the (role, output_type)."""
    raw = _psql(
        "SELECT model_type, fit_params::text, n_samples "
        "FROM spine_calibration.calibration_model "
        f"WHERE role = '{_q(role)}' AND output_type = '{_q(output_type)}' "
        "AND valid_to IS NULL LIMIT 1;", db_url)
    if not raw:
        return None
    try:
        mt, params, n = raw.split("|", 2)
        return {"model_type": mt, "fit_params": json.loads(params or "{}"),
                "n_samples": int(n or 0)}
    except (ValueError, json.JSONDecodeError):
        return None


def _fetch_labeled_corpus(role: str, output_type: str, db_url: Optional[str]
                          ) -> list[tuple[float, float]]:
    """All labeled (predicted, observed) pairs for the (role, output_type)."""
    raw = _psql(
        "SELECT p.predicted_value::text || '|' || o.observed_value::text "
        "FROM spine_calibration.prediction p "
        "JOIN spine_calibration.outcome o ON o.prediction_id = p.id "
        f"WHERE p.role = '{_q(role)}' AND p.output_type = '{_q(output_type)}' "
        "ORDER BY o.observed_at ASC;", db_url)
    if not raw:
        return []
    out: list[tuple[float, float]] = []
    for line in raw.splitlines():
        try:
            x, y = line.split("|", 1); out.append((float(x), float(y)))
        except ValueError:
            continue
    return out


def _persist_model(role: str, output_type: str, model_type: str,
                   fit_params: dict[str, Any], n_samples: int,
                   db_url: Optional[str]) -> bool:
    """Atomic refit: deactivate old active row + insert new fit in one TX."""
    if model_type not in _MODEL_TYPES:
        return False
    payload = json.dumps(fit_params, sort_keys=True, separators=(",", ":"))
    sql = (
        "BEGIN; "
        "UPDATE spine_calibration.calibration_model SET valid_to = NOW() "
        f"WHERE role = '{_q(role)}' AND output_type = '{_q(output_type)}' "
        "AND valid_to IS NULL; "
        "INSERT INTO spine_calibration.calibration_model "
        "(role, output_type, model_type, fit_params, n_samples) VALUES "
        f"('{_q(role)}', '{_q(output_type)}', '{_q(model_type)}', "
        f"'{_q(payload)}'::jsonb, {int(n_samples)}); "
        "COMMIT;")
    return _psql(sql, db_url) is not None


# ---- public API -----------------------------------------------------

def calibrate(role: str, output_type: str, raw_value: float, *,
              db_url: Optional[str] = None) -> CalibratedPrediction:
    """Apply the active calibration model; identity pass-through if none."""
    raw = max(0.0, min(1.0, float(raw_value)))
    model = _fetch_active_model(role, output_type, db_url)
    if model is None or model["model_type"] == "identity":
        return CalibratedPrediction(
            raw_value=raw, calibrated_value=raw, band="untrusted",
            model_used="identity",
            n_samples_basis=(model or {}).get("n_samples", 0),
            rationale="no fitted model yet; identity pass-through (band=untrusted)")
    mt, n = model["model_type"], int(model["n_samples"])
    cal = (_apply_platt(model["fit_params"], raw) if mt == "platt"
           else _apply_banded(model["fit_params"], raw))
    return CalibratedPrediction(
        raw_value=raw, calibrated_value=cal,
        band=_trust_band(mt, n, cal), model_used=mt,  # type: ignore[arg-type]
        n_samples_basis=n,
        rationale=f"{mt} mapping fit on N={n}; raw {raw:.3f} -> calibrated {cal:.3f}")


def refit_if_due(role: str, output_type: str, *, threshold: int = PLATT_THRESHOLD,
                 db_url: Optional[str] = None) -> Optional[str]:
    """Fit (or refit) the (role, output_type) model. Returns model_type or None.

    N < IDENTITY_THRESHOLD -> identity; < threshold -> banded; else -> platt.
    Idempotent for nightly runs: always writes a fresh row.
    """
    corpus = _fetch_labeled_corpus(role, output_type, db_url)
    n = len(corpus)
    if n < IDENTITY_THRESHOLD:
        mt, params = "identity", {}
    elif n < threshold:
        mt, params = "banded", fit_banded(corpus)
    else:
        a, b = fit_platt(corpus)
        mt, params = "platt", {"A": a, "B": b}
    return mt if _persist_model(role, output_type, mt, params, n, db_url) else None


__all__ = ["CalibratedPrediction", "calibrate", "fit_platt", "fit_banded",
           "refit_if_due", "IDENTITY_THRESHOLD", "PLATT_THRESHOLD"]
