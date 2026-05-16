"""
Spine Technical Review Swarm — architect-led fan-out / collect / synthesize.

Implements REQ-INIT-1 FR-3 (`docs/PRD.md`) and `STORY-1.2.1` + `STORY-1.2.4`
(`docs/BACKLOG.md` EPIC-1.2). The swarm engine is a LangGraph subgraph hosted
inside the architect daemon; this package is standalone-importable so it can
be unit-tested without the full Spine runtime.

See `swarm_README.md` for the architecture diagram and per-scout lens map.
"""

from .composition_rules import get_swarm_for, load_pipeline
from .scout_contribution import (
    Finding,
    RiskItem,
    ScoutContribution,
    ScoutLens,
    ScoutRole,
    Severity,
)
from .synthesis import SynthesisError, synthesize_trd

__all__ = [
    "Finding",
    "RiskItem",
    "ScoutContribution",
    "ScoutLens",
    "ScoutRole",
    "Severity",
    "SynthesisError",
    "get_swarm_for",
    "load_pipeline",
    "synthesize_trd",
]
