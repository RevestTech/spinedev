"""Spine eval CLI (STORY-3.4.2 / 3.4.3 / 3.4.4).

`spine eval run|regression|ab|status|smoke|datasets`. Exit codes (frozen):
0=pass, 1=fail, 2=regression, 3=error, 64=unknown subcommand.

Real LLM dispatch lives outside this module (MCP `*_dispatch`). Without a
real dispatcher this CLI uses a noop that returns empty output so the
harness is testable end-to-end without network or cost. Override with
the `SPINE_EVAL_DISPATCH=pkg.mod.callable` env var.
"""
from __future__ import annotations
import argparse, importlib, json, os, subprocess, sys
from pathlib import Path
from typing import Any, Optional

from shared.eval.loader import Case
from shared.eval.reporter import (format_json, format_junit,
                                  format_regression_diff, format_text)
from shared.eval.runner import (REGRESSION_TOLERANCE, ABReport, EvalRun,
                                RegressionReport, run_ab, run_full,
                                run_regression, run_smoke)

EXIT_PASS, EXIT_FAIL, EXIT_REGRESSION, EXIT_ERROR, EXIT_UNKNOWN = 0, 1, 2, 3, 64
DEFAULT_DB_URL = os.environ.get("SPINE_DB_URL", "postgresql://spine:spine@localhost:33000/spine")


def _noop_dispatch(case: Case, prompt: Path, model: str
                   ) -> tuple[str, Any, Optional[Path], float]:
    """Stand-in dispatcher; emits empty output unless SPINE_EVAL_DISPATCH set."""
    target = os.environ.get("SPINE_EVAL_DISPATCH", "")
    mod_name, _, attr = target.rpartition(".")
    if mod_name and attr:
        return getattr(importlib.import_module(mod_name), attr)(case, prompt, model)
    return "", None, None, 0.0


def _run_to_dict(run: EvalRun) -> dict[str, Any]:
    return {"run_uuid": str(run.run_uuid), "mode": run.mode,
            "candidate_prompt_path": run.candidate_prompt_path,
            "candidate_prompt_sha": run.candidate_prompt_sha,
            "candidate_model": run.candidate_model,
            "started_at": run.started_at.isoformat(),
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            "summary": run.summary, "cases": run.case_results}


def _print_run(run: EvalRun, fmt: str) -> None:
    payload = _run_to_dict(run)
    if fmt == "json": print(json.dumps(format_json(payload), indent=2, default=str))
    elif fmt == "junit": print(format_junit(payload))
    else: print(format_text(payload))


def _exit_for_run(run: EvalRun, threshold: float) -> int:
    if run.summary is None: return EXIT_ERROR
    if run.summary.error_count > 0 or run.summary.fail_count > 0: return EXIT_FAIL
    return EXIT_FAIL if run.summary.aggregate_score + 1e-9 < threshold else EXIT_PASS


def _psql_lines(sql: str, db_url: str) -> list[str]:
    try:
        r = subprocess.run(["psql", db_url, "-At", "-F", "|", "-v", "ON_ERROR_STOP=1",
                            "-c", sql], capture_output=True, text=True,
                           timeout=15, check=True)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
            FileNotFoundError) as e:
        print(f"psql error: {e}", file=sys.stderr)
        return []
    return r.stdout.strip().splitlines()


def cmd_run(args: argparse.Namespace) -> int:
    run = run_full(Path(args.dataset), Path(args.prompt), args.model,
                   dispatch=_noop_dispatch, actor=args.actor, db_url=args.db_url)
    _print_run(run, args.format)
    return _exit_for_run(run, args.threshold)


def cmd_regression(args: argparse.Namespace) -> int:
    report: RegressionReport = run_regression(
        Path(args.dataset), Path(args.prompt), args.model,
        dispatch=_noop_dispatch, tolerance=args.tolerance,
        actor=args.actor, db_url=args.db_url)
    _print_run(report.eval_run, args.format)
    diff = {"dataset_id": report.dataset_id, "per_case_deltas": report.per_case_deltas,
            "flagged_regressions": report.flagged_regressions,
            "overall_delta": report.overall_delta, "tolerance": report.tolerance}
    if args.format == "json": print(json.dumps(diff, default=str, indent=2))
    else: print(); print(format_regression_diff(diff))
    return EXIT_REGRESSION if report.flagged_regressions else \
        _exit_for_run(report.eval_run, args.threshold)


def cmd_ab(args: argparse.Namespace) -> int:
    report: ABReport = run_ab(
        Path(args.dataset), Path(args.baseline_prompt), Path(args.candidate_prompt),
        args.baseline_model, args.candidate_model, dispatch=_noop_dispatch,
        sample_fraction=args.fraction, seed=args.seed, actor=args.actor,
        db_url=args.db_url)
    print(json.dumps({"dataset_id": report.dataset_id, "sample_size": report.sample_size,
                      "wins": report.wins, "losses": report.losses, "ties": report.ties,
                      "p_value": report.p_value, "test_used": report.test_used,
                      "baseline_aggregate": getattr(report.baseline_run.summary, "aggregate_score", None),
                      "candidate_aggregate": getattr(report.candidate_run.summary, "aggregate_score", None)},
                     indent=2, default=str))
    return EXIT_PASS if report.wins >= report.losses else EXIT_FAIL


def cmd_smoke(args: argparse.Namespace) -> int:
    if not args.prompt:
        print("--prompt required for smoke run", file=sys.stderr); return EXIT_ERROR
    ok = run_smoke(Path(args.dataset), Path(args.prompt),
                   args.model or "claude-haiku-4-5",
                   dispatch=_noop_dispatch, seed=args.seed)
    print(f"smoke: {'pass' if ok else 'fail'}")
    return EXIT_PASS if ok else EXIT_FAIL


def cmd_status(args: argparse.Namespace) -> int:
    where = f"WHERE dataset_id = '{args.dataset_id}'" if args.dataset_id else ""
    rows = _psql_lines(
        f"SELECT dataset_id, mode, candidate_model, aggregate_score, pass_count, "
        f"fail_count, started_at FROM spine_eval.eval_run {where} "
        f"ORDER BY started_at DESC LIMIT 10;", args.db_url)
    if not rows: print("no eval runs found (or psql unavailable)"); return EXIT_PASS
    print("DATASET_ID | MODE | MODEL | SCORE | PASS | FAIL | STARTED_AT")
    for line in rows: print(line)
    return EXIT_PASS


def cmd_datasets(args: argparse.Namespace) -> int:
    rows = _psql_lines("SELECT dataset_id, role, version, case_count, created_at "
                       "FROM spine_eval.dataset ORDER BY dataset_id;", args.db_url)
    print("DATASET_ID | ROLE | VERSION | CASES | CREATED_AT")
    for line in rows: print(line)
    return EXIT_PASS


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="spine eval", description=__doc__.splitlines()[0])
    p.add_argument("--db-url", default=DEFAULT_DB_URL)
    p.add_argument("--actor", default=os.environ.get("USER", "user"))
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("run", "regression"):
        sp = sub.add_parser(name)
        sp.add_argument("dataset"); sp.add_argument("--prompt", required=True)
        sp.add_argument("--model", required=True)
        sp.add_argument("--format", choices=["text", "json", "junit"], default="text")
        sp.add_argument("--threshold", type=float, default=0.0)
        if name == "regression":
            sp.add_argument("--tolerance", type=float, default=REGRESSION_TOLERANCE)
    ab = sub.add_parser("ab")
    ab.add_argument("dataset")
    for a in ("--baseline-prompt", "--candidate-prompt", "--baseline-model", "--candidate-model"):
        ab.add_argument(a, required=True)
    ab.add_argument("--fraction", type=float, default=0.2)
    ab.add_argument("--seed", type=int, default=None)
    sm = sub.add_parser("smoke")
    sm.add_argument("dataset"); sm.add_argument("--prompt"); sm.add_argument("--model")
    sm.add_argument("--seed", type=int, default=None)
    sub.add_parser("status").add_argument("dataset_id", nargs="?")
    sub.add_parser("datasets")
    return p


_DISPATCH = {"run": cmd_run, "regression": cmd_regression, "ab": cmd_ab,
             "smoke": cmd_smoke, "status": cmd_status, "datasets": cmd_datasets}


def main(argv: Optional[list[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    fn = _DISPATCH.get(args.cmd)
    if fn is None:
        print(f"unknown subcommand: {args.cmd}", file=sys.stderr)
        return EXIT_UNKNOWN
    try:
        return fn(args)
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr); return EXIT_ERROR
    except Exception as e:  # broad: CLI must not crash hard
        print(f"error: {type(e).__name__}: {e}", file=sys.stderr); return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
