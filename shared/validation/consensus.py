"""Consensus / disagreement detection for cross-LLM validation (EPIC-3.7).

Reduces a list of independent ``ProviderResult`` verdicts into a single
``ConsensusResult`` with a calibrated confidence band. Mirrors the TRON
AuditManager pattern (`verify/tron/agents/manager.py::_apply_cross_validation`)
but lifts it out of the security-audit context so Plan and Build subsystems
can use the same shape.

Verdict vocabulary:
  agree         — secondary independently reproduces the primary's claim
  partial_agree — secondary agrees on substance, disputes details
  disagree      — secondary explicitly contradicts the primary
  abstain       — secondary refuses (insufficient information, out of scope)
  error         — provider call failed (SDK missing, network, parse error)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from shared.validation.cross_llm import ProviderResult

Verdict = Literal["agree", "disagree", "partial_agree", "abstain", "error"]
FinalVerdict = Literal["validated", "needs_review", "rejected", "indeterminate"]
ConfidenceBand = Literal["high", "medium", "low", "untrusted"]

_AGREEING: frozenset[str] = frozenset({"agree", "partial_agree"})


class ConsensusResult(BaseModel):
    """Aggregate verdict across all secondary providers."""

    model_config = ConfigDict(frozen=True)

    achieved: bool = Field(
        ...,
        description="True iff every non-error provider returned `agree` (strict).",
    )
    primary_agrees_with_majority: bool = Field(
        ...,
        description="The primary always 'agrees with itself'; this records "
                    "whether the majority of secondaries agree with the primary.",
    )
    dissenting_providers: list[str] = Field(default_factory=list)
    final_verdict: FinalVerdict
    confidence_band: ConfidenceBand
    avg_confidence: float = Field(ge=0.0, le=1.0)
    n_agree: int = 0
    n_disagree: int = 0
    n_partial: int = 0
    n_abstain: int = 0
    n_error: int = 0


def _band(
    n_total: int,
    n_agree: int,
    n_disagree: int,
    n_error: int,
    avg_conf: float,
) -> ConfidenceBand:
    """Map vote-counts + avg confidence into a 4-tier band."""
    if n_total == 0:
        return "untrusted"
    if n_error * 2 > n_total:  # > 50% errors
        return "untrusted"
    if n_disagree > 0:
        return "low"
    if n_agree == n_total and avg_conf >= 0.85:
        return "high"
    return "medium"


def _final_verdict(
    n_agree: int,
    n_disagree: int,
    n_partial: int,
    n_abstain: int,
    n_error: int,
    n_total: int,
) -> FinalVerdict:
    """Map vote-counts into a single ship-or-don't verdict."""
    n_useful = n_total - n_error
    if n_useful == 0:
        return "indeterminate"
    if n_abstain == n_useful:
        return "indeterminate"
    if n_disagree * 2 > n_useful:  # strict majority disagree
        return "rejected"
    if n_disagree > 0 or n_partial > 0:
        return "needs_review"
    if n_agree == n_useful:
        return "validated"
    return "needs_review"


def compute_consensus(
    primary_model: str,
    provider_results: list["ProviderResult"],
) -> ConsensusResult:
    """Reduce per-provider verdicts into a single ConsensusResult.

    The primary model is *not* itself a voter — it's the model whose output
    is being checked. ``provider_results`` contains only secondaries.
    """
    n_total = len(provider_results)
    n_agree = sum(1 for r in provider_results if r.verdict == "agree")
    n_disagree = sum(1 for r in provider_results if r.verdict == "disagree")
    n_partial = sum(1 for r in provider_results if r.verdict == "partial_agree")
    n_abstain = sum(1 for r in provider_results if r.verdict == "abstain")
    n_error = sum(1 for r in provider_results if r.verdict == "error")

    useful = [r for r in provider_results if r.verdict != "error"]
    avg_conf = (sum(r.confidence for r in useful) / len(useful)) if useful else 0.0

    achieved = (n_total > 0) and (n_disagree == 0) and (n_partial == 0) and (n_error == 0)
    n_agreeing = sum(1 for r in provider_results if r.verdict in _AGREEING)
    primary_agrees = (n_agreeing * 2) > max(n_total - n_error, 1)

    dissenting = [
        f"{r.provider}:{r.model}"
        for r in provider_results
        if r.verdict in ("disagree", "partial_agree")
    ]

    return ConsensusResult(
        achieved=achieved,
        primary_agrees_with_majority=primary_agrees,
        dissenting_providers=dissenting,
        final_verdict=_final_verdict(n_agree, n_disagree, n_partial, n_abstain, n_error, n_total),
        confidence_band=_band(n_total, n_agree, n_disagree, n_error, avg_conf),
        avg_confidence=round(avg_conf, 4),
        n_agree=n_agree, n_disagree=n_disagree, n_partial=n_partial,
        n_abstain=n_abstain, n_error=n_error,
    )


__all__ = ["ConfidenceBand", "ConsensusResult", "FinalVerdict", "Verdict", "compute_consensus"]
