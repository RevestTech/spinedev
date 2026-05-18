# Spine — Unified Architecture (v2.0)

| | |
|---|---|
| **Status** | **Approved** (locked 2026-05-16 by Khash) |
| **Last updated** | 2026-05-16 |
| **Sources** | `docs/research/COMPETITIVE_LANDSCAPE.md`, TRON evaluation (2026-05-16 session), 5-move protocol applied recursively |
| **Supersedes (when approved)** | Single-project assumption implicit in pre-v2 backlog. INIT-1 narrows to "Plan"; new INIT-7/8/9 added for Build, Verify (TRON), Orchestrator. |

---

## 1. Executive summary

Spine v2 is a **single product, three subsystems, one central orchestrator**, delivered as a **monorepo**. It unifies the Spine (orchestration / SDLC) and TRON (verification / audit) projects under one umbrella while preserving each subsystem's independent excellence. The product implements real-life SDLC: **Plan → Build → Verify**, coordinated by a central state machine that owns the lifecycle, gates, routing, cost, and audit. Authority is bounded by role; the pipeline is customizable by authorized roles via declarative manifests; standards / policy / budget are enforced by org bundles. Local-deploy. No SaaS lock-in. Costs controlled by tier-aware routing.

The five-corner moat from the competitive research remains: *local-deploy + multi-agent + role-bounded + SDLC-gated + requirements-first*. Spine v2 adds a sixth corner: *verification-as-first-class-phase* (TRON-grade), which none of Devin / Factory / Cursor / ruflo / MetaGPT match.

---

## 2. Architecture

```
                    ┌───────────────────────────────────────────┐
                    │         SPINE ORCHESTRATOR                │
                    │                                           │
                    │  Lifecycle state machine                  │
                    │  Phase gates + user approvals             │
                    │  Routing: dispatch to Plan / Build / Verify│
                    │  Reroute on Verify failure                │
                    │  Unified cost ledger + audit log          │
                    │  Portfolio mgmt (many projects)           │
                    │  Single user-facing UI + API              │
                    └───┬───────────────┬───────────────┬───────┘
                        │               │               │
                  ┌─────▼────┐    ┌─────▼─────┐    ┌────▼────────┐
                  │   PLAN   │    │   BUILD   │    │   VERIFY    │
                  │          │    │           │    │             │
                  │ intake   │    │ engineer  │    │ scanners +  │
                  │ PRD      │    │ operator  │    │ ISO agents +│
                  │ TRD swarm│    │ datawright│    │ sandbox +   │
                  │ roadmap  │    │ + roles   │    │ cross-LLM + │
                  │          │    │ + KG/MCP  │    │ calibration │
                  └──────────┘    └───────────┘    └─────────────┘
                  (Spine native)   (Spine native)   (TRON → integrated)

                  ▲                  ▲                  ▲
                  └──────────────────┼──────────────────┘
                                     │
                  ┌──────────────────▼──────────────────┐
                  │     CROSS-CUTTING FOUNDATION         │
                  │                                      │
                  │  • Knowledge Graph (INIT-6)          │
                  │  • Standards / Policy (INIT-2 +      │
                  │    TRON Standards Hierarchy)         │
                  │  • MCP server (shared)               │
                  │  • Cost router (EPIC-1.5)            │
                  │  • Audit log (INIT-3)                │
                  │  • Memory & lessons                  │
                  │  • Postgres backbone (db/)           │
                  └──────────────────────────────────────┘
```

**Why this shape:**
- **Plan / Build / Verify mirrors real SDLC** — same nouns enterprises use. Easy to map to org structures.
- **Orchestrator is a thin coordinator**, not a smart agent — owns state, routing, gates, lifecycle. Subsystems remain independently testable and deployable.
- **Cross-cutting foundation prevents duplication** — one MCP server, one cost ledger, one audit log, one KG, one standards hierarchy, one memory layer. Each lives in `shared/`.
- **Subsystem isolation preserved** — `verify/` (TRON) can still run standalone for audit-only deployments. `plan/` and `build/` can be exercised without Verify for trusted contexts.

---

## 3. Locked decisions

| # | Decision | Choice | Rationale |
|---|---|---|---|
| 1 | Umbrella name | **Spine** (working) | Metaphor fits the orchestrator role; rename freely later once brand exploration matures |
| 2 | Top-level shape | **Plan + Build + Verify + Orchestrator** | Maps to real-life SDLC; matches enterprise vocabulary |
| 3 | Repository | **Monorepo** | Atomic cross-cutting changes, single CI/release, single docs hub — right for solo-dev product |
| 4 | Orchestrator stack | **Hybrid: bash core + Postgres state + Python workers** | Bash for the orchestrator state machine (debuggability moat preserved); Python for heavy verification work where TRON already lives. Communicate via MCP/REST. No forced language consolidation. |
| 5 | TRON integration | **`git subtree` into `verify/`** | Preserves TRON's git history; TRON keeps internal cohesion; no submodule complexity for a single-developer product |
| 6 | Migration | **Phased / incremental** | No big-bang refactor; move code only when touching it; both halves keep working throughout |
| 7 | TRON Standards Hierarchy | **Lift into `shared/standards/`** | TRON already shipped what Spine INIT-2 is designing. Don't reinvent. |
| 8 | Postgres backbone | **Single instance, multiple schemas** | One `db/` Postgres serves recording layer + KG + orchestrator state + audit. No new infra. |

---

## 4. Repository structure (target)

```
spine/   (working repo name; rename later)
├── README.md                    # umbrella product README
├── CHANGELOG.md                 # unified releases
├── Makefile                     # umbrella task runner — dispatches per-module
├── pyproject.toml               # umbrella Python workspace
├── docker-compose.yml           # umbrella deployment (orchestrator + verify + ui)
│
├── docs/                        # SINGLE docs hub
│   ├── README.md
│   ├── ARCHITECTURE.md          ← this file
│   ├── PRD.md                   # all product requirements (REQ-INIT-N sections)
│   ├── BACKLOG.md               # operational backlog
│   ├── PRACTICES.md             # operating practices (drift / delivery / extensions)
│   ├── IMPROVEMENT_CHECKLIST.md # maintenance checklist
│   └── research/                # competitive landscape, future research
│
├── orchestrator/                # NEW — central lifecycle state machine
│   ├── lib/                     # state machine logic (bash + minimal Python)
│   ├── state/                   # Postgres schema for project lifecycle
│   ├── api/                     # MCP + REST surface
│   └── tests/
│
├── plan/                        # PLAN SUBSYSTEM (intake → PRD → TRD → Roadmap)
│   ├── roles/                   # product, architect, planner, swarm roles
│   ├── templates/               # intake templates per project type
│   ├── artifacts/               # PRD/TRD/Roadmap schemas (Pydantic — lifted from TRON pattern)
│   └── tests/
│
├── build/                       # BUILD SUBSYSTEM (existing Spine roles)
│   ├── roles/                   # engineer, operator, datawright
│   ├── daemons/                 # bash daemon infra
│   ├── workers/                 # worker pool primitives
│   ├── kg/                      # knowledge graph (INIT-6) — feeds Plan + Build + Verify
│   └── tests/
│
├── verify/                      # VERIFY SUBSYSTEM (TRON → integrated via subtree)
│   ├── agents/                  # ISO agents (SecurityISO, BuilderISO, QAISO, …)
│   ├── pipeline/                # 7-layer verification
│   ├── sandbox/                 # docker sandbox primitives
│   ├── workflows/               # Temporal workflows (preserved)
│   ├── calibration/             # Platt scaling
│   ├── api/                     # FastAPI routes (verify-internal)
│   └── tests/
│
├── shared/                      # CROSS-CUTTING (used by 2+ subsystems)
│   ├── db/                      # ← move existing db/ here; Postgres schemas: recording, kg, lifecycle, audit
│   │   ├── flyway/
│   │   ├── docker-compose.yml
│   │   └── watcher/
│   ├── mcp/                     # unified MCP server
│   ├── cost/                    # cost router + ledger
│   ├── audit/                   # audit log
│   ├── memory/                  # role memory + cross-project playbook
│   ├── standards/               # org policy bundles (lifted from TRON Standards Hierarchy)
│   └── ui/                      # dashboard / front-door UI (React, lifted from TRON frontend/ + admin-ui/)
│
├── lib/                         # legacy Spine bash — transitional, drains as we touch code
├── scripts/                     # legacy Spine scripts — transitional
├── recipes/                     # existing Spine recipes (stay)
├── templates/                   # existing Spine templates (stay until migrated to per-subsystem templates)
└── tools/                       # repo-level dev tooling
```

**Notes:**
- Existing `db/` directory moves under `shared/db/` in Phase 2.
- Existing `lib/` and `scripts/` are *transitional*; they drain as feature work touches the files. No mass migration.
- TRON's `frontend/` + `admin-ui/` merge into `shared/ui/` (frontend is current; admin-ui retires per TRON's own roadmap).
- TRON's `docker-compose.yml` either moves into `verify/docker-compose.yml` (verify-only) or its services are pulled up into a root `docker-compose.yml` that composes orchestrator + verify + ui + db together. Decision in Phase 1.

---

## 5. TRON → Spine code mapping

| TRON path (today) | Spine path (new) | Notes |
|---|---|---|
| `tron/agents/` | `verify/agents/` | ISO agents — core verify logic |
| `tron/verification/` | `verify/pipeline/` | 7-layer verification pipeline |
| `tron/sandbox/` | `verify/sandbox/` | Docker sandbox + seccomp |
| `tron/workflows/` | `verify/workflows/` | Temporal workflows |
| `tron/api/` | `verify/api/` | FastAPI routes |
| `tron/schemas/` | `verify/schemas/` (or `shared/schemas/` for cross-used) | Pydantic models |
| `tron/services/` | per-service split into `verify/` or `shared/` | E.g., `threat_intel.py` → `verify/services/`; `scan_handoff_export.py` → `shared/services/` |
| `tron/standards/` | `shared/standards/` | Standards Hierarchy — cross-cutting |
| `tron/mcp/` | `shared/mcp/` | Single MCP server for whole product |
| `tron/memory/` | `shared/memory/` | Cross-cutting memory |
| `tron/parsers/` | `build/kg/parsers/` | Tree-sitter parsers feed the KG |
| `tron/infra/` | `shared/infra/` | Secrets, vault, db helpers |
| `tron/realtime/` | `shared/realtime/` | Realtime infra (WebSocket / SSE) |
| `tron/agent_handoff_templates/` | `verify/agent_handoff_templates/` | Verify-specific output templates |
| `tron/cli.py` | `verify/cli.py` + integrate into umbrella CLI | Verify-specific subcommands surface through umbrella `spine verify ...` |
| `frontend/` | `shared/ui/` | Active SPA |
| `admin-ui/` | retire per TRON roadmap | Already scheduled for removal |
| `alembic/` | `shared/db/alembic/` | Postgres migrations consolidate with Flyway story (decide one tool) |
| `docs/` (TRON) | merge into `docs/` (Spine) under `docs/verify/` subdir | Preserve all TRON docs; namespace under verify |
| `tests/` | distribute per module to `verify/tests/` etc. | Or keep root `tests/` for integration-level tests |

---

## 6. Migration phases

### Phase 0 — Structure scaffold (this week)
**Risk: zero.** No code moves.

- Create empty top-level dirs (`orchestrator/`, `plan/`, `build/`, `verify/`, `shared/`).
- Write this architecture plan + memory entries.
- Update `docs/BACKLOG.md` to add INIT-7/8/9 and re-scope INIT-1.
- Commit; everything still works.

### Phase 1 — TRON in (next 1-2 sprints)
**Risk: low.** TRON keeps working standalone.

- `git subtree add --prefix=verify/ <tron-repo> main` — preserves TRON's history.
- Update TRON's internal paths if needed (most should be relative and survive the move).
- Adjust TRON's Docker compose paths.
- Run TRON's existing test suite from new location — verify everything passes.
- Update umbrella Makefile to dispatch `make verify-*` targets to TRON's existing Makefile.

### Phase 2 — Shared infrastructure (sprints 2-3)
**Risk: medium.** Touches both halves.

- Move `db/` → `shared/db/` (Spine recording layer).
- TRON's Postgres schemas (`alembic/`) merge with Spine's Flyway migrations under `shared/db/` — pick one migration tool (recommend Flyway per Spine convention; Alembic migrations port to Flyway SQL).
- TRON's `standards/` → `shared/standards/` — wire Spine roles to consume it.
- TRON's `mcp/` → `shared/mcp/` — establish single MCP server.
- TRON's `memory/` → `shared/memory/` (preserves Spine's role-memory pattern).

### Phase 3 — Orchestrator + Plan subsystem (sprints 3-5)
**Risk: medium.** New code, but in greenfield.

- Build orchestrator state machine (bash + Postgres schema in `orchestrator/state/`).
- Build Plan subsystem per `PRD.md#req-init-1` — 5-move dialogue protocol, PRD/TRD/Roadmap artifacts.
- Wire Plan → Build → Verify happy-path end-to-end (each subsystem bare-bones; integration thread complete).

### Phase 4 — Drain legacy + thicken subsystems (continuous)
**Risk: low (incremental).**

- Migrate Spine's `lib/` + `scripts/` into `plan/`, `build/`, `shared/` opportunistically as features touch them.
- Build INIT-6 Knowledge Graph per its REQ.
- Fill in Verify integration points (TRON ISO agents callable from Spine build flow).
- Retire `lib/`, `scripts/` when drained.

---

## 7. Backlog restructure

### INITs after restructure

| INIT | Title | Scope | Status |
|---|---|---|---|
| INIT-1 | **Plan Subsystem** (was: SDLC Front Door) | Intake, PRD, TRD swarm, Decomposition, approval gates, cost router, pipeline customization, front-door UI | Exists, narrow rename |
| INIT-2 | **Enterprise Control & Standards** | Org policy bundles + MCP server + spend caps. **Absorbs TRON Standards Hierarchy.** | Exists, expanded |
| INIT-3 | **Trust & Reproducibility** | Audit log, reproducible builds, eval harness (EPIC-3.4), **sandbox execution (from TRON), calibration (from TRON), cross-LLM validation (from TRON)** | Exists, expanded |
| INIT-4 | **Best-Practice Absorption** | Auto-triggering skills, vector memory, lite install path | Exists, unchanged |
| INIT-5 | **Positioning & GTM** | Public narrative, comparison page, naming, Jira export, research retention | Exists, unchanged |
| INIT-6 | **Code & Document Knowledge Graph** | Cross-cutting graph foundation for all three subsystems | Exists, cross-cutting role formalized |
| INIT-7 | **Build Subsystem** (NEW) | Formalize engineer / operator / datawright as a coordinated subsystem; integrate with KG + MCP + orchestrator | Add |
| INIT-8 | **Verify Subsystem — TRON Integration** (NEW) | git-subtree TRON into `verify/`; wire ISO agents callable from Spine; map TRON's pipeline as Spine SDLC verify phase | Add |
| INIT-9 | **Central Orchestrator** (NEW) | Lifecycle state machine, phase gates, routing, portfolio mgmt, unified cost+audit aggregation, user-facing surface | Add |

### REQs (all sections in `docs/PRD.md`)

| Section | Status |
|---|---|
| `PRD.md#req-init-1` | Draft v1 — awaiting sign-off; rename to reflect Plan-subsystem scope when restructure lands |
| `PRD.md#req-init-6` | Draft v1 — awaiting sign-off |
| `PRD.md#req-init-7` | To write (after this plan signs off) |
| `PRD.md#req-init-8` | To write |
| `PRD.md#req-init-9` | To write |

---

## 8. Sprint sequencing — first three sprints

Goal: working end-to-end skeleton in 3 sprints. Each subsystem bare-bones but the **thread** works.

### Sprint 1 — Foundation (1-2 weeks)
- [ ] Phase 0 + Phase 1 (TRON in via subtree)
- [ ] `INIT-9` orchestrator skeleton: Postgres `lifecycle` schema, project state table, phase-transition table
- [ ] Lift TRON Standards Hierarchy → `shared/standards/` (closes a duplicated INIT-2 design effort)
- [ ] Umbrella Makefile dispatching to per-module targets
- [ ] Smoke test: TRON's existing audit flow runs from new location

### Sprint 2 — End-to-end happy path (2-3 weeks)
- [ ] Orchestrator can create a project, transition through `intake → plan_done → build_done → verify_done`
- [ ] Plan subsystem: minimal `product` role prompt walks a user through one project type (web-app) and outputs a stub PRD
- [ ] Build subsystem: minimal `engineer` role takes the PRD, makes a trivial code change, writes a report
- [ ] Verify subsystem: TRON's `AuditManager` runs on the code change, returns findings
- [ ] Orchestrator routes Verify findings back to user; user approves → project marked `done`
- [ ] Cost ledger aggregates spend across all three subsystems

### Sprint 3 — Thicken Plan + start KG (2-3 weeks)
- [ ] Plan: full 5-move dialogue protocol (`STORY-1.1.1`)
- [ ] Plan: project-type templates for web-app, internal-tool, data-pipeline (`STORY-1.1.2`)
- [ ] Plan: PRD/TRD/Roadmap Pydantic schemas (`STORY-1.1.3`, lifted patterns from TRON `FindingOutput`)
- [ ] KG: `INIT-6` Phase 1 — schema (`STORY-6.1.1`) + tree-sitter parser scaffolding (`STORY-6.2.1`) + cold-start indexer (`STORY-6.4.3`)
- [ ] KG: first MCP tool (`find_callers`, `STORY-6.5.2`)
- [ ] Plan + KG: decomposer (`EPIC-1.3`) uses KG for story-dependency detection

After Sprint 3 the product has a working spine (pun retained) end-to-end. Sprints 4+ thicken each subsystem in parallel against the backlog.

---

## 9. Cross-cutting tech decisions (locked)

| Concern | Decision | Lives in |
|---|---|---|
| Orchestration core | Bash + Postgres | `orchestrator/lib/` + `orchestrator/state/` |
| Verify pipeline | Python + FastAPI + Temporal (TRON's existing stack) | `verify/` |
| Knowledge graph | Postgres `spine_kg` schema + pgvector + tree-sitter parsers | `shared/db/` + `build/kg/` |
| Hybrid graph+vector RAG | LangChain (`MultiVectorRetriever` + `GraphRetriever`) | `build/kg/` |
| Tech-review swarm | LangGraph subgraph inside architect daemon | `plan/roles/architect/` |
| Tier router | LangChain router primitives + Spine policy wrapper | `shared/cost/` |
| Eval harness | LangSmith-style harness (lift from TRON's `tests/golden_suite/`) | `shared/eval/` |
| MCP server | Unified server exposing tools from all subsystems | `shared/mcp/` |
| Audit log | Append-only Postgres schema; every action across subsystems writes here | `shared/audit/` |
| Standards / policy | Org bundles (lifted from TRON Standards Hierarchy) | `shared/standards/` |
| Memory & lessons | Per-role markdown + Postgres index | `shared/memory/` |
| UI | React (TRON's frontend), evolved into umbrella dashboard | `shared/ui/` |
| Sandbox execution | Docker ephemeral + seccomp (TRON's existing) | `verify/sandbox/` |
| Confidence calibration | Platt scaling + sklearn (TRON's existing) | `verify/calibration/` |
| Cross-LLM validation | TRON's existing AuditManager logic; expose for Plan + Build phases too | `shared/validation/` (lifted from `verify/`) |

---

## 10. Open questions / risks

### Open
- **OQ-1: Umbrella product name long-term.** Working name "Spine"; brand exploration deferred to a separate exercise once the architecture solidifies. No blocker.
- **OQ-2: One vs two migration tools.** TRON uses Alembic; Spine `db/` uses Flyway. Recommend converging on Flyway in Phase 2. Confirm.
- **OQ-3: Compose file consolidation.** Phase 2 decision — root-level compose (orchestrator + verify + ui + db) vs per-subsystem composes that wire together. Recommend root-level for production with per-subsystem composes for dev.
- **OQ-4: Single CLI surface.** Long-term, one `spine` CLI with subcommands (`spine plan ...`, `spine verify audit`, `spine status`). TRON's `tron` CLI subcommands become `spine verify` subcommands. Confirm.
- **OQ-5: TRON's "agent_handoff" model.** TRON writes findings into target apps' files. This is *exactly* the pattern Spine's Plan + Build could use to write artifacts back to a user's project. Worth promoting `agent_handoff` to a `shared/handoff/` module.

### Risks
- **R-1: Stack split (bash + Python) confuses contributors.** Mitigation: clean per-module conventions; module-level READMEs; umbrella Makefile abstracts the language difference.
- **R-2: Postgres schema sprawl.** Mitigation: one Postgres instance, but multiple schemas with clear ownership (`spine_recording`, `spine_kg`, `spine_lifecycle`, `spine_audit`, `spine_verify_*`).
- **R-3: TRON's existing deployment patterns (Vault, MinIO, multiple Docker services).** Mitigation: keep TRON's existing compose unchanged in Phase 1; consolidate in Phase 2 only if it simplifies.
- **R-4: Brand/naming churn if we rename later.** Mitigation: avoid hardcoding "spine" in user-facing strings; route brand via a single `BRAND_NAME` config var.
- **R-5: We're carrying two test suites (Spine bash, TRON pytest) until we converge them.** Mitigation: don't try to converge — each module owns its tests in its native style.

---

## 11. Sign-off checklist

When you sign off on this plan, the following happens (in order):

1. ✅ Memory: save unified architecture as durable decision
2. ✅ Backlog: restructure `docs/BACKLOG.md` — rename INIT-1 to "Plan Subsystem", add INIT-7/8/9, note cross-cutting role of INIT-6 + INIT-2 + INIT-3
3. ⏸ PRDs: write `PRD.md#req-init-7`, `PRD.md#req-init-8`, `PRD.md#req-init-9` (Draft v1 sections awaiting their own sign-off)
4. ⏸ Code: Phase 0 dirs creation (`orchestrator/`, `plan/`, `build/`, `verify/`, `shared/`) — defer until you say "go"
5. ⏸ Phase 1: `git subtree add` TRON — defer until you say "go" (also wants your call on whether to do it from current repo state or from a clean TRON branch)

**Steps 1-3 are docs-only; safe to execute on sign-off.** Steps 4-5 touch code/git and wait for an explicit "execute Phase 0" / "execute Phase 1" command.

---

## 12. Related artifacts

- `docs/research/COMPETITIVE_LANDSCAPE.md` — the *why* (the five-corner moat + TRON eval that justified this restructure)
- `docs/BACKLOG.md` — operational backlog (reflects this restructure)
- `docs/PRD.md` — product requirements (each REQ-INIT-N as a section with stable anchor)
- `docs/PRACTICES.md` — operating practices (drift, delivery, extensions)
- `docs/IMPROVEMENT_CHECKLIST.md` — maintenance checklist (unchanged)
- `PROTOCOL.md` (root) — full role/daemon protocol
- `~/.claude/.../memory/spine_positioning.md` — positioning
- `~/.claude/.../memory/spine_flexibility_principle.md` — pipeline-as-data
- `~/.claude/.../memory/spine_tech_stack_decisions.md` — where LangChain fits
- `~/.claude/.../memory/spine_unified_architecture.md` — pointer back to this file
