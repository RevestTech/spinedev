# `shared/eval/` runner — usage

> Implements `STORY-3.4.2` (eval runner), `STORY-3.4.3` (regression mode),
> and `STORY-3.4.4` (A/B mode) per `docs/BACKLOG.md`. Design lives in
> `runner_design.md`; this file is the operator manual.

## Layout

| File | Purpose |
|---|---|
| `loader.py` | Pydantic v2 models + YAML loaders for datasets and rubrics |
| `runner.py` | `run_full / run_regression / run_ab / run_smoke` |
| `scorer.py` | Per-check dispatch (regex / structured_field / llm_judge / deterministic) |
| `aggregator.py` | Per-case → per-run rollup (severity-weighted aggregate, tag rollups, top failed checks) |
| `reporter.py` | Output formatters (text table / JSON / JUnit XML / regression diff) |
| `cli.py` | `spine eval run|regression|ab|smoke|status|datasets` |

## Running an eval

```bash
# Full run — score candidate prompt against every case in the dataset.
python -m shared.eval.cli run shared/eval/example_engineer.yaml \
    --prompt shared/charters/engineer.md \
    --model claude-opus-4-7 \
    --format text --threshold 0.7

# Regression — diff candidate scores vs dataset.baseline.recorded_scores.
python -m shared.eval.cli regression shared/eval/example_engineer.yaml \
    --prompt shared/charters/engineer.md \
    --model claude-opus-4-7 \
    --tolerance 0.05

# A/B — paired run on `--fraction` of cases; reports wins / p-value.
python -m shared.eval.cli ab shared/eval/example_engineer.yaml \
    --baseline-prompt shared/charters/engineer.md \
    --candidate-prompt /tmp/engineer-v2.md \
    --baseline-model claude-opus-4-7 \
    --candidate-model claude-opus-4-7 \
    --fraction 0.2 --seed 7

# Smoke — single random case, no DB writes; CI-friendly.
python -m shared.eval.cli smoke shared/eval/example_engineer.yaml \
    --prompt shared/charters/engineer.md --model claude-haiku-4-5

# Status / registry
python -m shared.eval.cli status engineer-core-v1
python -m shared.eval.cli datasets
```

## Output formats

- **text** (default) — terminal table; `+check_id`=pass, `-check_id`=fail.
- **json** — full `format_json(run)` payload; safe for jq pipelines.
- **junit** — JUnit XML for GitHub Actions / GitLab / Jenkins widgets.

## Regression interpretation

`run_regression` flags any case where
`candidate_score < baseline_score - tolerance` (default 0.05).

Exit code:
- `0` — no regression and aggregate ≥ `--threshold`
- `1` — case-level failure or aggregate below threshold (no regression)
- `2` — regression detected (one or more flagged cases)
- `3` — loader / IO / subprocess error

Severity-weighted aggregate uses `critical*4`, `high*2`, `medium*1`,
`low*0.5`. A `must_not` trait failure is always treated as a hard fail
regardless of severity (see `runner_design.md §6`).

## A/B mode

`run_ab` invokes both prompts on a `--fraction` sample under the same
`--seed`, then runs a paired statistical test on the score vector.
`numpy` is used opportunistically (paired t-test); without it, the
runner falls back to a sign test (normal approximation). Both write
`spine_eval.eval_run` rows tagged `mode='ab'`.

## Pluggable dispatch

The runner does **not** know how to talk to your LLM. Wire your dispatch
via:

```bash
export SPINE_EVAL_DISPATCH=my_package.dispatch_to_role
python -m shared.eval.cli run ...
```

`my_package.dispatch_to_role(case, prompt_path, model)` must return
`(output_text, parsed_obj_or_None, artifact_path_or_None, cost_usd)`.

## Separate eval budget pool

Eval runs cost real money — especially `llm_judge` checks and A/B mode.
Per `runner_design.md §10`, eval spend draws from a dedicated
`spine_config.eval_budget_usd_monthly` pool, distinct from project
budgets. Runner records costs in `spine_eval.eval_run.total_cost_usd`
and `case_result.cost_usd`; pair with cost-router rules to keep evals
from starving real projects.

## CI integration

```yaml
- name: spine eval regression
  run: |
    python -m shared.eval.cli regression shared/eval/example_engineer.yaml \
      --prompt shared/charters/engineer.md --model claude-opus-4-7 \
      --format junit > eval-results.xml
- uses: mikepenz/action-junit-report@v4
  if: always()
  with: { report_paths: 'eval-results.xml' }
```

Exit `2` is the regression signal; gate your PR on that.

## See also

`runner_design.md` (architecture), `README.md` (authoring recipe),
`db/flyway/sql/V19__spine_eval_schema.sql` (storage),
`docs/BACKLOG.md` EPIC-3.4 (story tracking).
