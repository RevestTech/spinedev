# Spine Dashboard (v1)

> Full single-page control surface for a Spine deployment. Extends the
> approval queue (`shared/ui/approvals/`) into a five-tab dashboard:
> Projects, Cost, Activity, Knowledge, and a link out to Approvals.

Implements `STORY-9.9.4` (dashboard tile showing real-time orchestrator
state), `STORY-1.5.6` (UI cost meter), `STORY-1.5.7` (cost projection at
phase start), `STORY-1.6.2` (live phase indicator), and `STORY-1.6.3`
(role activity stream) from `docs/BACKLOG.md`.

## Architecture

```
browser (HTML/JS/CSS, :8080)
   |
   |--fetch--> proxy.py (:8081) --bash--> gate.sh --SQL--> Postgres
   |                                       |
   |                                       +--> /api/v2/projects, /api/v2/audit
   |                                       +--> /api/v2/kg/hybrid_search (MCP proxy)
   |
   +-- polling cadences: activity 5s | projects 10s | cost 60s | health 30s
```

Vanilla ES2020 modules. Each tab is a panel module that exports
`mount(container, ctx)` and `unmount(container)`. Switching tabs unmounts
the prior panel so its polling timer is reclaimed.

A WebSocket scaffold is left in `dashboard.js` (`initWsScaffold()`) so the
v2 live-events transport drops in without restructuring panels.

## Tabs

| Tab        | What it shows                                                            | Backend                                           |
|------------|--------------------------------------------------------------------------|---------------------------------------------------|
| Projects   | Tile per active project: name, phase (color), pending approvals, today's cost, age, owner. Click for detail. Filter by status/phase/owner; sort by age/cost/name. **+ New Project** modal POSTs to `/api/v2/projects`. | `GET /api/v2/projects`, `POST /api/v2/projects`, `GET /api/v2/projects/{id}`, `GET /api/v2/approvals?status=pending` |
| Cost       | Spend vs Budget bars (today/week/month), per-subsystem breakdown, per-phase projection (STORY-1.5.7), per-model rollup. | `GET /healthz`, `GET /api/v2/audit?project_id=...` |
| Activity   | Newest-first stream of audit events; color coded by subsystem; filter by project/role/window; pause/resume. Dedups by `event_id`. | `GET /api/v2/audit?project_id=...&limit=200` |
| Knowledge  | KG hybrid_search box -> sortable result table; quick actions (Find callers, Impact radius). Sidebar tracks most-queried nodes in localStorage. | `POST /api/v2/kg/hybrid_search` |
| Approvals  | Link out to the existing approval queue UI. | `shared/ui/approvals/index.html` |

## Cost meter explained

- **Spend vs Budget** - three bars (Today / Week / Month) coloured green
  under 80%, amber 80-100%, red over budget. Caps default per scope
  (org/user/project); swap caps when the budget enforcer (EPIC-2.3) lands.
- **Per-subsystem** - splits today's spend by `plan | build | verify |
  orchestrator | shared` (the V16 `subsystem` discriminator).
- **Next-phase projection (STORY-1.5.7)** - per project, estimates next
  phase cost as the historical avg cost of that phase across the deployment.
  In production this swaps for the planner model-menu output.
- **Per-model** - top 8 models by USD this window.

## KG search

- Free-text queries hit `/api/v2/kg/hybrid_search`. Phrase as if you were
  searching code: `"where do we validate phase tokens"`, `"engine for
  budget enforcement"`.
- Filter by node type (symbol/file/doc/test) and limit.
- **Find callers** / **Impact radius** re-issue the search with `action`
  set so the MCP server returns dependency edges instead of free-text hits.
- Sidebar tracks per-browser query analytics so you can see which nodes
  the operator returns to most.

## Run it

```bash
bash shared/ui/dashboard/serve.sh                       # 8080 (UI) + 8081 (proxy)
bash shared/ui/dashboard/serve.sh --port 9000 --api-port 9001
bash shared/ui/dashboard/serve.sh --open cost           # land on cost tab
bash shared/ui/dashboard/serve.sh --no-open             # no browser
```

If `shared/ui/approvals/serve.sh` is already running, the dashboard reuses
its proxy on :8081 (no duplicate spawn). Override the gate binary with
`SPINE_GATE_SH=/custom/path bash serve.sh`.

Visit <http://localhost:8080> then open **Settings** to set your actor
identity, polling intervals, and default tab.

## Keyboard

`R` refresh active panel - `1-4` switch tab - `Space` pause polling - `Esc` close modal.

## Not in v1 (deferred)

WebSocket / SSE live events, mobile layout, per-cell audit drill modal
(today logs to console), light theme, accessibility audit beyond
`aria-live` / `aria-selected`, server-side enrichment for
`_pending_approvals` and `_cost_today` (client fan-out today).

## Cross-refs

- `docs/PRD.md` REQ-INIT-9 §9.5 G-19, REQ-INIT-1 §1.5 FR-6, §1.5 G-7
- `docs/BACKLOG.md` STORY-9.9.4, STORY-1.5.6, STORY-1.5.7, STORY-1.6.2, STORY-1.6.3
- `shared/api/routes/projects.py`, `shared/api/routes/audit.py` (REST surface)
- `db/flyway/sql/V14__spine_lifecycle_schema.sql`,
  `V16__unified_cost_ledger.sql`, `V17__portfolio_views.sql` (data sources)
- `shared/ui/approvals/` (style sibling + reused dev proxy)
- `lib/dashboard.html` (Spine v1 Control Center palette)
