# portfolio.sh — orchestrator portfolio management

Implements `STORY-9.5.1` (multiple projects in flight), `STORY-9.5.2` (per-
project resource limits + queue) and `STORY-9.5.3` (cross-project rollups)
from `docs/BACKLOG.md` EPIC-9.5; satisfies `docs/PRD.md` REQ-INIT-9 §9.5
FR-6. Depends on `V14__spine_lifecycle_schema.sql` (project, route_history)
and `V17__portfolio_views.sql` (portfolio_queue + the five views).

## Why portfolio management matters

Without a coordinator one chatty project (say, a long Verify→Build remediation
loop) can fire directives back-to-back and starve every other project on the
host. `transition.sh` and `router.sh` are correct **per-project** but blind
to fleet state. `portfolio.sh` is the fleet-aware checkpoint that decides
whether `router.sh` is allowed to actually dispatch the next directive.

The split mirrors `gate.sh`: portfolio decides yes/no/queued, router moves
bytes over MCP (PRD FR-5).

## Resource-limit model

Two knobs, declared in priority order:

1. `project.metadata->>'max_parallel_directives'` (per-project override,
   editable via `portfolio.sh set-limit`).
2. `$SPINE_DEFAULT_MAX_PARALLEL` env var (set per-host / per-org-bundle).
3. Constant `3` (last resort).

`max_workers` is exposed symmetrically for downstream subsystems (daemons
that read project metadata to size their pools); portfolio.sh itself only
enforces `max_parallel_directives` at dispatch time.

`can-dispatch` counts open rows in `route_history` (where
`dispatched_at IS NOT NULL AND completed_at IS NULL`) and compares to the
limit. Exit codes: `0` capacity, `2` at limit (caller should queue), `3`
project paused / `metadata.blocked=true` (do NOT queue), `4` DB error.

## The queue

Overflow lands in `spine_lifecycle.portfolio_queue` with a JSON envelope
that preserves the full directive so the eventual drain is a verbatim
hand-off to `router.sh`. Two events drain it:

- **Event-driven:** `router.sh reply` (capacity-freeing) SHOULD call
  `portfolio.sh drain <project_id>` so the slot is reused immediately.
- **Timer-driven (cron-safe):** a periodic `portfolio.sh drain` (no
  project_id) sweeps the whole fleet — defence in depth if the event hook
  is missed.

Drain order is `ORDER BY priority ASC, queued_at ASC` (lower integer wins,
FIFO on ties). Cap of 100 per drain call so a backlog can't monopolise the
worker.

## The five SQL views (V17)

| View | Purpose | Primary consumer |
|---|---|---|
| `v_projects_by_phase`       | Count of active/paused projects per phase. | Dashboard heatmap. |
| `v_blocked_projects`        | Paused or `metadata.blocked=true`, with reason. | "What's stuck" card, alerting. |
| `v_active_directives`       | Every in-flight directive across the fleet + age. | Dispatch monitor, watchdog. |
| `v_portfolio_health`        | Single-row fleet snapshot (counts + spend today/month). | Dashboard header, `/healthz`. |
| `v_project_resource_usage`  | Per-project: limit, in-flight, queue depth, cost today. | `spine portfolio status` CLI, per-project tile. |

## Example: what is everything blocked on?

```sql
SELECT project_id, name, current_phase, reason, updated_at
FROM   spine_lifecycle.v_blocked_projects
ORDER  BY updated_at DESC;
```

## Cross-references

- `STORY-9.5.1 / 9.5.2 / 9.5.3` — `docs/BACKLOG.md` EPIC-9.5
- `docs/PRD.md` REQ-INIT-9 §9.5 FR-6
- `db/flyway/sql/V14__spine_lifecycle_schema.sql` — base schema (project,
  route_history)
- `db/flyway/sql/V17__portfolio_views.sql` — queue table + views
- `db/flyway/sql/V16__unified_cost_ledger.sql` — `spine_recording.costs`,
  joined into `v_portfolio_health` + `v_project_resource_usage`
- `orchestrator/lib/router.sh` — MCP dispatcher invoked by `drain`
- `orchestrator/lib/transition.sh` — per-project state machine
- EPIC-2.3 budget enforcement reads the same unified cost ledger; portfolio
  capacity is the second guard (parallelism cap), budget enforcement is the
  first (spend cap).
