# Eval runner design — STORY-3.4.2 (design only; implementation deferred)

> Closes the survey gap called out in `docs/research/COMPETITIVE_LANDSCAPE.md §4`
> ("did this role-prompt change make it better?"). Pattern lifted from TRON's
> `verify/tests/golden_suite/` but generalized from "verify ISO agents" to
> "any Spine role." Implements `EPIC-3.4` per `docs/BACKLOG.md`.

## 1. Architecture

```
+----------+   +--------+   +----------+   +---------+   +--------+   +-----------+   +--------+
| dataset  |-->| loader |-->| runner   |-->| output  |-->| scorer |-->| aggregator|-->| report |
| (yaml)   |   |        |   | (per     |   | parser  |   | (per   |   | (per      |   | (md +  |
|          |   |        |   | case)    |   |         |   | check) |   | dataset)  |   | jsonb) |
+----------+   +--------+   +----------+   +---------+   +--------+   +-----------+   +--------+
                                 |               |             |              |
                                 v               v             v              v
                         agent invocation    Pydantic     check_type      spine_eval
                         (prompt + model)    (or regex)   dispatcher      (postgres)
```

## 2. Per-case flow

1. **Load** — `loader` reads the dataset YAML, validates against `_dataset_schema.yaml`,
   resolves each `rubric_ref` (validates against `_rubric_schema.yaml`).
2. **Drift check** — hash `baseline.prompt_path`; if `prompt_sha` differs and `--allow-drift`
   not set, abort with "baseline drift detected; re-baseline or pass --allow-drift".
3. **Invoke** — `runner` builds an agent call with: candidate prompt (either baseline or
   `--candidate-prompt <path>`), model (baseline.model or `--candidate-model`),
   directive, and `inputs.files` / `prior_reports` / pre-resolved `kg_queries`.
4. **Capture** — write raw stdout + stderr + any artifact files (e.g. `build-artifact.json`)
   to `eval-runs/<run_id>/<case_id>/`.
5. **Parse** — dispatch to the right Pydantic schema based on the role:
   - `engineer` / `operator` / `datawright` → `BuildArtifact`
   - `product` → `PRD`
   - `architect` → `TRD`
   - `planner` → `Roadmap` / `Epic`
   - `qa` / `auditor` → text + finding list
   Fall back to text-matching if schema validation fails (record `parse_failed: true`
   in the case result — that itself becomes a checkable trait).
6. **Score** — for each check in the rubric, dispatch by `check_type` (see §3).
7. **Tally** — apply `scoring_method` from the rubric (strict_must / weighted_average /
   composite) to produce a single 0.0-1.0 case score + per-check pass/fail list.
8. **Record** — write `case_result` row to `spine_eval.case_result`.

## 3. Check-type dispatch

| check_type | impl |
|---|---|
| `regex` | `re.search(pattern, target_text)` with `case_sensitive` flag |
| `structured_field` | `import_class(schema_path)(parsed_output)`; resolve `field_path`; `eval(assertion, {"value": v})` in a no-builtins sandbox |
| `llm_judge` | render `judge_prompt` with `{output}`/`{directive}`/`{expected}`; call `judge_model`; parse float; compare to `passing_score`; retry on parse failure only |
| `deterministic` | `subprocess.run(script_path, env={**env, "OUTPUT_PATH": ..., "DIRECTIVE_ID": ...}, timeout=timeout_seconds)`; exit 0 = pass |

## 4. Scoring (per `rubric.scoring_method`)

- **strict_must** — any failing check (all must_pass=true by validation rule) → score 0.0; else 1.0.
- **weighted_average** — `sum(check_pass * weight) / sum(weight)` over all checks; weights validated to sum ≈ 1.0.
- **composite** — `all_must_pass ? weighted_average(remaining_checks) : 0.0`.

## 5. Aggregator → report

Per-dataset aggregate score = severity-weighted mean of case scores:
`sum(score * severity_weight) / sum(severity_weight)` where weight is
{critical: 3, high: 2, medium: 1, low: 0.5}.

Report is markdown + JSONB: per-case pass/fail table, per-check breakdown,
score delta vs `baseline.recorded_scores`, list of regressions sorted by
severity. Posted to dashboard view (STORY-3.4.5).

## 6. Regression mode (STORY-3.4.3)

`spine eval regression <dataset> --candidate-prompt <path>`:
1. Run candidate against full dataset.
2. Diff each case score vs `baseline.recorded_scores[case_id]`.
3. Flag any case where `candidate_score < baseline_score - tolerance` (default 0.05).
4. Exit non-zero if regressions present; print regression list with severity.
5. If no regressions and `--update-baseline`: rewrite `recorded_scores` block in dataset.

## 7. A/B mode (STORY-3.4.4)

`spine eval ab <role> --candidate-prompt <path> --traffic-fraction 0.1`:
1. Hook into orchestrator directive dispatch.
2. For each incoming directive routed to `<role>`, sample `traffic_fraction`.
3. Sampled directives run twice — baseline and candidate — in parallel.
4. Outcomes (downstream auditor verdict, gate pass/fail, revisions required)
   written to `spine_eval.ab_outcome`.
5. Weekly digest aggregates outcomes; auto-PR opens if candidate beats baseline
   on N≥50 directives with p<0.05.

## 8. Storage (deferred to follow-up story; sketch only)

New schema `spine_eval`:

| Table | Purpose |
|---|---|
| `dataset` | one row per dataset_id × version; stores YAML blob + parsed cases |
| `eval_run` | one row per invocation of the runner; `run_id`, `dataset_id`, `candidate_prompt_sha`, `model`, `started_at`, `aggregate_score` |
| `case_result` | one row per case per run; raw output path, parse_failed flag, per-check pass/fail JSONB, case_score |
| `aggregate_score` | denormalized rollup for dashboard queries |
| `ab_outcome` | A/B mode pairs (STORY-3.4.4 only) |

## 9. CI integration

GitHub Actions workflow at `.github/workflows/prompt-regression.yml` adopts
TRON's pattern (`verify/.github/workflows/prompt-regression.yml`) but
generalizes the trigger: any PR touching `lib/role-prompts/<role>.md` runs
the eval dataset for that role; PR fails on regression. The same workflow
runs nightly across all role datasets so model-side drift is caught.

## 10. Cost — eval budget pool

Eval runs cost real money (especially `llm_judge` checks + A/B mode). Without
isolation, evals consume project quota and operators turn evals off.
**Recommendation:** a separate "eval budget" pool in the cost router, distinct
from project budgets, set via `spine_config.eval_budget_usd_monthly`. The
dashboard surfaces eval spend separately; alerts fire when eval pool hits 80%.

## 11. LangSmith adaptation note

TRON's golden_suite uses unit-test-style Python files with mocked LLM
responses (deterministic, no cost). Spine's eval harness flips that: real
LLM calls against a candidate prompt, scored by a rubric. The two are
complementary — TRON's pattern catches "did the parser break"; Spine's
catches "did the prompt get worse." Both should live side-by-side; both
schemas should be importable from `shared/eval/`.
