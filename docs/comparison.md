# Spine vs the Field — Honest Comparison

> Comparison page for the README and the website. Implements `STORY-5.1.2` in `docs/BACKLOG.md`. Source: `docs/research/COMPETITIVE_LANDSCAPE.md`. Update when new comparators emerge.

---

## Preamble — read this first

We picked these competitors because they're the closest in **category** (full-team / multi-agent / AI-engineering tools that span more than the chat window), not because we think Spine is universally better. Three reasons to read this honestly:

1. **Most of these tools are excellent at what they do.** Devin is the best SaaS turnkey coding agent on the market. Cursor is the best IDE-native assistant. ruflo has the largest surface area in the multi-agent category. LangGraph is the right answer if you're building agent systems from scratch as a developer. Pick the right tool for *your* problem, not the one with the loudest marketing.
2. **Spine is not for everyone.** If you want a SaaS dashboard, polished onboarding, and a credit card that turns into shipped PRs, Spine is the wrong tool — go use Devin or Factory. If you live in your IDE, use Cursor. If you want maximum agent count, use ruflo. Spine is for one specific intersection: *local-deploy + multi-agent + role-bounded + SDLC-gated + verification-first*. Outside that intersection, other tools win.
3. **This page changes when the field changes.** If a competitor ships something that closes a Spine wedge, we update this page. If we ship something that closes a competitor wedge, we update this page too. The five-corner-moat positioning is real because we keep this file honest, not because we'd never admit a loss.

---

## The contenders

| Tool | Category | License | Stack |
|---|---|---|---|
| **Devin / Cognition** | SaaS autonomous SWE agent | Closed / SaaS | Proprietary |
| **Factory.ai** | SaaS AI engineering workspace | Closed / SaaS | Proprietary |
| **Cursor (background agents)** | IDE-native agent runtime | Closed / SaaS | Proprietary |
| **ruflo (claude-flow)** | Multi-agent orchestrator | MIT | TypeScript, Node |
| **MetaGPT / ChatDev** | "Software company in a box" | MIT | Python |
| **obra/superpowers** | Skill/methodology plugin | MIT | Shell |
| **LangGraph** | Agent framework | MIT | Python / TS |
| **Spine** | Local virtual engineering team | TBD (see below) | Bash + Postgres + Python |

---

## Capability matrix

Legend: ✅ Yes · ⚠️ Partial · ❌ No · 🔒 SaaS-only (cannot be self-hosted under your control) · — N/A

| Capability | Devin | Factory | Cursor | ruflo | MetaGPT | superpowers | LangGraph | **Spine** |
|---|---|---|---|---|---|---|---|---|
| Local-deploy (no SaaS required) | 🔒 | 🔒 | 🔒 | ⚠️ | ✅ | ✅ | ✅ | **✅** |
| Multi-agent (≥3 standing roles) | ⚠️ | ⚠️ | ⚠️ | ✅ | ✅ | ❌ | ✅ | **✅** |
| Role-bounded authority (enforced) | ❌ | ⚠️ | ❌ | ❌ | ✅ | ❌ | ⚠️ | **✅** |
| SDLC-gated workflow (phases + sign-off) | ❌ | ⚠️ | ❌ | ❌ | ✅ | ❌ | ⚠️ | **✅** |
| Requirements-first interrogation | ❌ | ❌ | ❌ | ❌ | ⚠️ | ⚠️ | ❌ | **✅** |
| Verification subsystem (sandbox + scanners) | ⚠️ | ⚠️ | ❌ | ⚠️ | ❌ | ⚠️ | ❌ | **✅** |
| Knowledge graph (deterministic code reasoning) | ❌ | ⚠️ | ❌ | ✅ | ❌ | ❌ | ❌ | **✅** |
| Org policy bundles (standards as data) | ❌ | ⚠️ | ❌ | ❌ | ❌ | ❌ | — | **✅** |
| Cost router + budget enforcement | ❌ | ⚠️ | ⚠️ | ⚠️ | ❌ | ❌ | — | **✅** |
| Approval gates (multi-approver) | ❌ | ⚠️ | ❌ | ❌ | ❌ | ❌ | ⚠️ | **✅** |
| Reproducible runs (replayable manifests) | ❌ | ❌ | ❌ | ⚠️ | ❌ | ❌ | ✅ | ⚠️ |
| Confidence calibration (Platt-scaled) | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | **✅** |
| Cross-LLM validation (Anthropic + OpenAI) | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | **✅** |
| Audit log (append-only, hash-chained) | ⚠️ | ⚠️ | ❌ | ⚠️ | ❌ | ❌ | ⚠️ | **✅** |
| Eval / regression harness | ⚠️ | ⚠️ | ❌ | ⚠️ | ❌ | ❌ | ✅ | **✅** |
| MCP server (callable from Claude/Cursor/Codex) | ❌ | ❌ | ❌ | ✅ | ❌ | ❌ | ⚠️ | **✅** |
| Open-source license | ❌ | ❌ | ❌ | ✅ MIT | ✅ MIT | ✅ MIT | ✅ MIT | TBD |
| Self-hosted only (no vendor runtime) | ❌ | ❌ | ❌ | ⚠️ | ✅ | ✅ | ✅ | **✅** |
| IDE-native UX | ❌ | ❌ | ✅ | ❌ | ❌ | ⚠️ | ❌ | ❌ |
| Polished onboarding / dashboard | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ⚠️ | ⚠️ |
| Async-by-default | ✅ | ✅ | ⚠️ | ⚠️ | ⚠️ | ❌ | ✅ | ✅ |
| Cross-machine federation | ❌ | — | ❌ | ✅ | ❌ | ❌ | ⚠️ | ❌ |
| Durable checkpointed state (resume mid-run) | ✅ | ✅ | ⚠️ | ✅ | ❌ | ❌ | ✅ | ⚠️ |

**How to read this honestly:** Spine wins 16 rows, loses 4 (IDE-UX, polish, federation, durable checkpoints). Three of those losses are not directly competing concerns; one (durable checkpoints) is a *real* gap acknowledged below.

---

## Where Spine wins (specific cases with examples)

### 1. Enterprise rollout under org control
A CTO needs every employee to have AI assistance *without* sending source code to a vendor, *without* using the vendor's LLM accounts, and *with* enforcement of the org's standards. Spine ships an org bundle (`shared/standards/bundle-schema.yaml`) that injects coding standards, banned patterns, security rules, approved libraries, cost caps, and required gates into every employee's local install. Drift detector warns when the user's bundle lags the org's published version. Devin, Factory, Cursor cannot do this without a custom contract; ruflo doesn't have a standards-bundle primitive; MetaGPT has no org concept at all.

### 2. Refusing to build a vague request
A user types *"build me an app for managing my team's time off."* Devin starts coding. Cursor starts coding. Spine's `product` role refuses, runs the 5-move dialogue protocol (naive cast → provoke → reframe → tier → artifact), produces a PRD with MUST/SHOULD/COULD goals, and *waits for the user to sign off* before the architect even sees the request. The PRD cannot be marked complete with any `TBD` field. Nobody else does this.

### 3. Auditor catching the engineer's missed callers
The engineer ships a change. The auditor re-runs `impact_radius` from the Knowledge Graph against the engineer's report and finds three callers the engineer didn't touch. The change is routed back to Build with a remediation directive — automatically, before anything ships. Devin and Cursor have no separate auditor role; they catch this kind of miss only if the test suite happens to cover it. MetaGPT has a QA role but no KG to query.

### 4. Hard-cap budget enforcement
An org sets *"Khash can spend $50/day on Spine."* The cost router (`shared/cost/router.py`) blocks directive dispatch when projected cost would exceed cap (exit code 2). Not a warning, not a notification — a hard block. Devin / Factory bill the org, not the user, and have no per-user hard caps. Cursor caps tokens by subscription tier but not by user-defined ceiling.

### 5. Cross-LLM validation on high-stakes outputs
Before a PRD is finalized or a security finding is filed, Spine runs the same prompt through Anthropic and OpenAI and reconciles the verdicts. If the keys are missing, confidence is capped at 0.7 and the cross-check is skipped (logged). Nobody else in the multi-agent category does this — they trust whichever model they're running.

---

## Where competitors win (be honest)

### 1. Devin / Factory — turnkey UX
You sign up, you type a problem, you get a PR. No install. No `make team-up`. No tarball. No Postgres. If your problem is "I want AI to write some code for me and I don't care about the rest," Devin or Factory is faster to value than Spine by an order of magnitude. Spine's first-mile UX is its biggest non-technical risk and a known gap (see `EPIC-1.6` Non-Terminal Front Door UI).

### 2. Cursor — IDE integration
If you live in your editor and want AI to live there with you, Cursor is built into the right place. Spine is not an IDE assistant and is not trying to be one. A Spine `engineer` daemon and a Cursor session can coexist (they should), but Cursor wins the "AI where I already work" problem.

### 3. ruflo — surface area + federation
ruflo has 32 plugins, 98 agents, 60+ commands, 30 skills, MCP server, daemons, hooks, cross-machine federation, GPU-accelerated vector search, and a SaaS UI at `flo.ruv.io`. If you want *every primitive in the multi-agent category in one tool*, ruflo wins. Spine intentionally has less surface area (debuggability moat); ruflo wins on raw capability count.

### 4. obra/superpowers — per-agent discipline
Superpowers has 14 auto-triggering skills (TDD, verification-before-completion, systematic-debugging, brainstorming, etc.) and a 94% PR rejection rate enforced by brutal contributor guidelines. As a *methodology layer inside a single agent*, it's better than anything Spine ships internally for a single role. Spine should **absorb superpowers** (see `EPIC-4.1`) rather than compete with it — superpowers shapes how one agent thinks; Spine orchestrates many.

### 5. LangGraph — durable checkpointed state
"Resume run from step 7 with the state from yesterday" is LangGraph's killer feature. Spine has nothing equivalent today (`EPIC-3.2` Reproducible Builds is the planned answer, not yet shipped). If you're a developer building an agent system from scratch and durable checkpointed state is your hard requirement, LangGraph is the right answer. Spine's swarm subgraphs use LangGraph internally (`EPIC-1.2`) for exactly this reason.

### 6. MetaGPT / ChatDev — academic completeness
The "PM → Architect → Engineer → QA → producing structured artifacts" pattern was published first by MetaGPT and ChatDev. Spine is architecturally similar but adds operational discipline (auditor, file hygiene, cost CSV, REQ gates, org bundles, KG-backed audit). If you want to read the papers that established the pattern, MetaGPT and ChatDev are the citations — Spine is the deployment-ready evolution.

---

## Choosing the right tool — decision matrix

Match your need to the right tool. Don't pick Spine because the comparison matrix has more checkmarks; pick it because you have the specific problem it solves.

| If you need... | Pick |
|---|---|
| **SaaS turnkey solution, polished UX, zero setup** | **Devin** or **Factory.ai** |
| **AI inside your IDE where you already work** | **Cursor** (or GitHub Copilot Workspace) |
| **Maximum agent count + cross-machine federation** | **ruflo** |
| **Per-agent behavioral discipline (TDD, verification)** | **superpowers** (or layer it inside Spine — they compose) |
| **Build your own agent system, durable state, full control** | **LangGraph** (or crewAI, AutoGen, OpenHands) |
| **Reference implementation of the multi-role SDLC pattern** | **MetaGPT** or **ChatDev** |
| **Local + multi-agent + role-bounded + SDLC-gated + verification + org-controlled** | **Spine** |

The last row is the only one where no other tool lines up the full set. That's the Spine wedge.

---

## What this comparison page does NOT claim

- **Spine is the best tool for everyone.** It is not. See the decision matrix.
- **Spine is feature-complete.** ~80 of ~180 stories Done; integration testing of end-to-end Plan → Build → Verify is the active sprint.
- **Spine is production-hardened at scale.** Solo-developer roots; multi-org production deployments are future work. If you need a battle-tested SaaS coding agent today, that's not Spine.
- **Devin / Factory / Cursor / ruflo / MetaGPT / superpowers / LangGraph are bad.** They are not. They are excellent at the corner of the market they're aiming at. We picked them as comparators *because* they're excellent — losing to a bad tool would mean nothing.
- **The matrix scores will never change.** They will. As the field ships, this page updates. Track changes via git history.

---

## Spine's honest gap list (so you can plan around it)

In rough priority order — also see `COMPETITIVE_LANDSCAPE.md §4` and `docs/BACKLOG.md`:

1. **Non-terminal UI front door** (`EPIC-1.6`) — vibecoders won't `make team-up` cold. Dashboard needs to be the front door, not a status page.
2. **Durable checkpointed state** — partial today (Postgres state machine + LangGraph subgraphs inside swarm); full "resume run from step N with yesterday's state" is `EPIC-3.2`.
3. **Polished onboarding** — install is `make team-up`; needs a one-command flow for non-developers.
4. **Reproducible-build manifests** (`EPIC-3.2`) — designed, not shipped.
5. **Two-tier install path** (`EPIC-4.3`) — lite plugin (no daemons, no Postgres) for users not ready for full install.
6. **Cross-machine federation** — explicitly out of scope today; ruflo is the right tool if you need this.
7. **IDE integration** — explicitly not the goal; Cursor coexistence is the answer.

If any of these blocks your use case, file a backlog story or pick one of the alternatives above.

---

## Cross-references

- `docs/positioning.md` — one-page positioning narrative
- `docs/research/COMPETITIVE_LANDSCAPE.md` — full competitive analysis
- `docs/BACKLOG.md` — all stories, including the closes-the-gap roadmap
- `docs/ARCHITECTURE.md` — why each design choice
- `docs/PRD.md` — full requirements per INIT
