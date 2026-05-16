# build_failure_router.sh — Build-fail → Plan re-route

Policy layer that turns an engineer's "I can't complete this — scope is
unclear" signal into a fresh Planner directive, links the loop via
`parent_directive_id`, and enforces the build→plan retry budget.
Implements `STORY-9.8.3` per `docs/PRD.md` REQ-INIT-9 FR-9 ("Build
failure → Plan re-route 'scope unclear' feedback").

This is the **mirror** of `remediation.sh` (verify→build) for the other
direction in the failure-handling diagram.

## The build-fail loop

```
   Plan ─► Build  ────►  (artifact emitted)  ─►  build_complete  ─►  verify
                │
                ▼ (engineer surfaces blocker)
     orchestrator main loop
                │
                ▼
     build_failure_router.sh route <failed_did> <reason> [feedback]
        │
        ├─ _reason_valid          (closed enum: scope_unclear | …)
        ├─ lookup parent          (route_history latest row for failed_did)
        ├─ bfr_check_retry        (COUNT build->plan transitions vs cap)
        ├─ _compose_replan_directive   (header + per-reason guidance + feedback)
        ├─ router.sh route_dispatch_to_subsystem plan   (MCP -> plan_dispatch)
        └─ transition.sh transition_execute            (build_in_progress -> plan_in_progress)
                │
                ▼
   Plan (re-plan N)  ─►  Build  ─►  ...  (bounded by build_plan_loop_max)
```

## Valid reasons (closed enum)

| Reason                     | When the engineer raises it                                  |
|----------------------------|--------------------------------------------------------------|
| `scope_unclear`            | Story is ambiguous; acceptance criteria can't be met deterministically. |
| `requirements_incomplete`  | PRD / TRD missing a field needed to implement.               |
| `blocked_by_dependency`    | Another story / external system must land first.             |
| `needs_decision`           | A trade-off requires user input before code can proceed.     |

Anything else is rejected (`invalid_reason`) so this script can't become
a generic back-routing escape hatch.

## Retry budget

No counter column — `SELECT COUNT(*) FROM spine_lifecycle.transition
 WHERE from_phase = 'build_in_progress' AND to_phase = 'plan_in_progress'`.
Compared to `transitions_metadata.retry_policy.build_plan_loop_max` in
`phases.yaml` (defaults to `3` via `BFR_DEFAULT_LOOP_MAX` if the key is
absent — this is a NEW key versus `verify_build_loop_max`).

On exhaustion, `bfr_route` calls `bfr_surface_to_user`, which sets
`project.status='paused'` + `metadata.blocker='excessive_replanning'`.

## Edge cases handled

- **Schema-compliant status update.** `project_status_chk` allows only
  `active | paused | terminated | completed`; we use `paused` plus a
  `metadata.blocker` marker rather than inventing a status value.
- **Set-e + non-zero rc.** Retry-budget check is captured into `rc` (not
  `if !`) so the exact exit code propagates — matches remediation.sh.
- **Latest dispatch wins.** If a directive was re-dispatched we take the
  most recent `route_history` row by `dispatched_at DESC LIMIT 1`.

## Edge cases NOT handled (future work)

- **Replan history surfacing.** The dashboard can render `route_history`
  filtered by `metadata->>'parent_directive_id'` chains; no helper view yet.
- **Cost annotation of the re-plan.** Cost of the original Build attempt
  is left intact; a follow-on story should mark it with `replan_uuid`.
- **Auto-pick planner role.** We dispatch to a fixed role
  (`SPINE_BFR_DEFAULT_PLANNER_ROLE`, default `planner`). A future story
  could pick the role from phases.yaml `role_lead` for `plan_in_progress`.

## CLI

```bash
build_failure_router.sh route d-103 scope_unclear \
  "Story 'export to CSV' has no acceptance criteria; quoting + encoding undefined"
# → {"ok":true,"project_id":12,"new_directive_id":"d-118",
#    "parent_directive_id":"d-103","reason":"scope_unclear",
#    "role":"engineer-backend","prior_subsystem":"build","target":"plan"}

build_failure_router.sh check-retry 12
# → {"ok":true,"project_id":12,"loops":1,"cap":3,"remaining":2}

build_failure_router.sh surface 12 "excessive replanning"
# → {"ok":true,"project_id":12,"status":"paused","blocker":"excessive_replanning"}
```

Exit codes: `0` ok, `2` invalid_input / invalid_reason, `3` retry budget
exhausted, `4` router/MCP failure, `5` transition failure, `6` db error,
`64` unknown subcommand.

## Cross-refs

- `orchestrator/lib/remediation.sh` — companion for verify→build loop
- `orchestrator/lib/router.sh` — `route_dispatch_to_subsystem` (MCP)
- `orchestrator/lib/transition.sh` — `transition_execute` (state writes)
- `orchestrator/state/phases.yaml` — `retry_policy.build_plan_loop_max`
- `db/flyway/sql/V14__spine_lifecycle_schema.sql` — route_history, transition, project
- `docs/PRD.md#req-init-9` FR-9 ("Build failure → Plan re-route")
- `docs/BACKLOG.md` EPIC-9.8 (STORY-9.8.3)
