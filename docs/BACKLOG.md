# Spine — Master Product Backlog

> **Purpose.** Strategic, business-level backlog of Spine's product evolution, structured as **INITIATIVE → EPIC → STORY** so it maps cleanly to Jira (or Linear / GitHub Projects / etc.) when we're ready to import. Not a maintenance checklist — that lives in `IMPROVEMENT_CHECKLIST.md`.
>
> **Why it exists.** This document is the output of a Spine-style `product`-role conversation Khash + Claude ran on Spine itself: scrutinize the user → finalize requirements → hand off to SDLC. *We are using Spine on Spine.* Every story below should link back to `docs/research/COMPETITIVE_LANDSCAPE.md` for the *why*.
>
> **How to read it.** Pick an Initiative when planning a release; pick Epics when planning a sprint; pick Stories when generating directives. Mark status inline as work moves.

---

## ID scheme & legend

- `INIT-N` — Initiative (business-level goal)
- `EPIC-N.M` — Epic under initiative N
- `STORY-N.M.K` — Story under epic N.M

**Status:** `Backlog` (default) · `In Design` · `In Progress` · `Done` · `Won't Do`
**Priority:** `P0` (must — adoption blocker) · `P1` (should — material differentiator) · `P2` (nice — competitive parity) · `P3` (someday)
**Size:** `XS` (<1 day) · `S` (1-3 days) · `M` (1-2 weeks) · `L` (3-6 weeks) · `XL` (release-scale)

**Tier:** maps to `COMPETITIVE_LANDSCAPE.md §4` — Tier 1 (adoption), Tier 2 (enterprise), Tier 3 (trust), Tier 4 (absorption).

---

## Sprint Plan (active — 2026-05-16 onward)

> Three sprints to a **working end-to-end skeleton** (Plan → Build → Verify with central Orchestrator). After Sprint 3, sprints become backlog-driven against any INIT/EPIC you prioritize. Full rationale: `docs/ARCHITECTURE.md §8`.

### Sprint 1 — Foundation (1-2 weeks)
**Goal:** TRON merged in, orchestrator skeleton stood up, Standards Hierarchy lifted.

| Story | What |
|---|---|
| `STORY-8.1.1` | `git subtree add` TRON → `verify/` (preserves history) |
| `STORY-8.1.2` | Verify TRON's standalone tests pass from new location |
| `STORY-9.1.1` | Postgres `spine_lifecycle` schema (project, phase, transition tables) |
| `STORY-9.2.1` | State transition engine skeleton (bash) |
| `STORY-2.4.1` | Lift TRON `tron/standards/` → `shared/standards/` |
| `STORY-8.4.1` | Umbrella Makefile dispatching to per-module targets |
| `STORY-9.1.2` | Top-level dirs scaffolded (`orchestrator/`, `plan/`, `build/`, `verify/`, `shared/`) |

### Sprint 2 — End-to-end happy path (2-3 weeks)
**Goal:** Plan → Build → Verify thread works for one trivial project, end-to-end.

| Story | What |
|---|---|
| `STORY-9.3.1` | Phase gates enforced (no advance without approval token) |
| `STORY-9.4.1` | Routing layer: orchestrator dispatches directive to subsystem via MCP |
| `STORY-1.1.1` (stub) | Minimal `product` role: trivial intake → stub PRD |
| `STORY-7.1.1` | `build/` subsystem boundary + minimal engineer-daemon execution |
| `STORY-8.5.1` | Orchestrator invokes TRON `AuditManager` on engineer's output |
| `STORY-9.6.1` | Unified cost ledger aggregates Spine + TRON costs |
| `STORY-9.8.1` | Verify findings route back to user for approval; pipeline can loop back |

### Sprint 3 — Thicken Plan + start KG (2-3 weeks)
**Goal:** Real intake protocol; KG operational; decomposer deterministic.

| Story | What |
|---|---|
| `STORY-1.1.1` (full) | 5-move dialogue protocol in `product` role |
| `STORY-1.1.2` | Project-type templates (web-app, internal-tool, data-pipeline) |
| `STORY-1.1.3` | PRD Pydantic schema (pattern lifted from TRON `FindingOutput`) |
| `STORY-6.1.1` | KG schema design (`spine_kg` Postgres) |
| `STORY-6.2.1` | Tree-sitter parser scaffolding (v1 language set) |
| `STORY-6.4.3` | Cold-start full KG index |
| `STORY-6.5.2` | First MCP tool: `find_callers` |
| `STORY-1.3.3` (upgraded) | Decomposer uses KG for story-dependency detection |

### Sprint 4+ — Thicken in parallel (backlog-driven)
Once the end-to-end thread works, each subsystem thickens against its INIT in parallel. Recommended next epics: `EPIC-1.2` (Tech Review Swarm), `EPIC-6.6` (Role-Prompt KG integration), `EPIC-8.6` (TRON ISO agents callable from Build phase), `EPIC-3.4` (Eval harness — lift TRON's golden suite).

---

## INIT-1 — Plan Subsystem: intake → PRD → TRD → Roadmap (was: SDLC Front Door)

**Tier:** 1 · **Priority:** P0 · **REQ:** [`docs/PRD.md#req-init-1`](PRD.md#req-init-1) · **Why:** Spine's *defining* feature. A real-life SDLC pipeline that produces real artifacts (PRD, TRD, Roadmap) gated on user sign-off — not a chat window pretending to be agile. See `COMPETITIVE_LANDSCAPE.md §4 Tier 1`.

> **Restructured 2026-05-16.** Original INIT-1 had 3 epics (intake / UI / gates). Expanded to 7 epics to cover the full upfront SDLC pipeline (Discovery → Technical Review swarm → Decomposition), the cost-aware tier router that powers it, and the *flexibility principle* (pipeline-as-data, customizable by authorized roles). Old EPIC-1.2 / EPIC-1.3 content absorbed into new EPIC-1.4 / EPIC-1.6.

### EPIC-1.1 — Product Discovery (intake → PRD)
Maps to REQ FR-2. Implements the 5-move dialogue protocol producing a signed PRD.

- `STORY-1.1.1` · `Done` · `P0` · `M` — Implement the 5-move dialogue protocol in the `product` role prompt (naive cast → provoke → reframe → tier → artifact). At `lib/role-prompts/product.md` (240 lines) with per-project-type templates, refuse-to-advance, worked web-app example. *(Done 2026-05-16.)*
- `STORY-1.1.2` · `Done` · `P0` · `M` — Author project-type intake templates: web-app, internal-tool, data-pipeline, mobile, api-service, cli-tool. ~10 questions each. Live in `plan/templates/intake/<type>.yaml`. *(Done 2026-05-16.)*
- `STORY-1.1.3` · `Done` · `P0` · `S` — Define the `prd-v1` template schema (problem, users, MUST/SHOULD/COULD goals, in-scope, out-of-scope, acceptance criteria, open questions). Pydantic at `plan/artifacts/prd_v1.py`. *(Done 2026-05-16.)*
- `STORY-1.1.4` · `Backlog` · `P0` · `S` — Refuse-to-advance gate: a PRD with any `TBD` field cannot be marked complete.
- `STORY-1.1.5` · `Backlog` · `P0` · `S` — PRD sign-off action (UI button + audit log entry).

### EPIC-1.2 — Technical Review Swarm (PRD → TRD)
Maps to REQ FR-3. **New orchestration pattern Spine doesn't have today** — architect convenes a swarm, synthesizes a TRD.

> **Tech:** Swarm internals implemented as a **LangGraph subgraph** inside the architect daemon (fan-out → collect → synthesize → checkpoint). Externally the daemon still receives a markdown directive and writes a markdown report; LangGraph is an implementation detail. Gives us typed state + interrupt/resume for free.

- `STORY-1.2.1` · `Done` · `P0` · `M` — Swarm orchestration primitive: architect-lead dispatches scoped sub-directives to swarm members, collects per-lens contributions, synthesizes one artifact. At `plan/swarm/` (LangGraph 7-node subgraph + checkpointing + linear-Python fallback + composition rules + synthesis). *(Done 2026-05-16.)*
- `STORY-1.2.2` · `Backlog` · `P0` · `S` — Per-project-type swarm composition rules declared in `sdlc-pipeline.yaml` (web-app → researcher+engineer+operator+qa; data-pipeline → adds datawright; etc.).
- `STORY-1.2.3` · `Done` · `P0` · `S` — Define the `trd-v1` template (architecture, data model, integrations, NFRs, tech choices, risks, open questions, scope, cost projection). Pydantic at `plan/artifacts/trd_v1.py`. *(Done 2026-05-16.)*
- `STORY-1.2.4` · `Done` · `P0` · `M` — Per-scout contribution format + architect synthesis pattern (how the architect merges 4-6 scout reports into one TRD). At `plan/swarm/scout_contribution.py` (Pydantic `ScoutContribution` w/ lens-role binding) + `plan/swarm/synthesis.py` (lens→TRD-section merge + optional LLM prose pass). *(Done 2026-05-16.)*
- `STORY-1.2.5` · `Backlog` · `P0` · `S` — TRD sign-off action.

### EPIC-1.3 — Roadmap Decomposer (PRD + TRD → INIT/EPIC/STORY)
Maps to REQ FR-4. **The bridge from spec to executable work.**

- `STORY-1.3.1` · `Done` · `P0` · `M` — `planner`-led decomposer playbook that reads PRD+TRD and emits a Roadmap. At `plan/decomposer/decomposer.py` (initiative→epic→story from PRD goals + TRD components; stable IDs; topological-sorted sprints). *(Done 2026-05-16.)*
- `STORY-1.3.2` · `Done` · `P0` · `S` — Story sizing heuristic (XS/S/M/L/XL) + per-story cost + duration estimate. At `plan/decomposer/sizing.py` (additive heuristic over prose volume + KG impact + keyword categories). *(Done 2026-05-16.)*
- `STORY-1.3.3` · `Done` · `P0` · `S` — Inter-story dependency detection + sequencing recommendation. At `plan/decomposer/dependency_detection.py` (KG `impact_radius` path + text-overlap fallback; DFS cycle detection). *(Done 2026-05-16 — upgraded from heuristic to deterministic via KG.)*
- `STORY-1.3.4` · `Done` · `P0` · `S` — Define `roadmap-v1` template (matches the INIT/EPIC/STORY shape already used by this file). Pydantic at `plan/artifacts/roadmap_v1.py`. *(Done 2026-05-16.)*
- `STORY-1.3.5` · `Backlog` · `P0` · `S` — Roadmap sign-off action.

### EPIC-1.4 — Approval Gate System
Maps to REQ FR-5. Absorbs the old EPIC-1.3.

- `STORY-1.4.1` · `Done` · `P0` · `M` — Gate engine: enforces phase boundaries; no phase advances without an approval token. At `orchestrator/lib/gate.sh` (5 functions: status/approve/reject/request-changes/list-pending) wraps `approval.py` + `transition.sh` + `router.sh`. *(Done 2026-05-16.)*
- `STORY-1.4.2` · `Done` · `P0` · `S` — Approval queue UI (pending PRD / TRD / Roadmap sign-offs across all projects). At `shared/ui/approvals/` (vanilla JS + dark theme + serve.sh + proxy.py); dev server `bash shared/ui/approvals/serve.sh`. *(Done 2026-05-16.)*
- `STORY-1.4.3` · `Done` · `P0` · `S` — Inline review surface (read the artifact, see the diff if it's a re-submission). Modal in approvals.js loads + renders artifact markdown; approve/reject/request-changes buttons with optimistic UI. *(Done 2026-05-16.)*
- `STORY-1.4.4` · `Done` · `P0` · `S` — Actions: approve / reject / request-changes (with notes). *(Done 2026-05-16 — `gate.sh approve|reject|request-changes` subcommands.)*
- `STORY-1.4.5` · `Done` · `P1` · `S` — Request-changes routes back to the producing role with the user's notes attached. *(Done 2026-05-16 — `gate_request_changes` composes follow-up directive + dispatches via `router.sh` with `parent_directive_id` linkage.)*
- `STORY-1.4.6` · `Backlog` · `P1` · `S` — Multi-approver gates (e.g., TRD requires CTO + Compliance both sign).
- `STORY-1.4.7` · `Backlog` · `P2` · `XS` — Notifications (email / Slack / system) when an approval is pending.

### EPIC-1.5 — Cost-Aware Tier Router
Maps to REQ FR-6. **Powers every phase.** Five composable mechanisms.

> **Tech:** Borrow **LangChain** model-router + tiered-fallback primitives where they slot cleanly; wrap with Spine's per-phase / budget / org-bundle policy layer. Don't reimplement routing primitives.

- `STORY-1.5.1` · `Done` · `P0` · `S` — Per-phase default tier table (declared in `sdlc-pipeline.yaml`). Read by `shared/cost/router.py` `route()` decision flow. *(Done 2026-05-16; sdlc-pipeline-default.yaml carries the table; cost router consumes it.)*
- `STORY-1.5.2` · `Done` · `P0` · `M` — Per-turn escalation classifier (cheap Haiku-class) — synthesis/decision turns escalate; chitchat stays cheap. At `shared/cost/classifier.py` (hybrid heuristic + LLM-judge; 6 turn types) + 35-case test corpus + `apply_to_route_request` integration. *(Done 2026-05-16.)*
- `STORY-1.5.3` · `Done` · `P0` · `M` — Org-bundle model menu + budget enforcement (hard block on cap exceed, not warn). At `shared/cost/router.py` (`route()` + `get_budget_status()`) + `shared/cost/router_cli.sh`. Exit code 2 = would-exceed-budget. *(Done 2026-05-16.)*
- `STORY-1.5.4` · `Backlog` · `P1` · `M` — Anthropic prompt-cache integration for long intake conversations (huge cost win on repeated context).
- `STORY-1.5.5` · `Backlog` · `P1` · `S` — User override (pin tier per directive; counted against budget; logged).
- `STORY-1.5.6` · `Backlog` · `P1` · `S` — UI cost meter (run / day / month + the rationale for each tier choice).
- `STORY-1.5.7` · `Backlog` · `P2` · `S` — Cost projection at phase start ("this phase will likely cost $X — proceed?").

### EPIC-1.6 — Non-Terminal Front Door UI
Maps to REQ G-7. Absorbs the old EPIC-1.2.

- `STORY-1.6.1` · `Backlog` · `P1` · `M` — Drop-a-project entry form (one-line problem statement → routes to `product` role for intake).
- `STORY-1.6.2` · `Backlog` · `P1` · `S` — Live phase indicator (which of discovery / tech-review / decomposition is active for each project).
- `STORY-1.6.3` · `Backlog` · `P1` · `S` — Role activity stream (who's working on what, last N events, across all projects).
- `STORY-1.6.4` · `Backlog` · `P1` · `S` — Per-project drill-in: artifacts, history, approvals, costs.
- `STORY-1.6.5` · `Backlog` · `P2` · `S` — Pipeline editor (YAML in v1; richer editor in a later cycle if non-engineers want to edit).

### EPIC-1.7 — Pipeline Customization & Authority (the Flexibility Principle)
Maps to REQ FR-7 + FR-8. **"Not etched in stone."** The principle that lets each org shape its own SDLC without forking Spine.

- `STORY-1.7.1` · `In Progress` · `P0` · `M` — `sdlc-pipeline.yaml` schema design + validator. Schema at `plan/artifacts/sdlc-pipeline-schema.yaml` + default + README *(design Done 2026-05-16; validator implementation pending)*.
- `STORY-1.7.2` · `Backlog` · `P0` · `S` — `can_modify_sdlc_pipeline` capability + grant mechanism (lives in org bundle from `INIT-2`).
- `STORY-1.7.3` · `Backlog` · `P0` · `S` — Override hierarchy enforcement: org bundle → team → project, most-specific wins, each level only edits what it's authorized to.
- `STORY-1.7.4` · `Backlog` · `P0` · `S` — Pipeline versioning: every edit = git commit with author + timestamp + rationale (rationale is *required*, not optional).
- `STORY-1.7.5` · `Backlog` · `P0` · `S` — Project-lock to pipeline version at project start (recorded in project metadata).
- `STORY-1.7.6` · `Backlog` · `P1` · `S` — Migration flow: explicit user action to migrate a locked project to a newer pipeline; diff preview required.
- `STORY-1.7.7` · `Backlog` · `P1` · `S` — Pipeline diff / audit view (compare two versions; see edit history).
- `STORY-1.7.8` · `Backlog` · `P2` · `S` — Reference pipeline templates: startup-lite, regulated-enterprise, design-led (G-13 in REQ).

---

## INIT-2 — Enterprise Control & Standards Layer

**Tier:** 2 · **Priority:** P1 · **Why:** This is *the* differentiator no competitor has. Devin owns the runtime; Factory owns the workspace; nobody else enforces an org's standards across every employee's local AI team. See `COMPETITIVE_LANDSCAPE.md §4 Tier 2`.

> **Restructured 2026-05-16:** Absorbs TRON's Standards Hierarchy (Default → Company → Project) — TRON already shipped what this INIT was designing. New `EPIC-2.4` covers the lift. Don't reinvent.

### EPIC-2.1 — Org policy bundles
Package an enterprise's coding standards, security rules, banned patterns, cost ceilings, and approved libraries; inject into every user's install.

- `STORY-2.1.1` · `Done` · `P1` · `M` — Design bundle schema (YAML / TOML): `standards`, `security`, `banned_patterns`, `approved_libs`, `cost_caps`, `deployment_targets`, `compliance_tags`. At `shared/standards/bundle-schema.yaml` + README. *(Done 2026-05-16.)*
- `STORY-2.1.2` · `Done` · `P1` · `S` — `spine install --org-bundle <url|path>` command + bundle validation. At `shared/standards/install_bundle.sh` (7 subcommands: install/validate/list/activate/status/remove/inject) + `validator.py` (Pydantic v2). *(Done 2026-05-16.)*
- `STORY-2.1.3` · `Done` · `P1` · `M` — Bundle injection into role prompts (each role gets the slice relevant to its authority). At `shared/standards/prompt_injector.py` with idempotent injection markers + per-role slice map (product/architect/engineer/qa/operator/auditor/datawright). *(Done 2026-05-16.)*
- `STORY-2.1.4` · `In Progress` · `P1` · `M` — Bundle injection into auditor checks (audit role enforces the banned patterns + security rules). Injector exists (`STORY-2.1.3`); auditor runtime hookup pending wave 4.
- `STORY-2.1.5` · `Backlog` · `P2` · `S` — Bundle versioning + drift detection (warn user when their bundle is older than org's published version).
- `STORY-2.1.6` · `Done` · `P2` · `M` — Reference bundle for "small SaaS startup" + "regulated enterprise" as starting templates. At `shared/standards/bundle-startup-saas.yaml` + `bundle-regulated-enterprise.yaml`. *(Done 2026-05-16.)*

### EPIC-2.2 — MCP server for Spine primitives
Make Spine callable *from* Claude Code / Cursor / Codex, not just the reverse. Closes the biggest concrete gap vs ruflo.

- `STORY-2.2.1` · `Done` · `P1` · `M` — MCP server scaffolding (stdio + HTTP transports, manifest, auth). At `shared/mcp/` (14 files: server.py, envelopes, tools/{orchestrator,plan,build,verify,kg,standards}.py, smoke tests). 17 tools registered as stubs. *(Done 2026-05-16.)*
- `STORY-2.2.2` · `Backlog` · `P1` · `S` — Tool: `directive_create(role, body, tier?)`.
- `STORY-2.2.3` · `Backlog` · `P1` · `S` — Tool: `report_read(role, directive_id?)`.
- `STORY-2.2.4` · `Backlog` · `P1` · `S` — Tool: `team_status()`.
- `STORY-2.2.5` · `Backlog` · `P1` · `S` — Tool: `org_standards_get(domain?)` so agents can query policy mid-task.
- `STORY-2.2.6` · `Backlog` · `P2` · `S` — Tool: `cost_summary(window?)`.

### EPIC-2.3 — Spend ceilings & per-user budgets
Tier hints are good; an org needs *enforcement*.

- `STORY-2.3.1` · `Backlog` · `P1` · `S` — User budget config (daily / weekly / monthly hard caps).
- `STORY-2.3.2` · `Backlog` · `P1` · `S` — Hard-cap enforcement: block directive dispatch if projected cost would exceed cap.
- `STORY-2.3.3` · `Backlog` · `P2` · `S` — Per-role and per-project rollups in addition to per-user.
- `STORY-2.3.4` · `Backlog` · `P2` · `S` — Admin override flow (justification + log entry).

### EPIC-2.4 — Lift TRON Standards Hierarchy (NEW — 2026-05-16)
TRON already shipped a Default → Company → Project standards hierarchy. Lift it into `shared/standards/` instead of reinventing.

- `STORY-2.4.1` · `Backlog` · `P0` · `M` — Move `tron/standards/` → `shared/standards/`; preserve TRON's existing internal APIs.
- `STORY-2.4.2` · `Backlog` · `P0` · `S` — Map TRON's hierarchy semantics to Spine's org-bundle schema (`EPIC-2.1`). Reconcile naming.
- `STORY-2.4.3` · `Backlog` · `P0` · `S` — Wire Spine roles (engineer, architect, auditor) to consume `shared/standards/`.
- `STORY-2.4.4` · `Backlog` · `P1` · `S` — Documentation: how org admins author a bundle that combines Spine pipeline overrides + TRON standards.
- `STORY-2.4.5` · `Backlog` · `P1` · `S` — Migration of TRON's existing reference packs (OWASP, SOC 2, ISO 27001, HIPAA) into the unified bundle catalog.

---

## INIT-3 — Trust & Reproducibility Layer

**Tier:** 3 · **Priority:** P1-P2 · **Why:** Without these an enterprise security review will block deployment. See `COMPETITIVE_LANDSCAPE.md §4 Tier 3`.

> **Restructured 2026-05-16:** Gains three new EPICs from TRON — `EPIC-3.5` (Sandbox), `EPIC-3.6` (Calibration), `EPIC-3.7` (Cross-LLM Validation). These exist working in TRON today; lift them into `shared/` so Plan and Build subsystems can use them, not just Verify.

### EPIC-3.1 — Audit log of every LLM call
Table-stakes for enterprise. Data already exists in `costs.csv`; needs the prompt/output payload + a queryable store.

- `STORY-3.1.1` · `Done` · `P1` · `S` — Audit record schema (prompt hash, output hash, model, cost, role, user, timestamp, directive ref). Pydantic at `shared/audit/audit_record.py` with hash chain. *(Done 2026-05-16.)*
- `STORY-3.1.2` · `Done` · `P1` · `M` — Storage backend: Postgres `spine_audit` schema with append-only enforcement (role + trigger). At `db/flyway/sql/V15__spine_audit_schema.sql` + README. *(Done 2026-05-16; decision updated from SQLite to Postgres per architecture lock; not yet run.)*
- `STORY-3.1.3` · `Backlog` · `P2` · `S` — Query / export interface (CSV, JSON, S3 push).
- `STORY-3.1.4` · `Backlog` · `P2` · `S` — Optional payload redaction (PII scrubbing) before persistence.

### EPIC-3.2 — Reproducible builds
A Spine run should be replayable from `directive + REQ + role-version + model-version`, like a Dockerfile.

- `STORY-3.2.1` · `Backlog` · `P2` · `M` — Run-manifest format capturing all inputs to a directive.
- `STORY-3.2.2` · `Backlog` · `P2` · `M` — `spine replay <manifest>` command.
- `STORY-3.2.3` · `Backlog` · `P3` · `M` — Diff two runs (same manifest, different model → output drift report).

### EPIC-3.3 — Team-of-models router
Today user picks the tier hint. Smarter: route automatically by (role, task complexity).

- `STORY-3.3.1` · `Backlog` · `P2` · `M` — Task-complexity scoring heuristic (length, file count, role, history).
- `STORY-3.3.2` · `Backlog` · `P2` · `M` — Model selection table indexed by (role, complexity).
- `STORY-3.3.3` · `Backlog` · `P3` · `S` — User override + cost-vs-quality slider in UI.

### EPIC-3.4 — Eval / regression harness (new — closes survey gap)
**Tech:** **LangSmith**-style evals for role prompts and pipeline outputs. Closes the "did this role-prompt change make it better?" gap called out in `COMPETITIVE_LANDSCAPE.md §4 Tier 5`.

- `STORY-3.4.1` · `Done` · `P1` · `M` — Eval dataset format: `(directive, expected_artifact_traits, scoring_rubric)` triples per role. At `shared/eval/_dataset_schema.yaml` + `_rubric_schema.yaml` + 2 worked examples (engineer + architect). 4 check types: regex / structured_field / llm_judge / deterministic. *(Done 2026-05-16.)*
- `STORY-3.4.2` · `In Progress` · `P1` · `M` — Eval runner: replays a directive against a candidate role prompt + model; scores output against rubric. Design at `shared/eval/runner_design.md` (architecture + per-case flow + scoring + regression mode + A/B mode + `spine_eval` schema sketch). Implementation pending wave 4.
- `STORY-3.4.3` · `Backlog` · `P1` · `S` — Regression mode: run candidate prompt against the full eval set; diff scores vs baseline.
- `STORY-3.4.4` · `Backlog` · `P2` · `S` — A/B mode: route a fraction of real directives to candidate prompt; record outcomes.
- `STORY-3.4.5` · `Backlog` · `P2` · `S` — Dashboard view: per-role score history; flag regressions on prompt edits.

### EPIC-3.5 — Sandbox Execution Verification (NEW — lifted from TRON)
TRON's Docker ephemeral sandbox + seccomp profile is the answer to "engineer self-reports success but never actually ran the code." Lift to `verify/sandbox/` and expose as a shared capability.

- `STORY-3.5.1` · `Backlog` · `P1` · `S` — Move TRON `tron/sandbox/` → `verify/sandbox/`. Verify standalone tests pass.
- `STORY-3.5.2` · `Done` · `P1` · `S` — MCP tool `sandbox_run(code, env)` exposes sandbox execution to any Spine role. At `shared/mcp/tools/sandbox.py` (248 lines, degraded-mode detection, lazy TRON import, cost model). TRON `sandbox_client.run` adapter call-site stubbed pending wave 5. *(Scaffold Done 2026-05-16.)*
- `STORY-3.5.3` · `Backlog` · `P1` · `M` — Engineer-daemon hook: optional sandbox-verify pass before report write.
- `STORY-3.5.4` · `Backlog` · `P2` · `S` — Seccomp profile customization via org bundle (sensitive orgs want stricter syscall filtering).
- `STORY-3.5.5` · `Backlog` · `P2` · `S` — Sandbox cost tracking (CPU-seconds, memory-seconds) into unified cost ledger.

### EPIC-3.6 — Confidence Calibration (NEW — lifted from TRON)
TRON's Platt-scaled calibration on LLM-only outputs is a real honesty layer Spine lacks. Apply to architect risk assessments, decomposer story estimates, qa findings.

- `STORY-3.6.1` · `Backlog` · `P2` · `M` — Move TRON `tron/verification/calibration*` → `verify/calibration/` (or `shared/calibration/` if Plan/Build also use).
- `STORY-3.6.2` · `Backlog` · `P2` · `M` — Labeled outcome corpus collection (Pipeline writes outcome rows to `spine_calibration` schema after every gate decision).
- `STORY-3.6.3` · `Backlog` · `P2` · `S` — Platt-scaled mapping fit when N ≥ 500 (else banded fallback) per role/output-type.
- `STORY-3.6.4` · `Backlog` · `P2` · `S` — Calibration applied to: architect risk scores, decomposer estimates, qa severity, auditor finding confidence.
- `STORY-3.6.5` · `Backlog` · `P3` · `S` — UI surface: show calibration band on each finding/score.

### EPIC-3.7 — Cross-LLM Validation (NEW — lifted from TRON)
TRON cross-validates severe findings across Anthropic + OpenAI. Spine should do the same for high-stakes outputs (PRD acceptance, TRD synthesis, security-critical engineer work).

- `STORY-3.7.1` · `Done` · `P2` · `M` — Move TRON `AuditManager` cross-validation logic to `shared/validation/`. At `shared/validation/cross_llm.py` (cross_validate service + lazy Anthropic/OpenAI SDKs). *(Done 2026-05-16 — pattern lifted as generalized service, not TRON code copy.)*
- `STORY-3.7.2` · `Done` · `P2` · `S` — Per-phase config: which phases trigger cross-validation (default: PRD-final, TRD-final, security findings). At `shared/validation/config.py` (`DEFAULT_CROSS_LLM_PHASES` + org-bundle override + severity floor). *(Done 2026-05-16.)*
- `STORY-3.7.3` · `Done` · `P2` · `S` — Provider keys checked at boot; single-key deployments degrade gracefully (cap confidence, skip cross-check). Implemented in cross_llm.py (`effective_confidence_cap=0.7` on skip; missing SDK → `ProviderResult(verdict="error")`). *(Done 2026-05-16.)*
- `STORY-3.7.4` · `Done` · `P2` · `S` — Cost projection — cross-validation roughly 2× the LLM cost for affected phases; surface in cost meter. `CrossLLMValidationResult.total_cost_usd` field; documented in cross_llm_README. *(Done 2026-05-16.)*

---

## INIT-4 — Best-Practice Absorption

**Tier:** 4 · **Priority:** P1-P2 · **Why:** Steal what already works in the field instead of inventing. See `COMPETITIVE_LANDSCAPE.md §3` for sources.

### EPIC-4.1 — Auto-triggering skills (from superpowers)
Session-start hooks that fire skill prompts at the right moments inside a role's invocation.

- `STORY-4.1.1` · `Backlog` · `P1` · `M` — Skill auto-trigger mechanism in role prompts (load + register at agent invocation).
- `STORY-4.1.2` · `Backlog` · `P1` · `S` — Port `verification-before-completion` as an engineer-internal step (engineers self-verify before writing reports; reduces auditor load).
- `STORY-4.1.3` · `Backlog` · `P1` · `M` — Port `using-git-worktrees` to replace scratch dirs (cleaner parallel-worker isolation).
- `STORY-4.1.4` · `Backlog` · `P1` · `S` — Port `brainstorming` to `product` role (overlaps with `STORY-1.1.4` — dedupe at execution time).
- `STORY-4.1.5` · `Backlog` · `P2` · `M` — Port `subagent-driven-development` pattern as a `conductor` playbook.
- `STORY-4.1.6` · `Backlog` · `P2` · `S` — Port `systematic-debugging` to `engineer` and `researcher`.

### EPIC-4.2 — Vector-backed memory (from ruflo)
Per-role `memory.md` is good but doesn't scale; add semantic recall.

- `STORY-4.2.1` · `Backlog` · `P2` · `M` — Vector store choice + embedding pipeline (local: e.g., sqlite-vss, lance, chromadb local mode).
- `STORY-4.2.2` · `Backlog` · `P2` · `M` — Per-role lesson retrieval at directive time (inject top-K relevant prior lessons into role prompt).
- `STORY-4.2.3` · `Backlog` · `P2` · `M` — Cross-project semantic recall (lessons from `~/.spine-development/playbook/` indexed too).
- `STORY-4.2.4` · `Backlog` · `P3` · `S` — Eviction / decay policy (lessons fade if never retrieved).

### EPIC-4.3 — Lite install path (from ruflo)
Two-tier install: Claude Code plugin only (no daemons, no MCP server) vs full daemon install.

- `STORY-4.3.1` · `Backlog` · `P2` · `M` — Claude Code plugin-only install path; minimum viable Spine surface.
- `STORY-4.3.2` · `Backlog` · `P2` · `S` — Feature matrix doc (lite vs full) so users know what they get.
- `STORY-4.3.3` · `Backlog` · `P3` · `S` — Upgrade path: lite → full without losing memory / lessons.

---

## INIT-5 — Positioning, Go-to-Market & Discovery

**Tier:** cross-cutting · **Priority:** P1 · **Why:** Five-corner-moat is real but invisible to outsiders. Spine needs a public narrative.

> **Cross-cutting tech decisions (added 2026-05-16, see `memory/spine_tech_stack_decisions.md`):**
> - **Bash orchestration core is non-negotiable** — debuggability moat. Never replaced by LangGraph at the daemon/file-bus layer.
> - **Postgres `db/` extended for Knowledge Graph** (new `spine_kg` schema, pgvector for embeddings). No new infra; no Neo4j.
> - **LangChain/LangGraph used inside specific roles/capabilities only** (optional Python dep). See affected epics: `EPIC-1.2`, `EPIC-1.5`, `EPIC-3.4`, `EPIC-6.5`, `EPIC-6.7`.
> - **Tree-sitter for code parsing** (no LSP servers required).

### EPIC-5.1 — Public positioning & competitive narrative
- `STORY-5.1.1` · `Backlog` · `P1` · `S` — One-page positioning doc: "Spine is the local-deployed virtual team for vibecoders under org control." Use the five-corner moat as the visual.
- `STORY-5.1.2` · `Backlog` · `P1` · `M` — Comparison page on the README / website: Spine vs Devin vs Factory vs Cursor vs ruflo vs MetaGPT. Honest matrix.
- `STORY-5.1.3` · `Backlog` · `P2` · `S` — Naming / branding decision: "SpineDevelopment" vs "Spine" vs new mark. Resolve before public launch.
- `STORY-5.1.4` · `Backlog` · `P3` · `M` — Landing page with the requirements-interrogation demo.

### EPIC-5.2 — Research & artifact retention
- `STORY-5.2.1` · `Done` · `—` · `XS` — Capture this competitive research as `docs/research/COMPETITIVE_LANDSCAPE.md`. *(Done 2026-05-16.)*
- `STORY-5.2.2` · `Backlog` · `P2` · `S` — Standing process: every time we research a new comparator, append to `COMPETITIVE_LANDSCAPE.md §3` and update the moat doc if anything shifts.
- `STORY-5.2.3` · `Backlog` · `P3` · `S` — Quarterly competitive scan (set as a Spine `seer` recurring directive once the daemon's mature).

### EPIC-5.3 — Jira / project-tool integration
- `STORY-5.3.1` · `Backlog` · `P2` · `S` — Script: convert this `BACKLOG.md` to Jira-CSV (one row per story, columns: Type, Summary, Parent, Description, Priority, Labels).
- `STORY-5.3.2` · `Backlog` · `P3` · `M` — Bi-directional sync (status updates in Jira reflect back here, or vice versa) — only if/when we actually pick a tool.

---

## INIT-6 — Code & Document Knowledge Graph (cross-cutting foundation)

**Tier:** foundational · **Priority:** P0 · **REQ:** [`docs/PRD.md#req-init-6`](PRD.md#req-init-6) · **Why:** Graph-based code+doc understanding is the 2026 standard (Microsoft GraphRAG, Thoughtworks CodeConcise, GitLab Knowledge Graph, ruflo, `safishamsi/graphify`). Spine has only a relational recording layer today — no structural reasoning. Graph turns "who calls this", "what's the blast radius", "which REQ drove this", "what tests cover it" from token-burning grep loops into deterministic millisecond queries. **Prerequisite for the decomposer (`EPIC-1.3`) to do real story-dependency detection.**

> **Cross-cutting role (added 2026-05-16):** KG is foundation infrastructure consumed by **all three subsystems** — Plan (architect/decomposer query existing-system shape), Build (engineer/auditor query impact radius), Verify (TRON ISO agents query call graph for taint analysis). Lives under `build/kg/` (parsers) + `shared/db/` (storage); MCP tools in `shared/mcp/`.

> **Tech:** Storage in existing **Postgres `db/`** (new `spine_kg` schema) + **pgvector** for embeddings. Code parsed via **tree-sitter** (no LSP servers). Docs parsed via markdown extractor. Hybrid graph+vector RAG via **LangChain** (`GraphRetriever` + `MultiVectorRetriever`). Exposed via the MCP server from `EPIC-2.2`. **No new infra, no Neo4j, no separate vector DB.**

### EPIC-6.1 — Graph schema + storage
Maps to REQ FR-1 + FR-2.

- `STORY-6.1.1` · `Done` · `P0` · `M` — Design the v1 node/edge type set (code, test, doc, Spine-flow, external, extensible CustomNode). *(Done 2026-05-16; documented in `db/flyway/sql/V2__spine_kg_schema.README.md`.)*
- `STORY-6.1.2` · `Done` · `P0` · `S` — Flyway migration: `kg_node`, `kg_edge`, `kg_node_embedding`, `kg_node_property`, `kg_index_state` tables; indexes (B-tree + GIN + IVFFlat on embeddings). At `db/flyway/sql/V2__spine_kg_schema.sql`. *(Done 2026-05-16; not yet run.)*
- `STORY-6.1.3` · `Backlog` · `P0` · `S` — `commit_sha` + `valid_from`/`valid_to` columns for point-in-time queries (REQ G-10, NFR-6).
- `STORY-6.1.4` · `Backlog` · `P1` · `S` — Org-bundle hooks for extensible node/edge types (e.g., `compliance_tag`).

### EPIC-6.2 — Code parser (tree-sitter)
Maps to REQ FR-3.

- `STORY-6.2.1` · `Backlog` · `P0` · `M` — Tree-sitter scaffolding + grammar bundles for the v1 language set: Python, TypeScript/JavaScript, Go, Rust, Bash, SQL, Markdown.
- `STORY-6.2.2` · `Done` · `P0` · `M` — Per-language extractor config format (`build/kg/extractors/<lang>.yaml`) — which AST nodes become graph nodes / edges. At `build/kg/extractors/_schema.yaml` + README. Multi-grammar pattern demonstrated. *(Done 2026-05-16.)*
- `STORY-6.2.3` · `In Progress` · `P0` · `S` — Default extractors for the v1 language set (functions, classes, calls, imports, defines, references). Python/TS-JS/Bash/Markdown shipped at `build/kg/extractors/*.yaml`. Go/Rust/SQL pending wave 4. *(Partial done 2026-05-16.)*
- `STORY-6.2.4` · `Backlog` · `P1` · `S` — Test-file detection + `TESTS`/`COVERS` edge generation.

### EPIC-6.3 — Document parser
Maps to REQ FR-4.

- `STORY-6.3.1` · `Backlog` · `P0` · `M` — Markdown parser: headings → nodes; links → edges; embedded Spine IDs (`INIT-N`, `EPIC-N.M`, `STORY-N.M.K`, `REQ-INIT-N`, `ADR-N`, `FR-N`) → typed reference edges.
- `STORY-6.3.2` · `Backlog` · `P0` · `S` — REQ / PRD / TRD / Roadmap document parsers (sections, acceptance criteria, requirements as child nodes).
- `STORY-6.3.3` · `Backlog` · `P0` · `S` — Role-prompt + `memory.md` parser: lessons become `MemoryLesson` nodes, pinned to code/doc nodes they touch.

### EPIC-6.4 — Incremental indexer
Maps to REQ FR-5.

- `STORY-6.4.1` · `Done` · `P0` · `M` — Extend existing `db/watcher/` to drive graph indexing on git commits (post-commit hook + watcher poll fallback). At `build/kg/indexer/watcher_extension.py` (kg_tick callback + render_post_commit_hook helper; no watcher modifications). *(Done 2026-05-16.)*
- `STORY-6.4.2` · `Done` · `P0` · `S` — Diff-based update: parse only changed files; compute node/edge insert/update/delete set. At `build/kg/indexer/diff_engine.py` + `indexer.py` `incremental_index()` (supersede pattern via valid_to). *(Done 2026-05-16.)*
- `STORY-6.4.3` · `Done` · `P0` · `S` — Cold-start full index on first install; record `kg_index_state.commit_sha`. At `build/kg/indexer/indexer.py` `cold_start_index()` (transactional batches of 1000; recoverable mid-walk). *(Done 2026-05-16.)*

### EPIC-6.5 — Query API + MCP tools
Maps to REQ FR-6. **Depends on `EPIC-2.2` MCP scaffolding.**

> **Tech:** Wraps **LangChain** `GraphRetriever` where natural; raw SQL for hot paths. Tools exposed via MCP for all roles.

- `STORY-6.5.1` · `Backlog` · `P0` · `S` — `graph_query(query)` — escape hatch for power users.
- `STORY-6.5.2` · `Done` · `P0` · `S` — `find_callers(symbol, depth)` — direct + transitive callers. Real impl at `shared/mcp/tools/kg.py` (recursive CTE for depth>1; point-in-time queries via commit_sha; subprocess psql; ≤50ms p95 target). *(Done 2026-05-16.)*
- `STORY-6.5.3` · `Done` · `P0` · `S` — `trace_dependency(from, to)` — shortest path in CALLS/IMPORTS graph. Recursive CTE BFS w/ cycle blocking + up-to-5-paths return. *(Done 2026-05-16.)*
- `STORY-6.5.4` · `Done` · `P0` · `S` — `code_neighborhood(node, radius)` — subgraph within N hops. Bidirectional recursive CTE + min-distance dedup + companion edge fetch. *(Done 2026-05-16.)*
- `STORY-6.5.5` · `Done` · `P0` · `S` — `impact_radius(symbol_or_region)` — files + tests potentially affected by a change. Real impl at `shared/mcp/tools/kg.py` (multi-CTE: callers + tests + importers + tests-via-callers; ≤200ms p95 target). Used by engineer/auditor BuildArtifact verification. *(Done 2026-05-16.)*
- `STORY-6.5.6` · `Done` · `P0` · `S` — `doc_for_region(file:lines)` — REQs / ADRs / lessons touching this code. Two-stage walk: code nodes in file → incoming Document edges (CITES/OWNS/TESTS/TOUCHES/DERIVED_FROM/DECIDED_BY). *(Done 2026-05-16.)*
- `STORY-6.5.7` · `Done` · `P0` · `S` — `who_owns(node)` — roles / lessons / ADRs claiming ownership. Two-stage: explicit OWNED_BY edges (confidence 1.0) → MemoryLesson fallback (confidence 0.5). Never fabricates. *(Done 2026-05-16.)*
- `STORY-6.5.8` · `Backlog` · `P1` · `S` — `find_by_satisfies(req_or_story_id)` — code regions claiming to satisfy a given REQ/STORY.

### EPIC-6.6 — Role-prompt integration
Maps to REQ FR-7. **One story per affected role.**

- `STORY-6.6.1` · `Done` · `P0` · `S` — Update `researcher.md`: use `find_callers` / `trace_dependency` / `code_neighborhood` before grep. *(Done 2026-05-16 — added KG section, +16 lines.)*
- `STORY-6.6.2` · `Done` · `P0` · `S` — Update `architect.md`: query `code_neighborhood` + `impact_radius` before drafting TRD sections that touch existing code; write TRD as delta. *(Done 2026-05-16 — added KG section, +13 lines.)*
- `STORY-6.6.3` · `Done` · `P0` · `S` — Update `engineer.md`: run `impact_radius` and include affected callers in `## Files touched`. *(Done 2026-05-16 — added KG section + BuildArtifact.kg_impact rule, +13 lines.)*
- `STORY-6.6.4` · `Done` · `P0` · `S` — Update `auditor.md`: re-run `impact_radius` against engineer's report; flag missed callers. *(Done 2026-05-16 — added KG section + numerical-diff verdict rule, +13 lines.)*
- `STORY-6.6.5` · `Backlog` · `P0` · `S` — Update `planner.md` (decomposer): use `code_neighborhood`/`impact_radius` to detect inter-story dependencies automatically (upgrades `STORY-1.3.3` from heuristic to deterministic).
- `STORY-6.6.6` · `Backlog` · `P1` · `S` — Update `memory.md`: pin every new lesson to code/doc nodes via `OWNS`/`TOUCHES` edges so lessons surface contextually.

### EPIC-6.7 — Hybrid graph + vector RAG
Maps to REQ FR-8.

> **Tech:** **LangChain** `MultiVectorRetriever` (semantic) + `GraphRetriever` (structural) + RRF re-rank. Exposed as `hybrid_search` MCP tool. Embeddings lazy + cached; embedding model configurable via org bundle.

- `STORY-6.7.1` · `Backlog` · `P1` · `M` — Embedding pipeline: lazy on first query touching a node; cached in `kg_node_embedding`.
- `STORY-6.7.2` · `Backlog` · `P1` · `S` — Default local embedding model (e.g., `nomic-embed-text`); org bundle override.
- `STORY-6.7.3` · `Backlog` · `P1` · `M` — `hybrid_search(natural_language_query)` MCP tool — graph + vector + re-rank.
- `STORY-6.7.4` · `Backlog` · `P2` · `S` — PII / secrets redactor (default scrubs AWS keys, JWTs, emails before embedding; org bundle can extend).

---

## INIT-7 — Build Subsystem: formalize the execution layer

**Tier:** structural · **Priority:** P0 · **REQ:** [`docs/PRD.md#req-init-7`](PRD.md#req-init-7) (stub) · **Why:** Today's Spine roles (engineer, operator, datawright) work but aren't formally grouped as a subsystem with a contract to the Orchestrator and Verify. INIT-7 draws the boundary, defines the artifact contract Build emits (code + tests + manifest), and wires KG/MCP integration.

> **Tech:** Lives in `build/`. Bash daemons (preserves debuggability moat). KG parsers under `build/kg/parsers/` (tree-sitter). No new languages introduced.

### EPIC-7.1 — Build subsystem boundary
- `STORY-7.1.1` · `Backlog` · `P0` · `M` — `build/` module scaffolding: roles/, daemons/, workers/, kg/, tests/.
- `STORY-7.1.2` · `Backlog` · `P0` · `S` — Per-subsystem README documenting the build contract (inputs from Plan/Orchestrator; outputs to Verify).
- `STORY-7.1.3` · `Done` · `P0` · `S` — Module boundary check: build/ imports nothing from plan/ or verify/; talks through shared/mcp/ only. At `tools/check-module-boundaries.sh` + `_boundary_parser.py` + `boundary-rules.yaml` + README. Generalized to all 5 subsystems; AST-level Python + regex bash/JS scanners; `--changed-only` / `--explain` / `--add-exception` / JSON+JUnit output. *(Done 2026-05-16.)*

### EPIC-7.2 — Wire Build to Orchestrator
- `STORY-7.2.1` · `Backlog` · `P0` · `M` — Build subsystem registers with orchestrator on boot; declares which roles it provides.
- `STORY-7.2.2` · `Backlog` · `P0` · `S` — Orchestrator dispatches directives to Build via MCP tool `build_dispatch(role, directive, locked_pipeline_version)`.
- `STORY-7.2.3` · `Backlog` · `P0` · `S` — Build reports completion to orchestrator with artifact manifest (files touched, tests added/run, KG impact node IDs).

### EPIC-7.3 — Wire Build to KG
- `STORY-7.3.1` · `Backlog` · `P0` · `S` — Engineer daemon calls `impact_radius` before completing a directive; includes affected nodes in report.
- `STORY-7.3.2` · `Backlog` · `P1` · `S` — Operator daemon calls `who_owns` before mutating infra; routes to right approver.
- `STORY-7.3.3` · `Backlog` · `P1` · `S` — Datawright daemon registers pipeline outputs as `Document` nodes linked to source data nodes.

### EPIC-7.4 — Build artifact contract
- `STORY-7.4.1` · `Done` · `P0` · `M` — Pydantic `BuildArtifact` schema: code_changes[], tests_added[], tests_run[], kg_impact[], cost, duration, rationale. At `shared/schemas/build/build_artifact.py` with refuse-to-seal validator + to_markdown + to_audit_metadata. *(Done 2026-05-16.)*
- `STORY-7.4.2` · `Backlog` · `P0` · `S` — Build always emits `BuildArtifact` (not free-form markdown report) — closes the "fragile contracts" gap from survey.
- `STORY-7.4.3` · `Backlog` · `P0` · `S` — Auditor verifies `BuildArtifact` against KG impact before passing to Verify.

### EPIC-7.5 — Migrate existing role daemons
- `STORY-7.5.1` · `Backlog` · `P1` · `M` — Move `lib/team-agent-daemon.sh` + role daemons into `build/daemons/`. Preserve existing behavior.
- `STORY-7.5.2` · `Backlog` · `P1` · `S` — Update existing role-prompts (engineer, operator, datawright) to read new paths.
- `STORY-7.5.3` · `Backlog` · `P2` · `S` — Retire `lib/` legacy bash as drained.

---

## INIT-8 — Verify Subsystem (TRON Integration)

**Tier:** structural · **Priority:** P0 · **REQ:** [`docs/PRD.md#req-init-8`](PRD.md#req-init-8) (stub) · **Why:** TRON is the verification subsystem Spine doesn't have built yet. Integration via `git subtree` into `verify/` preserves TRON's history + internal cohesion while making it a first-class Spine subsystem. See `docs/ARCHITECTURE.md §5` for the full code mapping.

> **Tech:** Lives in `verify/`. Stays Python + FastAPI + Temporal (TRON's existing stack). Communicates with Orchestrator via MCP. Standards Hierarchy + MCP + memory move to `shared/` as cross-cutting (handled by `EPIC-2.4`, `EPIC-2.2`, plus stories below).

### EPIC-8.1 — TRON subtree migration
- `STORY-8.1.1` · `Backlog` · `P0` · `M` — `git subtree add --prefix=verify/ <tron-repo> main` (preserves history).
- `STORY-8.1.2` · `Backlog` · `P0` · `S` — Update TRON's internal absolute paths to relative where needed.
- `STORY-8.1.3` · `Backlog` · `P0` · `S` — Run TRON's existing test suite from new location; all green.
- `STORY-8.1.4` · `Backlog` · `P0` · `S` — Update TRON's `docker-compose.yml` paths; verify dev stack comes up.

### EPIC-8.2 — TRON-Spine code mapping
- `STORY-8.2.1` · `Backlog` · `P0` · `S` — `tron/standards/` → `shared/standards/` (overlaps `EPIC-2.4` — same work).
- `STORY-8.2.2` · `Backlog` · `P0` · `S` — `tron/mcp/` → `shared/mcp/`; consolidate with planned Spine MCP server (`EPIC-2.2`).
- `STORY-8.2.3` · `Backlog` · `P0` · `S` — `tron/memory/` → `shared/memory/`; preserve Spine's role-memory pattern as a *separate flavor* under the same module.
- `STORY-8.2.4` · `Backlog` · `P0` · `S` — `tron/parsers/` → `build/kg/parsers/` (tree-sitter parsers feed KG).
- `STORY-8.2.5` · `Backlog` · `P1` · `S` — `tron/infra/` → `shared/infra/` (Vault, secrets helpers).
- `STORY-8.2.6` · `Backlog` · `P1` · `S` — `frontend/` → `shared/ui/`; retire `admin-ui/` per TRON's own roadmap.

### EPIC-8.3 — Postgres consolidation
- `STORY-8.3.1` · `Backlog` · `P1` · `M` — Decide single migration tool (Flyway recommended); port TRON's Alembic migrations to Flyway SQL.
- `STORY-8.3.2` · `Backlog` · `P1` · `M` — Multi-schema layout: `spine_recording` / `spine_kg` / `spine_lifecycle` / `spine_audit` / `spine_verify_*`.
- `STORY-8.3.3` · `Backlog` · `P1` · `S` — Move `db/` → `shared/db/`; update all paths.

### EPIC-8.4 — Verify ↔ Orchestrator wiring
- `STORY-8.4.1` · `Done` · `P0` · `S` — Umbrella Makefile dispatches `make verify-*` to TRON's internal Makefile. At `Makefile.v2` with self-documenting `make help`, per-subsystem pattern rules, all v1 targets preserved. *(Done 2026-05-16; rename to Makefile during cutover.)*
- `STORY-8.5.1` · `Done` · `P0` · `M` — Orchestrator invokes Verify via MCP `verify_audit(build_artifact, blueprint)`; returns `VerifyFindings`. At `shared/mcp/tools/verify.py` (10-step pipeline: validate sealed → docker probe → lazy TRON import → build AuditRequest → call AuditManager → map FindingOutput → cost rollup → pass_fail → persist findings). *(Done 2026-05-16; AuditManager call-site stub pending wave 6.)*
- `STORY-8.5.2` · `Done` · `P0` · `S` — Verify writes findings to `spine_audit`; orchestrator decides route-back-to-Build or surface-to-user. `_persist_findings` writes 1 summary + N per-finding AuditRecords; pass_fail decides route per FR-9. *(Done 2026-05-16.)*

### EPIC-8.5 — TRON ISO agents in the Build phase
- `STORY-8.6.1` · `In Progress` · `P1` · `M` — Expose TRON ISO agents (SecurityISO, QAISO, etc.) as MCP tools callable from Build phase for early-detect. Wrapper at `shared/mcp/tools/iso.py` with `iso_invoke` + 6 per-agent convenience tools (lazy TRON import). MCP contract complete; TRON `BaseISO.execute` call-site adapter stubbed pending wave 4. *(Design + scaffold Done 2026-05-16.)*
- `STORY-8.6.2` · `In Progress` · `P1` · `S` — Engineer daemon optionally invokes SecurityISO before completing a security-sensitive directive. MCP tool surface ready (`security_iso_scan`); engineer daemon hookup pending wave 4.
- `STORY-8.6.3` · `Backlog` · `P2` · `S` — Cost-aware: pre-verify costs counted against project budget (`EPIC-1.5`).

### EPIC-8.6 — Verification as canonical SDLC phase 7-8
- `STORY-8.7.1` · `Backlog` · `P0` · `S` — `sdlc-pipeline.yaml` adds `verify` phase between `build` and `acceptance`; default = TRON 7-layer pipeline.
- `STORY-8.7.2` · `Backlog` · `P0` · `S` — Org bundle can override which TRON ISO agents run for the verify phase (e.g., regulated orgs require ComplianceISO).
- `STORY-8.7.3` · `Backlog` · `P1` · `S` — Verify-fail routes back to Build with a remediation directive auto-generated from findings (handled by `EPIC-9.8`).

---

## INIT-9 — Central Orchestrator

**Tier:** structural · **Priority:** P0 · **REQ:** [`docs/PRD.md#req-init-9`](PRD.md#req-init-9) (stub) · **Why:** The unifying coordinator. Owns project lifecycle, gates, routing, cost/audit aggregation, user-facing surface. Without it, Plan/Build/Verify are three disconnected things; with it, they're one product. See `docs/ARCHITECTURE.md §2`.

> **Tech:** Bash core + Postgres state (preserves debuggability moat). Minimal Python helpers where needed. Talks to subsystems via MCP. Lives in `orchestrator/`.

### EPIC-9.1 — Lifecycle state machine
- `STORY-9.1.1` · `Done` · `P0` · `M` — Postgres `spine_lifecycle` schema: `project`, `phase_history`, `transition`, `approval`, `route_history` tables. At `db/flyway/sql/V14__spine_lifecycle_schema.sql`. *(Done 2026-05-16; renumbered from V3 due to slot collision; not yet run.)*
- `STORY-9.1.2` · `Done` · `P0` · `S` — Top-level dirs scaffolded (`orchestrator/`, `plan/`, `build/`, `verify/`, `shared/`). *(Done 2026-05-16 — Phase 0 scaffold + READMEs.)*
- `STORY-9.1.3` · `Done` · `P0` · `S` — Define canonical phases: `intake → plan_in_progress → plan_approved → build_in_progress → build_complete → verify_in_progress → verify_approved → acceptance → released → operate → retro`. At `orchestrator/state/phases.yaml`. *(Done 2026-05-16.)*
- `STORY-9.1.4` · `Backlog` · `P1` · `S` — Phase-set is editable via `sdlc-pipeline.yaml` (consistent with `EPIC-1.7` flexibility principle).

### EPIC-9.2 — State transition engine
- `STORY-9.2.1` · `Done` · `P0` · `M` — Transition engine in bash; reads current phase, validates transition, writes new state, emits audit row. At `orchestrator/lib/transition.sh` + `transition_test.sh` with per-error exit codes + atomic Postgres TX. *(Done 2026-05-16.)*
- `STORY-9.2.2` · `Done` · `P0` · `S` — Invalid transitions rejected with clear error (no implicit phase skipping). *(Done 2026-05-16 — covered by `STORY-9.2.1` `transition_validate` function.)*
- `STORY-9.2.3` · `Backlog` · `P1` · `S` — Rollback support: transition can revert to prior phase with rationale.

### EPIC-9.3 — Phase gate enforcement
- `STORY-9.3.1` · `Backlog` · `P0` · `S` — Gate check before any transition: required approvals satisfied? (uses `EPIC-1.4` approval system).
- `STORY-9.3.2` · `Done` · `P0` · `S` — Approval tokens stored in `spine_lifecycle.approval`; verifiable cryptographically (HMAC). At `orchestrator/lib/approval.py` (stdlib-only: genkey/sign/verify/grant/revoke; HMAC-SHA256; 0600 key perms). *(Done 2026-05-16.)*
- `STORY-9.3.3` · `Backlog` · `P1` · `S` — Multi-approver gates supported (e.g., TRD requires CTO + Compliance).

### EPIC-9.4 — Routing layer
- `STORY-9.4.1` · `Done` · `P0` · `M` — Orchestrator dispatches directives to subsystem via MCP (`plan_dispatch`, `build_dispatch`, `verify_audit`). At `orchestrator/lib/router.sh` + README (MCP CLI / HTTP fallback, route_history recording, remediation re-dispatch). *(Done 2026-05-16.)*
- `STORY-9.4.2` · `Done` · `P0` · `S` — Dispatched directives carry the locked pipeline version (per `EPIC-1.7.5`). *(Done 2026-05-16 — covered by `STORY-9.4.1`; `route_locked_pipeline_version()` enforces; hard error if missing.)*
- `STORY-9.4.3` · `Backlog` · `P1` · `S` — Subsystem reports back via MCP; orchestrator updates state + audit.

### EPIC-9.5 — Portfolio management
- `STORY-9.5.1` · `Done` · `P1` · `M` — Multiple projects in flight simultaneously; orchestrator routes per-project context. At `orchestrator/lib/portfolio.sh` (6 functions: can-dispatch/queue/drain/status/set-limit/blocked) + V17 `portfolio_queue` table. *(Done 2026-05-16.)*
- `STORY-9.5.2` · `Done` · `P1` · `S` — Per-project resource limits (max parallel directives, max workers). `portfolio_can_dispatch` reads `project.metadata->>'max_parallel_directives'` (default 3); blocks at limit, returns queued. *(Done 2026-05-16.)*
- `STORY-9.5.3` · `Done` · `P2` · `S` — Cross-project rollups: how many projects in each phase; what's blocked on what. V17 ships 5 views: `v_projects_by_phase`, `v_blocked_projects`, `v_active_directives`, `v_portfolio_health`, `v_project_resource_usage`. *(Done 2026-05-16.)*

### EPIC-9.6 — Unified cost ledger
- `STORY-9.6.1` · `Done` · `P0` · `M` — Cost rows from Plan + Build + Verify all aggregate into `spine_recording.costs` with `subsystem` column. At `db/flyway/sql/V16__unified_cost_ledger.sql` (ALTER + CHECK constraint + indexes). *(Done 2026-05-16; legacy `public.cost_row` coexists, backfill is a follow-on data migration.)*
- `STORY-9.6.2` · `Done` · `P0` · `S` — Per-phase / per-project / per-user / per-org rollups via SQL views. V16 defines `v_cost_per_project`, `v_cost_per_user`, `v_cost_per_org`, `v_cost_per_pipeline_version`. CLI rollup at `shared/cost/budget_rollup.sh` (5 subcommands). *(Done 2026-05-16.)*
- `STORY-9.6.3` · `Done` · `P1` · `S` — Budget enforcement (per `EPIC-2.3`) reads aggregated ledger. `shared/cost/router.py` `route()` checks budget via `get_budget_status()`; `budget_rollup.sh check-budget` exits 2 if over. *(Done 2026-05-16.)*

### EPIC-9.7 — Unified audit log
- `STORY-9.7.1` · `Done` · `P0` · `S` — Append-only `spine_audit` table; every subsystem writes here. At `db/flyway/sql/V15__spine_audit_schema.sql` with `spine_audit_writer` role (INSERT-only) + `reject_mutation` trigger (defense in depth). *(Done 2026-05-16.)*
- `STORY-9.7.2` · `Done` · `P0` · `S` — Schema: `(ts, project_id, phase, role, action, subject_id, rationale, prompt_hash?, output_hash?, cost?)`. All columns present + hash-chain (`prev_event_hash`, `content_hash`) for tamper detection. *(Done 2026-05-16; superset of original spec.)*
- `STORY-9.7.3` · `Backlog` · `P1` · `S` — Query API for compliance/audit: export project history; reconstruct any decision.

### EPIC-9.8 — Failure handling & re-routing
- `STORY-9.8.1` · `Done` · `P0` · `M` — Verify failure → orchestrator auto-generates remediation directive → routes back to Build with findings attached. At `orchestrator/lib/remediation.sh` (compose / check-retry / dispatch / surface). *(Done 2026-05-16.)*
- `STORY-9.8.2` · `Done` · `P1` · `S` — Max-retry policy per phase (default 5 verify-build loops before surfacing to user; read from `phases.yaml transitions_metadata.retry_policy.verify_build_loop_max`). Exit code 3 from `remediation_dispatch` on exhaustion → `remediation_surface_to_user` sets `project.status='paused'` + `metadata.blocked=true`. *(Done 2026-05-16.)*
- `STORY-9.8.3` · `Backlog` · `P1` · `S` — Build failure (engineer can't complete) → routes back to Plan with "scope unclear" feedback.

### EPIC-9.9 — Orchestrator API surface
- `STORY-9.9.1` · `Backlog` · `P0` · `M` — MCP server in `shared/mcp/` exposes orchestrator primitives (`project_create`, `project_status`, `phase_advance`, `approval_grant`).
- `STORY-9.9.2` · `Done` · `P1` · `M` — REST API for UI integration (`/api/v2/projects`, `/api/v2/approvals`, `/api/v2/audit`). At `shared/api/` (8 files, FastAPI app + 3 route modules + in-process MCP dispatch + subprocess-psql DB handle + JSON logging w/ secret redaction + request-id middleware + healthz/readyz/OpenAPI). *(Done 2026-05-16.)*
- `STORY-9.9.3` · `Done` · `P1` · `S` — CLI: `spine project new`, `spine project status`, `spine project approve <phase>`. At `orchestrator/bin/spine` (250 lines, full subcommand tree, MCP+psql dispatch, --format json|table|brief, --watch, --dry-run, exit codes 0/1/2/3/4/64) + README. *(Done 2026-05-16; chmod +x needed.)*
- `STORY-9.9.4` · `Backlog` · `P2` · `M` — Dashboard `shared/ui/` shows real-time orchestrator state (phase per project, approvals pending, cost rollup).

---

## Maintenance notes

### Restructure log
- **2026-05-16 (PM):** Documentation consolidation — 14 docs files → 10. New canonical structure:
  - `docs/ARCHITECTURE.md` (was `SPINE_UNIFIED_ARCHITECTURE.md`)
  - `docs/PRD.md` (absorbs `reqs/REQ-INIT-1*.md` + `reqs/REQ-INIT-6*.md` with section anchors)
  - `docs/BACKLOG.md` (was `MASTER_BACKLOG.md`)
  - `docs/PRACTICES.md` (absorbs `SPINE_PRACTICES.md` + `PROGRAM_DELIVERY.md` + `EXTENSIONS.md`)
  - `docs/IMPROVEMENT_CHECKLIST.md` (unchanged)
  - `docs/research/` (unchanged)
- **2026-05-16 (AM):** Major restructure — unified Spine + TRON architecture per `docs/ARCHITECTURE.md`. INIT-1 renamed to "Plan Subsystem"; INIT-2 absorbs TRON Standards Hierarchy (`EPIC-2.4`); INIT-3 gains TRON Sandbox/Calibration/Cross-LLM (`EPIC-3.5/6/7`); INIT-6 marked cross-cutting foundation; NEW `INIT-7` (Build), `INIT-8` (Verify/TRON), `INIT-9` (Orchestrator). Sprint Plan section added at top.

### Conventions
- When marking a story `Done`, leave the line in place and append `*(Done <YYYY-MM-DD>.)*` so the backlog stays a historical record, not just a TODO list.
- When adding a new story, follow the ID scheme strictly so the Jira-CSV converter (`STORY-5.3.1`) keeps working without ambiguity.
- When the verdict in `COMPETITIVE_LANDSCAPE.md` shifts (new competitor, new gap), re-tier the affected stories here and note the date in `EPIC-5.2`.
- **This file is the canonical product backlog.** `IMPROVEMENT_CHECKLIST.md` remains the maintenance/release-hygiene checklist — different scope, both stay.
