"""
Calibration & Drift Engine (L6/L7) - Calibration Service

This service calculates CalibrationMetric and applies calibrated_confidence to findings
based on historical accuracy data.
"""

from __future__ import annotations
from datetime import datetime
from typing import List, Dict, Optional
from uuid import UUID

from tron.schemas.verification import FindingOutput, CalibrationMetric


class CalibrationEngine:
    """
    Engine for calibrating finding confidence scores based on historical performance.
    
    Calibration ensures that a confidence score of 0.9 actually corresponds to a 90% 
    true positive rate in production.
    """

    def __init__(self, historical_data: Optional[Dict[str, Dict[str, int]]] = None):
        """
        Initialize with historical accuracy data.
        
        Data format: { "0.8-0.9": { "true_positives": 170, "total_findings": 200 } }
        """
        # Default mock data if none provided
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
            
            # Extract midpoint from band name for error calculation
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

    def apply_calibration(self, finding: FindingOutput) -> FindingOutput:
        """
        Apply calibrated_confidence to a finding based on its raw confidence.
        
        Uses historical accuracy of findings in the same confidence band to 
        provide a more realistic probability of the finding being a true positive.
        """
        band = self.get_confidence_band(finding.confidence)
        data = self.historical_data.get(band)
        
        if data and data["total_findings"] > 0:
            # For this prototype, we use the raw accuracy as the calibrated confidence.
            # In production, this would use Platt scaling or Isotonic regression.
            calibrated = data["true_positives"] / data["total_findings"]
            calibrated = max(0.0, min(1.0, calibrated))
            
            return finding.model_copy(update={
                "calibrated_confidence": calibrated
            })
        
        return finding

    def batch_calibrate(self, findings: List[FindingOutput]) -> List[FindingOutput]:
        """Apply calibration to a batch of findings."""
        return [self.apply_calibration(f) for f in findings]
