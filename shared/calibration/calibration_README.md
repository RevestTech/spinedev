# Spine confidence calibration runtime

Implements `STORY-3.6.1` through `STORY-3.6.4` (`docs/BACKLOG.md` EPIC-3.6).
Lifts TRON's Layer-6 calibration pattern
(`verify/tron/services/calibration_engine.py`) into `shared/calibration/`
so Plan, Build, and Verify all share one honesty layer.

## Why calibration

Raw LLM confidence is famously miscalibrated -- a self-reported `0.9` is
not, in practice, a 90% true-positive rate. Architect risk scores,
decomposer story estimates, qa severity, auditor finding confidence all
suffer the same systemic bias. The fix is the one TRON already proved:
pair every score with an observed outcome, fit a mapping, serve calibrated
values back. Granularity is `(role, output_type)` because each pair has its
own bias profile.

## Three modes (auto-selected on every refit)

| Labeled samples | Active model | What it does | Trust band cap |
|---|---|---|---|
| `< 50`        | `identity` | Pass-through; raw == calibrated. | `untrusted` |
| `50 .. 499`   | `banded`   | Per-decile mean-outcome table; no parametric assumption. | `medium-high` |
| `>= 500`      | `platt`    | Sigmoid `A*x + B` fit (numpy or stdlib GD). | `high` |

Implemented in `calibrator.py`: `fit_platt`, `fit_banded`, `calibrate`,
`refit_if_due`. numpy is lazy-imported -- stdlib-only environments fall
back to a pure-Python batch gradient descent on log-loss; same fitted
parameters, slower wall clock.

## How outcomes get labeled

Five accepted `outcome_source` values (CHECK-constrained in V18):

| Source | When | Producer |
|---|---|---|
| `user_approval` | Operator clicks approve/reject on a finding or plan. | Dashboard / `spine approve`. |
| `verify_pass`   | Verify subsystem confirms or refutes the prediction. | Verify orchestrator. |
| `prod_incident` | Post-deploy incident retroactively validates risk. | Postmortem job. |
| `time_elapsed`  | Story estimate vs measured hours; rollback didn't happen. | Nightly outcome collector. |
| `manual_review` | Calibration curator labels from the pending queue. | `spine_calibration.v_pending_outcomes`. |

## Re-fit cadence

`refit_if_due(role, output_type)` is idempotent and cheap -- safe to run
nightly (or after every batch of N new outcomes) on a cron. Each call:

1. Pulls the labeled corpus for the pair (subprocess psql).
2. Picks identity / banded / Platt by sample count.
3. Inside ONE transaction: `UPDATE` the old active row's `valid_to = NOW()`,
   `INSERT` the new fitted row. The partial unique index
   `uq_cm_one_active_per_pair` guarantees exactly one active model per pair.

## Per-role wrappers (`apply.py`)

`shared/calibration/apply.py` ships the four EPIC-3.6 output families:

| Function | role / output_type | Raw conversion |
|---|---|---|
| `calibrate_architect_risk(s)` | `architect / risk_score` | identity (already 0..1) |
| `calibrate_decomposer_estimate(h)` | `decomposer / story_estimate` | `log(h+1)/log(160)` capped at 1 |
| `calibrate_qa_severity(lbl)` | `qa / severity` | ordinal map (critical=1.0 ... info=0.05) |
| `calibrate_auditor_finding(c)` | `auditor / finding_confidence` | identity (already 0..1) |

## Three-line integration from a role daemon

```python
from shared.calibration import record_prediction, record_outcome
from shared.calibration.apply import calibrate_architect_risk

pid = record_prediction("architect", "risk_score", raw_risk,
                        project_id=project_id, subject_id=story_uuid)
shown = calibrate_architect_risk(raw_risk).calibrated_value   # show this
# ... later, when verify or the user gives us truth ...
record_outcome(pid, observed_value=1.0, source="user_approval")
```

## Cross-refs

- `STORY-3.6.1` -- TRON L6 lifted into `shared/calibration/` (this module).
- `STORY-3.6.2` -- labeled outcome corpus (`outcome_corpus.py` + V18 tables).
- `STORY-3.6.3` -- Platt when N>=500 else banded (`calibrator.refit_if_due`).
- `STORY-3.6.4` -- per-role wrappers (`apply.py`).
- `STORY-3.6.5` -- dashboard surface (open; consumes `band` + `model_used`).
- V18 schema: `db/flyway/sql/V18__calibration_corpus.sql`.
- TRON original: `verify/tron/services/calibration_engine.py`.
