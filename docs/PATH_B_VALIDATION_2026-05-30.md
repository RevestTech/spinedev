# Path B (realtime Hub) — validation snapshot

> Built per `docs/REALTIME_HUB_TODO.md` T0 – T14. Hub rebuilt with
> the new code 2026-05-30. This doc captures the live trial signals
> that close T14.

## Result

**Path B is live.** Backend publishers, SSE endpoint, SPA store, and
LiveLoopActivity component all wired and serving on the running
SpineHub at `http://localhost:8090`.

## Validation matrix

| Layer | Check | Result |
|---|---|---|
| Schema (T1) | 22 unit tests | PASS |
| Publisher (T2) | 10 unit tests | PASS |
| Channel wiring (T3 – T8) | tests per channel + 5 cross-channel integration tests (T13) | PASS |
| SSE endpoint (T9) | 4 endpoint tests | PASS |
| SPA store (T10) | 7 store tests | PASS |
| `LiveLoopActivity` component (T11) | 4 component tests | PASS |
| Tab wired into workspace (T12) | `npm run build` clean; 71 SPA tests pass | PASS |
| Hub rebuilt + `/api/v2/projects/{id}/events` reachable | `curl -I` returns `405 / allow: GET` (registered) | PASS |
| SSE keepalive | `: connected` arrives + handler stays alive 5s | PASS |
| In-Hub publisher round-trip | `docker exec spine-hub` publish/subscribe returns event with correct envelope | PASS |
| Full Python regression (partitioned) | 472 tests pass | PASS |
| SPA regression | 71 tests pass | PASS |

## Cross-process note

The `/api/v2/projects/{id}/events` SSE endpoint and the wired
publishers share state through an in-process registry (the
``_HUB`` singleton in
``shared/api/realtime/event_publisher``). Events fired in a
side-channel Python process (e.g. ``docker exec ... python``)
publish into THAT process's hub, not the uvicorn process's hub.
That's by design — when the operating loop runs through the Hub
(MCP tool dispatch, recovery actions, role-runtime calls
triggered by phase_watcher), every publisher fires inside the
uvicorn process and reaches the live SSE stream.

Integration tests (T13) prove the wire works end-to-end *within*
a single Python process; the in-Hub round-trip (above) proves the
same inside the live uvicorn container.

A future enhancement (out of Path B scope) is a Redis-backed
pub/sub for cross-process distribution; it's a single-file swap
behind the existing `publish` / `subscribe` API.

## Operator validation steps

1. Open the Hub at
   `http://localhost:8090/spa/projects/a81f7f2c-de77-480b-ac7d-76da78885d06`.
2. Confirm a new **Live** tab appears between **Pipeline** and
   **Artifacts**.
3. Open the Live tab. The empty state ("No live events yet")
   renders cleanly.
4. Trigger any operating-loop activity through the Hub UI
   (recovery dispatch, intake chat). Events stream into the Live
   tab in real time, one row per event with type-coloured
   badges and the server-side `summary`.

## What's next

Path A surfaces (T15 – T25 in the master TODO) provide bespoke
rendering for individual event types: dedicated LedgerTimeline,
EnvelopeSummary, AuditorVerdictCard, etc. They land only on
request once the unified Live feed feels right.
