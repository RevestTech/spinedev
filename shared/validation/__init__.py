"""Cross-LLM validation service (EPIC-3.7).

Lifts TRON's AuditManager cross-validation pattern (`verify/tron/agents/manager.py`)
into a generalized capability usable by Plan (PRD/TRD review), Build (security-
critical engineer work), and Verify (severe findings)."""

from __future__ import annotations

from shared.validation.config import (
    DEFAULT_CROSS_LLM_PHASES,
    PhaseConfig,
    should_cross_validate,
)
from shared.validation.consensus import (
    ConsensusResult,
    compute_consensus,
)
from shared.validation.cross_llm import (
    CrossLLMValidationResult,
    ProviderResult,
    ValidationRequest,
    cross_validate,
)

__all__: list[str] = [
    "ConsensusResult",
    "CrossLLMValidationResult",
    "DEFAULT_CROSS_LLM_PHASES",
    "PhaseConfig",
    "ProviderResult",
    "ValidationRequest",
    "compute_consensus",
    "cross_validate",
    "should_cross_validate",
]
