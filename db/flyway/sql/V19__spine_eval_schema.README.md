# V19 — Spine eval harness storage

Implements `STORY-3.4.2` (eval runner), `STORY-3.4.3` (regression mode), and
`STORY-3.4.4` (A/B mode) per `docs/BACKLOG.md`. Storage shape sketched in
`shared/eval/runner_design.md §8`; this migration freezes it.

## Why a dedicated schema (not `spine_audit`)

1. **Access pattern.** Audit is "everything for project 42." Eval is
   "score-history for `engineer-core-v1`." Joining audit rows by tag every
   render is the wrong index shape.
2. **Retention.** Audit is append-only forever; eval rows are rebaseable —
   operators delete stale runs after a model sunset. Mixing both would
   break the audit append-only invariant.

`spine_audit.audit_event` still records the *fact* that an eval ran
(`action = eval_run_started`); the scored detail lives here.

## Tables

| Table | Purpose |
|---|---|
| `dataset` | Registry of dataset YAMLs; loader upserts on first run. |
| `eval_run` | One row per `spine eval run|regression|ab|smoke`; UPDATEd on completion. |
| `case_result` | Per-case score; per-check breakdown in `check_results` JSONB; CASCADEs. |

`baseline_*` on `eval_run` are populated only for `mode in (regression, ab)`.

## Indexes

- `(dataset_id, started_at DESC)` — "latest run" tile.
- `(mode, started_at DESC)` — "did regression fail in last 24h" widget.
- `(eval_run_id, case_id)` on `case_result` — per-run detail view.
- GIN on `check_results jsonb_path_ops` — "most-failed checks this week"
  without a row-by-row Python pass.

## Why no append-only enforcement

Eval results are operator-rerunnable — you *want* to delete a flaky run
and re-score. Tables are mutable; the immutable record of "the eval
happened" stays in `spine_audit.audit_event`.

## Example queries

```sql
-- Latest run
SELECT * FROM spine_eval.eval_run
WHERE dataset_id = 'engineer-core-v1'
ORDER BY started_at DESC LIMIT 1;

-- Most-failed checks (uses GIN)
SELECT chk->>'check_id' AS check_id, COUNT(*) AS failures
FROM spine_eval.case_result, jsonb_array_elements(check_results) chk
WHERE chk @> '{"passed": false}'::jsonb
GROUP BY 1 ORDER BY 2 DESC LIMIT 10;
```
