# Spine Approval Queue (v1)

> First slice of `shared/ui/` outside TRON's existing frontend. Implements
> `STORY-1.4.2` (approval queue) + `STORY-1.4.3` (inline review surface).

## Why this exists

Phase gates (`docs/PRD.md` REQ-INIT-1 FR-5) require the user to sign off on
PRD, TRD, Roadmap, Verify findings, and acceptance. Without a UI, that means
SSH into the box and running `orchestrator/lib/gate.sh approve …` by hand — a
hard bottleneck. This queue is the smallest useful surface that unblocks
plan/build/verify with one-click approve / reject / request-changes.

Deliberately tiny: vanilla HTML + JS + CSS, no build, no npm, no framework.
The full React-based dashboard lands later (`STORY-1.6.4`).

## Architecture

```
browser (HTML/JS, :8080) ──fetch──> proxy.py (:8081) ──bash──> gate.sh ──SQL──> Postgres
                                       └── reads markdown artifacts from disk
```

`index.html` + `approvals.js` + `approvals.css` is the UI (static files).
`proxy.py` is a dev REST shim around `gate.sh list-pending|approve|reject|request-changes`.
`serve.sh` boots both servers, opens the browser, traps Ctrl-C cleanup.
Production replaces `proxy.py` with the FastAPI surface from `STORY-9.9.2`.

## Run it

```
bash shared/ui/approvals/serve.sh                  # default ports 8080 / 8081
bash shared/ui/approvals/serve.sh --port 9000 --api-port 9001 --no-open
```

(`chmod +x serve.sh proxy.py` to use `./serve.sh` directly.)

Visit <http://localhost:8080> then open **Settings** and set your approver
identity — that string is forwarded as `<approver>` to `gate.sh`.

Override gate location: `SPINE_GATE_SH=/custom/path bash serve.sh`.

## What the UI looks like

```
+-----------------------------------------------------------------+
| SPINE APPROVALS              synced 14:02  [Refresh] [Settings] |
| Phase [v]  Project [v]  Age [v]  ( Status: pending )            |
+-----------------------------------------------------------------+
| Pending Approvals (2)                                           |
|  +-------------------------------+ +--------------------------+ |
|  | my-saas-tool   [plan_approved]| | internal-dashboard       | |
|  | Project ID : 42               | | Project ID : 17          | |
|  | Artifact   : docs/.../prd.md  | | Artifact   : verify/...  | |
|  | Age        : 12m ago          | | Age        : 2h ago      | |
|  | [Review] [Approve] [Reject]   | | [Review] [Approve] ...   | |
|  |   [Request Changes]           | |                          | |
|  +-------------------------------+ +--------------------------+ |
+-----------------------------------------------------------------+
| Recently Approved (3)                                           |
|  foo  plan_approved  2h ago  khash@...                          |
+-----------------------------------------------------------------+
```

Clicking **Review Artifact** opens a modal that loads the markdown via
`GET /api/v2/artifacts?path=…`. Reject + Request-Changes reveal a required
notes textarea. Color coding: amber=pending, green=approve, red=reject,
blue=request-changes. Dark theme (matches `lib/dashboard.html`). Polls every
10s (configurable). Optimistic UI; reverts on server error.

## Not in v1 (deferred)

WebSocket/SSE realtime, mobile responsive, multi-user auth, per-project
drill-down, diff view for re-submissions, markdown rendering, light theme —
covered by `STORY-1.6.4` and follow-ups.

## Cross-refs

`orchestrator/lib/gate.sh` (backend); `STORY-9.9.2` (FastAPI replacement for proxy.py); `STORY-1.6.x` (Front Door UI); `lib/dashboard.html` (palette); `docs/PRD.md` REQ-INIT-1 FR-5, REQ-INIT-9 FR-10.
