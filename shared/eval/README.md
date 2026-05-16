# `shared/eval/` — Role-prompt regression harness

> **Status:** Design-only (STORY-3.4.1 + STORY-3.4.2 design). Runner
> implementation deferred. See `runner_design.md`.

## Why this exists

The competitive survey (`docs/research/COMPETITIVE_LANDSCAPE.md §4`) called out
a real gap: **no Spine operator can answer "did my edit to `architect.md` make
it better or worse?"**. Prompts drift, models drift, and the only feedback loop
today is "did the next project work" — which is too coarse, too slow, and too
expensive to learn from.

This directory is the answer. A dataset is `(directive, expected_artifact_traits,
scoring_rubric)` triples per role. A runner replays each directive against a
candidate prompt + model, scores the output against the rubric, and reports
pass/fail + score deltas vs the recorded baseline.

## Files

| File | Purpose |
|---|---|
| `_dataset_schema.yaml` | Schema for an eval dataset (STORY-3.4.1) |
| `_rubric_schema.yaml` | Schema for scoring rubrics (STORY-3.4.1) |
| `example_engineer.yaml` | Worked example: engineer regressions |
| `example_architect.yaml` | Worked example: architect TRD synthesis + delta-aware TRD |
| `runner_design.md` | Eval runner design (STORY-3.4.2) |

## How to author a dataset (5-step recipe)

1. **Pick a role.** Datasets are per-role (`engineer`, `architect`, `planner`, ...).
2. **Collect 5-20 directives** that exercise the regressions you fear most. Real
   directives from `spine_recording.directive` are gold — start there.
3. **For each directive, list expected traits** the output MUST/SHOULD/MUST_NOT
   contain. Prefer `structured_field` checks on typed artifacts (BuildArtifact,
   PRD, TRD) over `regex` over `llm_judge`. Cheaper and more stable in that order.
4. **Pick or write a rubric.** Most roles have a `strict.yaml` + `composite.yaml`
   pair; reuse before authoring new.
5. **Baseline.** Run `spine eval baseline <dataset>` to populate `baseline.prompt_sha`
   and `recorded_scores`. This is your green line.

## How to run an eval (implementation pending — see `runner_design.md`)

```bash
spine eval validate <dataset>                          # static check schema
spine eval run <dataset>                               # run against current baseline
spine eval regression <dataset> \                      # run candidate; diff vs baseline
  --candidate-prompt lib/role-prompts/engineer.md
spine eval ab <role> --candidate-prompt <path> \       # STORY-3.4.4
  --traffic-fraction 0.1
```

## How to interpret regressions

Regression = any case where `candidate_score < baseline_score - 0.05` (default
tolerance). Severity dictates response:

- **critical** regression → block the prompt edit; revert or fix.
- **high** regression → require operator sign-off; document why.
- **medium** / **low** → record as known degradation; bake into next baseline.

A regression on a `must_not` trait (e.g. scope sprawl, TBD placeholders)
ALWAYS blocks regardless of severity — those are correctness, not quality.

## Relationship to TRON's `verify/tests/golden_suite/`

TRON's golden_suite is **verify-internal unit tests** with mocked LLM responses —
catches "did the parser break." Spine's eval harness here is **cross-role
behavioral regression** with real LLM calls — catches "did the prompt get worse."

The two complement each other and should coexist. Spine's harness deliberately
lifts the *pattern* (per-role test directories, baseline diffs, CI workflow at
`.github/workflows/prompt-regression.yml`) but generalizes from verify-specific
ISO agents to any role in `lib/role-prompts/`.

## Cross-references

- `STORY-3.4.1` — Eval dataset format (this file + the two schemas)
- `STORY-3.4.2` — Eval runner design (`runner_design.md`)
- `STORY-3.4.3` — Regression mode (in `runner_design.md` §6)
- `STORY-3.4.4` — A/B mode (in `runner_design.md` §7)
- `STORY-3.4.5` — Dashboard view (per-role score history)
- `REQ-INIT-3 / EPIC-3.4` in `docs/BACKLOG.md`
- `docs/research/COMPETITIVE_LANDSCAPE.md §4` — gap survey
- `verify/tests/golden_suite/` — TRON's complementary pattern
