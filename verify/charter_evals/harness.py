"""Pass@k regression harness for charter evals (V3 #7a, B6 borrow).

Borrowed contract source: ECC ``eval-harness`` skill (`affaan-m/ecc`,
MIT). See ``docs/ECC_BORROWS.md`` B6.

Why
---

Charters in ``shared/charters/*.md`` are industry-anchored (#7) but a
charter edit can silently degrade role behaviour. V3 #7a binds a
regression-class gate: any PR touching a charter must run that role's
capability eval suite and report ``pass@k ≥ target``.

This module implements the smallest useful version of that contract:

* :class:`CapabilityEval` — declarative shape (yaml-loadable).
* :func:`run_capability_eval` — runs N trials via a caller-supplied
  ``role_callable`` and a list of :class:`EvalCriterion` graders.
* :func:`pass_at_k` — computes the pass@k metric from a list of results.
* :func:`evaluate_charter` — composes both: runs every eval for a role
  and returns the aggregate.

Provider-agnostic: the harness never calls an LLM directly. The
``role_callable`` is injected by the test or by the dispatch wrapper
(Claude Code / Cursor / charter daemon). The harness only orchestrates,
grades, and reports.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, Sequence

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)


DEFAULT_K = 5
"""Default trial count for pass@k."""

DEFAULT_PASS_AT_K_TARGET = 0.8
"""Default acceptance threshold for ``pass@k`` per V3 #7a."""


class EvalCriterion(BaseModel):
    """One check the harness will apply to each trial's output.

    A criterion has a short ``name`` (used in result rows) and one of
    three checker shapes:

      * ``required_substrings`` — every listed substring must appear in
        the trial output text.
      * ``forbidden_substrings`` — none of the listed substrings may
        appear.
      * ``custom`` — caller supplies a ``Callable[[str], bool]`` at
        runtime (not yaml-loadable).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(..., min_length=1)
    required_substrings: tuple[str, ...] = Field(default_factory=tuple)
    forbidden_substrings: tuple[str, ...] = Field(default_factory=tuple)

    def check(self, output_text: str) -> bool:
        """Apply the criterion to ``output_text``. Returns True on pass."""
        for s in self.required_substrings:
            if s not in output_text:
                return False
        for s in self.forbidden_substrings:
            if s in output_text:
                return False
        return True


class CapabilityEval(BaseModel):
    """One declarative capability eval for a charter.

    YAML shape (per ECC ``agent-eval``)::

        name: engineer-emits-build-artifact
        role: engineer
        task: |
          Implement REQ-FOO-1: add input validation to /api/foo.
        criteria:
          - name: cites_req
            required_substrings: ["REQ-FOO-1"]
          - name: no_silent_skip
            forbidden_substrings: ["TODO", "XXX"]
        target_k: 5
        target_pass_rate: 0.8
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1)
    role: str = Field(..., min_length=1)
    task: str = Field(..., min_length=1)
    criteria: list[EvalCriterion] = Field(..., min_length=1)
    target_k: int = Field(default=DEFAULT_K, ge=1)
    target_pass_rate: float = Field(
        default=DEFAULT_PASS_AT_K_TARGET, ge=0.0, le=1.0,
    )


@dataclass(frozen=True)
class EvalRunResult:
    """One trial of one :class:`CapabilityEval`."""

    eval_name: str
    trial_index: int
    output_text: str
    passed: bool
    failed_criteria: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class PassAtK:
    """Aggregate of N trial results."""

    eval_name: str
    trials: int
    passed: int
    target_pass_rate: float
    pass_rate: float
    meets_target: bool


RoleCallable = Callable[[CapabilityEval, int], str]
"""Returns trial output text for ``(eval, trial_index)``.

The harness graders consume ``output_text``. The caller decides how to
run the role (LLM call, mock, recorded fixture, etc.).
"""


def run_capability_eval(
    eval_: CapabilityEval,
    role: RoleCallable,
    *,
    k: int | None = None,
) -> list[EvalRunResult]:
    """Run ``k`` trials and return a result row per trial."""
    trials = k if k is not None else eval_.target_k
    results: list[EvalRunResult] = []
    for idx in range(trials):
        try:
            output = role(eval_, idx)
        except Exception as exc:  # noqa: BLE001 — surface in result row
            output = f"__role_raised__: {exc}"
        failed: list[str] = []
        for crit in eval_.criteria:
            if not crit.check(output):
                failed.append(crit.name)
        results.append(
            EvalRunResult(
                eval_name=eval_.name,
                trial_index=idx,
                output_text=output,
                passed=not failed,
                failed_criteria=tuple(failed),
            )
        )
    return results


def pass_at_k(
    results: Sequence[EvalRunResult],
    *,
    target_pass_rate: float = DEFAULT_PASS_AT_K_TARGET,
) -> PassAtK:
    """Aggregate ``results`` into a pass@k summary."""
    if not results:
        return PassAtK(
            eval_name="(empty)",
            trials=0,
            passed=0,
            target_pass_rate=target_pass_rate,
            pass_rate=0.0,
            meets_target=False,
        )
    name = results[0].eval_name
    passed = sum(1 for r in results if r.passed)
    rate = passed / len(results)
    return PassAtK(
        eval_name=name,
        trials=len(results),
        passed=passed,
        target_pass_rate=target_pass_rate,
        pass_rate=rate,
        meets_target=rate >= target_pass_rate,
    )


@dataclass(frozen=True)
class CharterReport:
    """Outcome of running every eval for one charter (role)."""

    role: str
    per_eval: tuple[PassAtK, ...]
    overall_meets_target: bool


def evaluate_charter(
    role: str,
    evals: Sequence[CapabilityEval],
    role_callable: RoleCallable,
) -> CharterReport:
    """Run every eval in ``evals`` and aggregate per-eval ``pass@k``.

    ``overall_meets_target`` is True iff *every* eval meets its own
    ``target_pass_rate``. One regressed eval fails the whole charter
    gate — V3 #7a is a regression contract, not an average.
    """
    per_eval: list[PassAtK] = []
    for ev in evals:
        if ev.role != role:
            raise ValueError(
                f"eval {ev.name!r} has role={ev.role!r} but charter "
                f"report is for role={role!r}"
            )
        trials = run_capability_eval(ev, role_callable, k=ev.target_k)
        per_eval.append(
            pass_at_k(trials, target_pass_rate=ev.target_pass_rate)
        )
    overall = all(p.meets_target for p in per_eval) if per_eval else False
    report = CharterReport(
        role=role,
        per_eval=tuple(per_eval),
        overall_meets_target=overall,
    )
    _publish_charter_eval(role=role, report=report)
    return report


def _publish_charter_eval(*, role: str, report: "CharterReport") -> None:
    """Emit a ``charter_eval_run`` realtime event. Fail-soft.

    Charter evals are project-agnostic in the harness, but the Hub
    surfaces them per role. The SPA's Live tab subscribes per
    project; the event publishes with the role name as the
    ``project_id`` so the role-scoped Eval surface (Path A T19) can
    pick it up. Operators viewing a project don't see this in their
    Live feed by design — eval-class events have their own surface.
    """
    try:
        from shared.api.realtime.event_publisher import publish
        from shared.api.realtime.event_schema import ProjectEvent

        per_eval = [
            {
                "eval_name": p.eval_name,
                "trials": p.trials,
                "passed": p.passed,
                "pass_rate": p.pass_rate,
                "target_pass_rate": p.target_pass_rate,
                "meets_target": p.meets_target,
            }
            for p in report.per_eval
        ]
        verdict = "passed" if report.overall_meets_target else "failed"
        publish(
            ProjectEvent(
                event_type="charter_eval_run",
                project_id=f"charter:{role}",
                actor=role,
                verdict=verdict,
                summary=(
                    f"charter eval {role} — "
                    f"{sum(1 for p in report.per_eval if p.meets_target)}/"
                    f"{len(report.per_eval)} evals pass"
                ),
                payload={
                    "role": role,
                    "overall_meets_target": report.overall_meets_target,
                    "per_eval": per_eval,
                },
            )
        )
    except Exception:  # noqa: BLE001 — fail-soft
        return


# ─── YAML loader ─────────────────────────────────────────────────────


def load_evals_for_role(
    role: str,
    *,
    root: "Path | str | None" = None,
) -> list[CapabilityEval]:
    """Load every ``*.yaml`` under ``<root>/<role>/`` as a CapabilityEval.

    ``root`` defaults to the on-disk location of this package
    (``verify/charter_evals/``). Files whose ``role`` field does not
    match the directory name are rejected — eval YAML must declare its
    own role to keep cross-role mistakes loud.

    Empty or missing role dirs return an empty list (no error). Callers
    that want a regression gate apply the policy "≥ 3 evals required to
    enforce #7a" themselves; the harness does not enforce a minimum.
    """
    # Local imports — keep harness importable without pyyaml installed
    # for the in-process unit tests; the loader path imports lazily.
    from pathlib import Path

    import yaml

    base = Path(root) if root is not None else Path(__file__).resolve().parent
    role_dir = base / role
    if not role_dir.is_dir():
        return []

    evals: list[CapabilityEval] = []
    for yaml_path in sorted(role_dir.glob("*.yaml")):
        raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ValueError(
                f"eval file {yaml_path} did not parse as a dict"
            )
        if raw.get("role") != role:
            raise ValueError(
                f"eval file {yaml_path} declares role="
                f"{raw.get('role')!r} but lives under {role!r}/"
            )
        evals.append(CapabilityEval.model_validate(raw))
    return evals


__all__ = [
    "DEFAULT_K",
    "DEFAULT_PASS_AT_K_TARGET",
    "CapabilityEval",
    "CharterReport",
    "EvalCriterion",
    "EvalRunResult",
    "PassAtK",
    "RoleCallable",
    "evaluate_charter",
    "load_evals_for_role",
    "pass_at_k",
    "run_capability_eval",
]
