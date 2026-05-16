# Spine — Competitive Landscape & Strategic Positioning

> **Source of truth for `docs/MASTER_BACKLOG.md` items.** Captured 2026-05-16 from a research session comparing Spine against `obra/superpowers`, `ruvnet/ruflo`, and the broader multi-agent / SDLC-orchestration field. Update when new comparators emerge; backlog stories should link back here for *why*.

---

## 1. What Spine actually is (the operating positioning)

Spine is an **enterprise-deployable virtual team** for vibecoders building under organizational control. Mental model: *"what if a single person needed to hire a full engineering team to build something — Spine is that team, on tap."*

- **Target user:** anyone who wants to ship software but needs guardrails — business analyst, junior PM, senior engineer delegating, or an org rolling Spine out to every employee.
- **The flow Spine implements:** scrutinize the user → lock requirements (REQ gates) → orchestrate the build across 13 roles → full SDLC to verified delivery → cost-controlled via tier hints + cheapest-viable-model routing.
- **Why it exists:** enterprises want every employee to have an AI team without losing control of standards, security, compliance, or budget. SaaS orchestrators (Devin, Factory) own the runtime and the data; Spine deploys locally, enforces org policy in role prompts + auditor checks, and bills to the user's own LLM accounts.

---

## 2. The five-corner moat

Nobody else has all five of these in one product:

1. **Local-deploy** — no SaaS; org keeps data; user pays own LLM bills
2. **Multi-agent** — not "one smart agent," a coordinated team
3. **Role-bounded authority** — researcher can't write code; engineer can't deploy
4. **SDLC-gated** — REQ → architecture → build → QA, can't skip
5. **Requirements-first interrogation** — refuses to build until the spec is real

Devin has 2. Factory has 1, 2, partial-3. MetaGPT has 2, 3, 4 but no 1. Cursor has 2, partial-1. **Spine is the only tool lining up all five.**

---

## 3. Adjacent projects researched

### obra/superpowers (193k★, MIT, Shell, Oct 2025)
A **skills/methodology layer** that runs *inside* Claude Code / Codex / Cursor / Gemini as a plugin. 14 auto-triggering skills: brainstorming, writing-plans, subagent-driven-development, TDD, verification-before-completion, using-git-worktrees, dispatching-parallel-agents, systematic-debugging, etc. Zero-dependency. 94% PR rejection rate, anti-slop, brutal contributor guidelines.

**Relationship to Spine:** *not a competitor — should be absorbed.* Superpowers shapes how *one* agent thinks; Spine orchestrates *many*. A Spine `engineer` role could literally install Superpowers and get better at TDD without changing anything Spine does. Ideas to absorb: auto-triggering skills via session-start hooks, git worktrees instead of scratch dirs, verification-before-completion as an engineer-internal step, brainstorming as a front door for the `product` role.

### ruvnet/ruflo (51k★, MIT, TypeScript, Jun 2025) — rebrand of claude-flow
The **maximalist version of Spine's category**. 32 plugins (swarm, autopilot, federation, agentdb vector DB, rag-memory, knowledge-graph, observability, cost-tracker, security-audit, jujutsu, SPARC, …), 98 agents, 60+ commands, 30 skills, MCP server, daemons, hooks, cross-machine federation, GPU-accelerated vector search, SaaS UI at flo.ruv.io. Lite mode (Claude marketplace plugin) or full mode (`npx ruflo init`).

**Relationship to Spine:** *same category, opposite philosophy.* Ruflo wins on surface area (MCP, federation, vector memory, multi-machine). Spine wins on debuggability, role discipline, and SDLC gating. Ideas to absorb: MCP server interface (biggest concrete gap), vector-backed memory, two-tier install path (lite plugin vs full daemon).

### Devin, Factory.ai, Cosine/Genie, Cognition, Reflection
SaaS autonomous SWE agents. Single-agent flavored, sandboxed runtimes, vendor-owned data and billing. **Spine's wedge against them:** local-deploy + multi-agent + your own LLM keys + your own standards. Their wedge against Spine: zero-setup UX, polished dashboards, async-by-default.

### MetaGPT, ChatDev
"Software company in a box" — PM/Architect/Engineer/QA agents producing structured artifacts. **Architecturally closest to Spine.** Spine wins on operational discipline (auditor, file hygiene, cost CSV, REQ gates). MetaGPT/ChatDev are demos; Spine is aiming to be a tool people actually deploy.

### Cursor background agents, GitHub Copilot Workspace
IDE/platform-native agent runtimes. **Spine's wedge:** not tied to one IDE, not SaaS, multi-agent with role bounds. Their wedge: integrated into where developers already work.

### LangGraph, crewAI, AutoGen, OpenHands
Developer frameworks for building agent systems. **Not Spine's competitors** — they're the runtime layer a Spine could (in theory) be built on, but Spine intentionally chose bash + markdown for debuggability and trust. The serious gap Spine has vs LangGraph is *durable checkpointed state* — "resume run from step 7" is LangGraph's killer feature and Spine has nothing equivalent.

---

## 4. Honest gap list (re-prioritized for Spine's actual positioning)

### Tier 1 — kill the adoption blocker
1. **Genuine onboarding interrogator** — structured intake conversation per project type (web app, internal tool, data pipeline, mobile). Today the `product` role has a prompt; what's needed is a guided dialogue that drags requirements out of someone who can't articulate them.
2. **Non-terminal UI** — vibecoders won't `make team-up`. Dashboard HTML needs to be the *front door* (directive intake, approval queue, cost meter, role activity stream), not a status page.
3. **Approval checkpoints with explicit pauses** — REQ approved → architecture starts; design approved → build starts. Today the gates exist conceptually; they need to be hard pauses with a UI to approve.

### Tier 2 — the standards-enforcement layer
4. **Org policy bundles** — package coding standards, security rules, deployment targets, approved libraries, banned patterns, cost ceilings. `spine install --org-bundle acme-corp` injects them into role prompts + auditor checks. *This is the differentiator nobody else has.*
5. **MCP server** for Spine primitives — so Claude Code / Cursor / Codex can call `directive_create`, `report_read`, `team_status`, `org_standards_get` from any session.
6. **Spend ceilings + per-user budgets** — "Khash can spend $50/day on Spine, hard cap." Cost CSV is the data; needs an enforcement layer.

### Tier 3 — the trust layer
7. **Audit log of every LLM call** — prompt, output, model, cost, role, who triggered. Table-stakes for enterprise.
8. **Reproducible builds** — replayable from directive + REQ + role versions, like a Dockerfile.
9. **Team-of-models router** — auto-route by (role, task complexity) instead of relying on the user picking a tier hint.

### Tier 4 — best-practice absorption
10. **Auto-triggering skills** (from superpowers) — session-start hooks that fire skill prompts at the right moments.
11. **Vector-backed memory** (from ruflo) — semantic recall across role lessons.
12. **Lite install path** (from ruflo) — Claude Code plugin-only flavor for users not ready for the full daemon install.

---

## 5. The honest verdict

Spine is neither superior nor lame — *the framing matters*. As a dev framework, it's lame (LangGraph wins). As an infra orchestrator, it's lame (ruflo wins). **As the thing it's actually trying to be — a local-deployed virtual team for vibecoders under org control — it's the only tool aiming at all five corners of that market.** Real product idea, real competitive moat.

The risk isn't that ruflo or superpowers steals Spine's lunch. The risk is that Spine never crosses the first-mile UX gap and stays a tool only its author can use. The bash + markdown core is fine — it's the right substrate for the trust/auditability story. What's missing is the *front door* (interrogation + approval UI) and the *enterprise wrapper* (policy bundles + spend caps + audit log).

---

## 6. Meta observation

This research session was itself the `product`-role conversation Spine is designed to run. The output (this file + `docs/MASTER_BACKLOG.md`) is the kind of REQ artifact a Spine `product` agent would have produced for the user. **Spine is being built using the methodology Spine implements.** That recursion is the strongest argument that the methodology works.
