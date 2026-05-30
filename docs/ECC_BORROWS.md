# ECC borrows — design note

> **Status:** Proposal — not ratified. Touches `V3_DESIGN_DECISIONS.md` #2, #7, #12, #27, #30, #34.
> Date: 2026-05-29.
> Source: [`affaan-m/ecc`](https://github.com/affaan-m/ecc) v2.0.0-rc.1, MIT.
>
> **Scope.** Identify patterns from the ECC harness layer that are architecturally
> aligned with Spine's v3 commitments and propose Spine-native adaptations
> (not ports). Each borrow names the target subsystem, the contract change, and
> whether ratification in `V3_DESIGN_DECISIONS.md` is required before code.
>
> **Out of scope.** The ECC plugin itself, AgentShield as a dependency, the
> 249-skill catalog, the Tkinter dashboard, and the Rust control-plane code.
> Spine and ECC have different product shapes — Spine is a self-hosted Hub (#3,
> #15); ECC is a Claude Code plugin pack.

---

## Already in flight (no new work)

`~/.claude/rules/ecc/{common,typescript}/*.md` is consumed via the user's
global Claude config. The `coding-style.md`, `git-workflow.md`, `testing.md`,
`security.md`, `code-review.md`, and `development-workflow.md` rules in that
tree are ECC's `rules/common/` upstream. No action — this is existing usage.

---

## Borrow list

| # | Borrow | Target subsystem | Touches | Priority |
|---|---|---|---|---|
| B1 | Recursive decision ledger + promotion gate | `shared/audit/` + `shared/standards/` | #12 | P0 |
| B2 | MCP tool response envelope | `shared/mcp/tools/*` | #30 | P0 |
| B3 | Instinct schema | `learning/` | #27 | P1 |
| B4 | Bounded iterative retrieval in dispatcher | `build/runtime/build_dispatcher.py` | #2, #34 | P1 |
| B5 | `spine status --markdown` handoff | `orchestrator/` | — | P1 |
| B6 | Pass@k eval contract for charters | `verify/` + per-charter tests | #7, #12 | P2 |
| B7 | `SPINE_HOOK_PROFILE` runtime gating | `tools/` + smoke + hygiene | — | P2 |
| B8 | `search-first` step in charters | `shared/charters/{engineer,architect}.md` | #7 | P2 |
| B9 | Agentic-OS layer table | `docs/ARCHITECTURE.md` | — | P3 |

---

## B1 — Recursive decision ledger + promotion gate

**ECC source.** `skills/recursive-decision-ledger/SKILL.md`.

**Why this fits Spine.** The Cite-or-Refuse contract (#12) requires verify-class
roles to cite KG node id / file:line / prior audit hash or refuse. ECC's
ledger formalizes the "what counts as cite-quality evidence" question with
explicit marks (`accept`, `watch`, `reject`, `decay`, `replay`) and a
**promotion gate**: recursive confidence alone never approves a live deploy.
That is exactly the Conductor's missing posture for production-class
work-items per #19.

**Adaptation.**
- Append-only JSONL ledger lives under `shared/audit/decision_ledger/` and chains
  into the existing hash-chained audit ledger.
- Every Conductor / Auditor / QA rollout records:
  - rollout id, timestamp, run_id
  - prior accepted winner + prior watchlist
  - fresh evidence ingested (KG node ids / file:line)
  - search space size, trial count, effective trial count
  - top candidates with decision marks
  - coherence mark against prior ledger
  - promotion gate result
- Promotion rules: for production deploys, capital-class migrations, and
  destructive ops, ledger entries must carry `live_promotion: false` unless
  freshness + replay gates pass. Default mode is paper / dry-run / preview.

**Ratification needed.** Extends #12 (Cite-or-Refuse) with a promotion-gate
sub-contract. Recommend a `#12a` annotation in `V3_DESIGN_DECISIONS.md`.

---

## B2 — Standardize MCP tool response envelope

**ECC source.** `skills/agent-harness-construction/SKILL.md` ("Observation Design").

**Why this fits Spine.** Spine ships 54 MCP tools per `EXPECTED_TOOL_COUNT`.
Envelope shape varies across modules (orchestrator / plan / build / verify
/ kg / ...). Inconsistent shapes hurt role-side recovery and observation
quality — the two largest constraints on agent completion rate per the ECC
model. A single envelope means roles can pattern-match `status / next_actions`
without provider-specific wrappers.

**Adaptation.** Land a typed `MCPToolResponse` schema (Pydantic) with:

```
status: success | warning | error | refusal
summary: str            # one-line result
next_actions: list[str] # actionable follow-ups for the calling role
artifacts: list[Artifact] # file paths, KG node ids, citation ids
metadata: dict          # tool-specific
```

- Verify-class tools (`requires_citation=True`) extend with `citations: list[Citation]`.
- Middleware in `shared/mcp/server.py` rejects responses that violate the schema
  in dev; warns in prod for graceful migration.
- Smoke test in `shared/mcp/tests/test_server_smoke.py` asserts every tool in
  `TOOL_REGISTRY` returns a conforming envelope.

**Ratification needed.** Refines #30 (API + MCP heavier scaffold). Schema is
additive, but middleware enforcement is a contract change — annotate `#30a`.

---

## B3 — Instinct schema for Smart Spine #27

**ECC source.** `skills/continuous-learning-v2/SKILL.md` (v2.1).

**Why this fits Spine.** #27 calls for a 3-tier learning loop with scope
resolver, consent, and anonymizer — but the schema for what gets learned is
unspecified. ECC's instinct model is the most concrete public design for this:
atomic learned behaviors with confidence (0.3 – 0.9), project-scoped by
default with promotion to global when seen in 2+ projects.

**Adaptation.**
- Schema in `learning/instinct.py` with project hash, confidence, evidence
  count, last-seen timestamp.
- Scope is determined by Spine project UUID (not git remote — Spine projects
  are first-class).
- Promotion threshold: instinct observed in 2+ projects within the same
  Hub federation tier promotes to global; consent + anonymizer middleware
  redacts project-identifying fields at the promotion step (per #27 existing
  consent layer).

**Ratification needed.** None — concretizes #27 rather than altering it.

---

## B4 — Bounded iterative retrieval in `build_dispatcher`

**ECC source.** `skills/iterative-retrieval/SKILL.md`.

**Why this fits Spine.** Current `build_dispatcher.py` ships full project
metadata (PRD/TRD blobs, decisions, role history) to each role on every
dispatch. This is the exact "send everything" failure mode that surfaced as
the Booger SPA hang per `SESSION_HANDOFF.md`. Also contributes to context
budget pressure on long-running runs (#34 workspace hygiene cousin).

**Adaptation.** 4-phase loop bounded to max 3 cycles:

1. **DISPATCH** — minimal seed (project id, work-item, prior winner).
2. **EVALUATE** — role returns `needs: [...]` if context insufficient.
3. **REFINE** — dispatcher resolves `needs` against KG / metadata.
4. **LOOP or proceed** — after cycle 3 the dispatcher proceeds with best-available.

**Ratification needed.** None — implementation detail under #2 (LLM-agnostic)
and #34 (workspace hygiene). Worth recording the bound in
`docs/ARCHITECTURE.md`.

---

## B5 — `spine status --markdown` handoff generator

**ECC source.** ECC v2.0 `ecc status --markdown --write status.md`.

**Why this fits Spine.** `SESSION_HANDOFF.md` and `MASTER_TODO.md` are hand-
written every session. The data is already in the orchestrator state store +
audit ledger + dispatcher in-flight registry — there's no reason this is manual.

**Adaptation.** New orchestrator CLI subcommand:

```
spine status --markdown --write docs/SESSION_HANDOFF.md
spine status --exit-code  # CI / cron use
```

Aggregates: active dispatches, charter health, smoke status, pending decisions,
stuck projects (per `projectRecoveryUtils`), and linked work-items. Output
matches the existing handoff format so the hand-written version becomes a
template, not a fresh write each session.

**Ratification needed.** None.

---

## B6 — Pass@k eval contract for charter regressions

**ECC source.** `skills/eval-harness/SKILL.md` + `skills/agent-eval/SKILL.md`.

**Why this fits Spine.** Charters (#7) are industry-anchored but currently lack
regression guarantees. A charter update can silently degrade role behavior.
Pass@k formalizes "this charter passes its capability evals N out of K times
at confidence ≥X."

**Adaptation.**
- `verify/charter_evals/<role>/` holds capability eval YAML per the ECC
  agent-eval pattern.
- Smoke gate: any PR touching `shared/charters/*.md` must run the affected
  role's eval suite. Default target `pass@5 ≥ 0.8`.
- Results recorded in the audit ledger (B1).

**Ratification needed.** Extends #7 with a regression-gate. Annotate `#7a`.

---

## B7 — `SPINE_HOOK_PROFILE` runtime gating

**ECC source.** ECC v1.8 `ECC_HOOK_PROFILE=minimal|standard|strict` +
`ECC_DISABLED_HOOKS=...`.

**Why this fits Spine.** `tools/smoke-test.sh`, `make hygiene`, the
dispatcher pre-checks, and the workspace gate are all-or-nothing today.
Profile gating lets ops run `strict` in CI and `minimal` in local dev
without editing scripts.

**Adaptation.** Single env var `SPINE_HOOK_PROFILE`:
- `minimal` — bootstrap + bash core sanity only.
- `standard` (default) — current 99 PASS contract.
- `strict` — adds extended LLM-bridge audits + KG drift checks.

`SPINE_DISABLED_HOOKS=<csv>` for targeted opt-outs.

**Ratification needed.** None. Implementation detail.

---

## B8 — `search-first` step in Engineer + Architect charters

**ECC source.** `skills/search-first/SKILL.md`.

**Why this fits Spine.** Charter contracts (#7) currently don't mandate
research-before-implement. The user's global rules already pull ECC's
`development-workflow.md` Step 0 ("Research & Reuse"), but Spine's role
charters don't yet bind to it.

**Adaptation.** Add a `Pre-implementation contract` section to
`shared/charters/engineer.md` and `shared/charters/architect.md`:

1. Tool availability preflight (gh / pip-index / mcp-registry).
2. Parallel registry + MCP + GitHub search.
3. Adopt-as-is / extend-wrap / build-custom decision matrix.
4. Cite chosen adoption (or "no fit found, building custom because …") in the
   ledger before any Write/Edit.

**Ratification needed.** Extends #7 charter contract. Annotate `#7b`.

---

## B9 — Agentic-OS layer table in `ARCHITECTURE.md`

**ECC source.** `skills/agentic-os/SKILL.md`.

**Why this fits Spine.** Spine implicitly has the 4-layer model (kernel /
charters / commands / daemons / state) but `docs/ARCHITECTURE.md` doesn't
state it explicitly. New contributors and tooling miss the structure. A
single table makes it explicit.

**Adaptation.** Add to `docs/ARCHITECTURE.md`:

| Layer | Purpose | Lives in | Persistence |
|---|---|---|---|
| Kernel | Identity, routing, design decisions | `CLAUDE.md`, `docs/V3_DESIGN_DECISIONS.md` | Git-tracked |
| Charters | Role identities + contracts | `shared/charters/` | Git-tracked |
| Commands | User + MCP-facing surface | `shared/mcp/tools/`, `shared/api/routes/` | Git-tracked |
| Daemons | Orchestration + scheduled tasks | `orchestrator/`, `tools/`, `recovery/` | Git-tracked |
| Workspace | Per-run scratch + promoted artifacts | `.spine/work/`, `.spine/archive/` | Hygiene-swept (#34) |
| Audit | Hash-chained ledger | `shared/audit/` | Append-only |

**Ratification needed.** None.

---

## What we explicitly do not borrow

| Not borrowed | Reason |
|---|---|
| ECC plugin install pipeline / marketplace / GitHub App | Wrong product shape (#3, #15). Spine is a Hub, not a plugin. |
| 249-skill catalog (most of it) | Spine roles are industry-anchored charters (#7), not workflow skills. |
| AgentShield as a runtime dependency | Security findings live in Spine's audit ledger; external scanner blurs trust boundary. |
| Tkinter dashboard | Spine SPA is the Hub UI (Part 4.1). |
| `ecc2/` Rust control plane code | Spine is bash core + Python wrappers (#7 / Wave 3 Squad A). Borrow the CLI surface only (B5). |
| `continuous-learning-v2` hooks-based observer | Spine learning ingests from MCP audit events, not Claude Code hooks. |

---

## Sequencing

```
P0 (concurrent)
 ├── B1 ledger + promotion gate
 └── B2 MCP envelope
P1 (after P0 lands)
 ├── B4 bounded retrieval         (uses B2 envelope for needs)
 ├── B5 spine status              (uses B1 ledger)
 └── B3 instinct schema           (uses B1 ledger)
P2
 ├── B6 pass@k charter evals      (uses B1 ledger)
 ├── B7 SPINE_HOOK_PROFILE
 └── B8 search-first contract     (uses B1 ledger for citations)
P3
 └── B9 ARCHITECTURE.md layer table
```

---

## Ratification asks

If the decisions below are not contested, fold them into
`docs/V3_DESIGN_DECISIONS.md` as annotated extensions:

- **#7a** — Charters must pass pass@k regression evals when touched (B6).
- **#7b** — Engineer + Architect charters bind to a `search-first` pre-implementation contract (B8).
- **#12a** — Recursive confidence does not promote work to live; explicit freshness + replay gates required (B1).
- **#30a** — MCP tool responses conform to the typed envelope; verify-class tools extend with citations (B2).

---

*Filed for review — no `shared/` code touched. Next step on approval: open B1 + B2 PRs in parallel.*
