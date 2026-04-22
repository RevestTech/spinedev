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
    """Fetch current confidence calibration metrics based on historical data."""
    engine = CalibrationEngine()
    return engine.calculate_metrics()


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
