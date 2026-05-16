# remediation.sh — Verify-Fail Auto-Remediation

Policy layer that turns a failing `VerifyFindings` into a fresh Build
directive, links the loop via `parent_directive_id`, and enforces the
max-retry budget. Implements `STORY-9.8.1` (auto-remediation) and
`STORY-9.8.2` (max-retry policy) per `docs/PRD.md` REQ-INIT-9 FR-9 and
REQ-INIT-8 FR-4.

## The verify-fail loop

```
   Build ─► Verify  ────►  (findings green)  ─►  verify_approved  ─►  acceptance
                │
                ▼ (findings red)
     orchestrator main loop
                │
                ▼
     remediation.sh dispatch <failed_did> <findings_json>
        │
        ├─ compose_directive   (read parent from route_history; summarize findings)
        ├─ check_retry_budget  (COUNT verify->build transitions; compare to cap)
        ├─ router.sh route_dispatch_remediation  (MCP -> build_dispatch)
        └─ transition.sh transition_execute      (verify_in_progress -> build_in_progress)
                │
                ▼
   Build (retry N)  ─►  Verify  ─►  ...   (loop bounded by verify_build_loop_max)
```

## Retry counter lives in the `transition` table

There is **no counter column**. The orchestrator queries:

```sql
SELECT COUNT(*) FROM spine_lifecycle.transition
 WHERE project_id = $1
   AND from_phase = 'verify_in_progress'
   AND to_phase   = 'build_in_progress';
```

…and compares against `transitions_metadata.retry_policy.verify_build_loop_max`
in `orchestrator/state/phases.yaml` (default `5`). The transition table is
the source of truth so the budget survives orchestrator crashes / replays —
no in-memory counter, no out-of-band cache.

## What triggers `surface_to_user`

When `check_retry_budget` returns exit code `3` (`retry_budget_exceeded`).
`dispatch` calls `surface_to_user` automatically. It performs a direct
`UPDATE spine_lifecycle.project SET status='paused'` (lifecycle envelope,
not a phase) and stamps `metadata.blocked = true` with a reason string so
the dashboard / CLI can render the blocker. Per `project_status_chk`
(V14 schema) the allowed statuses are `active | paused | terminated |
completed`; we use `paused` + a `blocked=true` marker rather than
inventing a new status value.

## Findings JSON shape (input)

Matches `VerifyFindings.findings[]` from REQ-INIT-8 FR-4:

```json
[
  { "severity":"critical", "file":"src/auth.py", "line":42,
    "rule":"SEC-API-KEY-001",
    "message":"Hardcoded API key detected",
    "fix_hint":"Move to ~/.spine/secrets/ and read via env var" },
  { "severity":"high", "file":"src/db.py", "line":120,
    "rule":"SEC-SQLI-003",
    "message":"User input concatenated into SQL",
    "fix_hint":"Use parameterized query" }
]
```

The summarizer sorts by severity (`critical > high > medium > low`),
deduplicates by `(file, rule)`, and truncates at ~1800 chars with a
`(+N more finding(s) omitted)` tail. Requires `jq`; falls back to a raw
awk truncate if absent.

## End-to-end example — SecurityISO hardcoded API key

```bash
# Verify returns failing findings; orchestrator gets failed_directive_id=d-042
remediation.sh dispatch d-042 '[
  {"severity":"critical","file":"src/auth.py","line":42,
   "rule":"SEC-API-KEY-001","message":"Hardcoded API key",
   "fix_hint":"Move to ~/.spine/secrets/"}
]'

# stdout:
# {"ok":true,"project_id":7,"new_directive_id":"d-051",
#  "parent_directive_id":"d-042","role":"engineer","target":"build"}

# route_history now contains:
#   d-042  build  engineer  outcome=failed
#   d-051  build  engineer  metadata.parent_directive_id=d-042
# transition table now contains:
#   verify_in_progress -> build_in_progress  reason='verify-fail-remediation'
```

The composed directive Build receives starts with
`REMEDIATE (verify-fail) parent=d-042 prior_subsystem=verify` followed by
the prioritized finding list — so Engineer-Backend can scope the fix
without consulting the orchestrator out-of-band.

## Cross-refs

- `orchestrator/lib/router.sh` — `route_dispatch_remediation` (MCP dispatch)
- `orchestrator/lib/transition.sh` — `transition_execute` (state writes)
- `orchestrator/state/phases.yaml` — `transitions_metadata.retry_policy.verify_build_loop_max`
- `db/flyway/sql/V14__spine_lifecycle_schema.sql` — `route_history`, `transition`, `project`
- `docs/PRD.md#req-init-9` FR-9, `#req-init-8` FR-4
- `docs/BACKLOG.md` EPIC-9.8 (STORY-9.8.1, STORY-9.8.2)
