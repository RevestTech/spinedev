"""Single-dispatch introspection trace (V3 B11 borrow).

Borrowed contract source: ECC ``agent-introspection-debugging`` skill
(``affaan-m/ecc``, MIT). See ``docs/ECC_BORROWS.md`` (B11 added
2026-05-29). Implemented natively against Spine's audit + ledger +
Cite-or-Refuse + bounded-retrieval surfaces.

Where this fits
---------------

The 12-layer audit (B10, :mod:`verify.agent_audit.twelve_layer`) tells
the operator *which layer* of the agent stack regressed across the
whole stack. This module is its sibling: given a single ``run_id`` it
traces *why this specific dispatch* produced the output it did by
collecting every audit event, decision-ledger entry, cite-or-refuse
refusal, and resolved bounded-retrieval need scoped to that run.

The module is loader-injected so it is callable in any environment.
With no loaders, every collection is empty and the trace summarises a
clean run. Tests pass synthetic loaders that emit fixture rows.

The module is read-only: it inspects loader output and returns a typed
trace. No fixes are applied.
"""
from __future__ import annotations

from typing import Callable, Sequence

from pydantic import BaseModel, ConfigDict, Field

CITE_OR_REFUSE_ACTION = "cite_or_refuse_refused"
"""Audit action emitted by ``shared.mcp.cite_or_refuse`` on refusal."""


LEDGER_APPEND_ACTION = "decision_ledger.append"
"""Audit action emitted by the decision-ledger shadow writer."""


BOUNDED_RETRIEVAL_ACTION = "bounded_retrieval.resolved_need"
"""Conventional action for ``resolved_need`` audit shadows.

The bounded-retrieval module itself does not persist audit rows today
(it is provider-agnostic). When a dispatcher chooses to shadow resolved
needs into the audit chain, this is the action it uses. The trace
collects them when present.
"""


AuditLoader = Callable[[str, str], Sequence[dict]]
"""``(project_id, run_id) -> sequence of audit row dicts`` (oldest first)."""


LedgerLoader = Callable[[str, str], Sequence[dict]]
"""``(project_id, run_id) -> sequence of decision_ledger row dicts``."""


class IntrospectionTrace(BaseModel):
    """End-to-end trace of one ``(project_id, run_id)`` dispatch."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str
    project_id: str
    audit_events: tuple[dict, ...] = Field(default_factory=tuple)
    ledger_entries: tuple[dict, ...] = Field(default_factory=tuple)
    refusals: tuple[dict, ...] = Field(default_factory=tuple)
    resolved_needs: tuple[dict, ...] = Field(default_factory=tuple)
    summary: str
    next_actions: tuple[str, ...] = Field(default_factory=tuple)


def _empty_loader(project_id: str, run_id: str) -> Sequence[dict]:
    return ()


def _is_refusal(event: dict) -> bool:
    return event.get("action") == CITE_OR_REFUSE_ACTION


def _is_resolved_need(event: dict) -> bool:
    return event.get("action") == BOUNDED_RETRIEVAL_ACTION


def _gate_from_entry(entry: dict) -> dict:
    """Extract the ``promotion_gate`` sub-dict from a ledger row.

    Tolerant of both nested-dict form (current shape) and flat columns
    so the trace works with either a JSONL row or a SQL projection.
    """
    gate = entry.get("promotion_gate")
    if isinstance(gate, dict):
        return gate
    return {
        "verdict": entry.get("promotion_verdict"),
        "reasons": entry.get("promotion_reasons") or [],
    }


def _derive_summary(
    *,
    audit_events: tuple[dict, ...],
    ledger_entries: tuple[dict, ...],
    refusals: tuple[dict, ...],
    resolved_needs: tuple[dict, ...],
) -> str:
    base = (
        f"{len(audit_events)} audit events, "
        f"{len(ledger_entries)} ledger entries, "
        f"{len(refusals)} refusals, "
        f"{len(resolved_needs)} resolved needs"
    )
    if not ledger_entries:
        return base
    last_gate = _gate_from_entry(ledger_entries[-1])
    verdict = last_gate.get("verdict")
    if verdict:
        return f"{base}; last promotion verdict: {verdict}"
    return base


def _derive_next_actions(
    *,
    ledger_entries: tuple[dict, ...],
    refusals: tuple[dict, ...],
) -> tuple[str, ...]:
    actions: list[str] = []
    if refusals:
        actions.append("review refusals")
    if ledger_entries:
        last_gate = _gate_from_entry(ledger_entries[-1])
        verdict = last_gate.get("verdict")
        reasons = tuple(last_gate.get("reasons") or ())
        if verdict == "denied":
            actions.append("resolve denial reasons")
            if reasons:
                joined = ",".join(str(r) for r in reasons)
                actions.append(f"check ledger denial reasons: {joined}")
        elif verdict == "allowed":
            actions.append("approve promotion gate")
    if not actions:
        actions.append("none")
    return tuple(actions)


def build_introspection_trace(
    *,
    run_id: str,
    project_id: str,
    audit_loader: AuditLoader | None = None,
    ledger_loader: LedgerLoader | None = None,
) -> IntrospectionTrace:
    """Assemble the trace for one ``(project_id, run_id)`` dispatch.

    Loaders are dependency-injected so the function is pure / testable.
    When a loader is ``None`` the corresponding collection is empty.
    """
    if not run_id:
        raise ValueError("run_id required")
    if not project_id:
        raise ValueError("project_id required")
    audit_fn: AuditLoader = audit_loader or _empty_loader
    ledger_fn: LedgerLoader = ledger_loader or _empty_loader

    audit_events = tuple(dict(row) for row in audit_fn(project_id, run_id))
    ledger_entries = tuple(dict(row) for row in ledger_fn(project_id, run_id))
    refusals = tuple(e for e in audit_events if _is_refusal(e))
    resolved_needs = tuple(e for e in audit_events if _is_resolved_need(e))

    summary = _derive_summary(
        audit_events=audit_events,
        ledger_entries=ledger_entries,
        refusals=refusals,
        resolved_needs=resolved_needs,
    )
    next_actions = _derive_next_actions(
        ledger_entries=ledger_entries,
        refusals=refusals,
    )

    return IntrospectionTrace(
        run_id=run_id,
        project_id=project_id,
        audit_events=audit_events,
        ledger_entries=ledger_entries,
        refusals=refusals,
        resolved_needs=resolved_needs,
        summary=summary,
        next_actions=next_actions,
    )


__all__ = [
    "BOUNDED_RETRIEVAL_ACTION",
    "CITE_OR_REFUSE_ACTION",
    "IntrospectionTrace",
    "LEDGER_APPEND_ACTION",
    "AuditLoader",
    "LedgerLoader",
    "build_introspection_trace",
]
