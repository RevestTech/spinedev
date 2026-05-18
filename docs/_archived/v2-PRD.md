# Spine — Product Requirements (PRD)

> Canonical product requirements document. Each REQ has a stable section anchor (`#req-init-N`). Cross-references from `BACKLOG.md`, `ARCHITECTURE.md`, and elsewhere link directly to those anchors.
>
> **Status legend:** *Draft v1* (awaiting first sign-off) · *Approved* (locked, work can proceed) · *Superseded* (new REQ replaces this one; keep for history)

## Index

| Anchor | REQ | Status | INIT |
|---|---|---|---|
| [#req-init-1](#req-init-1) | Plan Subsystem — intake → PRD → TRD → Roadmap | **Approved** 2026-05-16 | INIT-1 |
| [#req-init-6](#req-init-6) | Code & Document Knowledge Graph | **Approved** 2026-05-16 | INIT-6 |
| [#req-init-7](#req-init-7) | Build Subsystem — execution layer | **Draft v1** 2026-05-16 | INIT-7 |
| [#req-init-8](#req-init-8) | Verify Subsystem — TRON Integration | **Draft v1** 2026-05-16 | INIT-8 |
| [#req-init-9](#req-init-9) | Central Orchestrator | **Draft v1** 2026-05-16 | INIT-9 |

---

## REQ-INIT-1

**Plan Subsystem — SDLC Front Door (intake → PRD → TRD → Roadmap)**

| | |
|---|---|
| **Status** | **Approved** (locked 2026-05-16 by Khash) |
| **Owner** | Khash Sarrafi |
| **Initiative** | `INIT-1` in `docs/BACKLOG.md` |
| **Last updated** | 2026-05-16 |
| **Research** | `docs/research/COMPETITIVE_LANDSCAPE.md` |
| **Methodology source** | `~/.claude/.../memory/spine_intake_pattern.md` |

### 1.1. Summary

Build the **upfront SDLC pipeline** that takes a vibecoder from "I have an idea" to "fully baked, signed-off PRD + TRD + Roadmap, ready to execute." Pipeline composed of three phases: **Product Discovery → Technical Review (swarm) → Decomposition**, each producing a signed artifact, each gated on user approval, all powered by a **cost-aware tier router**, and all **declaratively customizable** by authorized roles so each org can shape the SDLC to fit its standards.

This is Spine's *defining* feature: a real-life SDLC pipeline that produces real artifacts, not a chat window pretending to be agile.

### 1.2. Problem

Today, Spine's `product` role has a prompt but no structured intake. A user with a vague idea ("I want to build an app for managing my team's time off") either gets a hallucinated build with wrong assumptions, or has to write a detailed directive cold — which they can't, because they don't yet know what they want.

Meanwhile, even when a user *can* write a clear directive, Spine has no pipeline that decomposes it into the standard SDLC artifacts (PRD, TRD, Roadmap) that engineering organizations actually use. Spine produces code without producing the spec the code is supposed to match.

The gap: **Spine has no front door, and no scaffold that turns the front-door conversation into the SDLC artifacts a real team would produce before writing code.**

### 1.3. Users & stakeholders

| Stakeholder | What they need from this feature |
|---|---|
| **Vibecoder** (non-technical builder) | Be walked through requirements they can't articulate cold; sign off on something they understand |
| **Solo developer using Spine for their own work** | Skip the intake quickly when the spec is already in their head; still get the SDLC artifacts for record |
| **Engineering / CTO / CPO (org-roles)** | Customize the pipeline to fit their org's standards (gates, swarm composition, artifact templates, banned patterns) |
| **CCO / COO / other exec roles** | Inject organizational concerns (compliance, ops readiness, customer impact) as gates or required swarm members |
| **Auditor / Security / Compliance** | Trust that every pipeline change is versioned + attributable; trust that every project is locked to a known pipeline version at start |
| **Finance / Procurement** | Trust that cost is bounded by per-project, per-user, per-org budgets enforced at the router |

### 1.4. Goals

#### MUST (P0 — release blocker)

- **G-1** The pipeline produces three signed artifacts in order: **PRD**, **TRD**, **Roadmap**. Each is a real file with a defined schema, not a chat transcript.
- **G-2** Each phase is gated on **explicit user sign-off**. No phase advances without it.
- **G-3** The pipeline definition is **declarative** (`sdlc-pipeline.yaml`) and editable by any role granted the `can_modify_sdlc_pipeline` capability.
- **G-4** The technical-review phase runs as a **swarm of supporting roles** synthesized by the architect, not a solo architect run.
- **G-5** **Cost-aware tier routing** is built in: each phase has a default tier; per-turn escalation rules; per-user/org budget enforcement.
- **G-6** Per-project-type intake **templates** exist for at least: web app, internal tool, data pipeline, mobile app, API service, CLI tool.

#### SHOULD (P1 — material to differentiation)

- **G-7** A **non-terminal UI** (web dashboard) is the primary front door — drop-a-project form, approval queue, cost meter, live phase status.
- **G-8** The pipeline manifest is **versioned in git** with author / timestamp / rationale per change.
- **G-9** Projects **lock to a pipeline version** at start so mid-flight edits don't break in-flight work.
- **G-10** Approval gates support **request-changes** (not just approve/reject), routing back to the producing role with the user's notes.

#### COULD (P2 — nice-to-have for v1)

- **G-11** Multi-approver gates (e.g., TRD requires CTO + Compliance to both sign).
- **G-12** Cost projection at the start of each phase ("this phase will likely cost $X — proceed?").
- **G-13** Pipeline templates for common org archetypes (startup-lite, regulated-enterprise, design-led).

#### WON'T (out of scope for this REQ)

- Actual code build / test / deploy execution — those live in `INIT-3` (Trust & Reproducibility), `INIT-7` (Build), `INIT-8` (Verify).
- Multi-tenant SaaS hosting — Spine is local-deploy by design.
- Replacing Jira/Linear — Spine produces a Roadmap that *exports* to those tools; it does not become the issue tracker.

### 1.5. Functional requirements

#### FR-1 — Pipeline-as-data manifest

A YAML file (`sdlc-pipeline.yaml` per project, with a root default at `~/.spine-development/pipelines/default.yaml`) declares:

```yaml
version: 1
phases:
  - id: discovery
    role_lead: product
    artifact: PRD
    template: prd-v1
    tier_default: medium
    gate:
      type: user_approval
      approvers: [user]
  - id: technical_review
    role_lead: architect
    swarm:
      members: [researcher, engineer, datawright, operator, qa]
      composition_rule: project_type
    artifact: TRD
    template: trd-v1
    tier_default: high
    gate:
      type: user_approval
      approvers: [user]
  - id: decomposition
    role_lead: planner
    role_support: [conductor]
    artifact: Roadmap
    template: roadmap-v1
    tier_default: medium
    gate:
      type: user_approval
      approvers: [user]
overrides:
  org_bundle: acme-corp
  team: null
  project: null
```

The Spine runtime reads this manifest and dispatches accordingly. No phase ordering, role assignment, or gate type is hardcoded in Spine source code.

#### FR-2 — Discovery (intake → PRD)

Implements the **5-move dialogue protocol** (`spine_intake_pattern.md`):

1. **Naive cast** — `product` makes a charitable guess at the user's intent from a 1-line problem statement; presents it as a strawman.
2. **Provoke correction** — invites the user to attack the strawman.
3. **Reframe and redo** — when corrected, throws out the strawman and rebuilds, not patches.
4. **Tier the outputs** — separates MUST / SHOULD / COULD goals; surfaces tradeoffs.
5. **Produce the artifact** — finalizes a PRD file matching `template: prd-v1`.

**Project-type templates** (`templates/intake/<type>.yaml`) define the question vocabulary for moves 1 and 4. The set of templates is editable; new types can be added without touching Spine source. Initial set: web-app, internal-tool, data-pipeline, mobile, api-service, cli-tool.

**Refuse-to-advance rule:** the PRD cannot be marked complete while any required field is `TBD` or empty.

#### FR-3 — Technical Review (swarm → TRD)

Architect runs as **swarm lead**: dispatches scoped sub-directives to each swarm member (researcher / engineer / datawright / operator / qa), collects their per-lens contributions, synthesizes into a single TRD matching `template: trd-v1`.

**Dynamic swarm composition** per project type:
- Web app → researcher, engineer, operator, qa (no datawright)
- Internal tool → researcher, engineer, qa (no datawright, no operator unless infra change)
- Data pipeline → researcher, engineer, datawright, operator
- Mobile → researcher, engineer, qa, operator (for distribution)
- API service → researcher, engineer, qa, operator
- CLI tool → researcher, engineer, qa

Swarm composition rules live in `sdlc-pipeline.yaml` under each project-type entry and are editable by authorized roles.

**TRD content (template trd-v1):** architecture, data model, integrations, NFRs, tech choices, risks, open questions, scope of work, cost projection.

#### FR-4 — Decomposition (PRD + TRD → Roadmap)

`planner` (with `conductor` as supporting role) reads PRD + TRD and produces a Roadmap matching `template: roadmap-v1`:

- INIT / EPIC / STORY hierarchy with stable IDs (matching the `INIT-N` / `EPIC-N.M` / `STORY-N.M.K` scheme already in `BACKLOG.md`)
- Each story sized (XS/S/M/L/XL) and estimated (cost + duration)
- Inter-story dependencies declared
- Sequencing recommendation (which epic first, why)

Roadmap export to Jira CSV (per `STORY-5.3.1` in BACKLOG.md) is a follow-on, not a blocker.

#### FR-5 — Approval gates

Each gate is one of:
- **`user_approval`** — single user signs; default
- **`multi_approver`** (P2) — list of roles, all must sign
- **`auto`** (escape hatch) — no gate; used for solo-dev rapid mode

Gate actions per artifact:
- **Approve** — phase advances
- **Reject** — pipeline terminates; user can restart from earlier phase
- **Request changes** — routes back to producing role with user's notes attached; phase re-runs

All gate actions are logged with timestamp + actor + decision + notes.

#### FR-6 — Cost-aware tier router

Five composable mechanisms:

1. **Per-phase default tier** — declared in `sdlc-pipeline.yaml` per phase; sets the baseline.
2. **Per-turn escalation classifier** — a cheap classifier (Haiku-class) inspects each turn's context and decides whether to escalate from the phase default to a higher tier. Classification rules: synthesis turns → high; decision turns → high; chitchat / clarification → low.
3. **Org-bundle model menu + budget** — org policy bundle (from `INIT-2`) defines the approved model menu and per-user/team/project budget caps. Router selects within the menu; blocks dispatch when budget exhausted.
4. **Prompt caching** — long intake conversations reuse cached prefix turns; cache-hit cost is a fraction of cold cost.
5. **User override** — power user can pin a tier per directive; logged and counted against budget.

All five surface to the UI (cost meter shows current spend + tier choice rationale).

#### FR-7 — Customization authority model

A **capability**, `can_modify_sdlc_pipeline`, gates pipeline edits. Capability is granted by the **org policy bundle** (from `INIT-2`) — Spine ships with sane defaults (engineering role granted by default), but the bundle is the source of truth.

Customizable surfaces:
- Phase set (add / remove / reorder)
- Roles per phase + swarm composition rules
- Artifact templates (PRD / TRD / Roadmap schemas)
- Gate types and approver lists
- Cost tier defaults
- Project-type templates

**Override hierarchy** (most specific wins):
1. Org policy bundle (baseline)
2. Team override
3. Project override

Each level can only override what it's authorized to override (e.g., a team may not be allowed to remove a compliance gate the org bundle requires).

#### FR-8 — Versioning, locking, audit

- Pipeline manifest is **git-tracked** in the org bundle repo + project repo.
- Every edit produces a commit with author / timestamp / rationale (rationale is a required field on the edit action, not optional).
- A new project **locks** to the pipeline version current at start; the lock is recorded in the project metadata.
- A locked project is **migrated** to a new pipeline version only by explicit user action (with diff preview).
- All gate decisions + all pipeline edits + all router decisions feed the audit log (defined in `INIT-3`).

### 1.6. Non-functional requirements

#### NFR-1 — Cost
- A complete intake → PRD → TRD → Roadmap cycle for a medium-complexity project (web app, ~10 acceptance criteria) must fit under **$5** when using the recommended default tier mix (Haiku-class for chat, Sonnet-class for synthesis, Opus-class only for TRD synthesis).
- Budget caps are *hard*: a dispatch that would exceed the cap is blocked, not warned.

#### NFR-2 — Performance
- Per-turn latency: intake turns ≤ 8s p95 (the existing daemon poll interval); TRD synthesis ≤ 60s p95.
- Full PRD → TRD → Roadmap wall-clock target: ≤ 30 minutes for medium complexity.

#### NFR-3 — Security & trust
- No outbound calls except to the configured LLM endpoint(s).
- Audit log is append-only and survives uninstall.
- Pipeline manifest changes never take effect until the next phase boundary (no mid-phase mutation).

#### NFR-4 — Customizability (the flexibility principle)
- Zero phase, role, artifact, or gate is hardcoded in Spine source. Everything lives in the manifest.
- Adding a new project-type template requires editing config only — no Spine source changes.
- An org can fork the default pipeline and run an entirely different SDLC shape without forking Spine itself.

#### NFR-5 — Observability
- The dashboard surfaces, in real time: which phase is active, which role is working, current tier choice, current run cost, projected total cost, pending approvals.
- Every artifact links to the turn-level history that produced it.

### 1.7. Dependencies

- **`INIT-2` (Enterprise Control & Standards)** — org policy bundle format is the carrier for capability grants and pipeline overrides.
- **`INIT-3` (Trust & Reproducibility)** — audit log primitives.
- **Existing Spine roles** — `product`, `architect`, `researcher`, `engineer`, `datawright`, `operator`, `qa`, `planner`, `conductor` all stay; their prompts get updated to fit the new pipeline contract.
- **Anthropic prompt caching** — assumed available for FR-6 mechanism #4.

### 1.8. Open questions

- **OQ-1: CCO scope.** "CCO" could be Chief Compliance / Customer / Creative / Communications Officer. Recommendation: treat as ambiguous in v1; let org bundle specify.
- **OQ-2: Solo-dev rapid mode.** Should there be a CLI shortcut that bypasses the front-door UI entirely? Recommendation: ship without; add only if usage shows demand.
- **OQ-3: PRD/TRD/Roadmap schema — invent vs adopt.** Adopt IEEE 830 / Arc42? Recommendation: invent a lighter schema for v1; document compatibility mappings for v2.
- **OQ-4: Pipeline editing UX.** Edit YAML directly vs. dedicated editor UI? Recommendation: YAML for v1; UI follows when there's evidence non-engineers want to edit.
- **OQ-5: Migration of locked projects.** Re-run completed phases? Recommendation: no by default; user-triggered re-run supported.

### 1.9. Acceptance criteria

A reasonable user (vibecoder profile, no prior Spine experience) can:
- [ ] Open the Spine front-door UI, type a one-line problem statement, and reach a signed-off PRD in ≤ 30 minutes for a medium-complexity web app.
- [ ] Reach a signed-off TRD from that PRD via swarm review in ≤ 45 minutes.
- [ ] Reach a signed-off Roadmap (INIT/EPIC/STORY) from PRD+TRD in ≤ 15 minutes.
- [ ] See per-phase cost breakdowns in the UI; total ≤ $5 for the above complexity profile.
- [ ] Reject the PRD mid-flight, request changes, and have the `product` role rebuild it incorporating their notes.

An org admin can:
- [ ] Edit `sdlc-pipeline.yaml` to insert a new "Security Review" phase between TRD and Decomposition without touching Spine source.
- [ ] Add a new project type "regulated-saas" with its own intake template and swarm composition.
- [ ] Set a team-wide budget cap and confirm dispatches blocked when exceeded.
- [ ] Roll back a pipeline change via git and see in-flight projects unaffected.

---

## REQ-INIT-6

**Code & Document Knowledge Graph**

| | |
|---|---|
| **Status** | **Approved** (locked 2026-05-16 by Khash) |
| **Owner** | Khash Sarrafi |
| **Initiative** | `INIT-6` in `docs/BACKLOG.md` |
| **Last updated** | 2026-05-16 |
| **Research** | `docs/research/COMPETITIVE_LANDSCAPE.md` + 2026-05-16 graph-RAG survey (Microsoft GraphRAG, Thoughtworks CodeConcise, GitLab Knowledge Graph, `safishamsi/graphify`) |

### 6.1. Summary

Build a **code + document knowledge graph** as a foundational capability every Spine role can query. Source-parse the codebase (tree-sitter) and the documentation/governance artifacts (REQs, PRDs, TRDs, ADRs, role memory, audit log) into a graph of typed nodes and edges, stored in the existing Postgres alongside the recording layer, queryable via MCP tools, kept fresh by the existing watcher. Hybrid graph + vector retrieval (LangChain) layered on top so semantic and structural questions both have a single answer.

This is the **structural-reasoning substrate** that makes every other Spine role smarter and cheaper to run.

### 6.2. Problem

Spine roles today reason about code and docs via grep + read-file. That works for tiny scopes but breaks down for the questions that matter most in an SDLC pipeline:

- *"Who calls this function?"* — researcher today greps; misses indirect callers.
- *"What's the blast radius of changing this module?"* — engineer today guesses; auditor can't verify.
- *"Which existing code does this PRD touch?"* — decomposer today hand-waves; story dependencies are heuristic.
- *"Which REQ drove the auth refactor and what tests cover it?"* — nobody can answer without a half-hour of manual archaeology.
- *"Has anyone touched this module before, and what lessons did the memory role learn?"* — lost.

Each of those questions burns thousands of tokens (and seconds-to-minutes of wall-clock) per ask, with non-deterministic answers. A graph turns them into millisecond, deterministic queries.

Field evidence (2026-05): Microsoft GraphRAG, Thoughtworks CodeConcise (6 weeks → 2 weeks reverse engineering), GitLab Knowledge Graph (shipped in-product), `safishamsi/graphify` (Claude Code skill), `ruflo-knowledge-graph` (one of ruflo's 32 plugins). The pattern has converged; Spine is conspicuously behind.

### 6.3. Users & stakeholders

| Stakeholder | What they need |
|---|---|
| **All role agents** | Cheap, deterministic answers to structural questions; reduced grep/read cost |
| **`researcher`** | `find_callers`, `trace_dependency`, `code_neighborhood` instead of grep loops |
| **`architect`** (TRD synthesis) | Query current system shape; write TRD as delta, not blank slate |
| **`engineer`** (refactor / build) | Enumerate impact radius before changing; cite affected callers in the report |
| **`auditor`** | Verify reported scope by graph traversal, not by trusting the engineer's `## Files touched` |
| **`planner` / decomposer** (EPIC-1.3) | Detect story dependencies deterministically from overlapping code regions |
| **`memory`** | Pin lessons to specific code/doc nodes so they surface only when those regions are touched |
| **Org admins** | Add custom node/edge types via config (e.g., `compliance_tag` nodes for regulated orgs) |
| **End user / vibecoder** | Implicit beneficiary — graph makes Spine cheaper and faster without them ever seeing it |

### 6.4. Goals

#### MUST (P0)

- **G-1** Graph nodes cover **code** (file, module, class, function, method, variable, type) and **docs** (REQ, PRD, TRD, ADR, Roadmap, README, role-prompt, memory lesson, audit event).
- **G-2** Graph edges cover **code relationships** (CALLS, IMPORTS, DEFINES, REFERENCES, CONTAINS) and **cross-link relationships** (TOUCHES, SATISFIES, DECIDED_BY, TESTED_BY, OWNED_BY).
- **G-3** Storage lives in the **existing Postgres** (new `spine_kg` schema), not a separate database. No new infra.
- **G-4** **Tree-sitter** parses code; no LSP servers required to run.
- **G-5** Indexer is **incremental** — updates on git commits, never re-indexes the whole tree.
- **G-6** Query API exposed via **MCP tools** (`graph_query`, `find_callers`, `trace_dependency`, `code_neighborhood`, `doc_for_region`, `impact_radius`, `who_owns`).
- **G-7** **At least 5 Spine roles** updated to call graph tools by default (researcher, architect, engineer, auditor, decomposer).

#### SHOULD (P1)

- **G-8** **Hybrid graph + vector RAG** (LangChain `GraphRetriever` + `MultiVectorRetriever`).
- **G-9** Node/edge types are **extensible via config** — org bundles can add custom types.
- **G-10** Graph snapshots are **versioned with commits** — point-in-time queries supported.

#### COULD (P2)

- **G-11** Apache AGE extension for native Cypher queries.
- **G-12** Graph visualization in the UI dashboard.
- **G-13** Cross-repository graph.

#### WON'T

- Replace Postgres with Neo4j or any graph-native DB.
- Build our own code parsers — tree-sitter exclusively.
- Index third-party libraries' internal code.

### 6.5. Functional requirements

#### FR-1 — Graph schema

**Node types (v1):**

| Category | Types |
|---|---|
| Code | `File`, `Module`, `Class`, `Function`, `Method`, `Variable`, `TypeDef` |
| Test | `TestFile`, `TestCase` |
| Doc | `Document` (subtype: REQ/PRD/TRD/ADR/Roadmap/README/role-prompt/memory), `Heading`, `Reference` |
| Spine flow | `Initiative`, `Epic`, `Story`, `Directive`, `Report`, `Role`, `AuditEvent` |
| External | `Issue`, `PullRequest`, `Commit`, `Person` |
| Extensible | `CustomNode` (typed by org bundle) |

**Edge types (v1):**

| Category | Types |
|---|---|
| Code | `CALLS`, `IMPORTS`, `DEFINES`, `REFERENCES`, `OVERRIDES`, `EXTENDS`, `IMPLEMENTS`, `CONTAINS` |
| Test | `TESTS`, `COVERS` |
| Doc | `LINKS_TO`, `CITES`, `SUPERSEDES`, `DERIVED_FROM`, `APPROVED_BY` |
| Cross-link | `TOUCHES`, `SATISFIES`, `DECIDED_BY`, `TESTED_BY`, `OWNED_BY`, `PRODUCED_BY` |
| Spine flow | `PART_OF`, `PRODUCED`, `LOCKED_TO` |

Every node has: `id`, `type`, `subtype?`, `repo`, `commit_sha`, `created_at`, `valid_from`, `valid_to?`, `properties_json`. Every edge has: `from_id`, `to_id`, `type`, `commit_sha`, `properties_json`. The `commit_sha + valid_from/to` columns enable point-in-time queries (G-10).

#### FR-2 — Storage

- New schema `spine_kg` in the existing `db/` Postgres instance.
- Tables: `kg_node`, `kg_edge`, `kg_node_embedding` (pgvector), `kg_node_property`, `kg_index_state`.
- Indexes: B-tree on `(type, repo, commit_sha)`, GIN on properties, IVFFlat on embedding.
- Migrations via existing Flyway setup (`db/flyway/sql/V<n>__kg_schema.sql`).
- **No separate database, no Neo4j, no new container.**

#### FR-3 — Code parser (tree-sitter)

- One grammar per supported language; v1: Python, TypeScript/JavaScript, Go, Rust, Bash, SQL, Markdown.
- Parser emits nodes + edges per file in a deterministic JSON format.
- New languages added by dropping a grammar + extractor config in `lib/kg/extractors/<lang>.yaml`.

#### FR-4 — Document parser

- Markdown parser extracts: headings → `Heading` nodes; links → `LINKS_TO` edges; embedded Spine IDs (`INIT-N` / `EPIC-N.M` / `STORY-N.M.K` / `REQ-INIT-N` / `ADR-N` / `FR-N`) → typed reference edges.
- REQ / PRD / TRD / Roadmap files parsed to `Document` nodes with sections as child `Heading` nodes; cross-references become `CITES` / `DERIVED_FROM` edges.
- Role prompts and `memory.md` files indexed similarly; lessons become `MemoryLesson` nodes.

#### FR-5 — Incremental indexer

- Extend `db/watcher/` to drive graph index.
- On every git commit: compute changed file set → re-parse changed files only → diff new vs current → emit `INSERT`/`UPDATE`/`DELETE` rows → update `kg_index_state`.
- Cold start: index whole repo at first install; incremental thereafter.
- Target: incremental update ≤ 5s for a 10-file commit on a 100k-LOC repo.

#### FR-6 — Query API + MCP tools

Exposed via the MCP server from `EPIC-2.2`. Tools (v1):

| Tool | Returns |
|---|---|
| `graph_query(cypher_or_sql)` | Raw query result (escape hatch) |
| `find_callers(symbol, depth=1)` | Caller functions/methods with file:line |
| `trace_dependency(from, to)` | Path through CALLS/IMPORTS graph |
| `code_neighborhood(file_or_symbol, radius=2)` | Subgraph within N hops |
| `doc_for_region(file:lines)` | REQs, ADRs, memory lessons touching this code |
| `impact_radius(symbol_or_region)` | Files/tests potentially affected |
| `who_owns(file_or_symbol)` | Roles + lessons + ADRs claiming ownership |
| `find_by_satisfies(req_or_story_id)` | Code regions satisfying a REQ/STORY |
| `hybrid_search(natural_language_query)` | LangChain-backed hybrid graph+vector retrieval (G-8) |

All tools subject to the org-bundle capability model.

#### FR-7 — Role-prompt integration

Updated role prompts (one story per role) teach each agent to **call graph tools before falling back to grep**:

- `researcher.md` — "Use `find_callers` / `trace_dependency` / `code_neighborhood` to answer structural questions. Fall back to grep only when the symbol isn't yet in the graph."
- `architect.md` — "Before drafting a TRD section that touches existing code, run `code_neighborhood` and `impact_radius` to write the TRD as a delta from current state."
- `engineer.md` — "Before reporting a change, run `impact_radius` and include affected callers in the `## Files touched` section."
- `auditor.md` — "Re-run `impact_radius` against the engineer's report; flag any caller they missed."
- `planner.md` (decomposer) — "Use `code_neighborhood` and `impact_radius` to detect overlapping code regions between candidate stories; flag dependencies automatically."
- `memory.md` — "Pin every new lesson to the code/doc nodes it applies to via `OWNS` / `TOUCHES` edges."

#### FR-8 — Hybrid graph + vector RAG (LangChain)

- LangChain `MultiVectorRetriever` over `kg_node_embedding` for semantic recall.
- LangChain `GraphRetriever` / custom traversal over `kg_node` + `kg_edge` for structural recall.
- Hybrid wrapper that runs both and re-ranks (default: BM25 + RRF, swappable).
- Exposed as `hybrid_search` MCP tool.
- Embeddings generated lazily on first query touching a node; cached.
- Embedding model configurable via org bundle.

### 6.6. Non-functional requirements

#### NFR-1 — Performance
- `find_callers` / `trace_dependency` / `code_neighborhood` (≤2 hops): p95 ≤ 50ms on a 100k-LOC repo.
- `impact_radius` (multi-hop): p95 ≤ 200ms.
- `hybrid_search`: p95 ≤ 500ms.
- Incremental index update: p95 ≤ 5s for a 10-file commit.
- Cold-start full index: ≤ 5 minutes per 100k LOC.

#### NFR-2 — Storage
- Graph storage overhead ≤ 30% of repo on-disk size for code; doc graph overhead negligible.
- Embeddings storage budget configurable; default 1024-dim float16 ≈ 2KB/node.

#### NFR-3 — Cost
- Graph queries are free (local Postgres, no LLM).
- Embedding generation cost bounded — only nodes hit by `hybrid_search` are embedded; lifetime cost capped via the same budget enforcement as `EPIC-1.5`.

#### NFR-4 — Customizability
- New node/edge types added via config files in `lib/kg/extractors/` and `lib/kg/schema-extensions/`.
- Org bundle can ship custom node types (`compliance_tag`, `sla_tier`, `pii_class`) and extract rules.

#### NFR-5 — Observability
- Dashboard shows: index freshness (commits behind), node/edge counts by type, query latency p50/p95, embedding spend.
- Every query logged to the audit log (per INIT-3).

#### NFR-6 — Reproducibility
- Point-in-time queries (`as_of <commit_sha>`) supported via `valid_from`/`valid_to` columns.

### 6.7. Dependencies

- **`db/` Postgres recording layer** — existing. KG lives in a new schema in the same instance.
- **`EPIC-2.2` (MCP server)** — KG tools exposed via MCP.
- **`INIT-3` audit log** — KG queries logged; KG `AuditEvent` nodes link to log rows.
- **Tree-sitter** — runtime dependency; ship pre-built grammars.
- **LangChain** — optional Python dep for hybrid RAG layer (FR-8 only).

### 6.8. Open questions

- **OQ-1: AGE vs adjacency-list.** v1 ships adjacency-list for portability. Add AGE later if Cypher missed.
- **OQ-2: Embedding provider.** Default to local model (e.g., `nomic-embed-text`); org bundle can override to cloud.
- **OQ-3: Cross-repo graph (G-13).** Schema already has `repo` column; ship single-repo in v1, design open for cross-repo later.
- **OQ-4: Indexing prior commits.** Ship current-commit only in v1; full history as P2.
- **OQ-5: PII / secrets in indexed code.** Pluggable redactor; default scrubs common patterns (AWS keys, JWTs, emails); org bundle can extend.

### 6.9. Acceptance criteria

A reasonable user / role agent can:

- [ ] Run `find_callers("validate_token")` and get all direct + transitive callers in ≤ 50ms on a 100k-LOC repo.
- [ ] Run `impact_radius("auth/session.py")` and get the full set of files + tests that depend on it.
- [ ] Ask `hybrid_search("functions that handle session expiration")` and get a ranked list combining semantic + structural matches.
- [ ] Run `doc_for_region("auth/session.py:1-50")` and get the REQs, ADRs, and memory lessons touching that code.
- [ ] An `auditor` agent can verify an engineer's `## Files touched` claim by comparing it to `impact_radius`, flagging missed callers automatically.
- [ ] A `planner` agent decomposing a PRD into stories can flag two candidate stories as dependent because they `TOUCHES` overlapping code nodes.
- [ ] An org admin can add a `compliance_tag` node type via config without changing Spine source.
- [ ] An auditor can run an `as_of <past_commit_sha>` query and reconstruct what the graph said when a historical directive was dispatched.

---

## REQ-INIT-7

**Build Subsystem — execution layer (engineer / operator / datawright + KG parsers)**

| | |
|---|---|
| **Status** | **Draft v1** (awaiting sign-off) |
| **Owner** | Khash Sarrafi |
| **Initiative** | `INIT-7` in `docs/BACKLOG.md` |
| **Last updated** | 2026-05-16 |
| **Research** | `docs/research/COMPETITIVE_LANDSCAPE.md` (fragile-contracts gap) · `docs/ARCHITECTURE.md` §4 + §5 · `memory/spine_tech_stack_decisions.md` (bash-daemon moat) |

### 7.1. Summary

Formalize Spine's existing execution roles (`engineer`, `operator`, `datawright`) into a coordinated **Build subsystem** with a clean boundary, a typed artifact contract to the Orchestrator and Verify, and first-class Knowledge Graph integration. Build receives directives from the Orchestrator, dispatches them to role daemons backed by a worker pool, emits a Pydantic-typed `BuildArtifact` (code + tests + manifest + KG impact set), and hands off to Verify via the shared MCP server. KG parsers (tree-sitter) live inside Build under `build/kg/parsers/`; their output flows into the shared `spine_kg` schema so Plan and Verify can query the same graph.

Closes three gaps: (1) Spine roles work but aren't grouped as a subsystem with explicit contract; (2) engineer reports are free-form markdown the auditor must trust, instead of typed artifacts the auditor can verify against the graph; (3) bash daemon infrastructure in `lib/` has no module boundary. Structural work — no new languages, bash daemons stay (debuggability moat preserved), opportunistic migration rather than big-bang.

### 7.2. Problem

Spine's execution layer today is *informal*. Three pain points:

- **No subsystem boundary.** Changes to `lib/team-agent-daemon.sh` can silently affect Plan-side or orchestration-side behavior. No place says "this is what Build owns."
- **Fragile contracts.** Engineer self-reports prose. Auditor reads, greps to spot-check, trusts. Verify cross-LLM validation has no machine-readable manifest. Same gap as Devin / Factory / Cursor.
- **KG integration is ad-hoc.** REQ-INIT-6 ships the graph, but no role uses it deterministically. Engineer guesses blast radius; operator asks the user; datawright doesn't register outputs.

INIT-7 promotes Build from a directory pattern to a subsystem with a contract.

### 7.3. Users & stakeholders

| Stakeholder | What they need |
|---|---|
| **Orchestrator** (`INIT-9`) | Single typed entry point (`build_dispatch`); typed completion event (`BuildArtifact`) |
| **`engineer` role** | Daemon contract making "call `impact_radius` before reporting done" the default path |
| **`operator` role** | Daemon contract surfacing `who_owns(target)` before mutating infra |
| **`datawright` role** | Way to register pipeline outputs as `Document` nodes in KG |
| **`auditor` / Verify** | Machine-readable `BuildArtifact` to verify against KG impact set — no prose-reading |
| **Plan subsystem** | Stable Build contract so decomposer can predict what stories emit |
| **KG** (`INIT-6`) | Build owns parsers + indexer hooks; storage stays in `shared/db/spine_kg/` |
| **Solo dev (Khash)** | Debug failing engineer run by reading bash + tailing one log — no Python stack to learn |

### 7.4. Goals

#### MUST (P0)

- **G-1** `build/` subsystem directory with sub-structure (`roles/`, `daemons/`, `workers/`, `kg/parsers/`, `kg/extractors/`, `tests/`) + module-level README.
- **G-2** Build talks to Plan and Verify **only through `shared/mcp/`**. CI boundary check enforces.
- **G-3** Orchestrator dispatches via `build_dispatch(role, directive, locked_pipeline_version, project_id)`.
- **G-4** Build emits Pydantic-typed `BuildArtifact` for every directive — never free-form markdown.
- **G-5** `engineer` daemon calls `impact_radius` before reporting completion; node IDs appear in `BuildArtifact.kg_impact`.
- **G-6** Existing bash daemons migrate into `build/daemons/` and `build/roles/` with no regression.
- **G-7** Bash stays the orchestration language; Python permitted only inside KG parsers/extractors.

#### SHOULD (P1)

- **G-8** `operator` daemon calls `who_owns(target)` before mutating infra.
- **G-9** `datawright` daemon registers pipeline outputs as `Document` nodes.
- **G-10** Auditor verifies `BuildArtifact.kg_impact` against graph traversal before passing to Verify.
- **G-11** Build registers with Orchestrator on boot; declares roles it provides.

#### COULD (P2)

- **G-12** Worker pool elasticity (per-role dynamic scaling).
- **G-13** Build health endpoint exposing daemon liveness, worker saturation, last KG-parse ts.
- **G-14** Parser cache (tree-sitter ASTs cached per (file, content_hash)).

#### WON'T

- Verification / scanning / sandbox — those live in `verify/` per REQ-INIT-8.
- Planning / intake / PRD/TRD/Roadmap — those live in `plan/` per REQ-INIT-1.
- KG storage / hybrid RAG / MCP graph-query — those live in REQ-INIT-6.
- Replacing bash daemons with Python orchestration framework.
- Multi-tenant isolation between Build workers.

### 7.5. Functional requirements

#### FR-1 — Subsystem boundary

`build/` is self-contained per `docs/ARCHITECTURE.md §4`. Source imports only from `build/**` and `shared/**`. Cross-subsystem calls via `shared/mcp/` only. CI lint (`tools/check-module-boundaries.sh`) fails build on cross-subsystem imports.

#### FR-2 — Orchestrator wiring (`build_dispatch` MCP tool)

Single MCP tool from `shared/mcp/`. Input: `(role, directive, project_id, locked_pipeline_version, parent_directive_id?, budget_remaining_usd)`. Output: `(directive_id, accepted, queued_position, estimated_start_seconds)`. Build registers on boot, declaring role set. Orchestrator never hardcodes the role list.

#### FR-3 — `BuildArtifact` contract

Every completed directive emits a Pydantic `BuildArtifact` written to `shared/db/spine_audit` and surfaced via MCP `build_completed`. Fields: `directive_id`, `project_id`, `role`, `code_changes[]` (path, change_type, diff_hash, lines_added/removed), `tests_added[]` / `tests_run[]`, `kg_impact: list[str]` (KG node IDs), `cost_usd`, `duration_seconds`, `rationale`, `completed_at`, `pipeline_version`.

**Refuse-to-emit rule:** `BuildArtifact` cannot be sealed if `kg_impact` is empty for an `engineer` directive that produced any `code_changes`.

#### FR-4 — KG integration call sites

- **Engineer**: before sealing artifact, calls MCP `impact_radius(changed_files=[...])`; writes IDs into `kg_impact`. Auditor cross-checks.
- **Operator** (P1): before infra-mutating action, calls `who_owns(target)`; routes approval to owner.
- **Datawright** (P1): after pipeline output, calls `kg_register_document(path, source_data_nodes=[...])`.

#### FR-5 — Daemon migration

`lib/team-agent-daemon.sh` → `build/daemons/`. Role-prompts → `build/roles/<role>/prompt.md`. Worker primitives → `build/workers/`. Legacy `lib/` paths kept as symlinks for one release cycle. Migration opportunistic per ARCHITECTURE §6 Phase 4.

#### FR-6 — Subsystem registration

On boot, Build issues MCP `subsystem_register(name="build", roles=[...], version=...)`. Orchestrator stores in `spine_lifecycle.subsystem_registry`. Dispatch to unknown role returns `accepted=False, reason="unknown_role"`.

#### FR-7 — Auditor verification hook

Before Orchestrator routes `BuildArtifact` to Verify, in-process check compares `kg_impact` to graph traversal of `code_changes`. Mismatch → reject + remediation directive. Lightweight check complementing Verify pipeline.

### 7.6. Non-functional requirements

- **NFR-1 Performance:** Daemon startup ≤ 5s. Directive → BuildArtifact p95 ≤ 90s trivial, ≤ 10 min medium. KG `impact_radius` p95 ≤ 500ms. Default 10 workers/manager.
- **NFR-2 Reliability:** Crash restart ≤ 5s; in-flight directives requeue via file-lock. Transactional `BuildArtifact` writes. CI boundary check.
- **NFR-3 Observability:** Structured log per transition. Dashboard surfaces per-role saturation, last artifact ts, graph latency. `BuildArtifact` is primary observability surface.
- **NFR-4 Cost:** No new model calls. KG queries are local Postgres — zero LLM cost. Per-directive cost in `cost_usd` rolls into `spine_recording.costs`.
- **NFR-5 Debuggability:** Bash-only orchestration; one log + one bash script per failed directive.

### 7.7. Dependencies

- **`INIT-6`** — provides KG MCP tools. Build is primary consumer.
- **`INIT-9`** — provides `build_dispatch` and lifecycle schema.
- **`EPIC-2.2`** — MCP server must host `build_dispatch`, `build_completed`, KG tools.
- **Existing Spine daemons** — INIT-7 migrates, doesn't rewrite.
- **`INIT-3`** — `BuildArtifact` writes into audit log.

### 7.8. Open questions

- **OQ-1:** `BuildArtifact` location — `build/schemas/` or `shared/schemas/`? Recommendation: `shared/schemas/build/`.
- **OQ-2:** Auditor hook (FR-7) placement — Orchestrator step or Verify pre-check? Recommendation: Orchestrator for v1.
- **OQ-3:** Worker elasticity — static 10 or per-role scaling? Recommendation: static for v1.
- **OQ-4:** Legacy `lib/` symlinks — keep how long? Recommendation: one release cycle.
- **OQ-5:** Datawright non-file outputs — `Document` node or new `DataAsset` type? Defer to REQ-INIT-6 extensibility.

### 7.9. Acceptance criteria

Developer:
- [ ] `spine project new --type web-app` → engineer daemon picks up dispatched directive within 5s.
- [ ] Engineer calls `impact_radius` before sealing `BuildArtifact` (visible in log).
- [ ] `BuildArtifact` in `spine_audit` has populated `code_changes`, `tests_added`, `kg_impact`, `cost_usd`, `rationale`.
- [ ] Skip `impact_radius` in daemon → artifact rejected with `kg_impact_missing` + auto-issued remediation directive.
- [ ] Stray cross-subsystem import → CI boundary check fails build.
- [ ] Move one daemon `lib/` → `build/daemons/` → integration tests still pass.

Auditor:
- [ ] Pull `BuildArtifact` for any directive, verify `kg_impact` matches independent `impact_radius` traversal.
- [ ] Confirm Build never wrote to `plan/**` or `verify/**` during a directive.
- [ ] Reconstruct full Build phase from `spine_audit` rows.

Future contributor:
- [ ] Write a new role daemon (e.g., `migrator`) from `build/README.md` + this REQ without touching Plan/Verify/Orchestrator.
- [ ] Debug failing engineer directive by tailing one log + reading one bash script.

### 7.10. Related artifacts

- `docs/ARCHITECTURE.md` §2, §4, §5
- `docs/BACKLOG.md` INIT-7 (`EPIC-7.1` through `EPIC-7.5`)
- `build/README.md`
- `docs/PRD.md#req-init-1` / `#req-init-6` / `#req-init-8` / `#req-init-9`
- `PROTOCOL.md`
- `memory/spine_tech_stack_decisions.md`
- `docs/research/COMPETITIVE_LANDSCAPE.md`

---

## REQ-INIT-8

**Verify Subsystem — TRON Integration**

| | |
|---|---|
| **Status** | **Draft v1** (awaiting sign-off) |
| **Owner** | Khash Sarrafi |
| **Initiative** | `INIT-8` in `docs/BACKLOG.md` |
| **Last updated** | 2026-05-16 |
| **Research** | `docs/research/COMPETITIVE_LANDSCAPE.md` (verification-as-first-class-phase moat); TRON evaluation 2026-05-16; `docs/ARCHITECTURE.md` §5 |
| **Source repo** | TRON: `/Users/khashsarrafi/Projects/Utilities/tron` (v5.4, "Implementation Ready") |

### 8.1. Summary

Integrate **TRON** — Python+FastAPI+Temporal enterprise AI QA platform with 7-layer verification + ISO-agent swarm — into Spine as the **canonical Verify subsystem**. Integration via `git subtree` into `verify/` (preserves TRON's git history + internal cohesion). Once integrated, TRON's `AuditManager` is invoked by Orchestrator at Verify phase via MCP (`verify_audit(build_artifact, blueprint) → VerifyFindings`). Cross-cutting TRON capabilities (Standards Hierarchy, MCP, memory, parsers, frontend, infra) move to `shared/`. **TRON must continue to run standalone** after integration.

Closes Spine's biggest functional gap (no verification subsystem) by lifting a shipped product into the umbrella — no rewrite, no loss of standalone positioning.

### 8.2. Problem

Spine today has no verification subsystem. Build emits code + self-report; nothing independently confirms correctness, safety, scope, or execution. Auditing is a role prompt, not a pipeline; no sandbox, no calibration, no cross-LLM consensus, no deterministic scanner baseline. The "verification-as-first-class-phase" sixth corner of the moat is aspirational.

Meanwhile **TRON exists and is built well** — 7-layer pipeline shipping, ISO agent swarm under `AuditManager`, Docker sandbox with seccomp, Platt-scaled calibration, cross-LLM validation, prompt-regression CI, golden test suite, audit webhooks, MinIO SARIF archival, scan handoff exports. Re-implementing inside Spine would waste effort *and* split verification into two divergent codebases.

**Spine needs verification; TRON is verification.** Question is integration shape: how to make TRON available to Orchestrator without forking, breaking standalone deployment, or freezing TRON's evolution.

### 8.3. Users & stakeholders

| Stakeholder | What they need |
|---|---|
| **Spine Orchestrator** | Single MCP tool (`verify_audit`); routes Verify failure back to Build |
| **Spine Build** | Optional early-detect — call individual ISO agents from inside Build before declaring done |
| **TRON audit-only users** | TRON keeps working standalone; no breaking changes |
| **Vibecoder (end user)** | Enterprise-grade verification with explicit provenance, calibrated confidence, sandbox-confirmed fixes |
| **Org admin** | Configure which ISO agents run via org bundle; require ComplianceISO for regulated workloads |
| **Auditor / Security** | Audit trail of every Verify run in unified `spine_audit`; per-finding provenance |
| **TRON maintainers** | Internal cohesion preserved — tests, CI, Docker stack, conventions intact under `verify/` |

### 8.4. Goals

#### MUST (P0)

- **G-1** TRON integrated under `verify/` via `git subtree add` (preserves history).
- **G-2** TRON's test suite **passes from new location** with no regressions.
- **G-3** Orchestrator invokes Verify via `verify_audit(build_artifact, blueprint) → VerifyFindings`.
- **G-4** Findings persist to `spine_audit` + `spine_verify_*`; surfaced through unified audit log.
- **G-5** TRON Standards Hierarchy → `shared/standards/` (per `EPIC-2.4`).
- **G-6** TRON MCP server consolidates into `shared/mcp/` (per `EPIC-2.2`).
- **G-7** TRON memory → `shared/memory/`; coexists with Spine role-memory.
- **G-8** TRON **runs standalone** after integration — no required Orchestrator dependency.
- **G-9** Verification is canonical SDLC phase in `sdlc-pipeline.yaml` between `build` and `acceptance`.

#### SHOULD (P1)

- **G-10** ISO agents individually addressable from Build for early-detect.
- **G-11** TRON tree-sitter parsers → `build/kg/parsers/` (feed KG per `EPIC-8.2.4`).
- **G-12** TRON frontend → `shared/ui/`; `admin-ui/` retires.
- **G-13** TRON infra (Vault, secrets) → `shared/infra/`.
- **G-14** Verify-fail auto-generates remediation directive (delegates to `EPIC-9.8`).
- **G-15** Postgres migrations converge on Flyway; Alembic ports to Flyway SQL.

#### COULD (P2)

- **G-16** Org bundle override of which ISO agents run.
- **G-17** Pre-verify cost projection at phase start.
- **G-18** TRON `agent_handoff` promoted to `shared/handoff/` for Plan + Build.

#### WON'T

- Rewriting TRON in another language — Python+FastAPI+Temporal stays.
- Forking TRON or breaking standalone deployment.
- Building a second verification pipeline.
- Replacing TRON's Temporal with Spine's bash daemons.
- Building new ISO agents in this REQ.

### 8.5. Functional requirements

#### FR-1 — Subtree migration

`git subtree add --prefix=verify/ <tron-repo> main` — full history preserved. Single atomic operation; no incremental file-by-file copy. Post-merge, internal absolute paths updated to relative where needed. Docker compose paths adjusted. TRON pytest suite passes from `verify/` with zero test logic modifications.

#### FR-2 — TRON → Spine code mapping

Authoritative table in `ARCHITECTURE.md §5`. Summary: `tron/agents/` → `verify/agents/`; `tron/verification/` → `verify/pipeline/`; `tron/sandbox/` → `verify/sandbox/`; `tron/workflows/` → `verify/workflows/`; `tron/api/` → `verify/api/`; `tron/standards/` → `shared/standards/`; `tron/mcp/` → `shared/mcp/`; `tron/memory/` → `shared/memory/`; `tron/parsers/` → `build/kg/parsers/`; `tron/infra/` → `shared/infra/`; `tron/realtime/` → `shared/realtime/`; `frontend/` → `shared/ui/`; `admin-ui/` retires; `alembic/` → `shared/db/alembic/` then migrates to Flyway.

#### FR-3 — Postgres consolidation (Alembic → Flyway)

Single Postgres, multiple schemas: `spine_recording`, `spine_kg`, `spine_lifecycle`, `spine_audit`, `spine_verify_*`. Alembic migrations ported to Flyway SQL. Cutover in Phase 2; Phase 1 leaves TRON on Alembic to avoid coupling. Migration ordering preserved; data not lost. `db/` moves to `shared/db/`.

#### FR-4 — Orchestrator wiring (`verify_audit` MCP tool)

Single tool: `verify_audit(build_artifact: BuildArtifact, blueprint: Blueprint) → VerifyFindings`. `BuildArtifact` per `EPIC-7.4`. `Blueprint` shapes scope (file patterns, check types, ISO agent selection, NOT_IN_SCOPE). `VerifyFindings` is typed envelope: list of `FindingOutput`, per-layer provenance, sandbox confirmation, calibration band, overall pass/fail. Implementation delegates to TRON's `AuditManager` — no parallel impl. Orchestrator writes findings to `spine_audit` and decides route-back vs surface based on severity + locked pipeline gate config.

#### FR-5 — ISO agents callable from Build (early-detect)

Each ISO agent individually addressable via MCP: `iso_invoke(agent_name, code_region, blueprint) → FindingOutput[]`. Engineer can optionally invoke SecurityISO before completing security-sensitive directive. Pre-verify findings surface in Build report. Pre-verify cost counted against project budget (no double-charging via audit marker).

#### FR-6 — Verification as canonical SDLC phase

`sdlc-pipeline.yaml` gains `verify` phase between `build` and `acceptance`. Default invokes TRON 7-layer pipeline. Org bundles override which ISO agents run. Verify phase has its own gate (default: user approval of findings summary; configurable to auto-pass if zero high/critical). Failure routes back to Build with auto-generated remediation directive (per `EPIC-9.8`); max-retry per `STORY-9.8.2`.

#### FR-7 — Standalone deployability preserved

TRON's `docker-compose.yml` continues to run standalone — Vault, MinIO, Temporal, Postgres, API, frontend all up. Orchestrator's MCP tool calls TRON via the same FastAPI surface TRON exposes — no internal-only API. No required env vars, schemas, or services from outside `verify/` to run TRON audit-only. Phase 2 consolidation is **additive** — TRON's standalone compose still wires its own services if umbrella isn't present.

### 8.6. Non-functional requirements

- **NFR-1 Performance:** `verify_audit` end-to-end (100-LOC change, default ISO swarm, no cross-LLM) ≤ 90s p95. With cross-LLM ≤ 180s p95. Sandbox sub-step ≤ 30s p95. Subtree merge ≤ 5min wall-clock.
- **NFR-2 Reliability:** Temporal durability preserved — verify runs survive worker restarts. Findings durable in Postgres before orchestrator notification. ISO agent failure doesn't block others; `AuditManager` marks missing as `unrun`.
- **NFR-3 Security:** Sandbox hardening preserved (Docker caps, read-only rootfs, network isolation, custom seccomp). Seccomp configurable per org bundle. Containers ephemeral. Sandbox can be disabled (degraded mode logged).
- **NFR-4 Cost:** Default verify ≤ $1. Cross-LLM ≈ 2× cost; surfaced in cost meter. Sandbox compute (CPU-sec, mem-sec) in unified ledger. No infra cost increase — single Postgres/Vault/MinIO/Temporal.
- **NFR-5 Customizability:** Which ISO agents run is config; declared in `sdlc-pipeline.yaml`, override-able by org bundle. Blueprints first-class.

### 8.7. Dependencies

- **TRON existing stack** — Python 3.11+, FastAPI, Temporal, Postgres (pgvector, ltree, pgcrypto), Redis, MinIO, Vault, Docker. All preserved.
- **`EPIC-2.4`** — Standards Hierarchy lift (joint ownership).
- **`EPIC-2.2`** — `verify_audit` and `iso_invoke` live on shared MCP server.
- **`INIT-3 EPIC-3.5/6/7`** — Sandbox / Calibration / Cross-LLM lifts overlap.
- **`INIT-9`** — must exist before `verify_audit` has a caller.
- **`INIT-7 EPIC-7.4`** — `BuildArtifact` is the input contract.

### 8.8. Open questions

- **OQ-1:** Alembic vs Flyway convergence timing — Phase 2 (after subtree). Confirm.
- **OQ-2:** Compose consolidation — root-level for prod, per-subsystem for dev. Phase 2 decision.
- **OQ-3:** TRON's Vault/MinIO/Temporal — TRON-specific or promote to umbrella? Recommend keep TRON-specific in Phase 1; promote in Phase 2 only if needed.
- **OQ-4:** TRON CLI — `tron audit` becomes `spine verify audit`? Recommend umbrella dispatches but `tron` CLI continues to work standalone.
- **OQ-5:** `agent_handoff` promotion to `shared/handoff/` — yes, but separate REQ.
- **OQ-6:** Schema co-tenancy — start under `verify/schemas/`; promote case-by-case.
- **OQ-7:** Standalone TRON MCP after consolidation — package `shared/mcp/` to run from `verify/` alone.
- **OQ-8:** Frontend merge timing — Phase 4.

### 8.9. Acceptance criteria

**Integration mechanics:**
- [ ] `git subtree add` completes; `git log -- verify/` shows TRON history preserved.
- [ ] TRON pytest suite passes from `verify/tests/` with zero modifications.
- [ ] TRON's `docker-compose.yml` brings full stack from `verify/docker-compose.yml`; `curl localhost:13000/health` returns 200.
- [ ] `make verify-test` dispatches to TRON's internal test target.

**Standalone deployability (hard requirement, G-8):**
- [ ] `cd verify/ && docker compose up -d` runs TRON audit-only with no Orchestrator / `plan/` / `build/`.
- [ ] Standalone audit completes end-to-end post-integration; findings persist; webhook fires; admin UI renders.
- [ ] No env var / schema / service from outside `verify/` required.
- [ ] TRON's `tron` CLI continues standalone.

**Orchestrator wiring:**
- [ ] `verify_audit` MCP tool callable from orchestrator; returns structured response.
- [ ] Orchestrator invokes Verify against Build output end-to-end (Sprint 2 happy path).
- [ ] Verify failure routes back to Build with remediation directive.
- [ ] Findings in `spine_audit` with full provenance.

**Cross-cutting moves:**
- [ ] `tron/standards/` at `shared/standards/`; at least one Spine role reads from it.
- [ ] `tron/mcp/` consolidated; single MCP server registers Verify + Orchestrator tools.
- [ ] `tron/memory/` at `shared/memory/`; Spine role-memory still works side-by-side.
- [ ] `tron/parsers/` at `build/kg/parsers/`; KG indexer consumes them.

**Canonical phase:**
- [ ] `sdlc-pipeline.yaml` default includes `verify` phase between `build` and `acceptance`.
- [ ] Org bundle can override ISO agent selection (verified via `regulated-enterprise` test bundle).

**ISO early-detect (SHOULD):**
- [ ] Engineer daemon can call `iso_invoke('SecurityISO', ...)` mid-Build; results surface in Build report.

### 8.10. Related artifacts

- `docs/ARCHITECTURE.md` §5 (code mapping), §6 (migration phases), §8 (sprint sequencing)
- `docs/BACKLOG.md` INIT-8 (6 EPICs, ~22 stories)
- `docs/BACKLOG.md` INIT-2 EPIC-2.4, INIT-3 EPIC-3.5/3.6/3.7 (overlapping lifts)
- `docs/BACKLOG.md` INIT-9 (caller), INIT-7 EPIC-7.4 (`BuildArtifact` input)
- `docs/PRD.md#req-init-7` (early-detect consumer), `#req-init-9` (caller)
- `verify/README.md` (subsystem boundary, standalone requirement)
- TRON source: `/Users/khashsarrafi/Projects/Utilities/tron`
- `docs/research/COMPETITIVE_LANDSCAPE.md` — sixth corner of the moat

---

## REQ-INIT-9

**Central Orchestrator — lifecycle, gates, routing, portfolio, unified cost+audit**

| | |
|---|---|
| **Status** | **Draft v1** (awaiting sign-off) |
| **Owner** | Khash Sarrafi |
| **Initiative** | `INIT-9` in `docs/BACKLOG.md` |
| **Last updated** | 2026-05-16 |
| **Architecture** | `docs/ARCHITECTURE.md` §2 (orchestrator at top of diagram), §9 (locked tech decisions) |
| **Boundary doc** | `orchestrator/README.md` |
| **Tech decisions** | `memory/spine_tech_stack_decisions.md` (bash + Postgres core; no Redis; Temporal stays in verify/) |

### 9.1. Summary

Build the **central coordinator** that turns Plan, Build, and Verify into one product. Orchestrator owns the project lifecycle state machine, enforces phase gates with cryptographic approval tokens, dispatches directives to subsystems exclusively via MCP, aggregates cost and audit data into unified ledgers, runs portfolio management for multiple in-flight projects, and exposes the single user-facing surface (MCP + REST + CLI).

Implemented as **bash + Postgres** (preserves debuggability moat) with minimal Python helpers. State lives in `spine_lifecycle` Postgres schema. Pipeline-as-data driven — canonical phase set editable via `sdlc-pipeline.yaml` (per `EPIC-1.7`), not hardcoded.

### 9.2. Problem

Without a central orchestrator, Spine v2 is **three disconnected things**: Plan produces a Roadmap into the void, Build executes against whatever directive lands, Verify runs whenever someone remembers to invoke it. Seven gaps:

- **No lifecycle state** — nobody knows which projects are in flight, in what phase, blocked on what.
- **No enforced gates** — Plan can hand off to Build without sign-off; Verify findings can be silently ignored.
- **No routing contract** — subsystems invoked ad hoc, no record of who asked for what.
- **No unified cost view** — Plan/Build/Verify tokens in three different ledgers.
- **No unified audit** — each subsystem writes its own format; reconstructing a decision crosses three logs.
- **No portfolio surface** — multi-project user has no place to see "what's where", no resource limits.
- **No single user surface** — user learns three CLIs (or UIs) to drive one product.

Orchestrator closes all seven. It is the *spine* in Spine.

### 9.3. Users & stakeholders

| Stakeholder | What they need |
|---|---|
| **Vibecoder** | Single front door: create project, see status, approve gates, watch cost — without knowing Plan/Build/Verify exist |
| **Solo dev / power user** | CLI driving full lifecycle from terminal |
| **Plan / Build / Verify** | Clear dispatch contract over MCP; well-defined place to report results; freedom from cross-subsystem coupling |
| **Auditor / Compliance** | Single append-only audit log; cryptographically verifiable approval tokens |
| **Finance / Procurement** | Unified cost ledger with per-phase/project/user/org rollups; budget enforcement reads aggregated spend |
| **CTO / Eng manager** | Portfolio view: how many projects in each phase, which are blocked, which exceed retry budgets |
| **Org admins** | Confidence org-bundle-required gates cannot be bypassed |

### 9.4. Goals

#### MUST (P0)

- **G-1** `spine_lifecycle` Postgres schema with `project`, `phase`, `transition`, `approval`, `route_history` tables.
- **G-2** Canonical phase set in `sdlc-pipeline.yaml` loaded at startup (default 11 phases: `intake → ... → retro`).
- **G-3** Bash-based state transition engine validating every transition against manifest, rejecting skips, writing atomically.
- **G-4** Phase-gate enforcement with **HMAC-signed approval tokens** stored in `approval` table.
- **G-5** Routing layer dispatching via MCP only (`plan_dispatch`, `build_dispatch`, `verify_audit`) — no direct imports.
- **G-6** Every dispatched directive carries **locked pipeline version**.
- **G-7** Unified cost ledger — Plan/Build/Verify rows in `spine_recording.costs` with `subsystem` column.
- **G-8** Unified audit log — append-only `spine_audit` table; every subsystem writes here.
- **G-9** Verify-failure auto-remediation — failing result generates remediation directive routed back to Build.
- **G-10** User-facing API: MCP primitives + CLI (`spine project new|status|approve`).

#### SHOULD (P1)

- **G-11** Rollback support — transition can revert with recorded rationale.
- **G-12** Multi-approver gates (TRD requires CTO + Compliance both sign).
- **G-13** Portfolio mode — multiple projects with per-project context routing + resource limits.
- **G-14** Max-retry policy per phase (default 3 build/verify loops before surfacing).
- **G-15** Build-failure → Plan re-route with "scope unclear" feedback.
- **G-16** REST API (`/api/v2/projects`, `/api/v2/approvals`, `/api/v2/audit`).
- **G-17** Per-phase/project/user/org cost rollup SQL views.

#### COULD (P2)

- **G-18** Cross-project rollups in dashboard.
- **G-19** Real-time dashboard tile.
- **G-20** Audit export API for compliance.

#### WON'T

- **Subsystem internals** — those live in their own REQs.
- **Temporal at orchestrator layer** — Temporal stays in `verify/` only.
- **Redis or any second state store** — Postgres is THE state store.
- **Multi-tenant SaaS** — local-deploy only in v1.
- **Knowledge graph, standards/policy enforcement** — those live in `build/kg/` and `shared/standards/`.

### 9.5. Functional requirements

#### FR-1 — Lifecycle state machine (Postgres schema)

Dedicated `spine_lifecycle` schema with five tables: `project` (id, name, project_type, pipeline_version locked, current_phase, status, created_ts/by), `phase` (catalog loaded from manifest), `transition` (append-only history), `approval` (HMAC-signed tokens), `route_history` (every dispatch + reply). Migrated via existing `db/flyway/` tooling.

#### FR-2 — Canonical phase set (pipeline-as-data)

Default 11 phases declared in `sdlc-pipeline.yaml`: `intake (user_approval) → plan_in_progress → plan_approved (user_approval) → build_in_progress → build_complete (system) → verify_in_progress → verify_approved (user_approval) → acceptance (user_approval) → released (system) → operate → retro (user_approval)`. Editable per `EPIC-1.7` — authorized roles add/remove/reorder phases via manifest without touching source. Orchestrator loads manifest at startup and writes phase catalog into `spine_lifecycle.phase`.

#### FR-3 — State transition engine

`orchestrator/lib/transition.sh` (bash) + `orchestrator/lib/approval.py` (Python helper for HMAC verify). For each transition: (1) Read current phase from `project`. (2) Validate target is next ordinal phase or permitted rollback. (3) Verify gate conditions (required approvals + valid HMAC). (4) Begin Postgres transaction — update `current_phase`, insert into `transition`, insert into `route_history` (if dispatching), insert into `spine_audit`. (5) Commit atomically.

Invalid transitions rejected with structured error referencing manifest phase ordering. No implicit phase skipping.

#### FR-4 — Phase gate enforcement (HMAC approval tokens)

HMAC key in `~/.spine/secrets/hmac.key` (per-install, 256-bit). Token payload: `(project_id, phase, approver, ts)`; signature: `HMAC-SHA256(payload, key)`. Stored in `approval` table; presented on every `phase_advance`. Multi-approver gates (P1) require N valid tokens with distinct approvers per manifest declaration.

#### FR-5 — Routing layer (MCP only)

Subsystems addressed **exclusively via MCP** — no direct imports, no cross-subsystem shell calls. Three dispatch tools via `shared/mcp/`: `plan_dispatch` (`{project_id, phase, directive, pipeline_version}`), `build_dispatch` (`{project_id, directive, story_id?, pipeline_version, prior_findings?}`), `verify_audit` (`{project_id, artifact_ref, scope, pipeline_version}`). Every directive carries `pipeline_version` (per `EPIC-1.7.5`) so mid-flight edits don't affect in-flight projects. Subsystems reply via MCP; orchestrator records reply in `route_history` + audit row.

#### FR-6 — Portfolio management

Orchestrator runs N projects concurrently. Per-project context keyed by `project_id`. Per-project resource limits (`max_parallel_directives`, `max_workers`) declared in org bundle or project metadata; exceeded requests queue. Cross-project rollups via SQL views: `v_projects_by_phase`, `v_blocked_projects`, `v_active_directives`. Per-project resource accounting rolls into unified cost ledger.

#### FR-7 — Unified cost ledger

All cost rows from all subsystems land in `spine_recording.costs` with added `subsystem` column (`plan`/`build`/`verify`/`orchestrator`). Orchestrator doesn't own the cost recorder (that's `shared/cost/`) but mandates the contract. Rollup views (P1): `v_cost_per_project`, `v_cost_per_user`, `v_cost_per_org`, `v_cost_per_pipeline_version`. Budget enforcement (per `EPIC-2.3`) reads these views, blocks dispatch when caps exhausted.

#### FR-8 — Unified audit log

Append-only `spine_audit` table: `(ts, project_id, phase, role, subsystem, action, subject_id, rationale, prompt_hash?, output_hash?, cost?, pipeline_version, audit_id)`. Append-only enforced by Postgres role (no UPDATE/DELETE grants). Survives uninstall — table is in durable `db/` instance. Queryable via compliance export API (P1): given `project_id`, return full chronological audit trail.

#### FR-9 — Failure handling & re-routing

Verify failure → Build re-route. When `verify_audit` returns failing findings, orchestrator auto-generates remediation directive (`{prior_findings, scope, fix_target}`), dispatches back to Build, records loop in `route_history`. Build failure → Plan re-route ("scope unclear" feedback). Max-retry policy per phase (default 3); exceeded → project transitions to `blocked` status. All loops are first-class state — re-routes write `transition` rows (annotated `rollback=true` where applicable).

#### FR-10 — API surface (MCP + REST + CLI)

| Surface | Tools / endpoints / commands |
|---|---|
| **MCP (P0)** | `project_create`, `project_status`, `phase_advance`, `approval_grant`, `plan_dispatch`, `build_dispatch`, `verify_audit`, `audit_query` |
| **REST (P1)** | `POST /api/v2/projects`, `GET /api/v2/projects/{id}`, `POST /api/v2/approvals`, `GET /api/v2/audit?project_id=...` |
| **CLI (P1)** | `spine project new <name> [--type=...]`, `spine project status [<id>]`, `spine project approve <id> <phase>`, `spine project rollback <id>` |

MCP is canonical; REST and CLI are thin wrappers. Dashboard tile (P2) consumes REST.

### 9.6. Non-functional requirements

- **NFR-1 Latency:** State transition (validate + write + audit) ≤ 100ms p95. MCP dispatch envelope (orchestrator overhead, not counting subsystem work) ≤ 50ms p95. `project_status` ≤ 200ms p95.
- **NFR-2 Throughput:** Audit log write ≥ 500 rows/sec sustained. Concurrent in-flight projects ≥ 50 on single-instance install.
- **NFR-3 Reliability:** Every transition atomic via Postgres ACID. Audit log append-only and survives uninstall. HMAC keys at `~/.spine/secrets/`, mode 0600, never logged. Mid-transition crash: Postgres rolls back; `current_phase` reflects last committed transition on restart.
- **NFR-4 Security:** Approval tokens HMAC-signed; tampering detected at gate-check. Postgres role for orchestrator has INSERT-only on `spine_audit` (no UPDATE/DELETE). No outbound calls from orchestrator layer itself.
- **NFR-5 Observability:** Every transition emits audit row with `actor`, `rationale`, `pipeline_version`, correlation ID. `route_history` exposes mean dispatch-to-reply latency per subsystem.

### 9.7. Dependencies

- **Existing Postgres** (`db/`, moves to `shared/db/` in Phase 2) — hosts new `spine_lifecycle` alongside `spine_recording`, `spine_kg`, `spine_audit`.
- **`EPIC-2.2`** — Unified MCP server is the dispatch transport.
- **`INIT-3`** — Audit log primitives.
- **`EPIC-1.7`** — Pipeline-as-data manifest supplies canonical phase set + override hierarchy.
- **`EPIC-1.4`** — Approval system.
- **`EPIC-2.3`** — Budget enforcement reads unified cost ledger.
- **`REQ-INIT-1`, `REQ-INIT-7`, `REQ-INIT-8`** — Dispatch targets; their MCP contracts must be implemented before end-to-end flow works.

### 9.8. Open questions

- **OQ-1:** Bash/Python boundary inside orchestrator. Initial split: bash for transition engine, dispatch, CLI; Python for HMAC + structured payload validation. Revisit if Python creeps past ~500 LOC.
- **OQ-2:** HMAC key management. Single per-install key in v1; defer rotation + per-approver keypairs to v1.1.
- **OQ-3:** Multi-tenant later. Add `tenant_id` columns with default `'local'` from day one (cheap insurance).
- **OQ-4:** Rollback semantics. Approvals remain valid after rollback (scoped to phase, not attempt); manifest can override per gate.
- **OQ-5:** Phase set evolution. Locked projects stay on locked version; user-triggered re-lock with diff preview supported; never auto-migrate.

### 9.9. Acceptance criteria

User (vibecoder):
- [ ] `spine project new my-idea --type=web-app` → project appears in `spine_lifecycle.project` at `intake`.
- [ ] `spine project status my-idea` shows current phase, last transition, pending approvals, total cost.
- [ ] `spine project approve my-idea plan_approved` → project advances to `build_in_progress` with audit row + HMAC token.
- [ ] Verify failure auto-routes back to Build (`route_history` shows two `build_dispatch` rows for same `project_id`, second carrying `prior_findings`) — no manual intervention.
- [ ] `GET /api/v2/audit?project_id=my-idea` returns complete chronological reconstruction.

Admin / operator:
- [ ] Run two concurrent projects, isolated in `spine_lifecycle`, per-project resource limits queue dispatches when exceeded.
- [ ] Tamper with approval token → next `phase_advance` rejects with HMAC verification error.
- [ ] Edit `sdlc-pipeline.yaml` to insert new phase, restart orchestrator → in-flight projects continue against locked version; new projects pick up new phase.
- [ ] Run `uninstall` → `spine_audit` rows survive in durable Postgres.
- [ ] `SELECT * FROM v_cost_per_project WHERE project_id=...` shows Plan + Build + Verify costs with `subsystem` column.

Subsystem:
- [ ] Receives directive only via MCP tool — no direct imports from orchestrator.
- [ ] Reports back via MCP; observe corresponding `route_history` row + audit row within latency NFR.
- [ ] Receives directive with `pipeline_version` and refuses if local manifest doesn't match.

### 9.10. Related artifacts

- `docs/ARCHITECTURE.md` §2, §9
- `docs/BACKLOG.md` INIT-9 (`EPIC-9.1` through `EPIC-9.9`)
- `orchestrator/README.md`
- `docs/PRD.md#req-init-1` / `#req-init-7` / `#req-init-8` (dispatch targets)
- `memory/spine_tech_stack_decisions.md` (bash + Postgres; no Redis; Temporal only in verify/)
- `memory/spine_flexibility_principle.md` (pipeline-as-data)
- `EPIC-1.7` (pipeline customization), `EPIC-2.2` (MCP server), `EPIC-2.3` (budget enforcement)
- `INIT-3` (audit log primitives)
