# `orchestrator/state/` — Lifecycle state machine

Implements INIT-9 / EPIC-9.1. Schema lives in Postgres
(`spine_lifecycle` schema, multi-schema design per `ARCHITECTURE.md` §3
R-2); the canonical phase set lives in `phases.yaml`.

## How a project moves through phases

1. A user creates a project; the orchestrator inserts a `project` row, locks
   the resolved `sdlc-pipeline.yaml` into `pipeline_version`, and writes the
   opening `phase_history` row at `intake`.
2. As work completes the orchestrator (or an authorised actor) requests a
   transition; the engine validates the move, writes one `transition` row,
   closes the prior `phase_history` row, and opens a new one.
3. Gated phases additionally require an approved + non-expired row in
   `approval`; without it the engine writes the attempt as
   `decision = rejected_gate` and leaves the project in place.
4. Verify failures, build failures, and operator incidents transition
   *backwards* via the `rollback_to` list, capturing rationale in
   `transition.reason` and `transition.metadata`.
5. Routing dispatches are logged independently in `route_history`; the
   project's lifecycle in `phase_history` continues regardless of how many
   directives a phase fans out to.

## Pipeline-as-data

`phases.yaml` is the **default** pipeline. Org bundles override or extend it
per EPIC-1.7 by shipping their own `sdlc-pipeline.yaml` higher in the
manifest precedence chain. The transition engine reads the manifest that
each project is pinned to (`project.pipeline_version` +
`project.pipeline_manifest_path`) — not this file directly — so two
projects in the same database can run different phase graphs without
schema changes. Phases are stored as `TEXT` in every table so adding a
new phase is a zero-migration change.

## Transition validation

Given a request to move project `P` from `X` to `Y`:

1. Load the manifest pinned to `P`.
2. If `Y in phases[X].next` → forward move. If `Y in phases[X].rollback_to`
   → rollback; require `rationale` (per `rollback_policy.requires_rationale`).
   Otherwise reject with `rejected_invalid` and the
   `invalid_transition_error` template populated.
3. If `phases[Y].gate` is set, scan `spine_lifecycle.approval` for a row
   with `(project_id, phase=Y, decision='approved')`, verify the HMAC
   `token`, and check `expires_at > now()`. No match → `rejected_gate`.
4. If the move requires a capability the actor lacks (e.g., only an
   operator can leave `released`) → `rejected_capability`.
5. On `allowed`: append `transition`, close the open `phase_history` row
   (`exited_at`, `outcome`), insert a new one, update
   `project.current_phase` (denormalised cache).

All four outcomes are persisted — rejected transitions are first-class
audit rows.

## Gate enforcement

Gates are declared per phase in `phases.yaml` (e.g., `gate: user_approval`).
The engine never grants approvals itself; user-facing tooling
(MCP `approval_grant`, REST `POST /api/v2/approvals`, CLI
`spine project approve <phase>`) writes signed rows into
`spine_lifecycle.approval` with an HMAC `token`. Multi-approver gates
(STORY-9.3.3) are supported by storing multiple `approved` rows for the
same `(project_id, phase)` — the engine treats the gate as satisfied only
when the count meets `gate_policy.<gate>.min_approvers` (default 1).

## Rollback

A rollback transition is identical mechanically to a forward one but
requires `Y in phases[X].rollback_to`, a non-empty `reason`, and an
`actor` recorded in `transition.actor`. The `phase_history.outcome`
of the prior row is set to `rolled_back` so audit consumers can
distinguish abandoned phases from successfully advanced ones.

## Where state lives

Single Postgres instance, multi-schema:

- `spine_lifecycle` — this module (projects, phase history, transitions,
  approvals, route dispatches).
- `public` / `spine_recording` — existing recording layer (workers, costs,
  assignments).
- `spine_audit`, `spine_kg`, `spine_verify_*` — future modules per
  `ARCHITECTURE.md` §3.

Cross-schema joins (e.g., `route_history.role` ↔ `public.role.role_id`)
are expected and supported.

## Example query

```sql
-- Show every project currently waiting in verify.
SELECT p.project_uuid,
       p.name,
       p.owner_user,
       ph.entered_at AS verify_started_at,
       NOW() - ph.entered_at AS in_verify_for
FROM   spine_lifecycle.project       AS p
JOIN   spine_lifecycle.phase_history AS ph
  ON   ph.project_id = p.id
  AND  ph.exited_at IS NULL
WHERE  p.status = 'active'
  AND  p.current_phase = 'verify_in_progress'
ORDER  BY ph.entered_at;
```

## See also

- `db/flyway/sql/V3__spine_lifecycle_schema.sql` — the migration (note the
  V-number collision flag inside the file header).
- `docs/BACKLOG.md` — INIT-9 (EPIC-9.1 through EPIC-9.9).
- `docs/ARCHITECTURE.md` §2, §3, §4.
- `orchestrator/README.md` — module-level scope and boundary.
