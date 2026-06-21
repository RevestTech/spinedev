"""
Calibration & Drift Engine (L6/L7) - API Routes

Exposes calibration and drift detection engines via administrative endpoints.
"""

from __future__ import annotations
from typing import List
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from tron.schemas.verification import CalibrationMetric, DriftScore, FindingOutput
from tron.services.calibration_engine import CalibrationEngine
from tron.services.drift_engine import DriftEngine
from tron.api.middleware.auth import require_api_key

router = APIRouter(prefix="/admin", tags=["Admin Metrics"])


class DriftCheckRequest(BaseModel):
    template_id: str
    current_text: str
    baseline_text: str
    threshold: float = 0.95


@router.get("/calibration", response_model=List[CalibrationMetric])
async def get_calibration_metrics(_: str = Depends(require_api_key)):
    """Fetch current confidence calibration metrics based on historical data.

    Each row's ``use_platt_scaling`` reflects whether the engine's
    Platt-scaling fit is currently active (i.e. a labeled corpus of
    sufficient size has been provided AND scikit-learn is available).
    """
    engine = CalibrationEngine()
    metrics = engine.calculate_metrics()
    # Reflect the engine's actual Platt status on every row so an
    # operator scanning the metrics table can tell at a glance whether
    # they're seeing a real fit or the banded fallback.
    is_platt = engine.is_platt_active
    return [m.model_copy(update={"use_platt_scaling": is_platt}) for m in metrics]


class CalibrationStatus(BaseModel):
    """Operator-facing summary: which calibration mode is in effect?"""

    mode: str  # "platt" | "banded"
    is_platt_active: bool
    platt_sample_count: int
    sklearn_available: bool


@router.get("/calibration/status", response_model=CalibrationStatus)
async def calibration_status(_: str = Depends(require_api_key)):
    """Report which calibration path is in effect right now.

    Useful for ops dashboards: "are we doing real Platt scaling, or is
    the engine still on the banded mock fallback?" When ``mode=banded``
    you're getting per-confidence-band TP rates from
    ``CalibrationEngine.historical_data`` (default mock unless a corpus
    has been loaded); when ``mode=platt`` you're getting a logistic fit
    over labeled outcomes.
    """
    from tron.services.calibration_engine import _HAS_SKLEARN

    engine = CalibrationEngine()
    return CalibrationStatus(
        mode="platt" if engine.is_platt_active else "banded",
        is_platt_active=engine.is_platt_active,
        platt_sample_count=engine.platt_sample_count,
        sklearn_available=_HAS_SKLEARN,
    )


@router.post("/calibration/apply", response_model=List[FindingOutput])
async def apply_calibration(findings: List[FindingOutput], _: str = Depends(require_api_key)):
    """Apply historical calibration to a batch of findings."""
    engine = CalibrationEngine()
    return engine.batch_calibrate(findings)


@router.post("/drift/check", response_model=DriftScore)
async def check_drift(req: DriftCheckRequest, _: str = Depends(require_api_key)):
    """Check for semantic or hash-based drift in agent prompts."""
    engine = DriftEngine()
    return engine.calculate_drift(
        template_id=req.template_id,
        current_text=req.current_text,
        baseline_text=req.baseline_text,
        threshold=req.threshold
    )


class RegressionTestRequest(BaseModel):
    template_id: str
    test_input: str
    expected_behavior: bool
    actual_behavior: bool


@router.post("/regression/run")
async def run_regression_test(req: RegressionTestRequest, _: str = Depends(require_api_key)):
    """Trigger a simple regression test for an agent template."""
    engine = DriftEngine()
    passed = engine.verify_regression(
        template_id=req.template_id,
        test_input=req.test_input,
        expected_behavior=req.expected_behavior,
        actual_behavior=req.actual_behavior
    )
    return {"template_id": req.template_id, "passed": passed}
