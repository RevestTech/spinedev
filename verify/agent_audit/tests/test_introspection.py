"""Tests for ``verify.agent_audit.introspection`` (V3 B11).

Covers:
  * Empty trace when no loaders supplied.
  * All-green trace with audit events, ledger allowed verdict, no refusals.
  * Refusal in trace surfaces via ``refusals`` + next_actions.
  * Denied promotion gate surfaces verdict + denial reasons.
  * Mixed run combines refusals and denial reasons.
  * Resolved needs are surfaced from audit events.
  * Bad input raises.
  * Trace model is frozen / forbids extra fields.
"""
from __future__ import annotations

from typing import Sequence

import pytest

from verify.agent_audit.introspection import (
    BOUNDED_RETRIEVAL_ACTION,
    CITE_OR_REFUSE_ACTION,
    LEDGER_APPEND_ACTION,
    IntrospectionTrace,
    build_introspection_trace,
)


def _audit_row(action: str, **extra: object) -> dict:
    base = {
        "action": action,
        "role": "verify",
        "subsystem": "shared",
        "actor": "mcp_server",
    }
    base.update(extra)
    return base


def _ledger_row(verdict: str, reasons: Sequence[str] = ()) -> dict:
    return {
        "entry_id": "00000000-0000-0000-0000-000000000001",
        "project_id": "proj-A",
        "run_id": "run-1",
        "actor": "conductor",
        "rollout_index": 0,
        "candidates": [{"candidate_id": "c1", "mark": "accept"}],
        "promotion_gate": {
            "verdict": verdict,
            "tier": "production",
            "freshness_passed": verdict == "allowed",
            "replay_passed": verdict == "allowed",
            "reasons": list(reasons),
        },
    }


# ─── empty / no-loader path ───


def test_empty_trace_when_no_loaders() -> None:
    trace = build_introspection_trace(
        run_id="run-1", project_id="proj-A",
    )
    assert isinstance(trace, IntrospectionTrace)
    assert trace.run_id == "run-1"
    assert trace.project_id == "proj-A"
    assert trace.audit_events == ()
    assert trace.ledger_entries == ()
    assert trace.refusals == ()
    assert trace.resolved_needs == ()
    assert trace.summary == (
        "0 audit events, 0 ledger entries, 0 refusals, 0 resolved needs"
    )
    assert trace.next_actions == ("none",)


def test_empty_loaders_explicit() -> None:
    audit = lambda p, r: []
    ledger = lambda p, r: []
    trace = build_introspection_trace(
        run_id="run-1", project_id="proj-A",
        audit_loader=audit, ledger_loader=ledger,
    )
    assert trace.next_actions == ("none",)


# ─── all-green path ───


def test_all_green_trace_with_allowed_verdict() -> None:
    audit = lambda p, r: [
        _audit_row("llm_call"),
        _audit_row(LEDGER_APPEND_ACTION),
    ]
    ledger = lambda p, r: [_ledger_row("allowed")]
    trace = build_introspection_trace(
        run_id="run-1", project_id="proj-A",
        audit_loader=audit, ledger_loader=ledger,
    )
    assert len(trace.audit_events) == 2
    assert len(trace.ledger_entries) == 1
    assert trace.refusals == ()
    assert "1 ledger entries" in trace.summary
    assert "last promotion verdict: allowed" in trace.summary
    assert trace.next_actions == ("approve promotion gate",)


# ─── refusal path ───


def test_refusal_in_trace_surfaces() -> None:
    audit = lambda p, r: [
        _audit_row("llm_call"),
        _audit_row(CITE_OR_REFUSE_ACTION, subject_id="verify.audit_tool"),
    ]
    trace = build_introspection_trace(
        run_id="run-1", project_id="proj-A",
        audit_loader=audit,
    )
    assert len(trace.refusals) == 1
    assert trace.refusals[0]["subject_id"] == "verify.audit_tool"
    assert "review refusals" in trace.next_actions


# ─── denied promotion path ───


def test_denied_promotion_surfaces_reasons() -> None:
    ledger = lambda p, r: [
        _ledger_row("denied", reasons=["freshness_stale", "replay_failed"]),
    ]
    trace = build_introspection_trace(
        run_id="run-1", project_id="proj-A",
        ledger_loader=ledger,
    )
    assert "denied" in trace.summary
    assert "resolve denial reasons" in trace.next_actions
    assert any(
        "freshness_stale,replay_failed" in a for a in trace.next_actions
    )


def test_denied_without_reasons_still_actionable() -> None:
    ledger = lambda p, r: [_ledger_row("denied", reasons=[])]
    trace = build_introspection_trace(
        run_id="run-1", project_id="proj-A",
        ledger_loader=ledger,
    )
    assert "resolve denial reasons" in trace.next_actions
    # No "check ledger denial reasons:" line when reasons list is empty.
    assert not any(
        a.startswith("check ledger denial reasons") for a in trace.next_actions
    )


# ─── mixed path ───


def test_mixed_trace_combines_refusals_and_denial() -> None:
    audit = lambda p, r: [
        _audit_row("llm_call"),
        _audit_row(CITE_OR_REFUSE_ACTION),
        _audit_row(BOUNDED_RETRIEVAL_ACTION, subject_id="kg_node:abc"),
    ]
    ledger = lambda p, r: [
        _ledger_row("allowed"),
        _ledger_row("denied", reasons=["replay_failed"]),
    ]
    trace = build_introspection_trace(
        run_id="run-1", project_id="proj-A",
        audit_loader=audit, ledger_loader=ledger,
    )
    assert len(trace.refusals) == 1
    assert len(trace.resolved_needs) == 1
    assert trace.resolved_needs[0]["subject_id"] == "kg_node:abc"
    assert "review refusals" in trace.next_actions
    assert "resolve denial reasons" in trace.next_actions
    assert any(
        "replay_failed" in a for a in trace.next_actions
    )
    assert "denied" in trace.summary


# ─── flat-shape ledger row (SQL projection style) ───


def test_flat_ledger_row_is_understood() -> None:
    ledger = lambda p, r: [
        {
            "entry_id": "x",
            "promotion_verdict": "denied",
            "promotion_reasons": ["operator_not_confirmed"],
        },
    ]
    trace = build_introspection_trace(
        run_id="run-1", project_id="proj-A",
        ledger_loader=ledger,
    )
    assert "denied" in trace.summary
    assert any(
        "operator_not_confirmed" in a for a in trace.next_actions
    )


# ─── validation / shape ───


def test_missing_run_id_raises() -> None:
    with pytest.raises(ValueError):
        build_introspection_trace(run_id="", project_id="proj-A")


def test_missing_project_id_raises() -> None:
    with pytest.raises(ValueError):
        build_introspection_trace(run_id="run-1", project_id="")


def test_trace_is_frozen_and_forbids_extras() -> None:
    trace = build_introspection_trace(
        run_id="run-1", project_id="proj-A",
    )
    with pytest.raises(Exception):
        # Pydantic frozen → ValidationError on mutation attempt.
        trace.run_id = "other"  # type: ignore[misc]
    with pytest.raises(Exception):
        IntrospectionTrace(
            run_id="run-1", project_id="proj-A",
            summary="x",
            bogus_field="nope",  # type: ignore[call-arg]
        )


def test_loader_receives_project_and_run_ids() -> None:
    captured: list[tuple[str, str]] = []

    def _audit(project_id: str, run_id: str) -> Sequence[dict]:
        captured.append((project_id, run_id))
        return ()

    def _ledger(project_id: str, run_id: str) -> Sequence[dict]:
        captured.append((project_id, run_id))
        return ()

    build_introspection_trace(
        run_id="run-1", project_id="proj-A",
        audit_loader=_audit, ledger_loader=_ledger,
    )
    assert captured == [("proj-A", "run-1"), ("proj-A", "run-1")]
