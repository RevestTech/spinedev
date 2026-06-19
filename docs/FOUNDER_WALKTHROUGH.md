# Founder walkthrough — non-engineer golden path

> **Task:** SPINE-015 · **Evidence project:** `fe4c11c3-cd46-4878-aa69-2873c44962ab`  
> **Reached:** `operate` (2026-06-19) · **Name at run time:** `Orchestrator E2E Resume 045201`

This document is the honest, non-engineer guide to running Spine's golden path on
a laptop. It is based on a **real** end-to-end run that cleared intake through
deploy and entered the operate phase — not a theoretical checklist.

For architecture and gap matrix, start at [`SPINE_MASTER.md`](SPINE_MASTER.md) §2
and §9.

---

## What you are doing

You describe a product idea. Spine's named roles (Product, Architect, Engineer,
QA, DevOps, …) produce artifacts and push **Decision Queue** cards. You approve
those cards at gates. Spine advances the project through SDLC phases until code
exists, is verified, deployed locally, and operate monitoring starts.

**You are the founder, not the implementer.** Your job is intake conversation +
approving cards — not editing code or running role scripts by hand.

---

## Prerequisites

| Requirement | Why |
|---|---|
| Docker Desktop (or Linux Docker) | Hub runs containerized (`hub/docker-compose.yml`) |
| Valid `ANTHROPIC_API_KEY` | Intake chat + role runners call LLM through Hub |
| ~60–90 minutes wall time | Build + verify roles are slow; walkthrough polls every few seconds |
| Optional: browser at `http://localhost:8090/spa/` | Manual approval path (see below) |

Export a real API key before bringing Hub up (placeholder keys break intake):

```bash
export ANTHROPIC_API_KEY='sk-ant-…'   # real key, not placeholder
bash tools/hub-up.sh --rebuild
```

`hub-up.sh --rebuild` matters for the **operate bridge**: the Hub image must include
recent fixes (phase watcher tail, `deploy_result` persistence on deploy ack,
pgvector init). If you are on stale Hub code, projects stall at `released`.

Confirm smoke:

```bash
bash tools/smoke-test.sh   # expect 99 PASS / 0 FAIL
curl -s http://localhost:8090/healthz
```

---

## Two ways to run it

### A — Automated approval proxy (recommended for repeat runs)

The walkthrough script creates a `spine_on_spine` project, completes intake via
chat API, then auto-acks pending decision cards until the queue drains or limits
hit.

```bash
export ANTHROPIC_API_KEY='sk-ant-…'
bash tools/hub-up.sh --rebuild

# Full run (new project each time unless GOLDEN_PATH_UNIQUE=0)
bash tools/golden-path-walkthrough.sh "My first app"

# Website profile (Next.js landing + contact)
GOLDEN_PATH_PROFILE=website bash tools/golden-path-walkthrough.sh "Sample Website"
```

**Resume an existing project** (skip create + intake):

```bash
PROJECT_UUID=fe4c11c3-cd46-4878-aa69-2873c44962ab \
  MAX_EMPTY_POLLS=5 \
  bash tools/golden-path-walkthrough.sh
```

Useful env overrides:

| Variable | Default | Purpose |
|---|---|---|
| `BASE` | `http://localhost:8090` | Hub URL |
| `MAX_ITERATIONS` | `50` | Ack loop cap — see caveats |
| `MAX_RUNTIME_SEC` | `3600` | Wall-clock cap |
| `MAX_EMPTY_POLLS` | `120` | Stop after N empty queue polls |
| `POLL_SLEEP_SEC` | `3` | Poll interval |
| `GOLDEN_PATH_PROFILE` | `cli` | Intake script (`cli` or `website`) |

On success the script prints `project_uuid`, `current_phase`, and `cards_acked`.
For the reference run, `current_phase=operate`.

### B — Manual Hub SPA (true founder UX)

1. Open `http://localhost:8090/spa/`
2. **Create project** — greenfield or spine-on-spine
3. **Decision Queue** — ack `intake_briefing`, then use **Intake chat** (Product role)
4. As cards appear, read and **Approve** each gate in order (see table below)
5. Watch **Project workspace** for phase changes and artifacts

The automated script is an approval *proxy* for testing; design partners should
use the SPA path (SPINE-020).

---

## Phase-by-phase — what you approve

Canonical phases (`orchestrator/state/phases.yaml`):

```
intake → plan_in_progress → plan_approved → build_in_progress → build_complete
  → verify_in_progress → verify_approved → acceptance → released → operate → retro
```

Typical **Decision Queue** card kinds you approve (in order):

| Gate card | What Spine does after you approve |
|---|---|
| `intake_briefing` | Opens intake; Product role interviews you |
| `prd_approval` | Planner + architect chain starts; PRD locked |
| `roadmap_approval` | Roadmap / epic breakdown |
| `trd_approval` | Technical design from architect swarm |
| `sprint_plan_approval` | Conductor sprint plan |
| `code_approval` | Engineer output ready for review |
| `code_review_pass` | Code review cleared |
| `devops_approval` | DevOps install / start prep |
| `qa_approval` | QA sign-off |
| `release_gate_approval` | Advances to `released`; enqueues deploy choices |
| `local_deploy_prompt` | Runs container/local deploy |
| `deploy_status` | Confirms deploy — **must** persist `deploy_result` for operate tail |
| *(phase watcher)* `operate_kickoff` | DevOps operate runner; sets `operate_started_at` |

Generated code for non–spine-on-spine projects lands under
`~/spine-projects/<uuid>/` (or `SPINE_PROJECTS_DIR`). Spine-on-spine dogfood
writes to `.spine/dogfood/<uuid>/`.

---

## Reference E2E run (SPINE-009)

| Field | Value |
|---|---|
| Project UUID | `fe4c11c3-cd46-4878-aa69-2873c44962ab` |
| Final phase | `operate` |
| `operate_started_at` | `2026-06-19T05:21:31Z` |
| `deploy_result` | `{ ok: true, mode: cli }` |
| Commits that unblocked tail | `af2e115` (`deploy_result` on deploy ack), `6382331` (pgvector + walkthrough limits) |

Inspect live state (Hub must be up):

```bash
curl -s http://localhost:8090/api/v2/projects/fe4c11c3-cd46-4878-aa69-2873c44962ab | python3 -m json.tool
```

**Note:** This project may still show a **stale** `last_role_failure` in metadata
from an earlier failed `operate_kickoff` attempt. Operate had already started; the
walkthrough now **soft-continues** past that card instead of exiting (see caveats).

---

## Known caveats (read before you blame yourself)

### 1. Iteration and time limits

The walkthrough stops when `MAX_ITERATIONS` (default **50**) or
`MAX_RUNTIME_SEC` (default **1 hour**) is reached, even if cards remain. Slow
build/verify phases can hit this on first run.

**Mitigation:** Resume with `PROJECT_UUID=…` and raise limits:

```bash
PROJECT_UUID=<uuid> MAX_ITERATIONS=200 MAX_RUNTIME_SEC=7200 bash tools/golden-path-walkthrough.sh
```

### 2. Hub rebuild for operate bridge

The `released → operate` transition is driven by **phase watcher** rules, not
by you clicking one more card. Watcher requires:

- `metadata.deploy_result` present (set when you ack `deploy_status`)
- `metadata.operate_started_at` absent (until operate runner fires)

If Hub predates the `deploy_result` fix, projects **stick at `released`** after
deploy. Rebuild:

```bash
bash tools/hub-up.sh --rebuild
```

Then resume the project or ack `deploy_status` again if needed.

### 3. `deploy_result` fix (2026-06-19)

Previously, acking `deploy_status` was a no-op in `_post_ack.py`, so watcher
never saw `deploy_result` and operate never kicked off. Fixed in commit
`af2e115`. Without it, golden path ends at `released` — not a founder mistake.

### 4. pgvector on Hub Postgres

KG embeddings and some migrations need the `vector` extension. Hub compose uses
`pgvector/pgvector:pg16` with first-boot init (`hub/postgres/init/01-pgvector.sql`).
If smoke warns `pgvector unavailable`, recycle Postgres volumes after image swap:

```bash
bash tools/hub-up.sh --down   # removes volumes — destructive to local DB
bash tools/hub-up.sh --rebuild
```

### 5. Human approval gates — not unattended

| Still human or scripted | Detail |
|---|---|
| Intake answers | Product role asks clarifying questions; script uses canned prompts |
| Every gate card | Script auto-acks = you delegating approval, not removing the gate |
| Deploy path choice | Container vs host cards need judgment in SPA; script acks first pending |
| `orchestrator_gap` | Script **stops** (exit 2) — bridge miss needs engineer fix |
| `role_failure` | Script **stops** unless `operate_started_at` already set (stale failure) |
| Valid LLM key | No key → intake hangs or roles fail |
| Cloud / BYOC deploy | Manual; vault-stored creds not wired for unattended cloud |

### 6. What is not production-ready yet

- **Role chat panel** — STUB badge in SPA (`REALITY-AUDIT-2026-06-19.md`)
- **Operate planes 2–8** — heartbeat stub; plane status often `unknown`
- **Background role workers** — partial; long runs depend on Hub lifespan + ack chain
- **Design partner onboarding without founder** — SPINE-020 / `V1_SHIP_CHECKLIST.md` §6
- **Independent human re-audit** — SPINE-014 before customer ship

---

## Troubleshooting

| Symptom | Likely cause | Action |
|---|---|---|
| Intake never finishes | Bad/missing API key | `export ANTHROPIC_API_KEY=…`; `hub-up --rebuild` |
| Stuck at `build_in_progress` | Role worker slow or failed | Check Hub logs; look for `role_failure` card in queue |
| Stuck at `released` | Missing `deploy_result` | Rebuild Hub; ack `deploy_status`; confirm metadata |
| Script exit 2 `orchestrator_gap` | Bridge mapping missing | Engineer fix — do not auto-ack past this |
| Script exit 2 `role_failure` | Role dispatch failed | Fix root error; or if already in `operate`, resume (soft continue) |
| `401 invalid x-api-key` | Placeholder key in container | Re-export key; rebuild Hub |

Dry-run (no LLM, bridge registry only):

```bash
bash tools/golden-path-dry-run.sh
```

---

## Success criteria (§9 one-liner)

From [`SPINE_MASTER.md`](SPINE_MASTER.md) §9:

> *Can a non-engineer founder describe an app, approve a handful of cards, and
> receive a deployed, maintained product — with every step performed by named
> expert roles, backed by the knowledge graph and audit chain?*

**Sprint 0 honest answer:** **Partial yes** on laptop — reference project reached
`operate` with local deploy. **Full yes** still blocked on unattended design-partner
onboarding, real operate planes, and independent re-audit before `V1_SHIP_CHECKLIST.md`.

---

## Related docs

- [`SPINE_MASTER.md`](SPINE_MASTER.md) §7 — golden path commands
- [`docs/product/REALITY-AUDIT-2026-06-19.md`](product/REALITY-AUDIT-2026-06-19.md) — LIVE vs STUB matrix
- [`docs/OPERATING_LOOP_GAP.md`](OPERATING_LOOP_GAP.md) — released → operate wiring
- [`todo/BACKLOG.md`](../todo/BACKLOG.md) — SPINE-009 (done), SPINE-015 (this doc)
