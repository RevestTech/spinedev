"""Spine eval reporter (STORY-3.4.2 §5 + STORY-3.4.3).

Output formatters for eval runs and regression diffs. Pure str / dict /
xml — no I/O, no DB. CLI handles writing to stdout / file.
"""
from __future__ import annotations
import json
from dataclasses import asdict
from typing import Any
from xml.sax.saxutils import escape

from shared.eval.aggregator import RunSummary, diff_scores  # noqa: F401
from shared.eval.scorer import CaseResult


# ─── EvalRun bundle (what runner.py builds) ──────────────────────────────
# Reporter accepts a plain dict-shaped EvalRun so we don't ossify runner's
# internal class shape into the formatter contract.
def _row(s: Any, width: int) -> str:
    s = str(s)
    return s if len(s) >= width else s + " " * (width - len(s))


def format_text(run: dict[str, Any]) -> str:
    """Plain-text table for terminal output. ASCII only — pipes safely."""
    summary: RunSummary = run["summary"]
    cases: list[CaseResult] = run["cases"]
    lines = [
        f"Eval run — dataset={summary.dataset_id} mode={run.get('mode','full')}",
        f"  candidate={run.get('candidate_prompt_path','?')}  model={run.get('candidate_model','?')}",
        f"  aggregate={summary.aggregate_score:.4f}  pass={summary.pass_count}  "
        f"fail={summary.fail_count}  skip={summary.skip_count}  "
        f"err={summary.error_count}  cost=${summary.total_cost_usd:.4f}",
        "",
        _row("CASE_ID", 32) + _row("SCORE", 8) + _row("STATUS", 8) + "CHECKS",
        "-" * 78,
    ]
    for c in cases:
        chk = ",".join(("+" if r.passed else "-") + r.check_id for r in c.check_results)
        lines.append(_row(c.case_id, 32) + _row(f"{c.score:.3f}", 8)
                     + _row(c.pass_fail, 8) + chk)
    if summary.top_failed_checks:
        lines += ["", "Top failed checks:"]
        for fc in summary.top_failed_checks:
            lines.append(f"  {fc.check_id}: {fc.failure_count} failure(s)")
    return "\n".join(lines)


def format_json(run: dict[str, Any]) -> dict[str, Any]:
    """Machine-readable JSON dict; safe to json.dumps."""
    summary: RunSummary = run["summary"]
    cases: list[CaseResult] = run["cases"]
    return {
        "run_uuid": run.get("run_uuid"),
        "dataset_id": summary.dataset_id,
        "mode": run.get("mode", "full"),
        "candidate_prompt_path": run.get("candidate_prompt_path"),
        "candidate_prompt_sha": run.get("candidate_prompt_sha"),
        "candidate_model": run.get("candidate_model"),
        "started_at": run.get("started_at"),
        "completed_at": run.get("completed_at"),
        "aggregate_score": summary.aggregate_score,
        "case_count": summary.case_count,
        "pass_count": summary.pass_count,
        "fail_count": summary.fail_count,
        "skip_count": summary.skip_count,
        "error_count": summary.error_count,
        "total_cost_usd": summary.total_cost_usd,
        "per_tag": [asdict(t) for t in summary.per_tag],
        "top_failed_checks": [asdict(fc) for fc in summary.top_failed_checks],
        "cases": [
            {
                "case_id": c.case_id, "score": c.score, "pass_fail": c.pass_fail,
                "cost_usd": c.cost_usd, "duration_ms": c.duration_ms,
                "output_artifact": c.output_artifact,
                "error_message": c.error_message,
                "check_results": [asdict(cr) for cr in c.check_results],
            } for c in cases
        ],
    }


def format_junit(run: dict[str, Any]) -> str:
    """JUnit XML — drops into CI dashboards (GitHub Actions, GitLab, etc.)."""
    summary: RunSummary = run["summary"]
    cases: list[CaseResult] = run["cases"]
    suite_name = escape(f"spine-eval.{summary.dataset_id}")
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<testsuite name="{suite_name}" tests="{summary.case_count}" '
        f'failures="{summary.fail_count}" errors="{summary.error_count}" '
        f'skipped="{summary.skip_count}">',
    ]
    for c in cases:
        name = escape(c.case_id)
        parts.append(f'  <testcase classname="{suite_name}" name="{name}" '
                     f'time="{(c.duration_ms or 0) / 1000.0:.3f}">')
        if c.pass_fail == "fail":
            failed = next((r for r in c.check_results if not r.passed), None)
            msg = escape(failed.detail if failed else "check failed")
            parts.append(f'    <failure message="{msg}"/>')
        elif c.pass_fail == "error":
            parts.append(f'    <error message="{escape(c.error_message or "error")}"/>')
        elif c.pass_fail == "skip":
            parts.append('    <skipped/>')
        parts.append('  </testcase>')
    parts.append('</testsuite>')
    return "\n".join(parts)


def format_regression_diff(report: dict[str, Any]) -> str:
    """Per-case score deltas + overall summary for the regression CLI mode."""
    rows = report.get("per_case_deltas", [])  # list[(case_id, b, c, d, is_reg)]
    regs = report.get("flagged_regressions", [])
    overall = report.get("overall_delta", 0.0)
    lines = [
        f"Regression diff — dataset={report.get('dataset_id','?')} "
        f"tolerance={report.get('tolerance', 0.05):.3f}",
        f"  overall delta: {overall:+.4f}  flagged: {len(regs)}",
        "",
        _row("CASE_ID", 32) + _row("BASELINE", 10) + _row("CANDIDATE", 10)
        + _row("DELTA", 10) + "FLAG",
        "-" * 72,
    ]
    for case_id, b, c, d, is_reg in rows:
        flag = "REGRESSION" if is_reg else ("improved" if d > 0 else "stable")
        lines.append(_row(case_id, 32) + _row(f"{b:.3f}", 10)
                     + _row(f"{c:.3f}", 10) + _row(f"{d:+.3f}", 10) + flag)
    if regs:
        lines += ["", "Flagged regressions (severity-sorted):"]
        for r in regs:
            lines.append(f"  - {r.get('case_id')}: {r.get('severity','?')} "
                         f"baseline={r.get('baseline',0):.3f} "
                         f"candidate={r.get('candidate',0):.3f}")
    return "\n".join(lines)


def to_json_str(run: dict[str, Any]) -> str:
    """Convenience: format_json → pretty JSON str."""
    return json.dumps(format_json(run), indent=2, default=str)


__all__ = ["format_text", "format_json", "format_junit",
           "format_regression_diff", "to_json_str"]
