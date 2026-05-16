# `gate.sh` — phase-gate engine (approve / reject / request-changes)

Implements `STORY-1.4.1` (engine), `STORY-1.4.4` (three actions),
`STORY-1.4.5` (request-changes routing). Wraps `approval.py` (HMAC) and
`transition.sh` (state machine); calls `router.sh` for MCP re-dispatch on
request-changes. Cross-refs: `STORY-1.4.1` … `STORY-1.4.7`, `STORY-9.3.1`
… `STORY-9.3.3`. PRD: `docs/PRD.md#req-init-1` FR-5, `#req-init-9` FR-3 / FR-4.

## Three actions

| Action            | `approval.decision` | State change |
|-------------------|---------------------|--------------|
| `approve`         | `approved`          | Phase advances to first `next:` if gate satisfied AND `auto_advance:true`. Otherwise sits, awaiting more approvers. |
| `reject`          | `rejected`          | Rolls back to declared `rollback_to:` via `transition_rollback`; if none, marks `status='paused'` + `metadata.blocked=true` (schema CHECK does not yet accept literal `blocked` — treat the metadata flag as truth). |
| `request-changes` | `request_changes`   | Rolls back to `*_in_progress`, then dispatches a fresh directive carrying reviewer notes to `role_lead` (override via `target_role` arg). |

Every action writes `spine_lifecycle.approval` + a `spine_audit.audit_event`
row (via `shared/audit/audit_record.py`; falls back to the `spine_audit.events`
stub used by `transition.sh::_audit_row`).

## Multi-approver gates (STORY-1.4.6 / STORY-9.3.3)

Declare per-phase in `phases.yaml`:

```yaml
- id: trd_approved
  gate: multi_approver
  required_approvers: [cto, compliance]
  min_approvers: 2          # default = len(required_approvers); else 1
  auto_advance: true        # default true
```

`_count_valid_approvals` runs each stored token through `approval.py verify`
and counts **distinct** approvers whose HMAC checks out. Gate is satisfied
when count `>= min_approvers`. Approvers outside `required_approvers` get
`approver_not_authorized` (exit 2).

## HMAC chain

This module never signs/verifies HMACs itself — all crypto goes through
`approval.py` (see `approval_README.md`):

- `approve` shells to `approval.py grant` (signs + INSERTs in one round-trip).
- `_count_valid_approvals` calls `approval.py verify` per row; tampered or
  expired tokens drop out silently — they can't deadlock the gate.
- `transition_execute` independently re-runs `transition_gate_check` on
  advance, so bypassing `gate.sh` doesn't bypass HMAC.

## Request-changes loop

```
artifact (PRD / TRD / build_artifact / verify_findings)
   │ reviewer clicks "request changes" with notes
   ▼
gate.sh request-changes <pid> <reviewer> "<notes>" [target_role]
   ├─ INSERT approval (decision=request_changes, notes=…)
   ├─ transition_rollback <pid> <*_in_progress>           ← STORY-9.2.1
   ├─ route_dispatch_to_subsystem <sub> <role> ...        ← STORY-9.4.1
   │     directive: "USER FEEDBACK on {artifact}: {notes}\n\nPlease revise…"
   │     parent_directive_id: latest dispatch in producing subsystem
   └─ audit_record.py (action=gate_request_changes)
   ▼
producing role works in *_in_progress → re-emits artifact → gate re-presents
```

## Rollback target resolution

1. First entry of `phases.yaml`'s `rollback_to:` list (matches
   `transition_rollback` semantics).
2. Else derived as `<prefix>_in_progress` from current phase id
   (`plan_approved` → `plan_in_progress`, `verify_approved` →
   `verify_in_progress`).

## Example — PRD gate end-to-end

```bash
gate.sh status 42
# {"phase":"plan_approved","gate":"user_approval","artifact":"roadmap",
#  "min_approvers":1,"valid_approvals":0,"satisfied":false}

gate.sh approve 42 khash "LGTM"
# {"approval_id":17,"gate_satisfied":true,"phase_advanced":true,"new_phase":"build_in_progress"}
```

Side effects: `approval` row (token + 7d expiry), `transition` row
(`plan_approved`→`build_in_progress`), `phase_history` close/open pair,
`project.current_phase` update, `audit_event` (`approval_granted`). Reject
and request-changes paths produce analogous rows. `gate.sh list-pending`
feeds the `STORY-1.4.2` approval-queue UI.
