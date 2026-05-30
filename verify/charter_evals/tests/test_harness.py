"""Tests for ``verify.charter_evals.harness`` (V3 B6 borrow)."""
from __future__ import annotations

import pytest

from verify.charter_evals.harness import (
    CapabilityEval,
    EvalCriterion,
    EvalRunResult,
    evaluate_charter,
    pass_at_k,
    run_capability_eval,
)


def _eval(
    *,
    target_k: int = 5,
    target: float = 0.8,
    role: str = "engineer",
) -> CapabilityEval:
    return CapabilityEval(
        name="cites-req",
        role=role,
        task="Implement REQ-FOO-1",
        criteria=[
            EvalCriterion(
                name="cites_req",
                required_substrings=("REQ-FOO-1",),
            ),
            EvalCriterion(
                name="no_todo",
                forbidden_substrings=("TODO", "XXX"),
            ),
        ],
        target_k=target_k,
        target_pass_rate=target,
    )


# ─── EvalCriterion ───


def test_criterion_required_substrings_all_present() -> None:
    crit = EvalCriterion(
        name="x", required_substrings=("foo", "bar"),
    )
    assert crit.check("foo and bar are here") is True
    assert crit.check("only foo here") is False


def test_criterion_forbidden_substrings() -> None:
    crit = EvalCriterion(name="x", forbidden_substrings=("TODO",))
    assert crit.check("clean output") is True
    assert crit.check("contains TODO marker") is False


def test_criterion_combined() -> None:
    crit = EvalCriterion(
        name="x",
        required_substrings=("REQ-1",),
        forbidden_substrings=("XXX",),
    )
    assert crit.check("REQ-1 implemented cleanly") is True
    assert crit.check("REQ-1 implemented XXX") is False
    assert crit.check("no req cited") is False


# ─── run_capability_eval ───


def test_run_returns_one_result_per_trial() -> None:
    ev = _eval(target_k=3)
    calls: list[int] = []

    def role(_ev: CapabilityEval, idx: int) -> str:
        calls.append(idx)
        return f"trial {idx} for REQ-FOO-1 — done"

    results = run_capability_eval(ev, role)
    assert len(results) == 3
    assert calls == [0, 1, 2]
    assert all(r.passed for r in results)


def test_run_records_failed_criteria_names() -> None:
    ev = _eval(target_k=2)

    def role(_ev: CapabilityEval, idx: int) -> str:
        if idx == 0:
            return "TODO: implement REQ-FOO-1"  # has TODO + has REQ
        return "missing the requirement"        # missing REQ-FOO-1

    results = run_capability_eval(ev, role)
    assert results[0].failed_criteria == ("no_todo",)
    assert results[1].failed_criteria == ("cites_req",)
    assert all(not r.passed for r in results)


def test_run_handles_role_exception() -> None:
    ev = _eval(target_k=1)

    def role(_ev: CapabilityEval, idx: int) -> str:
        raise RuntimeError("LLM down")

    results = run_capability_eval(ev, role)
    assert len(results) == 1
    assert results[0].passed is False
    assert "__role_raised__" in results[0].output_text


# ─── pass_at_k ───


def test_pass_at_k_meets_target_when_all_pass() -> None:
    name = "cites-req"
    results = [
        EvalRunResult(eval_name=name, trial_index=i,
                      output_text="ok", passed=True)
        for i in range(5)
    ]
    summary = pass_at_k(results, target_pass_rate=0.8)
    assert summary.pass_rate == 1.0
    assert summary.meets_target is True


def test_pass_at_k_below_target() -> None:
    name = "x"
    results = [
        EvalRunResult(
            eval_name=name, trial_index=i,
            output_text="ok", passed=(i < 3),  # 3 of 5 pass
        )
        for i in range(5)
    ]
    summary = pass_at_k(results, target_pass_rate=0.8)
    assert summary.passed == 3
    assert summary.pass_rate == 0.6
    assert summary.meets_target is False


def test_pass_at_k_empty_results() -> None:
    summary = pass_at_k([])
    assert summary.trials == 0
    assert summary.meets_target is False


# ─── evaluate_charter ───


def test_evaluate_charter_all_pass() -> None:
    ev = _eval(target_k=4, target=0.75)

    def role(_ev: CapabilityEval, idx: int) -> str:
        return "REQ-FOO-1 implemented"

    report = evaluate_charter("engineer", [ev], role)
    assert report.role == "engineer"
    assert len(report.per_eval) == 1
    assert report.overall_meets_target is True


def test_evaluate_charter_one_fail_fails_overall() -> None:
    good = CapabilityEval(
        name="good",
        role="engineer",
        task="t",
        criteria=[EvalCriterion(
            name="ok", required_substrings=("X",),
        )],
        target_k=2,
        target_pass_rate=0.5,
    )
    bad = CapabilityEval(
        name="bad",
        role="engineer",
        task="t",
        criteria=[EvalCriterion(
            name="needs_unique_marker",
            required_substrings=("UNIQUE_MARKER_NOT_IN_OUTPUT",),
        )],
        target_k=2,
        target_pass_rate=1.0,  # impossible target for this role
    )

    def role(_ev: CapabilityEval, idx: int) -> str:
        return "X but no marker"

    report = evaluate_charter("engineer", [good, bad], role)
    rates = {p.eval_name: p.meets_target for p in report.per_eval}
    assert rates == {"good": True, "bad": False}
    assert report.overall_meets_target is False


def test_evaluate_charter_rejects_role_mismatch() -> None:
    ev = _eval(role="architect")

    def role(_ev: CapabilityEval, idx: int) -> str:
        return ""

    with pytest.raises(ValueError, match="role="):
        evaluate_charter("engineer", [ev], role)
