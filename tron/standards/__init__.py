"""Standards hierarchy + quality gates (proposal §Standards Enforcement)."""

from tron.standards.defaults import DEFAULT_QUALITY_GATES
from tron.standards.engine import evaluate_quality_gates, merge_quality_gates

__all__ = [
    "DEFAULT_QUALITY_GATES",
    "merge_quality_gates",
    "evaluate_quality_gates",
]
