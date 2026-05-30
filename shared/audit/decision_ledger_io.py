"""Convenience writers + readers for the V3 #12a decision ledger.

Wraps :mod:`shared.audit.decision_ledger` (B1) with the patterns the
operating-loop runners actually need. Lives separately from the core
ledger module so the core stays a pure data layer.

Public API
----------

* :func:`append_promotion_decision` — records one rollout outcome from
  a Conductor / Auditor / QA pass. The most common write path.
* :func:`latest_promotion_verdict` — fetches the most recent ledger
  entry for a project (any run) and returns the gate verdict. Used by
  the bash phase-gate hook (`orchestrator/lib/gate.sh`).
* :func:`SafePromotionInputs` — tiny shape carrying the per-role
  per-rollout inputs callers supply.

Failures are fail-soft. A ledger write that raises does not block the
caller — the directive's report and audit chain are the source of
truth. Errors are logged.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from shared.audit.decision_ledger import (
    Candidate,
    DecisionLedger,
    DecisionMark,
    LedgerEntry,
    PromotionGate,
    PromotionVerdict,
    WorkItemTier,
    default_ledger_root,
)

logger = logging.getLogger("spine.audit.decision_ledger_io")


@dataclass(frozen=True)
class SafePromotionInputs:
    """Per-rollout inputs callers supply to :func:`append_promotion_decision`.

    Held in one frozen record so callers cannot accidentally re-order
    positional args between calls — a real bug when six different
    runners write here.
    """

    project_id: str
    run_id: str
    role: str
    rollout_index: int = 0
    tier: WorkItemTier = "internal"
    freshness_passed: bool = False
    replay_passed: bool = False
    operator_confirmed: bool = False
    candidates: tuple[Candidate, ...] = field(default_factory=tuple)
    prior_winner: str | None = None
    fresh_evidence: tuple[str, ...] = field(default_factory=tuple)


def append_promotion_decision(
    inputs: SafePromotionInputs,
    *,
    root: Path | str | None = None,
) -> LedgerEntry | None:
    """Append one ledger entry for ``inputs``. Returns the chained entry.

    On any write failure, returns ``None`` and logs the cause. Callers
    treat ``None`` as "ledger unavailable; proceed with the directive
    but flag the audit chain gap upstream."
    """
    if not inputs.candidates:
        # Synthesize a single-candidate row so the loop callers can pass
        # a verdict-only payload without re-shaping their data.
        candidates: tuple[Candidate, ...] = (
            Candidate(
                candidate_id=f"{inputs.role}:rollout-{inputs.rollout_index}",
                mark="accept",
                rationale=f"{inputs.role} rollout outcome recorded",
            ),
        )
    else:
        candidates = inputs.candidates

    gate = PromotionGate.evaluate(
        tier=inputs.tier,
        freshness_passed=inputs.freshness_passed,
        replay_passed=inputs.replay_passed,
        operator_confirmed=inputs.operator_confirmed,
    )

    try:
        ledger = DecisionLedger(
            project_id=inputs.project_id,
            run_id=inputs.run_id,
            root=root,
        )
        entry = LedgerEntry(
            project_id=inputs.project_id,
            run_id=inputs.run_id,
            actor=inputs.role,
            rollout_index=inputs.rollout_index,
            fresh_evidence=list(inputs.fresh_evidence),
            candidates=list(candidates),
            prior_accepted_winner=inputs.prior_winner,
            promotion_gate=gate,
        )
        return ledger.append(entry)
    except Exception:  # noqa: BLE001 — fail-soft
        logger.exception(
            "decision_ledger_io.append_failed",
            extra={"project_id": inputs.project_id, "role": inputs.role},
        )
        return None


def latest_promotion_verdict(
    project_id: str,
    *,
    root: Path | str | None = None,
) -> tuple[PromotionVerdict, tuple[str, ...]] | None:
    """Return ``(verdict, reasons)`` for the most recent ledger entry.

    "Most recent" = newest mtime across every ``<root>/<project>/<run>.jsonl``
    file. Returns ``None`` when no entries exist for the project — the
    bash gate treats this as "no information; allow but warn", and the
    caller can decide whether to escalate.
    """
    base = Path(root).expanduser() if root else default_ledger_root()
    project_dir = base / project_id
    if not project_dir.is_dir():
        return None
    run_files = sorted(
        project_dir.glob("*.jsonl"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not run_files:
        return None
    run_id = run_files[0].stem
    try:
        ledger = DecisionLedger(
            project_id=project_id,
            run_id=run_id,
            root=base,
        )
    except ValueError:
        return None
    tail = ledger.tail(1)
    if not tail:
        return None
    gate = tail[0].promotion_gate
    return gate.verdict, tuple(gate.reasons)


def make_candidate(
    candidate_id: str,
    mark: DecisionMark = "accept",
    *,
    rationale: str | None = None,
    score: float | None = None,
) -> Candidate:
    """Construct a :class:`Candidate` with the conventional fields."""
    return Candidate(
        candidate_id=candidate_id,
        mark=mark,
        rationale=rationale,
        score=score,
    )


__all__ = [
    "SafePromotionInputs",
    "append_promotion_decision",
    "latest_promotion_verdict",
    "make_candidate",
]
