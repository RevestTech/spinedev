# rollback.sh — Project-level rollback orchestration

Policy + side-effects layer that turns a manifest-sanctioned rollback edge
into a durable state change with full audit. Implements `STORY-9.2.3`
(rollback support with rationale, capability, downstream invalidation)
per `docs/PRD.md` REQ-INIT-9 FR-3 + FR-9.

## Why this exists

`orchestrator/lib/transition.sh` already has `transition_rollback` — that
is the **writer**. It does not, however, address the second-order effects
of moving a project backwards through its lifecycle:

- An approval granted for a later phase becomes meaningless once the
  project is no longer pursuing it. It must not unlock a future advance.
- A directive dispatched to Build / Verify while the project was in a
  later phase may still be in flight. The orchestrator must mark it so
  late-arriving replies don't mutate state that has already moved on.
- The operator needs ONE consolidated audit row that says "rollback to
  X invalidated N approvals + cancelled M directives" — not three.

This file owns that policy; the writer stays minimal.

## The flow

```
   rollback.sh rollback <pid> <target> --actor A --rationale R
        │
        ├─ 1. assert rationale length      (rollback_policy.requires_rationale)
        ├─ 2. capability_checker           (actor needs can_modify_sdlc_pipeline)
        ├─ 3. _rollback_target_allowed     (target ∈ phases[current].rollback_to[])
        ├─ 4. _target_entry_ts             (when did the project last enter target?)
        ├─ 5. transition.sh transition_rollback   ← phase_history + project + transition rows
        ├─ 6. UPDATE approval SET expires_at = NOW() WHERE granted_at >= ts
        ├─ 7. UPDATE route_history SET metadata ||= {cancelled_by_rollback:true}
        │                              WHERE completed_at IS NULL AND dispatched_at >= ts
        └─ 8. _audit_row("project_rolled_back", …)
```

## Edge cases handled

- **Rationale required.** `rollback_policy.requires_rationale: true` in
  `phases.yaml` says rationale is non-optional; we enforce a minimum
  length (`SPINE_ROLLBACK_RATIONALE_MIN`, default 8).
- **Invalid edges.** Only direct `phases[current].rollback_to[]` targets
  are accepted — no auto-chain. Rejected with `rejected_invalid` + the
  allowed set in `extra.allowed_rollback` so the UI can render guidance.
- **Schema CHECK constraint.** `route_history_outcome_chk` permits only
  `completed | failed | timeout | retry`. We can't set
  `outcome='cancelled'`, so we stamp `metadata.cancelled_by_rollback=true`
  with `rollback_to_phase` + `rollback_at` and leave `outcome` NULL.
  Reply-handlers (`router.sh route_record_reply`) MUST check the marker
  before mutating state on a late reply.
- **Side-effects partial failure.** The phase rows commit first
  (durability). The cleanup TX is best-effort and logged on failure — a
  rollback is never half-applied.
- **Capability infra missing (skeleton mode).** `_actor_capability_check`
  soft-passes when `capability_checker.py` is unreachable so dev installs
  don't lock themselves out. Production installs always have it.

## Edge cases NOT handled (future work)

- **Multi-hop rollback.** Rolling back from `acceptance` all the way to
  `plan_in_progress` requires the user to chain calls. A future helper
  could compute the shortest path through `rollback_to[]` edges.
- **Cost reversal.** Cost rows already recorded for cancelled directives
  are left intact (cost is sunk; audit value > reversal value). A future
  story could stamp them with `metadata.rollback_uuid` for downstream
  reporting.
- **Sub-directive cascade.** If a cancelled directive itself spawned
  sub-directives, those are not transitively marked. Single-level
  cancellation matches current router semantics.

## CLI

```bash
rollback.sh preview  7 plan_approved
# → {"ok":true,"preview":true,"project_id":7,"from":"build_in_progress",
#    "to":"plan_approved","would_invalidate_approvals":0,
#    "would_cancel_directives":1}

rollback.sh rollback 7 plan_approved \
  --actor user:alice \
  --rationale "scope inflated mid-sprint; replan with new constraints"
# → {"ok":true,"rollback":true,"project_id":7,"from":"build_in_progress",
#    "to":"plan_approved","actor":"user:alice",
#    "invalidated_approvals":0,"cancelled_directives":1}

rollback.sh history 7
# → {"ok":true,"project_id":7,"rollbacks":[{"at":"…","from_phase":"…",…}]}
```

Exit codes: `0` ok, `2` invalid_input / project_not_found, `4`
rejected_invalid, `6` db / transition failure, `7` rationale_required,
`8` capability_denied, `64` unknown subcommand.

## Cross-refs

- `orchestrator/lib/transition.sh` — `transition_rollback` (low-level writer)
- `orchestrator/state/phases.yaml` — `rollback_to[]` + `rollback_policy`
- `plan/pipeline/capability_checker.py` — `require_capability`
- `db/flyway/sql/V14__spine_lifecycle_schema.sql` — `transition.metadata`,
  `approval.expires_at`, `route_history.metadata`,
  `route_history_outcome_chk`
- `docs/PRD.md` REQ-INIT-9 FR-3 (transition engine) + FR-9 (re-routing)
- `docs/BACKLOG.md` EPIC-9.2 (STORY-9.2.3)
