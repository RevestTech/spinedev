# Spine — Master Reference

> **Always read this first.** Single source of truth for what Spine *is*, what it
> *must do*, what exists today, and what is still unwired.
>
> **Origin session:** [`docs/_archived/chatsession-2026-05-17.md`](_archived/chatsession-2026-05-17.md)
> (design conversation that locked v3). **Locked decisions:**
> [`V3_DESIGN_DECISIONS.md`](V3_DESIGN_DECISIONS.md). **Product reqs:**
> [`PRD.md`](PRD.md). **Launch gate (ops only):**
> [`V1_SHIP_CHECKLIST.md`](V1_SHIP_CHECKLIST.md).
>
> **Last updated:** 2026-05-23

---

## 1. What Spine is

**An AI software company in a box** — not a vibecoder, not SaaS, not a template
you drop into a project.

You are the founder. Spine provides **AI employees** (roles) — each an expert
anchored in industry methodology (Scrum, PMBOK, NIST, SRE, TOGAF, etc.). You
bring an idea; the **company** runs SDLC: intake → plan → build → verify →
release → operate. You approve at gates; roles **push** decision cards and
briefings (#5). Everything is audit-trailed (#24). Secrets stay in vault (#9).

**The Hub IS the product (#3).** Generated customer apps live under
`~/spine-projects/<uuid>/` (or `SPINE_PROJECTS_DIR`) — never in this platform
repo. **Exception — Spine-on-Spine dogfood:** projects with
`metadata.spine_on_spine=true` write to `.spine/dogfood/<uuid>/` by default
(`tools/spine-on-spine.sh`). Set `SPINE_ON_SPINE_ALLOW_REPO_WRITE=1` only when
you intend to patch the platform repo directly.

### Institutional hybrid (#13)

| Layer | Who | What |
|---|---|---|
| **Governance** | Spine Hub | Phases, decision queue, audit, vault, KG, role charters |
| **Execution** | Claude / Cursor / subagents | Work inside a named role under one directive |
| **Human** | Founder | Approves at gates — not every subagent spawn |

The **engineer** role is a squad lead: optional FE/BE/DB subagents
(`build/runtime/engineer_squad.py`) merge into one sealed commit. Session
multi-agent ≈ temporary task force; Spine ≈ durable org chart + records.

---

## 2. What the system is supposed to do

### 2.1 User journey (golden path)

| Step | Human | Spine |
|---|---|---|
| 1 | Opens Hub, creates greenfield project | Seeds project in `intake`; briefing card in Decision Queue |
| 2 | Answers intake questions | **Product** role runs 5-move protocol → **PRD** artifact |
| 3 | Approves PRD card | Phase advances; **Architect + swarm** → **TRD** |
| 4 | Approves TRD / roadmap cards | **Planner + Conductor** → **Roadmap** (INIT→EPIC→STORY) |
| 5 | Approves sprint plan | **Engineer** (hybrid #13: Claude Code/Cursor wrapper) writes code to project workspace |
| 6 | Approves code / review | **Security + Auditor** review; **DevOps** prepares deploy |
| 7 | Approves release | **Release manager** + **Operator** deploy to customer cloud |
| 8 | Requests new feature later | Same pipeline; **KG** holds institutional memory |

### 2.2 SDLC phases (canonical)

Source: `plan/artifacts/sdlc-pipeline-default.yaml` +
`orchestrator/state/phases.yaml`.

```
intake → plan_in_progress → plan_approved → build_in_progress → build_complete
  → verify_in_progress → verify_approved → acceptance → released
  → operate → retro
```

Each phase has: **role_lead**, optional **swarm**, **artifact**, **gate**,
**tier_default** (LLM cost routing).

### 2.3 Role hierarchy (#8)

| Tier | Roles | Behavior |
|---|---|---|
| **Master** (Director) | Product, Architect, Conductor, Engineer, QA, DevOps, Security, Release, Compliance | Portfolio view; daily briefings; bounded emergency override |
| **Project** | Same disciplines per project | Execute SDLC for one product |

Charters: `shared/charters/*.md` (18 roles). Registry: `shared/charters/__init__.py`.

### 2.4 Three layers (from design session — do not invert)

```
┌─────────────────────────────────────────────────────────┐
│ ORCHESTRATION — between roles                           │
│ bash/router.sh, phase transitions, daemons, file bus    │
│ Hub ack → router.sh → MCP (plan/build/verify)           │
├─────────────────────────────────────────────────────────┤
│ ROLE EXECUTION — within one role                        │
│ charter + tools + optional LangGraph swarm (architect)  │
│ directive → worker reports → aggregate → artifact       │
├─────────────────────────────────────────────────────────┤
│ CAPABILITY — shared primitives                          │
│ KG, shared/llm/, TRON, vault, audit, notify, devops     │
└─────────────────────────────────────────────────────────┘
```

LangChain/LangGraph lives **inside roles** (swarm, RAG), never replaces
orchestration.

### 2.5 Central brain — Knowledge Graph (two layers)

The graph is Spine's **memory**. It has **two layers** — do not conflate them.

#### Layer A — Per-project graph (primary for build/verify)

**Every Project Spine gets its own graph** describing *that project's codebase*.

| What | Where |
|---|---|
| **Actual bytes (source of truth)** | **Git repo** in `~/spine-projects/<uuid>/` — real files, real commits |
| **Graph (map of meaning)** | Postgres `spine_kg.*` — nodes/edges keyed by `repo` + `commit_sha` + `path` |

The graph does **not** replace git. It **explains** git:

- Which files, functions, classes, imports, tests exist
- How they call and depend on each other
- How PRD/TRD/roadmap nodes link to code regions
- Which commit each fact was true at (`commit_sha`, bitemporal `valid_from`/`valid_to`)

**On every git commit** in the project repo, the indexer updates the graph for
that commit only (incremental). Hook: `build/kg/indexer_commit_hook.py`
(installs `post-commit`). Roles query via MCP/API with `project_id` + `repo`.

Plain English: *Git holds the music. The graph holds the sheet music and
annotations so every AI employee knows what's in the codebase without re-reading
every file every time.*

#### Layer B — Hub / portfolio graph (secondary)

Cross-project lessons, Master role aggregation, federation, Smart Spine (#27).
Default ON within-Hub; cross-org opt-in. Does not substitute for Layer A.

#### Required behavior (PRD REQ-INIT-10)

- Every role dispatch: **retrieve** from the **project graph** (Layer A) first
- Every role artifact / code change: **index back** into Layer A at commit time
- Cite-or-Refuse (#12): citations point at `kg_node` IDs or `file:line`, backed
  by git at a known `commit_sha`

**Schema:** `spine_kg.kg_node` / `kg_edge` (Flyway V2+). **Indexers:**
`build/kg/` (commit hook, audit subscriber, sweep). **Tools:**
`shared/mcp/tools/kg.py`, `shared/api/routes/kg.py`.

### 2.6 Loops and daemons

Process must **advance without the user clicking "next"** between roles:

1. **Phase watcher** — sees pending work / approved gate → calls orchestrator
2. **Role daemons** — poll directive files (or equivalent queue), invoke agent,
   write report, checkpoint
3. **Verify loop** — verify fail → auto-remediate to build (#12, router.sh)
4. **Operate loop** — heartbeat, drift, dependency updates (devops planes)

Design session explicitly: *"Don't replace bash daemon + file bus — debuggability
moat."* v3 may implement daemons in Python, but **per-role runtime** must exist;
one API handler calling LLM is not the product.

---

## 3. Master component registry

| Component | Purpose | Key paths | Wired in Hub demo? |
|---|---|---|---|
| **Hub** | Containerized product + SPA | `hub/`, `shared/ui/spa/`, `tools/hub-up.sh` | Yes (UI) |
| **Orchestrator** | Phase machine + routing | `orchestrator/`, `orchestrator/lib/router.sh`, `phases.yaml` | **Wired** — `_post_ack` → MCP bridge; inline LLM fallback removed |
| **Plan** | Intake, PRD, TRD, roadmap | `plan/`, `plan/runtime/intake_runner.py` | **Partial** — intake chat + hub runners for plan roles |
| **Build** | Engineer dispatch, KG, artifacts | `build/runtime/build_dispatcher.py`, `build/kg/` | **Partial** — hub runner + hybrid + squad lead |
| **Verify** | TRON + cite-or-refuse | `verify/tron/`, `verify/runtime/hub_verify_runner.py` | **Wired** in approval chain via MCP |
| **DevOps** | 8 control planes, deploy | `devops/`, `devops/runtime/hub_deploy_runner.py` | **Partial** — local deploy via orchestrator |
| **Shared LLM** | All model calls (#2) | `shared/llm/` | Yes (when key set) |
| **Shared secrets** | Vault-only (#9) | `shared/secrets/` | Dev: InMemoryAdapter |
| **Charters** | Role identity + authority (#7) | `shared/charters/` | Loaded as prompt text only |
| **MCP** | Tool surface (54 tools) | `shared/mcp/` | In-process; Hub REST wraps some |
| **API routes** | Hub REST | `shared/api/routes/` | **Wired** — `_post_ack.py` orchestrator-only; gap cards on miss |
| **Decisions** | Active push queue (#5) | `shared/api/routes/decisions.py` | Yes |
| **Audit** | Hash chain (#24) | `shared/audit/` | Yes |
| **Federation** | Hub-to-Hub (#10) | `federation/` | Scaffold |
| **License** | Feature flags (#23) | `license/` | Scaffold |
| **Evidence** | SOC2 exporters (#24) | `evidence/` | Scaffold |
| **Learning** | Smart Spine 3-tier (#27) | `learning/` | Scaffold |
| **Recovery** | 12-layer DR (#31) | `recovery/` | Scaffold |
| **Migration** | Export/import (#33) | `migration/` | Scaffold |

**Honest status:** Golden-path **scaffolding is wired** (orchestrator bridge,
hub runners, KG retrieve, TRON verify, engineer hybrid + squad). Still need a
**real founder walkthrough** (§9) before v1 ship. Full role worker queues and
Smart Spine (#27) remain open.

---

## 4. Gap matrix — session intent → today → fix

Priority order for making Spine deliver on the promise.

| P | Intent (design session) | Today | Fix |
|---|---|---|---|
| **P0** | Hub approval → orchestrator → MCP dispatch | Inline LLM fallback in `_post_ack.py` | **Wired** — `_require_orchestrate_hub_role`; gap cards on miss |
| **P0** | Valid LLM keys in Hub | Placeholder `ANTHROPIC_API_KEY` breaks intake | Export real key; `hub-up.sh --rebuild` |
| **P0** | Phase daemon advances work | User must manually trigger; no watcher | Phase watcher loop: gate cleared → dispatch next role |
| **P0** | Per-role runtime (directives/workers) | v1 daemons deleted (Wave 6); no replacement | **Partial:** `shared/runtime/role_runtime.py` directive bus; full worker queue TBD |
| **P1** | KG retrieve on every dispatch | KG indexers exist; roles don't query | **Wired:** `kg_role_context.py` → bridge + hub runners |
| **P1** | **Per-project graph ↔ git repo** | Schema has `repo`+`commit_sha`; hook exists; not auto-installed on new projects | **Wired:** `project_workspace.py` on project create; engineer commits trigger indexer |
| **P1** | KG index on every artifact | Partial indexer hooks | **Wired:** plan markdown → `docs/` + commit; engineer via post-commit hook |
| **P1** | Architect swarm (LangGraph) | Charter text only | **Wired:** `architect_swarm_runner.py` → `run_swarm` in Hub architect dispatch |
| **P1** | Engineer hybrid (#13) | Monolithic codegen in `_post_ack.py` | **Wired:** hybrid + squad lead (`engineer_squad.py`) |
| **P1** | TRON verify in loop | TRON exists; Hub shortcut skips | Ack chain → `verify_audit` MCP → remediate on fail |
| **P1** | DevOps deploy + maintain | Planes scaffolded | **Partial:** `local_deploy_prompt` → orchestrator → container deploy |
| **P2** | Master role daemons + briefings | SPA panels | **Wired:** `master_briefing.py` loop + `/registry/master-briefings/preview` |
| **P2** | Smart Spine learning (#27) | MCP tools exist | **Partial:** `smart_spine_bridge.py` on dispatch success + memory writer_hooks via audit |
| **P2** | Federation / license polish | Built as libraries | Defer until golden path works |

---

## 5. Documentation map

Read in this order. Do **not** treat overlapping docs as equal authority.

| Order | Doc | Use when |
|---|---|---|
| **0** | **`docs/SPINE_MASTER.md`** (this file) | Always — vision, gaps, component list |
| 1 | `docs/V3_DESIGN_DECISIONS.md` | Why a decision was locked (#1–#34) |
| 2 | `docs/PRD.md` | Detailed REQ acceptance criteria |
| 3 | `docs/ARCHITECTURE.md` | Subsystem boundaries + data flow |
| 4 | `docs/V3_BUILD_SEQUENCE.md` | Historical wave execution order |
| 5 | `docs/V1_SHIP_CHECKLIST.md` | Customer launch / ops gates only |
| 6 | Operational guides | `HUB_OPERATIONS_GUIDE`, `DEPLOYMENT_SHAPES`, etc. |

### Historical / deprecated — do not extend

| Doc / path | Status |
|---|---|
| `docs/_archived/chatsession-2026-05-17.md` | **Origin transcript** — reference only |
| `docs/_archived/v1-PROTOCOL.md`, `v1-REQUIREMENTS.md`, `v1-IMPROVEMENT_CHECKLIST.md`, `v1-PRACTICES.md` | v1/v2 file-bus — **retired** |
| `lib/` (removed) | Was deprecated role prompts; use `shared/charters/` |
| `docs/STATUS.md` | Wave log; **superseded for "what to build"** by this file |
| `docs/BACKLOG.md` | Story IDs; use gap matrix §4 for current priorities |
| `HANDOFF_FOR_AGENT.md` | Removed — use this file instead |

---

## 6. Repository hygiene

### Belongs in platform repo

- Hub, orchestrator, plan, build, verify, shared/*, subsystems, db/flyway, tools/
- Charters, pipeline manifests, tests co-located with subsystems

### Does NOT belong (never commit)

- Generated customer apps → `~/spine-projects/<uuid>/`
- Agent scratch → `.spine/work/<run_id>/` (sweep with `make hygiene`)
- Secrets / `.env` with real values (#9)
- One-off experiments at repo root

### Removed scratch (2026-05-21)

- `fishtanks/` — generated demo app (wrong place)
- `downloads_organizer.py` + `tests/test_organizer.py` — unrelated utility

---

## 7. How to run the golden path (local)

```bash
export ANTHROPIC_API_KEY='sk-ant-...'   # real key, not placeholder
bash tools/hub-up.sh --rebuild
open http://localhost:8090/spa/
```

Create project → intake chat → approve Decision Queue cards through PRD → plan
→ build → verify → release. Code lands in `~/spine-projects/<uuid>/`.

**Spine-on-Spine dogfood:**

```bash
bash tools/hub-up.sh --rebuild
bash tools/spine-on-spine.sh "Improve phase watcher"
bash tools/golden-path-walkthrough.sh "Automated founder walkthrough"
```

Engineer output lands in `.spine/dogfood/<uuid>/` unless repo write is enabled.
Workspace zip/list/read routes use `resolve_code_dir` (dogfood-aware).

**Smoke contract:** `bash tools/smoke-test.sh` → 99 PASS / 0 FAIL.

---

## 8. Execution tracker (living)

Check off as wired. Update this section when a gap closes.

- [x] P0: `_post_ack.py` → `router.sh` / MCP only (phase + role dispatch bridges)
- [x] P0: Phase watcher daemon (`shared/runtime/phase_watcher.py`, Hub lifespan)
- [x] P0: Per-role runtime (`shared/runtime/role_runtime.py` directive bus under `.spine/work/`)
- [x] P1: KG retrieve on dispatch (`shared/runtime/kg_role_context.py` + bridge/runners)
- [x] P1: Per-project git repo + post-commit indexer (`shared/runtime/project_workspace.py` on project create)
- [x] P1: Architect LangGraph swarm (`plan/runtime/architect_swarm_runner.py`)
- [x] P1: Engineer hybrid (#13) (`build/runtime/engineer_hybrid.py` + executor.sh)
- [x] P1: Engineer squad lead (#13) (`build/runtime/engineer_squad.py` FE/BE/DB subagents)
- [x] P1: Inline LLM fallback removed (`_require_orchestrate_hub_role` + gap cards)
- [x] P1: Spine-on-Spine dogfood (`resolve_code_dir`, `tools/spine-on-spine.sh`)
- [x] P1: Plan artifact git promotion (`promote_plan_artifacts` → `docs/` + KG commit)
- [x] P1: TRON in Hub approval chain (`verify_hub_review` MCP + workspace artifact seal)
- [x] P1: DevOps deploy on release gate (`local_deploy_prompt` → orchestrator → `hub_deploy_runner`)
- [x] P2: Master role briefings (`shared/runtime/master_briefing.py` + registry preview)
- [x] P2: Smart Spine dispatch hook (`shared/runtime/smart_spine_bridge.py`)
- [x] Golden path post-ack tests (`shared/api/tests/test_post_ack_golden_path.py`)
- [x] Golden path dry-run tool (`tools/golden-path-dry-run.sh`)
- [x] Golden path walkthrough automation (`tools/golden-path-walkthrough.sh`)
- [x] Dogfood workspace API (`resolve_code_dir` in zip/list/read + verify artifact)

---

## 9. One-line test

> *Can a non-engineer founder describe an app, approve a handful of cards, and
> receive a deployed, maintained product — with every step performed by named
> expert roles, backed by the knowledge graph and audit chain?*

If no → keep working §4 P0/P1. If yes → proceed to `V1_SHIP_CHECKLIST.md`.
