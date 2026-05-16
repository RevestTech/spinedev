"""Spine eval aggregator (STORY-3.4.2 §5).

Per-case CaseResults → per-run rollup. Severity-weighted aggregate score
(`critical*4`, `high*2`, `medium*1`, `low*0.5` — matches the runner_design
weights). Per-tag rollups and most-common failed checks feed the dashboard
(STORY-3.4.5). No DB, no I/O.
"""
from __future__ import annotations
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

from shared.eval.loader import Case, EvalDataset
from shared.eval.scorer import CaseResult

# Severity weights for the aggregate roll-up.
SEVERITY_WEIGHTS: dict[str, float] = {
    "critical": 4.0,
    "high": 2.0,
    "medium": 1.0,
    "low": 0.5,
}


@dataclass
class TagRollup:
    tag: str
    case_count: int
    pass_count: int
    avg_score: float


@dataclass
class FailedCheckRollup:
    check_id: str
    failure_count: int


@dataclass
class RunSummary:
    """Roll-up of one eval_run's case_results."""
    dataset_id: str
    case_count: int = 0
    pass_count: int = 0
    fail_count: int = 0
    skip_count: int = 0
    error_count: int = 0
    aggregate_score: float = 0.0
    total_cost_usd: float = 0.0
    per_tag: list[TagRollup] = field(default_factory=list)
    top_failed_checks: list[FailedCheckRollup] = field(default_factory=list)


def _case_index(dataset: EvalDataset) -> dict[str, Case]:
    return {c.case_id: c for c in dataset.cases}


def _severity_for(case: Optional[Case]) -> float:
    if case is None:
        return SEVERITY_WEIGHTS["medium"]
    return SEVERITY_WEIGHTS.get(case.severity, SEVERITY_WEIGHTS["medium"])


def aggregate_run(case_results: list[CaseResult], dataset: EvalDataset) -> RunSummary:
    """Roll up a list of CaseResults into a RunSummary for the eval_run row."""
    case_by_id = _case_index(dataset)
    counts = Counter(r.pass_fail for r in case_results)
    pass_count = counts.get("pass", 0)
    fail_count = counts.get("fail", 0)
    skip_count = counts.get("skip", 0)
    error_count = counts.get("error", 0)

    # Severity-weighted aggregate: skip+error rows do not contribute (they
    # have no signal); pass/fail rows contribute score*weight / weight.
    scored = [r for r in case_results if r.pass_fail in ("pass", "fail")]
    if scored:
        num = sum(r.score * _severity_for(case_by_id.get(r.case_id)) for r in scored)
        den = sum(_severity_for(case_by_id.get(r.case_id)) for r in scored)
        agg = num / den if den > 0 else 0.0
    else:
        agg = 0.0

    return RunSummary(
        dataset_id=dataset.dataset_id,
        case_count=len(case_results),
        pass_count=pass_count,
        fail_count=fail_count,
        skip_count=skip_count,
        error_count=error_count,
        aggregate_score=max(0.0, min(1.0, float(agg))),
        total_cost_usd=float(sum(r.cost_usd for r in case_results)),
        per_tag=_per_tag_rollup(case_results, case_by_id),
        top_failed_checks=_top_failed_checks(case_results, limit=10),
    )


def _per_tag_rollup(case_results: list[CaseResult],
                    case_by_id: dict[str, Case]) -> list[TagRollup]:
    """One row per distinct tag; case_count / pass_count / avg_score per tag."""
    rows: dict[str, dict[str, float]] = {}
    for r in case_results:
        case = case_by_id.get(r.case_id)
        if case is None:
            continue
        for tag in case.tags:
            slot = rows.setdefault(tag, {"count": 0.0, "pass": 0.0, "score_sum": 0.0})
            slot["count"] += 1
            slot["pass"] += 1 if r.pass_fail == "pass" else 0
            slot["score_sum"] += r.score
    return [
        TagRollup(tag=tag, case_count=int(s["count"]),
                  pass_count=int(s["pass"]),
                  avg_score=(s["score_sum"] / s["count"]) if s["count"] > 0 else 0.0)
        for tag, s in sorted(rows.items())
    ]


def _top_failed_checks(case_results: list[CaseResult], *, limit: int = 10
                       ) -> list[FailedCheckRollup]:
    """Most common failing check_ids — drives the regression triage view."""
    counter: Counter[str] = Counter()
    for r in case_results:
        for ch in r.check_results:
            if not ch.passed:
                counter[ch.check_id] += 1
    return [FailedCheckRollup(check_id=cid, failure_count=cnt)
            for cid, cnt in counter.most_common(limit)]


def diff_scores(baseline: dict[str, float], candidate: dict[str, float],
                tolerance: float = 0.05) -> list[tuple[str, float, float, float, bool]]:
    """Per-case (case_id, baseline_score, candidate_score, delta, is_regression)."""
    rows: list[tuple[str, float, float, float, bool]] = []
    for case_id in sorted(set(baseline) | set(candidate)):
        b = float(baseline.get(case_id, 0.0))
        c = float(candidate.get(case_id, 0.0))
        delta = c - b
        rows.append((case_id, b, c, delta, c < b - tolerance))
    return rows


__all__ = ["SEVERITY_WEIGHTS", "TagRollup", "FailedCheckRollup", "RunSummary",
           "aggregate_run", "diff_scores"]
