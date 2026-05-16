# V17 — Portfolio queue + cross-project rollup views

Implements `STORY-9.5.2` (per-project resource limits → overflow queue) and
`STORY-9.5.3` (cross-project rollups) from EPIC-9.5; maps to PRD
REQ-INIT-9 §9.5 FR-6. Backs `orchestrator/lib/portfolio.sh`.

## What this migration adds

- One table — `spine_lifecycle.portfolio_queue` (overflow buffer for
  directives that exceeded a project's `max_parallel_directives`).
- Five read-only views — `v_projects_by_phase`, `v_blocked_projects`,
  `v_active_directives`, `v_portfolio_health`, `v_project_resource_usage`.
- Two partial indexes on the queue: one for per-project drains, one for
  the fleet-wide priority sweep.

## Why `portfolio_queue` lives in `spine_lifecycle`

The queue is fleet-control state — it belongs next to `project`,
`phase_history`, and `route_history`, all of which already live in
`spine_lifecycle`. Keeping it in the same schema lets the rollup views join
without crossing schema boundaries and lets `ON DELETE CASCADE` from
`project` reach it automatically.

## View rationale

| View | Why it exists |
|---|---|
| `v_projects_by_phase`      | Answers "how is the fleet distributed across the pipeline?" Cheap aggregate; replaces the V14 `portfolio_view` for richer pause/status awareness. |
| `v_blocked_projects`       | The first query a sleepy operator runs: what needs me? Single column with a humane `reason` string keeps the alert template trivial. |
| `v_active_directives`      | The fleet's equivalent of `ps`. `age_seconds` powers the stuck-directive watchdog. |
| `v_portfolio_health`       | One-row composite so the dashboard header is a single fast `SELECT * LIMIT 1`. |
| `v_project_resource_usage` | Per-project drill-down: limit vs in-flight vs queue depth, plus today's spend. Joins `spine_recording.costs` (V16). |

## Read-only by design

No view here is updatable; no triggers, no rules. The only writer to
`portfolio_queue` is `portfolio.sh` (which sets `dispatched_at` once on
drain). This preserves the audit story: every state change goes through
either `transition.sh`, `router.sh`, or `portfolio.sh`.

## Cross-references

- `STORY-9.5.2 / 9.5.3` — `docs/BACKLOG.md` EPIC-9.5
- PRD REQ-INIT-9 §9.5 FR-6 — portfolio management requirements
- `V14__spine_lifecycle_schema.sql` — base tables joined by these views
- `V16__unified_cost_ledger.sql` — `spine_recording.costs`, joined into
  the health + usage views
- `orchestrator/lib/portfolio.sh` — the single intended writer
- `orchestrator/lib/portfolio_README.md` — operator-facing docs
