"""Per-phase cross-LLM validation policy (STORY-3.7.2).

Decides whether a given (phase, severity) combination warrants spending the
extra ~2x LLM cost to have a second provider independently verify the primary
model's output. Defaults follow the PRD guidance in REQ-INIT-3 / EPIC-3.7:

- Discovery / decomposition / acceptance — too cheap or too routine; skip.
- Technical review (TRD synthesis) and verify (severe findings) — always on.
- Build — gated by call site (only security-critical changes trigger it).

The org bundle's ``verify_overrides.cross_llm_validation_required`` (see
``shared/standards/bundle-schema.yaml``) is a single global on/off; when True,
phases default to enabled; when False, only ``critical`` severity overrides.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Severity = Literal["critical", "high", "medium", "low"]

DEFAULT_CROSS_LLM_PHASES: dict[str, bool] = {
    "discovery": False,           # cheap intake — skip
    "technical_review": True,     # TRD synthesis — yes (Plan honesty layer)
    "decomposition": False,
    "build": True,                # call-site gated to security-critical work
    "verify": True,               # critical / high findings (TRON pattern)
    "acceptance": False,
}

_SEVERITY_RANK: dict[str, int] = {"low": 0, "medium": 1, "high": 2, "critical": 3}


class PhaseConfig(BaseModel):
    """Resolved per-phase policy after merging defaults + bundle overrides."""

    model_config = ConfigDict(frozen=True)

    phase: str = Field(..., min_length=1)
    enabled: bool
    severity_floor: Severity = "high"
    source: Literal["default", "bundle_override", "severity_escalation"] = "default"


def _bundle_override(bundle: dict[str, Any] | None) -> bool | None:
    """Read ``verify_overrides.cross_llm_validation_required``; None if unset."""
    if not bundle:
        return None
    vo = (bundle.get("verify_overrides") or {}) if isinstance(bundle, dict) else {}
    val = vo.get("cross_llm_validation_required")
    return bool(val) if isinstance(val, bool) else None


def resolve_phase_config(phase: str, bundle: dict[str, Any] | None = None) -> PhaseConfig:
    """Return the effective PhaseConfig for ``phase``, honouring bundle overrides."""
    default = DEFAULT_CROSS_LLM_PHASES.get(phase, False)
    override = _bundle_override(bundle)
    if override is None:
        return PhaseConfig(phase=phase, enabled=default, source="default")
    return PhaseConfig(phase=phase, enabled=override, source="bundle_override")


def should_cross_validate(
    phase: str,
    severity: str,
    bundle: dict[str, Any] | None = None,
) -> bool:
    """True iff cross-LLM validation should run for this (phase, severity).

    Algorithm:
      1. ``critical`` severity always triggers (regardless of phase config).
      2. Otherwise, look up phase in defaults + apply bundle override.
      3. ``high`` follows phase config; ``medium`` / ``low`` only run when
         the bundle explicitly opts in *and* the phase default is True.
    """
    sev = severity if severity in _SEVERITY_RANK else "high"
    if sev == "critical":
        return True
    cfg = resolve_phase_config(phase, bundle=bundle)
    if not cfg.enabled:
        return False
    return _SEVERITY_RANK[sev] >= _SEVERITY_RANK[cfg.severity_floor]


__all__ = [
    "DEFAULT_CROSS_LLM_PHASES",
    "PhaseConfig",
    "Severity",
    "resolve_phase_config",
    "should_cross_validate",
]
