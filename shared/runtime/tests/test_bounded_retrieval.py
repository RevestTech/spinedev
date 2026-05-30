"""Tests for ``shared.runtime.bounded_retrieval`` (V3 B4).

Covers:
  * Seed augmentation is immutable (new Seed returned, not in-place).
  * ``parse_needs`` decodes the wire encoding and rejects malformed lines.
  * ``run_bounded_retrieval`` proceeds when the role returns no needs.
  * Loop bound: stops at ``max_cycles`` and emits ``cycle_exhausted``.
  * Resolver exception → ResolvedNeed records failure, loop continues.
  * Resolved needs accumulate across cycles in order.
"""
from __future__ import annotations

import pytest

from shared.mcp.schemas import Artifact, ToolResponse
from shared.runtime.bounded_retrieval import (
    CYCLE_EXHAUSTED_REASON,
    Need,
    ResolvedNeed,
    Seed,
    parse_needs,
    run_bounded_retrieval,
)


def _seed(**overrides) -> Seed:
    defaults = dict(
        project_id="proj-a",
        work_item="implement auth",
        role="engineer",
    )
    defaults.update(overrides)
    return Seed(**defaults)


def _response_with_needs(*needs: str, status: str = "warning") -> ToolResponse:
    return ToolResponse(
        status=status,  # type: ignore[arg-type]
        summary="more context required",
        next_actions=list(needs),
    )


def _final_response(summary: str = "done") -> ToolResponse:
    return ToolResponse(status="ok", summary=summary)


# ─── Need encoding ────────────────────────────────────────────────────


def test_need_to_next_action_round_trip() -> None:
    need = Need(type="kg_node", ref="node-auth-123", reason="for context")
    encoded = need.to_next_action()
    assert encoded == "need:kg_node:node-auth-123|for context"
    parsed = parse_needs(_response_with_needs(encoded))
    assert len(parsed) == 1
    assert parsed[0] == need


def test_need_without_reason_round_trip() -> None:
    need = Need(type="file_path", ref="src/api/auth.py:42")
    parsed = parse_needs(_response_with_needs(need.to_next_action()))
    assert parsed == [need]


def test_parse_needs_ignores_non_need_actions() -> None:
    resp = _response_with_needs(
        "need:kg_node:n1",
        "approve_decision 99",
        "retry_engineer_remediate",
    )
    parsed = parse_needs(resp)
    assert len(parsed) == 1
    assert parsed[0].type == "kg_node"


def test_parse_needs_skips_malformed_lines() -> None:
    resp = _response_with_needs(
        "need:malformed",            # no colon → skipped
        "need:unknown_type:foo",     # unknown type → skipped
        "need:kg_node:",             # empty ref → skipped
        "need:file_path:valid.py",   # ok
    )
    parsed = parse_needs(resp)
    assert len(parsed) == 1
    assert parsed[0].ref == "valid.py"


# ─── Seed immutability ────────────────────────────────────────────────


def test_seed_augment_returns_new_seed() -> None:
    s = _seed()
    resolved = [
        ResolvedNeed(
            need=Need(type="kg_node", ref="n1"),
            content="hello",
            success=True,
        ),
    ]
    augmented = s.augment(resolved)
    assert augmented is not s
    assert augmented.resolved == resolved
    assert s.resolved == []


# ─── Bounded loop ─────────────────────────────────────────────────────


def test_role_returning_no_needs_finishes_on_cycle_one() -> None:
    calls = []

    def role(seed: Seed) -> ToolResponse:
        calls.append(seed)
        return _final_response()

    def resolver(needs):  # should not be called
        raise AssertionError("resolver should not run when role asks nothing")

    outcome = run_bounded_retrieval(seed=_seed(), role=role, resolver=resolver)
    assert outcome.cycles_used == 1
    assert outcome.warnings == []
    assert outcome.final_response.status == "ok"
    assert len(calls) == 1


def test_loop_refines_then_finishes() -> None:
    cycle = {"n": 0}

    def role(seed: Seed) -> ToolResponse:
        cycle["n"] += 1
        if cycle["n"] == 1:
            return _response_with_needs("need:kg_node:auth-design")
        return _final_response()

    def resolver(needs):
        return [
            ResolvedNeed(
                need=n,
                content=f"resolved-{n.ref}",
                artifact=Artifact(type="kg_node", ref=n.ref),
                success=True,
            )
            for n in needs
        ]

    outcome = run_bounded_retrieval(seed=_seed(), role=role, resolver=resolver)
    assert outcome.cycles_used == 2
    assert outcome.warnings == []
    assert len(outcome.resolved_needs) == 1
    assert outcome.resolved_needs[0].content == "resolved-auth-design"


def test_loop_bound_emits_cycle_exhausted() -> None:
    def role(seed: Seed) -> ToolResponse:
        # Always asks for more, never finishes.
        return _response_with_needs("need:kg_node:never-enough")

    def resolver(needs):
        return [
            ResolvedNeed(need=n, content="x", success=True)
            for n in needs
        ]

    outcome = run_bounded_retrieval(
        seed=_seed(), role=role, resolver=resolver, max_cycles=2,
    )
    assert outcome.cycles_used == 2
    assert CYCLE_EXHAUSTED_REASON in outcome.warnings
    assert len(outcome.resolved_needs) == 2  # one per cycle


def test_max_cycles_zero_treated_as_one() -> None:
    def role(seed: Seed) -> ToolResponse:
        return _final_response()

    outcome = run_bounded_retrieval(
        seed=_seed(), role=role, resolver=lambda n: [], max_cycles=0,
    )
    assert outcome.cycles_used == 1


# ─── Resolver failure ─────────────────────────────────────────────────


def test_resolver_exception_records_failure_and_continues() -> None:
    cycle = {"n": 0}

    def role(seed: Seed) -> ToolResponse:
        cycle["n"] += 1
        if cycle["n"] == 1:
            return _response_with_needs("need:kg_node:broken")
        # Cycle 2: role sees the failed resolution and refuses.
        return ToolResponse(status="refusal", summary="cannot proceed")

    def resolver(needs):
        raise RuntimeError("KG down")

    outcome = run_bounded_retrieval(seed=_seed(), role=role, resolver=resolver)
    assert outcome.cycles_used == 2
    assert outcome.final_response.status == "refusal"
    assert len(outcome.resolved_needs) == 1
    failed = outcome.resolved_needs[0]
    assert failed.success is False
    assert failed.error is not None
    assert "KG down" in failed.error


def test_resolved_needs_accumulate_across_cycles() -> None:
    cycle = {"n": 0}
    requested = [
        ("need:kg_node:a",),
        ("need:file_path:b.py", "need:audit_hash:c"),
    ]

    def role(seed: Seed) -> ToolResponse:
        idx = cycle["n"]
        cycle["n"] += 1
        if idx < len(requested):
            return _response_with_needs(*requested[idx])
        return _final_response()

    def resolver(needs):
        return [
            ResolvedNeed(need=n, content=f"r-{n.ref}", success=True)
            for n in needs
        ]

    outcome = run_bounded_retrieval(seed=_seed(), role=role, resolver=resolver)
    # cycle 1 → 1 need; cycle 2 → 2 needs; cycle 3 → final answer
    assert outcome.cycles_used == 3
    assert outcome.warnings == []
    assert [r.need.ref for r in outcome.resolved_needs] == ["a", "b.py", "c"]
