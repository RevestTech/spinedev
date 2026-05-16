"""Spine eval runner (STORY-3.4.2 / 3.4.3 / 3.4.4).

Modes: run_full, run_regression, run_ab, run_smoke. Candidate invocation
goes through a pluggable `dispatch` callable so we can unit-test without
an LLM. DB writes via subprocess `psql` (no psycopg dep), matching
`shared/cost/router.py` + `shared/audit/audit_record.py` patterns.
"""
from __future__ import annotations
import json, os, random, subprocess, time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from math import erf, sqrt
from pathlib import Path
from typing import Any, Callable, Optional
from uuid import UUID, uuid4

from shared.eval.aggregator import RunSummary, aggregate_run, diff_scores
from shared.eval.loader import (Case, EvalDataset, EvalRubric,
                                load_dataset_with_rubrics, resolve_rubric,
                                sha256_file)
from shared.eval.scorer import CaseResult, JudgeFn, score_case

DEFAULT_DB_URL = os.environ.get("SPINE_DB_URL", "postgresql://spine:spine@localhost:33000/spine")
REGRESSION_TOLERANCE = 0.05
# dispatch: (case, prompt, model) -> (text, parsed_obj_or_None, artifact_path_or_None, cost)
DispatchFn = Callable[[Case, Path, str], tuple[str, Any, Optional[Path], float]]
_SEV_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}


@dataclass
class EvalRun:
    run_uuid: UUID
    dataset_id: str
    mode: str
    candidate_prompt_path: str
    candidate_prompt_sha: str
    candidate_model: str
    started_at: datetime
    completed_at: Optional[datetime] = None
    baseline_prompt_sha: Optional[str] = None
    baseline_model: Optional[str] = None
    case_results: list[CaseResult] = field(default_factory=list)
    summary: Optional[RunSummary] = None
    eval_run_id: Optional[int] = None
    actor: str = "user"

@dataclass
class RegressionReport:
    dataset_id: str
    eval_run: EvalRun
    per_case_deltas: list[tuple[str, float, float, float, bool]]
    flagged_regressions: list[dict[str, Any]]
    overall_delta: float
    tolerance: float = REGRESSION_TOLERANCE

@dataclass
class ABReport:
    dataset_id: str
    baseline_run: EvalRun
    candidate_run: EvalRun
    sample_size: int
    wins: int
    losses: int
    ties: int
    p_value: Optional[float]
    test_used: str


# ─── DB helpers (no-op if psql unavailable; tests pass db_url=None) ──────
def _psql(sql: str, db_url: Optional[str] = None, *, fetch: bool = False) -> Optional[str]:
    args = ["psql", db_url or DEFAULT_DB_URL, "-At", "-v", "ON_ERROR_STOP=1", "-c", sql]
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=15, check=True)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return None
    return r.stdout.strip() if fetch else None

_esc = lambda v: str(v).replace("'", "''")
_q = lambda v: "NULL" if v is None else f"'{_esc(v)}'"


def _register_dataset(d: EvalDataset, path: Path, db_url: Optional[str]) -> None:
    _psql(f"INSERT INTO spine_eval.dataset (dataset_id, role, version, path, case_count) "
          f"VALUES ({_q(d.dataset_id)}, {_q(d.role)}, 1, {_q(path)}, {len(d.cases)}) "
          f"ON CONFLICT (dataset_id) DO UPDATE SET path = EXCLUDED.path, "
          f"case_count = EXCLUDED.case_count;", db_url)


def _insert_eval_run(run: EvalRun, db_url: Optional[str]) -> Optional[int]:
    cols = {"run_uuid": run.run_uuid, "dataset_id": run.dataset_id,
            "candidate_prompt_path": run.candidate_prompt_path,
            "candidate_prompt_sha": run.candidate_prompt_sha,
            "candidate_model": run.candidate_model,
            "baseline_prompt_sha": run.baseline_prompt_sha,
            "baseline_model": run.baseline_model,
            "started_at": run.started_at.isoformat(),
            "mode": run.mode, "actor": run.actor}
    keys = [k for k, v in cols.items() if v is not None]
    raw = _psql(f"INSERT INTO spine_eval.eval_run ({', '.join(keys)}) VALUES "
                f"({', '.join(_q(cols[k]) for k in keys)}) RETURNING id;",
                db_url, fetch=True)
    return int(raw.splitlines()[-1]) if raw else None


def _finalize_eval_run(run: EvalRun, s: RunSummary, db_url: Optional[str]) -> None:
    if run.eval_run_id is None: return
    ts = (run.completed_at or datetime.now(timezone.utc)).isoformat()
    _psql(f"UPDATE spine_eval.eval_run SET completed_at = {_q(ts)}, "
          f"total_cost_usd = {s.total_cost_usd:.4f}, "
          f"aggregate_score = {s.aggregate_score:.4f}, pass_count = {s.pass_count}, "
          f"fail_count = {s.fail_count}, skip_count = {s.skip_count} "
          f"WHERE id = {run.eval_run_id};", db_url)


def _insert_case_results(run: EvalRun, db_url: Optional[str]) -> None:
    if run.eval_run_id is None: return
    for c in run.case_results:
        checks = json.dumps([{"check_id": r.check_id, "check_type": r.check_type,
                              "passed": r.passed, "score": r.score, "weight": r.weight,
                              "must_pass": r.must_pass, "detail": r.detail}
                             for r in c.check_results])
        _psql(f"INSERT INTO spine_eval.case_result (eval_run_id, case_id, score, "
              f"pass_fail, check_results, output_artifact, cost_usd, duration_ms, "
              f"error_message) VALUES ({run.eval_run_id}, {_q(c.case_id)}, "
              f"{c.score:.4f}, {_q(c.pass_fail)}, {_q(checks)}::jsonb, "
              f"{_q(c.output_artifact)}, {c.cost_usd:.4f}, {c.duration_ms}, "
              f"{_q(c.error_message)});", db_url)


# ─── Per-case execution + shared loop ────────────────────────────────────
def _run_one_case(case: Case, dataset_path: Path, rubrics: dict[str, EvalRubric],
                  prompt: Path, model: str, dispatch: DispatchFn,
                  judge: Optional[JudgeFn], root: Path) -> CaseResult:
    """Dispatch candidate, score against rubric. Catches dispatch errors."""
    rubric = rubrics.get(str(resolve_rubric(dataset_path, case)))
    if rubric is None:
        return CaseResult(case_id=case.case_id, score=0.0, pass_fail="error",
                          error_message="rubric not loaded")
    t0 = time.monotonic()
    try:
        text, obj, artifact, cost = dispatch(case, prompt, model)
    except Exception as e:  # broad: dispatch is caller-supplied
        return CaseResult(case_id=case.case_id, score=0.0, pass_fail="error",
                          error_message=f"dispatch error: {e}",
                          duration_ms=int((time.monotonic() - t0) * 1000))
    result = score_case(case, text or "", obj, rubric, judge=judge,
                        artifact_path=artifact, repo_root=root)
    result.cost_usd = float(cost or 0.0)
    result.output_artifact = str(artifact) if artifact else None
    result.duration_ms = int((time.monotonic() - t0) * 1000)
    return result


def _new_run(dataset_id: str, mode: str, prompt: Path, model: str, actor: str,
             baseline_prompt: Optional[Path] = None,
             baseline_model: Optional[str] = None) -> EvalRun:
    return EvalRun(run_uuid=uuid4(), dataset_id=dataset_id, mode=mode,
                   candidate_prompt_path=str(prompt),
                   candidate_prompt_sha=sha256_file(prompt),
                   candidate_model=model, started_at=datetime.now(timezone.utc),
                   baseline_prompt_sha=sha256_file(baseline_prompt) if baseline_prompt else None,
                   baseline_model=baseline_model, actor=actor)


def _execute(run: EvalRun, cases: list[Case], dataset_path: Path,
             rubrics: dict[str, EvalRubric], dispatch: DispatchFn,
             judge: Optional[JudgeFn], root: Path, dataset: EvalDataset,
             db_url: Optional[str]) -> EvalRun:
    """Common loop: dispatch each case, build summary, persist."""
    for case in cases:
        run.case_results.append(_run_one_case(
            case, dataset_path, rubrics, Path(run.candidate_prompt_path),
            run.candidate_model, dispatch, judge, root))
    run.completed_at = datetime.now(timezone.utc)
    run.summary = aggregate_run(run.case_results, dataset)
    _insert_case_results(run, db_url)
    _finalize_eval_run(run, run.summary, db_url)
    return run


# ─── Mode: full ──────────────────────────────────────────────────────────
def run_full(dataset_path: Path, candidate_prompt_path: Path, candidate_model: str,
             *, dispatch: DispatchFn, judge: Optional[JudgeFn] = None,
             actor: str = "user", db_url: Optional[str] = None,
             repo_root: Optional[Path] = None, mode: str = "full") -> EvalRun:
    """Score candidate prompt against every case in the dataset; persist."""
    root = repo_root or Path.cwd()
    dataset, rubrics = load_dataset_with_rubrics(dataset_path, repo_root=root)
    _register_dataset(dataset, dataset_path, db_url)
    run = _new_run(dataset.dataset_id, mode, candidate_prompt_path, candidate_model, actor)
    run.eval_run_id = _insert_eval_run(run, db_url)
    return _execute(run, dataset.cases, dataset_path, rubrics, dispatch, judge,
                    root, dataset, db_url)


# ─── Mode: regression ────────────────────────────────────────────────────
def run_regression(dataset_path: Path, candidate_prompt_path: Path,
                   candidate_model: str, *, dispatch: DispatchFn,
                   judge: Optional[JudgeFn] = None,
                   tolerance: float = REGRESSION_TOLERANCE,
                   actor: str = "user", db_url: Optional[str] = None,
                   repo_root: Optional[Path] = None) -> RegressionReport:
    """Run candidate; diff each case score vs dataset.baseline.recorded_scores."""
    run = run_full(dataset_path, candidate_prompt_path, candidate_model,
                   dispatch=dispatch, judge=judge, actor=actor,
                   db_url=db_url, repo_root=repo_root, mode="regression")
    dataset, _ = load_dataset_with_rubrics(dataset_path,
                                           repo_root=repo_root or Path.cwd())
    deltas = diff_scores(dict(dataset.baseline.recorded_scores),
                         {r.case_id: r.score for r in run.case_results},
                         tolerance=tolerance)
    case_by_id = {c.case_id: c for c in dataset.cases}
    flagged = sorted(
        ({"case_id": cid, "baseline": b, "candidate": c, "delta": d,
          "severity": case_by_id[cid].severity if cid in case_by_id else "medium"}
         for cid, b, c, d, is_reg in deltas if is_reg),
        key=lambda r: _SEV_RANK.get(r["severity"], 2))
    overall = (sum(c - b for _, b, c, _, _ in deltas) / len(deltas)) if deltas else 0.0
    return RegressionReport(dataset_id=dataset.dataset_id, eval_run=run,
                            per_case_deltas=deltas, flagged_regressions=flagged,
                            overall_delta=overall, tolerance=tolerance)


# ─── Mode: A/B ───────────────────────────────────────────────────────────
def _paired_stats(b: list[float], c: list[float]) -> tuple[Optional[float], str]:
    """numpy paired t-test if available, else sign-test (normal approx)."""
    n = min(len(b), len(c))
    if n < 2: return None, "insufficient_sample"
    diffs = [cs - bs for bs, cs in zip(b, c)]
    try:
        import numpy as np  # noqa: F401
        mean = sum(diffs) / n
        var = sum((d - mean) ** 2 for d in diffs) / (n - 1)
        if var == 0: return (0.0 if mean != 0 else 1.0), "paired_t"
        t_stat = mean / ((var / n) ** 0.5)
        p = 2 * (1 - 0.5 * (1 + erf(abs(t_stat) / sqrt(2))))
        return max(0.0, min(1.0, p)), "paired_t"
    except ImportError:
        wins = sum(1 for d in diffs if d > 0)
        z = (wins - n / 2) / ((n * 0.25) ** 0.5)
        p = 2 * (1 - 0.5 * (1 + erf(abs(z) / sqrt(2))))
        return max(0.0, min(1.0, p)), "sign_test"


def run_ab(dataset_path: Path, baseline_prompt: Path, candidate_prompt: Path,
           baseline_model: str, candidate_model: str, *, dispatch: DispatchFn,
           judge: Optional[JudgeFn] = None, sample_fraction: float = 0.2,
           seed: Optional[int] = None, actor: str = "user",
           db_url: Optional[str] = None,
           repo_root: Optional[Path] = None) -> ABReport:
    """Run both prompts on `sample_fraction` of cases; compare paired scores."""
    root = repo_root or Path.cwd()
    dataset, rubrics = load_dataset_with_rubrics(dataset_path, repo_root=root)
    _register_dataset(dataset, dataset_path, db_url)
    n_sample = max(1, int(round(len(dataset.cases)
                                * max(0.0, min(1.0, sample_fraction)))))
    sample = random.Random(seed).sample(dataset.cases, n_sample)

    def _ab_one(prompt: Path, model: str) -> EvalRun:
        run = _new_run(dataset.dataset_id, "ab", prompt, model, actor,
                       baseline_prompt=baseline_prompt, baseline_model=baseline_model)
        run.eval_run_id = _insert_eval_run(run, db_url)
        return _execute(run, sample, dataset_path, rubrics, dispatch, judge,
                        root, dataset, db_url)

    b_run = _ab_one(baseline_prompt, baseline_model)
    c_run = _ab_one(candidate_prompt, candidate_model)
    b_by = {r.case_id: r.score for r in b_run.case_results}
    c_by = {r.case_id: r.score for r in c_run.case_results}
    common = sorted(set(b_by) & set(c_by))
    wins = sum(1 for cid in common if c_by[cid] > b_by[cid])
    losses = sum(1 for cid in common if c_by[cid] < b_by[cid])
    p_val, test_used = _paired_stats([b_by[k] for k in common],
                                     [c_by[k] for k in common])
    return ABReport(dataset_id=dataset.dataset_id, baseline_run=b_run,
                    candidate_run=c_run, sample_size=len(common), wins=wins,
                    losses=losses, ties=len(common) - wins - losses,
                    p_value=p_val, test_used=test_used)


# ─── Mode: smoke (CI) ────────────────────────────────────────────────────
def run_smoke(dataset_path: Path, candidate_prompt_path: Path, candidate_model: str,
              *, dispatch: DispatchFn, judge: Optional[JudgeFn] = None,
              seed: Optional[int] = None,
              repo_root: Optional[Path] = None) -> bool:
    """Single random case; fast pass/fail for CI. Does NOT persist to DB."""
    root = repo_root or Path.cwd()
    dataset, rubrics = load_dataset_with_rubrics(dataset_path, repo_root=root)
    case = random.Random(seed).choice(dataset.cases)
    result = _run_one_case(case, dataset_path, rubrics, candidate_prompt_path,
                           candidate_model, dispatch, judge, root)
    return result.pass_fail == "pass"


__all__ = ["EvalRun", "RegressionReport", "ABReport", "DispatchFn",
           "run_full", "run_regression", "run_ab", "run_smoke",
           "REGRESSION_TOLERANCE"]
