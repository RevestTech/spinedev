# V18 -- Confidence calibration corpus + fitted models

Implements `STORY-3.6.1` through `STORY-3.6.4` (`docs/BACKLOG.md` EPIC-3.6).
Lifts TRON's Layer-6 calibration pattern out of
`verify/tron/services/calibration_engine.py` into a Spine-wide schema that
Plan, Build, and Verify roles can all consume.

## Why a dedicated schema

Raw LLM confidence has no honesty guarantee: self-reported `0.9` is not a
90% true-positive rate. The fix is the one TRON ships: pair every score with
an observed outcome, fit a mapping, serve calibrated values back.
Granularity is `(role, output_type)` -- architect risk bias is unrelated to
qa severity bias.

## Schema overview

| Table | Purpose |
|---|---|
| `prediction` | Raw LLM score in `[0,1]` per (role, output_type). One row per LLM-only output we want to calibrate. |
| `outcome` | Observed ground truth in `[0,1]` paired to a prediction. Sources: `user_approval`, `verify_pass`, `prod_incident`, `time_elapsed`, `manual_review`. |
| `calibration_model` | Fitted mapping per (role, output_type). `model_type` in `{platt, banded, identity}`. Active row = `valid_to IS NULL`. |

## Active-model invariant

`uq_cm_one_active_per_pair` (partial unique index) enforces at most one row
per `(role, output_type)` with `valid_to IS NULL`. Refit is one transaction:
`UPDATE` old active row's `valid_to = NOW()`, `INSERT` the new fit. The
dashboard never sees zero or two active models.

## Thresholds (algorithm in `shared/calibration/calibrator.py`)

| Labeled samples | Active model | Trust band |
|---|---|---|
| `< 50` | `identity` (pass-through) | `untrusted` |
| `50 .. 499` | `banded` (per-decile TP rate) | `medium/low` per band |
| `>= 500` | `platt` (sigmoid `A*x+B`) | `high/medium-high` per band |

## Views

- `v_calibration_status` -- per (role, output_type): labeled count, active
  model type + age, calibration band the corpus has unlocked.
- `v_pending_outcomes` -- predictions still missing an outcome row; backs
  the manual-labeler queue and feeds automated collectors.

## Example queries

```sql
SELECT * FROM spine_calibration.v_calibration_status;
SELECT * FROM spine_calibration.v_pending_outcomes
WHERE  role = 'architect' AND output_type = 'risk_score';
SELECT model_type, fit_params, n_samples FROM spine_calibration.calibration_model
WHERE  role = 'qa' AND output_type = 'severity' AND valid_to IS NULL;
```

## Cross-refs

- `shared/calibration/{calibrator,outcome_corpus,apply}.py` -- runtime.
- `verify/tron/services/calibration_engine.py` -- original L6 pattern.
- `docs/BACKLOG.md` INIT-3 EPIC-3.6 stories.
