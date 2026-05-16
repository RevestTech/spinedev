# router.sh — Orchestrator Routing Layer

Bash dispatch chokepoint that turns orchestrator decisions into MCP calls
to Plan / Build / Verify. Implements `STORY-9.4.1` (MCP dispatch),
`STORY-9.4.2` (locked pipeline version on every dispatch), `STORY-9.4.3`
(reply recording), `STORY-9.8.1` (verify-fail auto-remediation).

## The MCP-only contract (hard rule)

PRD `REQ-INIT-9 FR-5`: subsystems are addressed **exclusively via MCP**.
This module is the single dispatch chokepoint. It enforces:

- **No direct imports** across subsystem trees (`plan/`, `build/`, `verify/`).
- **No cross-subsystem shell calls**.
- **Every dispatch** goes through `_mcp_call` (stdio `mcp` CLI, or HTTP POST
  to `shared/mcp/server.py`, STORY-2.2.1).

CI boundary check (`tools/check-module-boundaries.sh`) catches violations.

## Functions

| Function | When called |
|---|---|
| `route_dispatch_to_subsystem` | Main loop has decided a phase needs work — dispatches to plan/build/verify, writes `route_history`, calls audit hook. |
| `route_decide_subsystem` | Main loop needs to know which subsystem owns a phase — reads `phases.yaml`. |
| `route_record_reply` | MCP listener receives `*_completed` — sets `completed_at` + `outcome` on the matching row. |
| `route_dispatch_remediation` | Verify reports failing findings — composes remediation directive, links via `parent_directive_id`, redispatches (usually to Build). |
| `route_locked_pipeline_version` | Internal — pre-flight lookup before every dispatch. Missing => hard error. |

## Dispatch flow

```
user: spine project new --type=web-app
      │
      ▼
orchestrator main loop  ──►  router.sh decide <phase>  ──►  "build"
                             router.sh dispatch build <role> <directive> <pid>
                                   │
                                   ├── route_locked_pipeline_version(pid)   ← HARD ERROR if absent
                                   ├── _mcp_call(build_dispatch, payload+pipeline_version)
                                   │         ▼
                                   │   shared/mcp/server.py → build subsystem → {"directive_id":...}
                                   ├── INSERT spine_lifecycle.route_history (completed_at=NULL)
                                   └── _audit_dispatch (shared/audit CLI or psql stub)
```

## Reply flow

```
build finishes → emits MCP `build_completed {directive_id, status, cost?}`
              → shared/mcp/server.py routes to orchestrator listener
              → router.sh reply <directive_id> <status> [error]
              → UPDATE spine_lifecycle.route_history SET completed_at, outcome
```

## Locked pipeline version (`STORY-9.4.2` / `EPIC-1.7.5`)

Every payload carries `pipeline_version`. The receiving subsystem MUST
refuse the dispatch if its local manifest digest doesn't match — protects
in-flight projects from mid-flight pipeline edits.
`route_locked_pipeline_version` is non-optional: missing project row or
missing version is a hard error, **not** a warning. There is no
"best effort" dispatch.

## Failure / remediation flow

Verify returns failing findings →
`router.sh remediate <failed_did> <findings_ref> build`. A new
`build_dispatch` row appears in `route_history` with
`metadata.parent_directive_id = failed_did`. The loop is bounded by
`transitions_metadata.retry_policy.verify_build_loop_max` in `phases.yaml`
(default 5). Exceeding it transitions the project to `status='blocked'` —
handled by the main loop reading `route_history`, **not** by router.sh.

## Local test recipe

1. `make migrate` to load `V14__spine_lifecycle_schema.sql`.
2. Postgres on `localhost:33000` (default `SPINE_DB_URL`).
3. Seed a project row with a locked `pipeline_version`.
4. Stub `shared/mcp/server.py` to echo `{"directive_id":"d-001","accepted":true}`.
5. `orchestrator/lib/router.sh dispatch build engineer "hello" 1`
6. Check: `SELECT * FROM spine_lifecycle.route_history;`
7. `router.sh reply d-001 completed` → row gains `completed_at` + outcome.

## Stubs / TODOs

- `_audit_dispatch` prefers `shared/audit/audit_record.py` (STORY-3.1) and
  falls back to a best-effort `spine_audit.events` insert. Drop the
  fallback once STORY-3.1 lands.
- `_mcp_call` assumes `shared/mcp/server.py` (STORY-2.2.1) is reachable.
  Until then a one-line FastAPI/HTTP stub serves the CLI happy-path.
