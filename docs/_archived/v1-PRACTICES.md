# Spine — Operating Practices

> Operating-guidance reference for Spine maintainers, contributors, and AI agents working on or with Spine. Three concerns in one file: **drift-prevention practices**, **program-delivery flow** (SDLC orchestration with REQ gates), and **historical extension status** (what shipped vs what didn't).
>
> Related canonical docs:
> - `docs/ARCHITECTURE.md` — system architecture (Plan / Build / Verify / Orchestrator / Shared)
> - `docs/PRD.md` — product requirements (REQ-INIT-N sections)
> - `docs/BACKLOG.md` — operational backlog (INIT / EPIC / STORY)
> - `docs/IMPROVEMENT_CHECKLIST.md` — maintenance / release-hygiene checklist
> - `PROTOCOL.md` (root) — full role/daemon protocol
> - `REQUIREMENTS.md` (root) — host prerequisites to run Spine

---

## Part 1 — Drift prevention: multi-agent development without drift

Spine's purpose is keeping software coherent when many agents and humans work in parallel. The pattern works only if the operating practices below are followed.

### Goals

1. **Multi-agent program delivery** — Specialized roles (product, architect, conductor, engineering squads, UX, QA, plus core operators) coordinate through the same **file bus** and worker fan-out rules.
2. **Less drift** — Single protocol, structured reports, ADRs, REQ linkage, session handoff, and per-role memory so context does not live only in one model turn.
3. **Durable documentation** — Protocol, requirements, recipes in-repo, and optional `DECISIONS.md` / `SESSION_HANDOFF.md` / `MASTER_TODO.md` at `.planning/orchestration/` give every new session the same baseline.

### How drift shows up — and how the spine counters it

| Risk | Mitigation |
| ------ | ------------ |
| Two agents edit the same file | Role boundaries; manager declares file scope per worker; optional `file-lock.sh` |
| "It passed" without running checks | Auditor role; reports list **Files touched**; engineer runs gates |
| Lost decisions | `memory` role + `DECISIONS.md`; append-only ADRs |
| Model spend runaway | Tier hints + `costs.csv` + `make team-budget` |
| Sloppy temp files | Scratch dirs wiped per directive; hygiene rules in protocol |
| Stale instructions | `--pull-knowledge-only` refresh of recipes and role prompts without replacing daemons |

### Context stack (what to read, in order)

1. **`.planning/orchestration/AGENT_TEAM_PROTOCOL.md`** — Contract for all roles.
2. **`.planning/orchestration/DECISIONS.md`** — What was decided and why.
3. **`SESSION_HANDOFF.md`** / **`MASTER_TODO.md`** — If present, current focus and queue.
4. **`teams/<role>/memory.md`** — Lessons for that role on this repo.
5. **`~/.spine-development/playbook/<role>/lessons.md`** — Cross-project lessons (optional).

Agents invoked by the daemon get role prompt + memory + directive; keeping these files accurate is **the** lever for quality.

### Architect habits that help

- Write directives with **explicit constraints**, **report format**, and **`## Tier hint`** when non-default.
- Use **`## Requires approval: yes`** for destructive or production-adjacent work.
- After major work, queue a **`memory`** directive to fold outcomes into spine docs.
- Periodically run **`make team-budget`** and **`make team-clean`** (or `team.sh clean all`).
- Re-run **`install.sh <repo> --pull-knowledge-only`** on long-lived projects to pick up new recipes and prompts without touching customized scripts.

### Trust boundary

Only **trusted** people and processes should write under `.planning/orchestration/`. Directive files can trigger shell-backed agent CLIs. Treat that tree like commit access to your build.

---

## Part 2 — Program delivery: SDLC orchestration flow

This part is the operational bridge between **business intent** and the **daemon-backed AI team**.

### Artifact stack (canonical locations)

Install places templates under `.planning/orchestration/program/`. Maintain at least:

| Path | Purpose |
| ------ | --------- |
| `POLICY.stub.md` | Linked corporate controls (privacy, branching, ML usage, spend caps) |
| `REQ-xxxx.md` or similar | Approved/draft requirement records |
| `PROGRAM_PHASES.md` | Lifecycle gate ledger (who signed what, when) |
| `DECISIONS.md` | Append-only ADRs |
| `ux/`, `qa/` subfolders | Specialized narrative outputs |

Agents load these via directives and `memory` hygiene passes.

### Who runs which phase

1. **`product`** — drafts REQ, captures stakeholder intents.
2. **Humans** (CPO/COO/legal/CTO delegates) flip `revision: approved`.
3. **`architect`** + **`planner`** — technical planning, decomposition, spikes.
4. **`conductor`** — issues parallel squad directives with `## Linked REQ` guards.
5. **`engineering-*` / `qa` / `ux` / `operator` / `datawright`** execute with workers.
6. **`auditor` + `memory`** mitigate drift once milestones close.

Always propagate **`## Tier hint`** so telemetry in `teams/*/state/costs.csv` reflects spend policy.

### Recursive collaboration pattern

Squads rerun the **exact same orchestration primitives**:

- `# Directive → # Plan → # Worker Directive/report → aggregated # Report`.

No extra daemon tiers — breadth emerges from parallel roles enumerated in `scripts/roles.sh`.

### Executive alignment

Executive titles (**CTO**, **COO**, **CPO**) do **not** map 1:1 to always-on AI daemons — they anchor approvals in Markdown and ADR merges. Exceptions require explicit waiver text inside the REQ or ADR with human attribution.

---

## Part 3 — Extension status: roadmap vs shipped

Early versions of this document read like a backlog of features that had not landed. The **v1.4.x** template now ships a large fraction of that list. Use the **status** tags below: **Shipped**, **Partial**, **Not shipped**.

Canonical role count and mechanics live in **`scripts/roles.sh`** / **`PROTOCOL.md` §1** — not in this file.

### Summary

| § | Topic | Status |
| --- | -------- | -------- |
| 1 | Planner cross-manager aggregation | **Not shipped** |
| 2 | Seer / observability role | **Shipped** |
| 3 | Auditor / verification role | **Shipped** |
| 4 | Memory / spine-doc role | **Shipped** |
| 5 | Per-invocation wall limits + long-job hint | **Shipped** — **`## Long job:`** extends **`INVOCATION_TIMEOUT_S`** only; stall scales when extended; **`scripts/costs-csv.sh`** migrates legacy CSV atomically |
| 6 | Stall / liveness kill | **Shipped** (`STALL_THRESHOLD_S`, scaled when long job set; agent log growth) |
| 7 | Cost / budget tracking + reap visibility | **Shipped** (`costs.csv` includes **`outcome`**: `completed` / `timeout` / `stall` / `killed`; `team status` / `doctor` / Control Center) |
| 8 | Conflict avoidance for shared files | **Partial** (`scripts/file-lock.sh` + PROTOCOL; agents must call it — not auto-wired) |
| 9 | Web dashboard | **Shipped** — **Spine Control Center** (`dashboard/index.html`): tabs, drawer, costs/program/docs, polling |
| 10 | Cross-project playbook | **Shipped** (`~/.spine-development/playbook/`, `team learn`) |
| 11 | TL;DR on reports | **Shipped** (prompt + daemon aggregate guidance) |
| 12 | Recipes library | **Shipped** (`recipes/` via installer) |

### Detail

#### 1. Cross-team aggregation for planner — **Not shipped**

**Why.** Planner spawns directives in **other** managers' folders, then can sit in `# Plan` state because its daemon only watches **its own** tree. The architect often performs manual aggregation today.

**Sketch.** Planner writes `state/manifest.txt` listing spawned paths. Daemon watches those `directive.md` files; when every entry is `# Report`, daemon re-invokes planner in aggregate mode.

**Design note.** The stock **planner → # Plan → parallel workers → manager aggregate** loop already covers most decomposition. A manifest watcher adds coupling (extra file or brittle path parsing) with modest upside; **conductor**, **REQ gates**, and deliberate human follow-up fit cross-role SDLC better. A light future option is a **`## Manifest:`** stanza inside the planner's **# Plan** listing spawned paths — still optional. Unshipped until a team hits a concrete unattended-synthesis pain.

#### 2. "Seer" / observability role — **Shipped**

Originally proposed as a sixth role; the stock roster now includes **`seer`** (`roles.sh`), read-only digest across managers, plus **`seer-tick.sh`** for periodic nudges. See `lib/role-prompts/seer.md`.

#### 3. Auditor / QA role — **Shipped**

**`auditor`** ships as a first-class manager role. **Human QA / release discipline** is layered with **`qa`** and CI (v1.4 SDLC). Automated "dispatch auditor after every report" is still convention-driven — not a separate daemon trigger.

#### 4. "Memory" role — **Shipped**

**`memory`** edits spine docs + per-role `memory.md` per **`PROTOCOL.md`**. Install seeds team dirs and prompts.

#### 5. Worker timeouts + `## Long job:` — **Shipped** (v1.4.3)

Every manager/worker daemon wraps the executor in **`timeout`** when **`timeout`/`gtimeout`** is on `PATH`. **`INVOCATION_TIMEOUT_S`** (default 25 minutes) is the baseline. **`## Long job:`** on a specific **`directive.md`** or **`workers/NN-directive.md`** may **raise** only **that invocation's** wall ceiling (values at or below default are ignored — never stricter) and scale the stall watcher (**`min(wall_seconds/3, 30m)`**, floor **60s**) **when** the wall budget is actually extended. **`yes`/`true` ⇒ 90 minutes** shortcut. **`costs.csv`** records **`outcome`** separately from **`rc`** — **`timeout`** is attributed only when the timeout wrapper ran (**§13**, **§13b**).

#### 6. Heartbeat / stall handling — **Shipped**

Stall detection kills a stuck agent when the agent log stops growing for **`STALL_THRESHOLD_S`**. Watchdog restarts managers with stale heartbeats.

#### 7. Cost / budget tracking — **Shipped**

`teams/<role>/state/costs.csv` + **`make team-budget`** / **`bash scripts/team.sh budget`**.

#### 8. Conflict resolution for shared files — **Partial**

**`scripts/file-lock.sh`** provides atomic acquire/release. **PROTOCOL.md** documents usage. The daemon does **not** automatically wrap every edit — workers still rely on **file scope** in directives and optional lock calls.

#### 9. Web dashboard — **Shipped** (Spine Control Center)

**v1.4.1** replaced the old single-pane sketch with **Spine Control Center** in **`lib/dashboard.html`** (installed to **`.planning/orchestration/dashboard/index.html`**): tabbed UI (Overview, costs & tiers, program, docs, help), filters, per-role cards, detail drawer (manager text, workers 01–10, costs CSV, rollback hints), path presets, safer polling. Serve from **orchestration root** via **`make dashboard`** / **`scripts/serve-dashboard.sh`** so relative fetches resolve.

Optional **Tier-1** extensions (live actions, host metrics, authenticated APIs) remain **out of scope** for the static template — build on top if you need them.

#### 10. Cross-project knowledge — **Shipped**

**`~/.spine-development/playbook/<role>/lessons.md`** + **`team learn`**. Role prompts reference playbook habits.

#### 11. Auto-summarization (TL;DR) — **Shipped**

**`## TL;DR`** (≤5 lines) is required in manager reports per prompts and aggregate instructions in the daemon.

#### 12. Pattern library (recipes) — **Shipped**

**`recipes/`** is copied on install / knowledge pull. Grow it with your own directive shapes.

### What to build next (if anything)

1. **Planner manifest aggregation** (§1) — largest remaining *code* gap called out here.
2. **Auto file-lock** or stricter merge workflow — if parallel editors keep colliding despite file-scope rules.

Do not pre-build abstractions before real friction appears.
