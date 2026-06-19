# Spine — Positioning

> One-page positioning doc. Strategic source-of-truth for how Spine describes itself to outsiders. Implements `STORY-5.1.1` in `docs/BACKLOG.md`. Source: `docs/research/COMPETITIVE_LANDSCAPE.md`.

---

## Tagline

**Spine is the local-deployed virtual engineering team for vibecoders building under organizational control.**

## What Spine is (two paragraphs)

Spine is a **single product, three subsystems, one central orchestrator** that runs an entire SDLC — Plan → Build → Verify — on the user's own machine, against the user's own LLM accounts, under the user's organization's standards. Mental model: *what if a single person needed to hire a full engineering team to ship something — Spine is that team, on tap.* Thirteen role-bounded agents (product, planner, architect, conductor, researcher, engineer, ux, qa, operator, datawright, seer, auditor, memory) collaborate via a markdown message bus, gated by approval checkpoints, coordinated by a bash state machine, and persisted in a single Postgres backbone.

Spine is **not** a SaaS coding agent, not an IDE plugin, not a developer framework. It is the *only* product aiming at the intersection of **local-deploy + multi-agent + role-bounded + SDLC-gated + requirements-first + verification-as-first-class**. Every other category has at least one player that beats Spine on a single corner (Devin on SaaS turnkey UX, ruflo on surface area, LangGraph on programmatic control, Cursor on IDE feel, superpowers on per-agent discipline) — none of them line up all six corners that an enterprise rolling AI to every employee actually needs.

---

## The six-corner moat

```
                       LOCAL-DEPLOY
                            │
                            │
  REQUIREMENTS    ──────────●──────────    MULTI-AGENT
   -FIRST                  / \
                          /   \
                         /     \
                        /  SPINE \
                       /          \
                      /            \
  VERIFICATION  ─────●──────────────●─────  ROLE-BOUNDED
   -AS-PHASE          \            /         AUTHORITY
                       \          /
                        \        /
                         \      /
                          \    /
                           \  /
                       SDLC-GATED
```

Each corner is necessary; the moat is *all six together*.

### 1. Local-deploy
No SaaS runtime. The org keeps its data. The user pays their own LLM bills. Spine installs from a tarball, runs as bash daemons + a Postgres instance on the user's own machine, and never phones home. Compliance, security review, and data-residency arguments collapse: there's nothing to review except the code the org already audited at install time.
**Who has this:** ruflo (partial — federation tilts SaaS), MetaGPT (research demo). **Who doesn't:** Devin, Factory, Cursor, superpowers (plugin only).

### 2. Multi-agent
Not "one smart agent with subagents on demand" — a *standing coordinated team*. Thirteen roles, each with its own daemon, prompt, memory, and authority bounds. Fan-out to up to ten workers per manager (130 parallel worker slots stock). The orchestrator dispatches; roles report back; the auditor cross-checks every file touched.
**Who has this:** ruflo (98 agents), MetaGPT (4-7), Spine (13). **Partial:** Devin, Factory (single agent w/ subagent calls).

### 3. Role-bounded authority
Researchers cannot write code. Engineers cannot deploy. Operators cannot edit application source. The boundary is enforced by *role prompt + auditor cross-check + module-boundary linter*, not just by hope. Mistakes get caught at the role boundary instead of mid-execution.
**Who has this:** MetaGPT (architecturally), Spine (deeply). **Who doesn't:** ruflo, Devin, Factory, Cursor — any agent can do anything in those tools.

### 4. SDLC-gated
Plan → Build → Verify. Each phase produces a signed artifact (PRD → TRD → Roadmap → BuildArtifact → VerifyFindings). No phase advances without explicit user approval. The pipeline definition lives in declarative YAML (`sdlc-pipeline.yaml`) and is editable by authorized roles — but a project locks to a pipeline version at start so mid-flight edits never break in-flight work.
**Who has this:** MetaGPT (rigidly), Spine (with the flexibility principle). **Who doesn't:** Devin, Factory, Cursor, ruflo — any of those will happily skip from "idea" to "PR".

### 5. Requirements-first interrogation
Spine *refuses to build* until the spec is real. The `product` role runs a 5-move dialogue protocol (naive cast → provoke correction → reframe and redo → tier MUST/SHOULD/COULD → produce the PRD artifact). Per-project-type intake templates (web-app, internal-tool, data-pipeline, mobile, api-service, cli-tool) drag the requirements out of someone who can't articulate them. A PRD with any `TBD` field cannot be marked complete.
**Who has this:** Spine. Uniquely. Every other tool treats intake as a free-form prompt to an agent.

### 6. Verification-as-first-class-phase
A separate subsystem (`verify/`, integrated from TRON) runs scanners, ISO agents, ephemeral Docker sandbox execution, cross-LLM validation (Anthropic + OpenAI), and Platt-scaled confidence calibration. The auditor verifies the engineer's `BuildArtifact` against the Knowledge Graph impact set *before* anything ships. Verify failure auto-generates a remediation directive that routes back to Build.
**Who has this:** Spine (via TRON integration). **Who doesn't:** anyone else in the multi-agent category — verification is at best a linter call.

### Who has what — quick matrix

| Corner | Devin | Factory | Cursor | ruflo | MetaGPT | superpowers | **Spine** |
|---|---|---|---|---|---|---|---|
| Local-deploy | ❌ | ❌ | ⚠️ | ⚠️ | ✅ | ✅ | **✅** |
| Multi-agent | ⚠️ | ⚠️ | ⚠️ | ✅ | ✅ | ❌ | **✅** |
| Role-bounded | ❌ | ⚠️ | ❌ | ❌ | ✅ | ❌ | **✅** |
| SDLC-gated | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ | **✅** |
| Requirements-first | ❌ | ❌ | ❌ | ❌ | ⚠️ | ⚠️ | **✅** |
| Verify-as-phase | ⚠️ | ⚠️ | ❌ | ⚠️ | ❌ | ⚠️ | **✅** |

---

## Target user

### Vibecoder
Someone who wants to ship software but cannot articulate what they want, cannot write code well enough to debug failures, and cannot afford to be wrong. Spine is the front door (`product` role drags requirements out), the engine room (Plan → Build → Verify produces the artifacts a real team would produce), and the safety net (auditor + verify catch the mistakes the vibecoder can't see).

### Enterprise dev team
A CTO who wants every employee to have an AI engineering team without losing control of standards, security, compliance, or budget. SaaS orchestrators (Devin, Factory) own the runtime and the data; Spine deploys locally, enforces org policy in role prompts and auditor checks via **org bundles** (`shared/standards/bundle-schema.yaml`), and bills directly to each user's LLM account with **per-user budget enforcement** (hard caps, not warnings).

### Solo founder
One person trying to be a full team. Spine fills the gaps — `product` is the PM, `architect` is the staff engineer, `engineer` is the implementer, `qa` is the tester, `operator` is the DevOps lead, `datawright` is the data engineer — without the salary line items or the meeting overhead. The same person stays in the loop as the approver at every gate.

---

## Three worked examples

### A. Vibecoder builds a SaaS app
*"I want to build an app for managing my team's time off."* User runs `spine project new`. `product` role asks ten web-app intake questions (auth model, user roles, payment, deployment target, etc.), drafts a strawman PRD, invites attack, rebuilds. User signs off. Technical review swarm (architect + researcher + engineer + operator + qa) produces a TRD. User signs off. Decomposer emits a Roadmap. Engineer daemons fan out to build. Auditor cross-checks every file. Sandbox runs the test suite. Cross-LLM validates the security-critical paths. User approves the build artifact. Five days, one person, full SDLC.

### B. Engineering team uses Spine for a refactor
A staff engineer at a 50-person company runs `spine project new` with the directive *"migrate auth service from session cookies to OAuth2"*. Architect queries the Knowledge Graph (`impact_radius`, `who_owns`) to compute blast radius before drafting the TRD. Decomposer uses KG dependency detection (not heuristics) to sequence the stories. Engineer daemons fan out across the touched modules. Auditor re-runs `impact_radius` against each engineer's report and flags missed callers. The company's org bundle (`acme-corp.yaml`) injected its banned-patterns list (no `eval()`, no raw SQL, no `requests` without timeout) into every role prompt automatically. The migration ships behind a feature flag with full test coverage and no scope creep.

### C. Org rolls Spine to 50 employees
A CTO publishes an org bundle (`acme-corp-v3.yaml`) containing coding standards, security rules, approved libraries, banned patterns, per-user budget caps ($50/day), required swarm composition (must include `qa` and `operator` for production-bound work), and required gates (TRD requires CTO + Compliance both sign for revenue-critical projects). Every employee runs `spine install --org-bundle acme-corp-v3.yaml`. Drift detector warns each user when the bundle is older than the org's published version. The CTO can audit every LLM call via the append-only `spine_audit` table — prompt hash, output hash, model, cost, role, user, timestamp, directive ref, with HMAC hash-chain for tamper detection.

---

## Key tech choices

### Bash + Postgres core (debuggability moat)
The orchestrator state machine, daemon infra, transitions, gates, and routing are bash + Postgres. When something breaks, you can `cat` the daemon log and `psql` the state table. No abstract framework to debug, no opaque agent runtime to introspect, no Temporal cluster to keep alive. Python is used selectively (HMAC, structured validation, swarm subgraphs) but stays under ~500 LOC inside the orchestrator.

### Pipeline-as-data (custom SDLC per org via YAML, no fork)
`sdlc-pipeline.yaml` declares phases, role leads, swarm composition, artifact templates, tier defaults, and gates. Each org can shape its own SDLC without forking Spine. Override hierarchy: org bundle → team → project (most-specific wins). Every edit is a git commit with author + timestamp + rationale (≥8 chars enforced). Projects lock to a pipeline version at start; explicit migration is the only legal change path.

### Knowledge Graph (deterministic code reasoning, not grep)
Code parsed by tree-sitter (Python, TypeScript, Bash, Markdown shipping; Go, Rust, SQL next). Nodes + edges + embeddings live in Postgres (`spine_kg` schema + pgvector). Eight MCP tools (`find_callers`, `trace_dependency`, `code_neighborhood`, `impact_radius`, `doc_for_region`, `who_owns`, `find_by_satisfies`, `hybrid_search`) replace token-burning grep loops with deterministic millisecond queries. Architect and engineer query the KG *before* drafting; auditor queries it *after* the report to verify nothing was missed.

### TRON-integrated verify (sandbox + cross-LLM + calibration)
The Verify subsystem is TRON, integrated via `git subtree` into `verify/`. Ephemeral Docker sandbox with seccomp profile runs untrusted code. Cross-LLM validation (Anthropic + OpenAI) on high-stakes outputs (PRD final, TRD final, security findings); single-key deployments degrade gracefully (cap confidence at 0.7, skip cross-check). Platt-scaled calibration applied to architect risk scores, decomposer estimates, qa severity, auditor finding confidence.

### Local-first; no SaaS dependency
No external service is required to operate Spine. Postgres, the LLM API of choice, and bash are the only runtime dependencies. The org's data never leaves the org's machines. The user's LLM account is the only billing relationship.

---

## Status

**v2 unified architecture in active build.** Eight commits, ~25,000 LOC, ~80 stories Done out of ~180 across 9 INITs. Core runtime functional: orchestrator state machine, gate engine, routing layer, cost router with budget enforcement, unified cost ledger, unified audit log, eight Knowledge Graph MCP tools, build artifact contract, verify subsystem MCP wrappers. Integration testing (end-to-end Plan → Build → Verify thread) is the active focus of Sprints 1–3 (see `docs/BACKLOG.md` Sprint Plan). Source visible in the repo; license terms not yet finalized — track `STORY-5.1.3` (naming + branding) and the project root for the final declaration.

---

## Try it

```bash
git clone <repo>
cd SpineDevelopment
make team-up      # bring up the agent team
make team-status  # see what's in flight
```

Full instructions: [`INSTALL.md`](../../INSTALL.md). Architecture deep-dive: [`docs/ARCHITECTURE.md`](../ARCHITECTURE.md). Why each design choice: [`docs/research/COMPETITIVE_LANDSCAPE.md`](../research/COMPETITIVE_LANDSCAPE.md). Honest comparison vs the field: [`docs/comparison.md`](../comparison.md).
