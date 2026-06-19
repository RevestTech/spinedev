# SPA project workspace hang (SPA-HANG)

**Status:** Fixed 2026-06-02 (verified in Chromium via Playwright).  
**Task ID:** SPA-HANG  
**Primary URL:** `http://localhost:8090/spa/projects/<project_id>`

---

## Symptom

Opening a project workspace caused the browser tab to become **unresponsive**:

- Full-page **“Preparing pipeline”** spinner (early reports), or
- Pipeline shell visible but **“Loading actions”** never finishing, or
- Chrome **“Page Unresponsive”** while the activity log showed **“Loading actions”**

The Hub API was healthy: `GET /api/v2/projects/{id}/recovery` returned in ~150ms with a small JSON payload (e.g. five actions). The failure was **client-side main-thread starvation**, not a slow backend.

---

## Root cause

Several expensive operations started **at the same time** on first paint:

| Source | What it did |
|--------|-------------|
| Layout `+layout.svelte` | Opened global `GET /api/v2/decisions/subscribe` SSE on every Hub page |
| Project `+page.svelte` | Loaded summary, then recovery, then mounted runtime |
| `ProjectWorkspaceRuntime` | Called `wsBind()` → subscribed to every SSE `activity` event |
| `syncInitialWorkspaceTab` / `PipelineActivityLog` | Fetched `GET .../activity/terminal` and called `wsTerminal.set()` synchronously |
| `decisions.ts` `emitActivity` | Non–`role_log` events called `activity.set()` **synchronously** (one subscriber notification per event) |

Playwright isolation (Chromium, project `3f2a6e0e-15a3-44cd-9bc1-c06880199342`):

| SSE subscribe | Terminal fetch | Result |
|---------------|----------------|--------|
| blocked | blocked | OK (~3s, actions visible) |
| allowed | blocked | OK (~2s) |
| blocked | allowed | **Hang** |
| allowed | allowed | **Hang** |

**Conclusion:** Recovery alone is fine. The tab froze when **terminal history loaded** while **SSE was active** (or reconnecting), flooding the main thread before recovery UI could paint.

Earlier mitigations (parallel boot, Path A/B tab removal, SSE store refactor) reduced severity but did not serialize boot correctly.

---

## Fix: staged boot contract

Boot order is now explicit and enforced in code:

```
1. Disconnect layout SSE on project workspace routes
2. GET /api/v2/projects/{id}/summary  → paint project shell (workspaceReady)
3. GET /api/v2/projects/{id}/recovery  → paint pipeline actions (await, ≤8s)
4. wsPipelineBootReady = true          → mount runtime + activity log shell
5. +600ms                              → decisions.connect() (SSE)
6. +1200ms after boot ready             → GET .../activity/terminal (deferred)
```

**Rules:**

- **Never** open SSE and apply terminal history in the same tight window as the first recovery snapshot.
- **Never** call `scheduleLoadRecovery` / duplicate `wsLoadRecoveryNow` from runtime or controls on mount (boot already loaded recovery).
- Terminal history is **not** auto-fetched on activity-log mount; user can click **“Load prior activity”**, or the page loads it ~1.2s after boot via a guarded reactive (pipeline tab only).

---

## Code changes (by area)

### Layout — `shared/ui/spa/src/routes/+layout.svelte`

- `projectWorkspaceOwnsSse()` — layout **does not** call `decisions.connect()` on `/projects/{uuid}` (cold load or `afterNavigate`).
- Project page owns SSE lifecycle during boot; layout reconnects when navigating away.

### Project page — `shared/ui/spa/src/routes/projects/[project_id]/+page.svelte`

- `onMount`: `decisions.disconnect()` immediately; `ssePausedForWorkspaceBoot = true`.
- Boot: `await wsLoadRecoveryNow(id)` (race 8s) → `flushFrameCommitsForBoot()` → `yieldMainThread()` → `wsMarkPipelineBootReady()`.
- SSE: `setTimeout(ensureSseConnectedAfterBoot, 600)` after recovery (not in the same turn as terminal).
- `ProjectWorkspaceRuntime` mounts only when `$wsPipelineBootReady`.
- Terminal: deferred load via reactive when pipeline tab + boot ready (+1.2s), not during `syncInitialWorkspaceTab`.

### Store — `shared/ui/spa/src/lib/stores/projectWorkspace.ts`

- `wsPipelineBootReady` — gates runtime bind and activity pane.
- `wsMarkPipelineBootReady()` / `wsResetPipelineBoot()` — set/clear on project switch and `wsUnbind`.
- `wsLoadTerminal` — applies lines via `scheduleFrameCommit` + `flushFrameCommitsForBoot` (not synchronous `wsTerminal.set`).

### Runtime — `shared/ui/spa/src/lib/components/ProjectWorkspaceRuntime.svelte`

- `wsBind` only when `$wsPipelineBootReady`.
- Removed `scheduleLoadRecovery(projectId, true)` on mount (duplicate GET).

### Pipeline UI

- `ProjectPipelinePanel.svelte` — `PipelineActivityLog` only when `$wsPipelineBootReady`.
- `PipelineRecoveryControls.svelte` — removed redundant `wsLoadRecoveryNow` on mount.
- `PipelineActivityLog.svelte` — **“Load prior activity”** button; no `requestIdleCallback` auto-fetch on mount.

### Decisions store — `shared/ui/spa/src/lib/stores/decisions.ts`

- `emitActivity` (non–`role_log`): `scheduleFrameCommit(() => activity.set(evt))` so SSE bursts do not synchronously notify all subscribers.

### Earlier context (still relevant)

- **2026-05-30:** Path A/B tabs removed from project page (large lazy chunks froze tab even when tab-gated).
- **SSE batching** in `projectWorkspace.ts` (`queueActivityEvent`, `flushSseQueue`, batched role logs) remains; staged boot is what made recovery actions reliably visible.

---

## Verification

### APIs (curl)

```bash
curl -sf 'http://localhost:8090/api/v2/projects/<id>/recovery' | jq '.actions | length'
# expect small integer quickly (~0.15s)
```

### Playwright (required regression)

From repo root after `bash tools/hub-up.sh --rebuild`:

```bash
cd shared/ui/spa
npx playwright test e2e/project-workspace-hang.spec.ts e2e/booger-workspace.spec.ts
```

Expected: **3 passed**. Typical timings:

- `recovery-actions-ready` visible in **~1.5–3s**
- Ten main-thread probes with **0 freezes**

Optional project ID:

```bash
HUB_E2E_PROJECT_ID=<uuid> npx playwright test e2e/project-workspace-hang.spec.ts
```

### Unit tests

```bash
cd shared/ui/spa && npm test
# 105 passed (includes projectWorkspace SSE batching tests)
```

---

## If it regresses locally

1. **Hard refresh** (Cmd+Shift+R) — stale `/_app` bundles are a common false “still broken”.
2. **Rebuild Hub** so `static/spa` matches source: `bash tools/hub-up.sh --rebuild`, wait ~30s.
3. Run Playwright tests above; if they pass but Chrome hangs, suspect extensions or cache, not API.
4. Do **not** re-add eager `wsLoadTerminal` on boot or layout `decisions.connect()` on project URLs without revisiting this doc.

---

## Related files

| File | Role |
|------|------|
| `shared/ui/spa/e2e/project-workspace-hang.spec.ts` | Regression: actions + responsiveness + SSE/terminal |
| `shared/ui/spa/e2e/booger-workspace.spec.ts` | Boot spinner hidden, pipeline visible |
| `shared/ui/spa/src/lib/uiFrameScheduler.ts` | `scheduleFrameCommit`, `flushFrameCommitsForBoot` |
| `shared/ui/spa/src/lib/components/ProjectWorkspaceRuntime.svelte` | SSE bind + fallback polls (after boot ready) |

---

## Design contract (do not break)

From `projectWorkspace.ts` header and SPA-HANG learnings:

1. Hub SSE for the bound project is filtered **before** queueing (`shouldAcceptActivityEvent`).
2. High-frequency terminal/feed updates use **`scheduleFrameCommit`**.
3. Leaf components (`PipelineActivityLog`, `PipelineRecoveryControls`) subscribe to **narrow stores** so the project `+page.svelte` does not re-render on every log line.
4. **Recovery GET** must complete and paint before **SSE bind** and **terminal bulk load**.
