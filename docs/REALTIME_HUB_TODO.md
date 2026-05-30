# Real-time Hub — master TODO

> **Single source of truth for the SpineHub real-time alignment work.**
> Started 2026-05-30 after the user flagged the divergence between
> what `spinedev` ships and what `spinehub` shows. We work this list
> top-to-bottom; no side-quests, no scope creep.
>
> Two paths: **Path B (pragmatic real-time)** first — one unified
> SSE + one Live activity panel that brings every backend channel
> visible immediately. **Path A (deep dedicated surfaces)** after,
> piece-by-piece, only for surfaces where bespoke rendering earns
> its keep.

## Status legend

- `[ ]` pending
- `[~]` in progress
- `[x]` done
- `[-]` deferred / dropped (explain in note)

---

## T0 — Pre-work: commit prior-session SPA refactor

The 13 modified + 5 new SPA files in the working tree have been
sitting uncommitted since the IDE crash that started this session.
E1 (waste audit, finding #14) confirmed they are clean. Commit them
first so every subsequent SPA change applies to a coherent
front-end.

**Owns:** `shared/ui/spa/package.json`, the 7 modified `.svelte` /
`.ts` files, the 5 new `Pipeline*` / `ProjectWorkspace*` components,
new `uiFrameScheduler.ts`, `projectWorkspaceTypes.ts`,
`projectDecisionsStore.ts`, the deleted `RoleTerminalLive.svelte`,
new `e2e/` + `playwright.config.ts`.

**Acceptance:** working tree clean except for the new Path B / A
files. Commit message names the prior session's intent (workspace
performance isolation, store separation).

**Status:** `[ ]`

---

## Path B — Pragmatic real-time

### T1 — ProjectEvent schema

Define the wire shape every realtime channel uses.

**Owns:** new `shared/api/realtime/event_schema.py`.

**Contract:**
```python
class ProjectEvent(BaseModel):
    event_id: UUID
    event_type: ProjectEventType  # Literal[...]
    project_id: str
    occurred_at: datetime
    actor: str
    payload: dict[str, Any]
    citation_count: int = 0
    verdict: str | None = None
```

`ProjectEventType` = Literal[
  `"ledger_append"`, `"directive_complete"`, `"instinct_recorded"`,
  `"auditor_verdict"`, `"auditor_refusal"`, `"audit_event"`,
  `"charter_eval_run"`, `"operate_plane_status"`,
  `"envelope_warning"`
].

**Acceptance:** Pydantic frozen + `extra="forbid"`; named exports;
≥ 1 test per event type variant.

**Status:** `[ ]`

### T2 — Event publisher hub

In-process pub/sub. One asyncio Queue per subscriber; per-project
filtered routing. No durability requirement at this stage (the
audit ledger + decision ledger remain the source of truth).

**Owns:** `shared/api/realtime/event_publisher.py`, tests under
`shared/api/realtime/tests/`.

**Contract:**
- `publish(event: ProjectEvent) -> None`
- `subscribe(project_id: str) -> asyncio.Queue[ProjectEvent]`
- `unsubscribe(queue) -> None`
- Subscribers are auto-dropped on disconnect (the SSE handler
  manages this).

**Acceptance:** Concurrent publish + 3-subscriber test; queue
overflow drops oldest (bounded `maxsize=256`); ≥ 80% coverage.

**Status:** `[ ]`

### T3 — Wire `append_promotion_decision`

Emit `ledger_append` event after every successful ledger write.
Fail-soft: publish failure never blocks the ledger write.

**Owns:** edit `shared/audit/decision_ledger_io.py`; test additions
in `shared/audit/tests/test_decision_ledger_io.py`.

**Acceptance:** existing 10 tests still pass; 1 new test asserts
event published with correct `verdict` + `citation_count`.

**Status:** `[ ]`

### T4 — Wire `complete_directive`

Emit `directive_complete` on success; emit `instinct_recorded` when
the instinct write succeeds.

**Owns:** edit `shared/runtime/role_runtime.py`; test additions in
`shared/runtime/tests/test_role_runtime_instinct.py`.

**Acceptance:** existing 5 tests still pass; 2 new tests assert
both events fire on success.

**Status:** `[ ]`

### T5 — Wire `run_auditor`

Emit `auditor_verdict` or `auditor_refusal` after envelope is
built (in addition to existing ledger write).

**Owns:** edit `verify/runtime/auditor_runner.py`; test additions in
`verify/runtime/tests/test_auditor_runner.py`.

**Acceptance:** existing 9 tests still pass; 2 new tests assert
each event fires with `verdict` + `citation_count` set correctly.

**Status:** `[ ]`

### T6 — Wire `audit_record`

Emit `audit_event` from `AuditRecord.write_via_psql` when the row
succeeds. Project-id is taken from the record metadata.

**Owns:** edit `shared/audit/audit_record.py`; test additions in
`shared/audit/tests/`.

**Acceptance:** existing audit tests still pass; 1 new test asserts
event published with the chained `content_hash`.

**Status:** `[ ]`

### T7 — Wire `evaluate_charter`

Emit `charter_eval_run` after the report aggregates; carries the
per-eval pass-rate dict + overall `meets_target` boolean.

**Owns:** edit `verify/charter_evals/harness.py`; test additions in
`verify/charter_evals/tests/test_harness.py`.

**Acceptance:** existing 12 tests still pass; 1 new test asserts
event fires with the report shape.

**Status:** `[ ]`

### T8 — Wire `run_operate`

Emit one `operate_plane_status` event per plane in the report (so
the UI can show planes filling in as they report), plus a final
roll-up.

**Owns:** edit `devops/runtime/operate_runner.py`; test additions
in `devops/runtime/tests/test_operate_runner.py`.

**Acceptance:** existing 6 tests still pass; 2 new tests assert
per-plane events + roll-up fire.

**Status:** `[ ]`

### T9 — SSE endpoint `/api/v2/projects/{id}/events`

FastAPI `StreamingResponse` mirroring the pattern in
`shared/api/routes/decisions.py:subscribe`. Each event emitted as
`event: <type>` + `data: <json>`. Includes a 15-second keepalive
comment and unsubscribes the queue on connection drop.

**Owns:** new `shared/api/routes/project_events.py`; register in
`shared/api/app.py` (or the existing include path).

**Acceptance:** unit test with FastAPI `TestClient` confirms first
keepalive arrives + a published event arrives in the stream; auth
honoured per existing pattern.

**Status:** `[ ]`

### T10 — SPA event store

Single Svelte store (`projectEvents`) that subscribes to the SSE
endpoint, buffers the last 200 events in memory, and exposes a
filtered readable per event type.

**Owns:** new `shared/ui/spa/src/lib/stores/projectEvents.ts`;
tests in the SPA's `__tests__/`.

**Acceptance:** unit test mocks `EventSource`, sends 3 events of
different types, asserts the store buffer + filtered readables
update.

**Status:** `[ ]`

### T11 — `LiveLoopActivity.svelte`

Chronological timeline component. One row per event with:

- icon + colour tied to event type (verdict → green; refusal →
  amber; audit_event → grey; instinct → blue; charter_eval → cyan)
- one-line summary derived from payload
- relative timestamp + per-row click-to-expand for full payload

Maxes out at the last 100 rows; older rows roll off.

**Owns:** new
`shared/ui/spa/src/lib/components/LiveLoopActivity.svelte`; CSS
inline per the SPA's existing Tailwind convention.

**Acceptance:** Svelte component tests assert per-event-type
rendering + the click-to-expand toggle.

**Status:** `[ ]`

### T12 — Wire `LiveLoopActivity` into the workspace

Insert as a new tab (`Live`) in the project workspace, between
`Pipeline` and `Decisions`. Default tab when project state is
`build_in_progress` or later.

**Owns:** edit
`shared/ui/spa/src/lib/components/ProjectWorkspaceTabs.svelte` and
the project page route. Touches files already modified in the
prior-session refactor (committed in T0), so no merge surprise.

**Acceptance:** manual: open the running Hub at
`http://localhost:8090/spa/projects/a81f7f2c-…`, see the new tab
populated as events stream in.

**Status:** `[ ]`

### T13 — Event publisher + SSE wire tests

Cross-module integration test: publish from each of T3–T8 with
fakes, assert SSE endpoint emits the wire shape, assert SPA store
fixtures parse it correctly.

**Owns:** new
`shared/api/realtime/tests/test_event_wire_integration.py`.

**Acceptance:** all six wiring paths fire correctly through the
event publisher + SSE format; SPA store fixture parses each.

**Status:** `[ ]`

### T14 — Path B validation + commit + push

Live Hub. Drive the validation project (`a81f7f2c-…`) through one
auditor call + one operate call; confirm:

1. Both events arrive at the SSE endpoint
2. The new `Live` tab renders both events with the right colour
   and summary
3. The `spine status --markdown` CLI still works
4. Full session regression sweep passes (target: > 391 tests)
5. Commit (one Conventional Commit per T-item or one big
   `feat(realtime)` — operator choice; recommended one per file
   boundary so the diff is reviewable)
6. Push to `origin/main`

**Status:** `[ ]`

---

## Path A — Deep dedicated surfaces

Begin AFTER Path B is live and the user has confirmed the unified
feed feels right. Each task is independent; pick by user priority.

### T15 — `LedgerTimeline.svelte`

Dedicated view of the decision ledger for the active project.
Per-row: rollout-index, verdict color, candidate marks, chain
integrity badge (green ✓ if `verify_chain()` passes; red ✗
otherwise). Filter by tier; export CSV.

**Owns:** new `LedgerTimeline.svelte` + matching SPA store.

**Status:** `[ ]`

### T16 — `EnvelopeSummary.svelte`

Renders the V3 #30a observation contract on every tool response
surface. `summary`, `next_actions` as clickable chips that
dispatch the next-action when clicked, `artifacts` as a
ref-typed link list.

**Owns:** new component + integration into every existing tool
response render site (audit log, recovery dispatch, build
artifact).

**Status:** `[ ]`

### T17 — `AuditorVerdictCard.svelte`

Verdict / refusal card with the citation list explicit, plus a
"why was this denied?" expansion showing the
`PromotionGate.reasons` list.

**Owns:** new component + insertion into the project workspace
when an `auditor_verdict` / `auditor_refusal` event arrives.

**Status:** `[ ]`

### T18 — `InstinctBadge.svelte`

Surfaces when a fingerprint crosses the promotion threshold (per
B3 `check_promotion`). Shows the pattern, the corroborating
projects, and a one-click "promote to lesson" action that calls
the existing `promote_to_lesson_payload` helper.

**Owns:** new component + store; integration into the project
workspace.

**Status:** `[ ]`

### T19 — `CharterEvalReport.svelte`

Pass@k report per role. Triggers a fresh `evaluate_charter` run
with the stub callable on-demand (so operators can sanity-check
without burning API credits). Surfaces red on any regressed
eval.

**Owns:** new component + an API route that wraps the harness.

**Status:** `[ ]`

### T20 — `AgentAuditOverview.svelte`

12-layer audit status with drill-down. Renders the
`AgentAuditReport.findings` tuple per layer with colour-coded
status (clean / warning / regressed / pending). Click into a
layer to see the finding's evidence + next actions.

**Owns:** new component + API route wrapping `scan_agent_stack`.

**Status:** `[ ]`

### T21 — `OperatePlaneGrid.svelte`

8-plane live status grid. Receives per-plane `operate_plane_status`
events (T8) and updates the matching cell in real time. Operators
can click into a plane to invoke an action via the existing
`ControlPlane.invoke()` path.

**Owns:** new component + API route for `invoke()` calls.

**Status:** `[ ]`

### T22 — Wire Path A components into workspace tabs

`Ledger` tab (T15), `Audit` tab gets `AgentAuditOverview` + the
existing `AuditPanel`, `Operate` tab (T21), `Evals` tab (T19).
`EnvelopeSummary` (T16) lands inline wherever envelopes render.
`AuditorVerdictCard` (T17) + `InstinctBadge` (T18) surface inline
in the Live tab.

**Owns:** edits to `ProjectWorkspaceTabs.svelte` + the project
page.

**Status:** `[ ]`

### T23 — Per-component tests

Unit + visual regression where feasible (Playwright is already
landed in the prior-session refactor). One test file per
component covering: empty state, populated state, click
interactions, error state.

**Owns:** matching `__tests__/` files for each component.

**Status:** `[ ]`

### T24 — Full SPA build + lint + test

`npm run build`, `npm run lint`, `npm run test -- --run`.
Playwright e2e (`RUN_PLAYWRIGHT=1 bash tools/verify-project-workspace.sh`)
optional but recommended.

**Acceptance:** all green; zero warnings introduced.

**Status:** `[ ]`

### T25 — Path A validation + commit + push

Live Hub. Walk every new tab on the validation project + a
second fresh project to confirm cross-project isolation. Commit
per-component or as a single `feat(spa)` depending on diff size.
Push.

**Status:** `[ ]`

---

*Update this file as we go — flip status on each task as it
moves, add notes inline when a task deferred.*
