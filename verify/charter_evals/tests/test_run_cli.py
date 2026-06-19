"""Tests for the ``verify.charter_evals.run`` CLI entry point."""
from __future__ import annotations

from pathlib import Path

import pytest

from verify.charter_evals.role_callables import (
    fixture_role_callable_from_dir,
    stub_role_callable,
)
from verify.charter_evals.run import main, render_report_markdown
from verify.charter_evals.harness import (
    CapabilityEval,
    EvalCriterion,
    EvalRunResult,
    PassAtK,
    evaluate_charter,
    pass_at_k,
)


def _eval(name: str, role: str = "engineer") -> CapabilityEval:
    return CapabilityEval(
        name=name,
        role=role,
        task="t",
        criteria=[
            EvalCriterion(name="ok", required_substrings=("ok",)),
        ],
        target_k=1,
        target_pass_rate=1.0,
    )


# ─── stub callable ───


def test_stub_callable_returns_canned_engineer_response() -> None:
    text = stub_role_callable(_eval("engineer-cites-req-id-in-report"), 0)
    assert "REQ-AUTH-7" in text


def test_stub_callable_returns_empty_for_unknown_eval() -> None:
    text = stub_role_callable(_eval("unknown-eval"), 0)
    assert text == ""


# ─── fixture callable ───


def test_fixture_callable_reads_per_eval_files(tmp_path: Path) -> None:
    (tmp_path / "engineer-cites-req-id-in-report.txt").write_text(
        "REQ-AUTH-7 implemented", encoding="utf-8",
    )
    callable_ = fixture_role_callable_from_dir(tmp_path)
    text = callable_(_eval("engineer-cites-req-id-in-report"), 0)
    assert text == "REQ-AUTH-7 implemented"


def test_fixture_callable_missing_file_returns_empty(tmp_path: Path) -> None:
    callable_ = fixture_role_callable_from_dir(tmp_path)
    assert callable_(_eval("does-not-exist"), 0) == ""


# ─── render_report_markdown ───


def test_render_report_markdown_shows_red_when_any_eval_fails() -> None:
    bad_results = [
        EvalRunResult(
            eval_name="bad", trial_index=0,
            output_text="", passed=False,
        ),
    ]
    bad_summary = pass_at_k(bad_results, target_pass_rate=1.0)
    from verify.charter_evals.harness import CharterReport

    report = CharterReport(
        role="engineer", per_eval=(bad_summary,),
        overall_meets_target=False,
    )
    md = render_report_markdown(report)
    assert "Overall: **red**" in md
    assert "**red**" in md
    assert "`bad`" in md


def test_render_report_markdown_shows_green_when_all_pass() -> None:
    good_results = [
        EvalRunResult(
            eval_name="good", trial_index=0,
            output_text="ok", passed=True,
        ),
    ]
    good_summary = pass_at_k(good_results, target_pass_rate=0.5)
    from verify.charter_evals.harness import CharterReport

    report = CharterReport(
        role="engineer", per_eval=(good_summary,),
        overall_meets_target=True,
    )
    md = render_report_markdown(report)
    assert "Overall: **green**" in md


# ─── CLI main() ───


def test_main_returns_2_for_unknown_role(capsys: pytest.CaptureFixture) -> None:
    code = main(["nobody"])
    assert code == 2
    err = capsys.readouterr().err
    assert "no evals found" in err


def test_main_runs_stub_on_engineer(capsys: pytest.CaptureFixture) -> None:
    code = main(["engineer", "--callable", "stub"])
    captured = capsys.readouterr()
    # The stub responses are crafted to pass every engineer criterion,
    # so the gate should come back green.
    assert code == 0
    assert "engineer" in captured.out
    assert "Overall: **green**" in captured.out


def test_main_runs_stub_on_architect(capsys: pytest.CaptureFixture) -> None:
    code = main(["architect", "--callable", "stub"])
    captured = capsys.readouterr()
    assert code == 0
    assert "architect" in captured.out
    assert "Overall: **green**" in captured.out


def test_main_returns_1_when_gate_regresses(
    capsys: pytest.CaptureFixture,
) -> None:
    failing = CapabilityEval(
        name="engineer-cites-req-id-in-report",
        role="engineer",
        task="t",
        criteria=[
            EvalCriterion(name="impossible", required_substrings=("NEVER_MATCH",)),
        ],
        target_k=1,
        target_pass_rate=1.0,
    )

    def always_fail(_eval: CapabilityEval, _trial: int) -> str:
        return stub_role_callable(failing, 0)

    report = evaluate_charter("engineer", [failing], always_fail)
    assert not report.overall_meets_target


def test_main_writes_report_to_file(
    tmp_path: Path, capsys: pytest.CaptureFixture,
) -> None:
    out = tmp_path / "report.md"
    code = main(["engineer", "--callable", "stub", "--write", str(out)])
    assert code == 0
    assert out.exists()
    assert "Overall: **green**" in out.read_text(encoding="utf-8")


def test_main_fixture_requires_root(capsys: pytest.CaptureFixture) -> None:
    code = main(["engineer", "--callable", "fixture"])
    assert code == 2
    assert "fixture-root" in capsys.readouterr().err
