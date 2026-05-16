# V16 — Unified Cost Ledger

Implements `STORY-9.6.1` / `9.6.2` / `9.6.3` (EPIC-9.6); maps to PRD
REQ-INIT-9 FR-7; feeds EPIC-2.3 budget enforcement.

## Why the `subsystem` column

Pre-V16, cost rows had no way to answer "how much of project X's spend was
Plan vs Build vs Verify?". `subsystem` is the discriminator that unlocks
every rollup view here. Pre-migration rows default to `'unknown'`; new
dispatches MUST set it (contract enforced at `shared/cost/`).

## Architecture

```
  Plan ──┐
  Build ─┼──► spine_recording.costs ──► v_cost_per_project ──┐
  Verify ┤      (subsystem column)      v_cost_per_user      ├──► budget_rollup.sh
  Orch ──┤                              v_cost_per_org       │     (EPIC-2.3 enforcer)
  Shared ┘                              v_cost_per_pipeline  ┘
```

The orchestrator does NOT own the recorder (`shared/cost/` does); it mandates
that every directive reply carries `cost_usd` + `subsystem`.

## Example queries

```sql
-- v_cost_per_project: total Plan spend for project 42
SELECT phase, total_cost, event_count FROM spine_recording.v_cost_per_project
WHERE project_id = 42 AND subsystem = 'plan' ORDER BY total_cost DESC;

-- v_cost_per_user: top spenders this week
SELECT user_id, SUM(total_cost) AS week_spend
FROM spine_recording.v_cost_per_user
WHERE week_bucket = date_trunc('week', NOW())::date
GROUP BY user_id ORDER BY week_spend DESC LIMIT 10;

-- v_cost_per_org: org-wide Verify spend
SELECT org_id, SUM(total_cost) AS verify_spend
FROM spine_recording.v_cost_per_org WHERE subsystem = 'verify'
GROUP BY org_id ORDER BY verify_spend DESC;

-- v_cost_per_pipeline_version: did v1.4.0 raise per-project cost?
SELECT pipeline_version, avg_cost_per_event, project_count
FROM spine_recording.v_cost_per_pipeline_version
WHERE pipeline_version IN ('v1.3.0','v1.4.0') ORDER BY pipeline_version;
```

### TRON cross-LLM validation cost for project X this week

Cross-LLM validation runs in Verify under phase `cross_llm_validate`:

```sql
SELECT subsystem, phase, SUM(total_cost) AS week_spend
FROM   spine_recording.v_cost_per_project
WHERE  project_id = (SELECT id FROM spine_lifecycle.project WHERE name = 'project-X')
  AND  subsystem = 'verify' AND phase = 'cross_llm_validate'
  AND  last_event >= date_trunc('week', NOW())
GROUP  BY subsystem, phase;
```

## Budget enforcement (EPIC-2.3)

`shared/cost/budget_rollup.sh check-budget <project_id>` reads
`v_cost_per_project`, sums across (phase, subsystem), and compares to the
cap at `spine_lifecycle.project.metadata ->> 'budget_cap_usd'`. Exit codes:
`0` under budget, `2` over (orchestrator MUST block dispatch), `3` DB error
(fail-closed). `orchestrator/lib/router.sh` invokes it before each dispatch.

## Migration notes

- **Forward-only:** the `ALTER TABLE ADD COLUMN subsystem` has no rollback;
  drop views + column manually to revert.
- **Legacy `public.cost_row`:** V1 shipped `cost_row` in `public`. V16 does
  not relocate or backfill it; a separate one-time data migration (out of
  scope) should COPY surviving rows into `spine_recording.costs` with
  `subsystem='unknown'`. Until then, both tables coexist.
- **New writers:** daemons MUST set `subsystem` on insert. Writers that
  forget land as `'unknown'`, visible (by design) in every rollup view.
