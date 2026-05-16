"""Spine eval scorer (STORY-3.4.2 §3, §4).

Dispatches each rubric check by `check_type`, applies the rubric's
scoring_method, and returns a CaseResult. Sandboxed `structured_field`
assertions (no builtins, no imports, no I/O). `llm_judge` calls are
funneled through a pluggable callable so test code can mock without
patching globally. No DB writes here.
"""
from __future__ import annotations
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from shared.eval.loader import Case, EvalRubric, RubricCheck

# Caller-supplied judge: (judge_prompt, judge_model) -> float in [0,1].
JudgeFn = Callable[[str, str], float]


@dataclass
class CheckResult:
    """One rubric check's outcome."""
    check_id: str
    check_type: str
    passed: bool
    score: float                       # 0.0-1.0
    weight: float
    must_pass: bool
    detail: str = ""                   # human-readable why


@dataclass
class CaseResult:
    """One case's score (after scoring_method applied)."""
    case_id: str
    score: float                       # 0.0-1.0
    pass_fail: str                     # 'pass' | 'fail' | 'skip' | 'error'
    check_results: list[CheckResult] = field(default_factory=list)
    output_artifact: Optional[str] = None
    cost_usd: float = 0.0
    duration_ms: int = 0
    error_message: Optional[str] = None


# ─── Check-type dispatch ─────────────────────────────────────────────────
def _check_regex(payload: dict[str, Any], output_text: str,
                 output_obj: Any) -> tuple[bool, str]:
    cfg = (payload or {}).get("regex") or {}
    pattern = cfg.get("pattern")
    if not pattern:
        return False, "regex.pattern missing"
    flags = 0 if cfg.get("case_sensitive") else re.IGNORECASE
    target = cfg.get("target", "stdout")
    text = output_text if target != "field" else _resolve_field(output_obj, cfg.get("field_path", ""))
    if not isinstance(text, str):
        text = str(text)
    try:
        m = re.search(pattern, text, flags=flags)
    except re.error as e:
        return False, f"regex error: {e}"
    return (m is not None, f"pattern {'matched' if m else 'did not match'}: {pattern!r}")


def _resolve_field(obj: Any, path: str) -> Any:
    """Walk a dot/bracket path (`a.b[0].c`) over a Pydantic obj or dict."""
    if not path:
        return obj
    cur = obj
    for part in re.findall(r"[^.\[\]]+|\[\d+\]", path):
        if part.startswith("["):
            cur = cur[int(part[1:-1])]
        else:
            cur = getattr(cur, part, None) if not isinstance(cur, dict) else cur.get(part)
        if cur is None:
            return None
    return cur


# Whitelist for assertion sandbox — len + comparison ops are pure functions.
_ASSERT_GLOBALS = {"__builtins__": {}, "len": len, "any": any, "all": all,
                   "min": min, "max": max, "sum": sum, "abs": abs,
                   "True": True, "False": False, "None": None}


def _check_structured_field(payload: dict[str, Any], output_obj: Any) -> tuple[bool, str]:
    cfg = (payload or {}).get("structured_field") or {}
    field_path = cfg.get("field_path", "")
    assertion = cfg.get("assertion")
    if not assertion:
        return False, "structured_field.assertion missing"
    if output_obj is None:
        return False, "no parsed output object (parse failed?)"
    value = _resolve_field(output_obj, field_path)
    try:
        ok = bool(eval(assertion, _ASSERT_GLOBALS, {"value": value}))
    except Exception as e:  # broad: assertion is user-supplied YAML
        return False, f"assertion eval error: {e}"
    return ok, f"field {field_path!r} assertion {'passed' if ok else 'failed'}"


def _check_llm_judge(payload: dict[str, Any], output_text: str, directive: str,
                     judge: Optional[JudgeFn]) -> tuple[bool, str, float]:
    cfg = (payload or {}).get("llm_judge") or {}
    passing = float(cfg.get("passing_score", 0.7))
    if judge is None:
        return False, "no judge callable provided (skipped)", 0.0
    prompt = str(cfg.get("judge_prompt", "")).replace("{output}", output_text or "") \
                                              .replace("{directive}", directive or "") \
                                              .replace("{expected}", "")
    model = cfg.get("judge_model", "claude-haiku-4-5")
    retries = max(0, int(cfg.get("retries", 2)))
    score = 0.0
    last_err = ""
    for _ in range(retries + 1):
        try:
            score = float(judge(prompt, model))
            break
        except Exception as e:
            last_err = str(e)
            score = 0.0
    if last_err:
        return False, f"judge error: {last_err}", 0.0
    return (score >= passing, f"judge score {score:.2f} vs threshold {passing:.2f}", score)


def _check_deterministic(payload: dict[str, Any], artifact_path: Optional[Path],
                         directive_id: str, repo_root: Path) -> tuple[bool, str]:
    cfg = (payload or {}).get("deterministic") or {}
    script = cfg.get("script_path")
    if not script:
        return False, "deterministic.script_path missing"
    script_path = (repo_root / script).resolve()
    if not script_path.is_file():
        return False, f"script not found: {script_path}"
    env = {"OUTPUT_PATH": str(artifact_path or ""), "DIRECTIVE_ID": directive_id,
           **{k: str(v) for k, v in (cfg.get("env") or {}).items()}}
    try:
        proc = subprocess.run([str(script_path)], env=env, capture_output=True,
                              text=True, timeout=int(cfg.get("timeout_seconds", 60)))
    except subprocess.TimeoutExpired:
        return False, "deterministic check timed out"
    except OSError as e:
        return False, f"deterministic check exec error: {e}"
    return (proc.returncode == 0,
            f"exit {proc.returncode}; stderr[:200]={proc.stderr[:200]!r}")


# ─── Dispatcher + scoring ────────────────────────────────────────────────
def _run_check(check: RubricCheck, output_text: str, output_obj: Any,
               case: Case, judge: Optional[JudgeFn],
               artifact_path: Optional[Path], repo_root: Path) -> CheckResult:
    """Apply one rubric check and produce a CheckResult."""
    pl, ct = check.payload, check.check_type
    if ct == "regex":
        passed, detail = _check_regex(pl, output_text, output_obj)
        score = 1.0 if passed else 0.0
    elif ct == "structured_field":
        passed, detail = _check_structured_field(pl, output_obj)
        score = 1.0 if passed else 0.0
    elif ct == "llm_judge":
        passed, detail, score = _check_llm_judge(pl, output_text, case.directive, judge)
    elif ct == "deterministic":
        passed, detail = _check_deterministic(pl, artifact_path, case.case_id, repo_root)
        score = 1.0 if passed else 0.0
    else:
        passed, detail, score = False, f"unknown check_type: {ct}", 0.0
    return CheckResult(check_id=check.check_id, check_type=ct, passed=passed,
                       score=score, weight=check.weight, must_pass=check.must_pass,
                       detail=detail)


def score_case(case: Case, output_text: str, output_obj: Any, rubric: EvalRubric,
               *, judge: Optional[JudgeFn] = None,
               artifact_path: Optional[Path] = None,
               repo_root: Optional[Path] = None) -> CaseResult:
    """Run every rubric check, then apply scoring_method → CaseResult."""
    root = repo_root or Path.cwd()
    results = [_run_check(c, output_text, output_obj, case, judge, artifact_path, root)
               for c in rubric.checks]
    all_must = all(r.passed for r in results if r.must_pass)
    if rubric.scoring_method == "strict_must":
        score = 1.0 if all(r.passed for r in results) else 0.0
    elif rubric.scoring_method == "weighted_average":
        denom = sum(r.weight for r in results) or 1.0
        score = sum(r.score * r.weight for r in results) / denom
    else:  # composite
        rest = [r for r in results if not r.must_pass]
        denom = sum(r.weight for r in rest) or 1.0
        weighted = sum(r.score * r.weight for r in rest) / denom
        score = weighted if all_must else 0.0
    score = max(0.0, min(1.0, float(score)))
    return CaseResult(case_id=case.case_id, score=score,
                      pass_fail="pass" if (score > 0.0 and all_must) else "fail",
                      check_results=results)


__all__ = ["CheckResult", "CaseResult", "JudgeFn", "score_case"]
