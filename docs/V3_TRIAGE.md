# Spine v3 — Codebase Triage (Aggregated)

> **Status:** Canonical aggregate of the 6-agent codebase triage executed 2026-05-17.
> Each subsystem was walked file-by-file against the 34 locked design decisions
> (`docs/V3_DESIGN_DECISIONS.md`). Each artifact got one of:
> **KEEP** / **REFACTOR** / **REBUILD** / **BUILD-NEW** / **DELETE** + priority (P0/P1/P2) +
> decision drivers + dependencies + notes.
>
> **Source of truth.** This doc is the canonical execution plan for the v3 rebuild. If anything
> in `docs/BACKLOG.md`, `docs/STATUS.md`, or per-file TODOs conflicts with what's here, this doc
> wins until explicitly revised.
>
> **Pre-read.** Per Decision #22, this triage is the bridge from design to build. The next doc
> after this is the build sequence (`docs/V3_BUILD_SEQUENCE.md` — forthcoming) which orders the
> BUILD-NEW + REBUILD work by dependency.

---

## Quick navigation

- [Executive summary](#executive-summary) — cumulative tally + headline findings
- [Cross-cutting themes](#cross-cutting-themes) — patterns across multiple subsystems
- [Architectural restructure proposal](#architectural-restructure-proposal) — T1+T5+T6 convergence on new top-level shape
- [Open architectural questions](#open-architectural-questions) — items the triage surfaced that need explicit resolution before build
- [Build sequence](#build-sequence) — placeholder for forthcoming dependency-ordered execution plan
- [Part Two: Per-Subsystem Triage Reports](#part-two-per-subsystem-triage-reports)
  - [T1 — shared/](#t1--shared)
  - [T2 — plan/](#t2--plan)
  - [T3 — build/](#t3--build)
  - [T4 — verify/](#t4--verify)
  - [T5 — orchestrator/ + lib/](#t5--orchestrator--lib)
  - [T6 — db/ + tools/ + docs/ + root](#t6--db--tools--docs--root)
- [References](#references)

---

## Executive summary

### Cumulative tally

| | plan/ | build/ | verify | orch+lib | db+tools+docs+root | shared/ | **Total** |
|---|---|---|---|---|---|---|---|
| Files reviewed | 35 | 42 | ~13 | 79 | ~110 | ~104 | **~383** |
| KEEP | 17 | 22 | 6 | ~21 | ~46 | 56 | **~168 (44%)** |
| REFACTOR | 17 | 11 | 5 | ~25 | ~32 | 30 | **~120 (31%)** |
| REBUILD | 0 | 0 | 1 | 5 | ~14 | 3 | **~23 (6%)** |
| DELETE | 0 | 3 | 0 | ~10 | ~5 | 2 | **~20 (5%)** |
| BUILD-NEW (proposed) | 30 | 31 | 9 | 24 | ~60+ | ~110 | **~264** |

### Headline findings

1. **~75% of existing code is KEEP or REFACTOR.** The substrate is largely sound; v3 is overwhelmingly
   *addition*, not subtraction. Only 6% REBUILD; only 5% DELETE.
2. **The biggest subtraction zone is `lib/`** (v1-era file-bus daemon system: ~5000 LOC bash + the
   1262-line `dashboard.html`). Per T5, retire entirely after migrating the keepers to `shared/runtime/`.
3. **The biggest REBUILD concentration is landing docs** — README, INSTALL, ARCHITECTURE, PRD,
   BACKLOG, positioning, install.sh, db/README all pitch the v1 "drop-Spine-into-your-project template"
   framing, which is wrong per #3 (Hub-as-product). T6 flagged this as the highest-leverage UX bug and
   recommends a "big-bang" coherent rewrite of landing docs.
4. **~264 BUILD-NEW items proposed** — filling in genuinely new architecture (federation, devops role,
   vault adapters, Hub container/UI, role charters, Keycloak, license, evidence, learning, recovery,
   integrations, migration, mobile API, voice scaffold). The v2 architecture didn't anticipate these.
5. **Three agents (T1, T5, T6) independently converge on the same new top-level subsystems**
   (see Architectural restructure proposal). This is the most consequential structural recommendation
   in the triage.

---

## Cross-cutting themes

Patterns that emerged across multiple subsystems. These should drive build-sequence design.

### 1. Substrate-correct, surface-incorrect

The dominant pattern. A file's *concept* is right for v3 but its *surface* assumes laptop-only,
single-user, single-provider posture: env vars for secrets, `~/.spine/...` for state, in-process
MCP only, no auth, single LLM provider hardcoded.

**Examples:** `shared/cost/router.py` (concept right, but loads bundle from `~/.spine` directly);
`shared/api/dependencies.py` (right shape, but header-stub auth + subprocess psql + in-process MCP);
`shared/notify/channels.py` (right channel pattern, but creds from `~/.spine/*.yaml`); `shared/memory/playbook_store.py`
(right Vector recall, but single cross-project bucket — #27 needs 3 tiers).

**Implication:** most REFACTOR work is wiring + surface fixes, not algorithmic rewrites. AI velocity
should chew through this fast.

### 2. The wiring is broken, not the substrate

T3 said it best: *"KG indexer's 0-node state is a wiring problem, not a code problem."* Same across
all 6 reports — components exist (KG, audit chain, calibration, memory, swarm engine, build
dispatcher, cross-LLM consensus) but aren't connected to their inputs/outputs in the v3 architecture.

**Implication:** build sequence should prioritize **wiring before adding** — turning on the substrate
that already exists before building net-new subsystems.

### 3. Vault gap is universal

Almost every file that touches secrets reads from environment variables or `~/.spine/*.yaml` instead
of going through a vault adapter (which doesn't yet exist) — violates #9.

**5 specific vault violations** identified in current code (T5):
- `orchestrator/lib/approval.py` (HMAC key on disk)
- `lib/_env_loader.sh` (DB password from `.env`)
- `lib/share-pg.sh` (**prints DB password!**)
- `lib/run-standalone-watcher.sh` (shared DSN)
- `lib/spine-connect.sh` (raw DSN)

**Implication:** `shared/secrets/` BUILD-NEW + Vault adapter layer is **P0 with hard prerequisite
status** — must land before any new feature ships secrets. Without it, #18 (closed-source v1.0) ships
with exploitable known-bad surfaces.

### 4. Single-provider gravity

Anthropic is implicit throughout: `shared/cost/prompt_cache.py`, `shared/cost/classifier.py`
LLM-judge call, `shared/validation/cross_llm.py` provider Literal, build/runtime dispatch defaults.

**Implication:** real LLM-agnosticism per #2 requires the new `shared/llm/` surface absorbing all
provider-specific code as adapters. `shared/cost/prompt_cache.py` becomes
`shared/llm/providers/anthropic.py`'s cache trait.

### 5. Federation-blind code

No current file anticipates parent/child Hub topology (#4, #10). All identifiers and lookups are
local-Hub-only. ProjectType, AuditRecord.subsystem, MCP server, notify rate-limit, lesson-store
scope — all need federation context propagation.

**Implication:** federation isn't a feature to add at the end — it's a context that needs to thread
through every subsystem. Plan for additive field migration (e.g. add `parent_hub_id`, `learning_scope`,
`origin_hub`) across multiple schemas in a single coordinated wave.

### 6. Cite-or-Refuse (#12) is unenforced everywhere it should be

Verify wrappers (`shared/mcp/tools/verify.py`, `iso.py`) don't enforce. `build/swarm/scout_contribution.py`
has no citation field. Build hooks don't check. The substrate exists in `shared/calibration/`; the
contract isn't wired.

**Implication:** add `citation: list[Citation]` field to verify-class output envelopes; middleware in
MCP server enforces presence on any tool tagged `verify-class`. P0 — refuses won't pass without this.

### 7. Smart Spine (#27) is a data loss on every audit

Both `shared/mcp/tools/verify.py` and `shared/mcp/tools/iso.py` extract calibration data and **discard
it**. Memory writer hooks (the 7 trigger points from R4) aren't wired. KG indexer is 0 nodes. The
learning loop isn't a loop — it's a substrate.

**Implication:** before any Smart Spine value materializes, need to land `shared/learning/` package
+ calibration sink helper called from every audit/invoke + memory writer hooks at the 7 trigger
points + KG indexer running on every commit.

### 8. Work-item types beyond `feature` (#19) — missing dimension everywhere

No bug/incident/support/refactor/infra/compliance templates exist. Doc parsers only recognize
STORY/EPIC/INIT. Dispatcher only routes feature work. ProjectType Literal in
`shared/mcp/tools/orchestrator.py` is 4 values, should be 7.

**Implication:** work-item-type expansion is a horizontal migration across plan templates + build
pipeline + role charters + UX + integrations. Add `work_item_type` field to schemas; subclass intake
runners per type; add intake templates × 6 (for the new types).

### 9. Zero tests under `build/` and `plan/tests/`

Significant credibility gap — flagged by T2 and T3. Need to address proactively, not retroactively.

**Implication:** test infrastructure is a P0 BUILD-NEW item for both subsystems.

### 10. Specific quiet bugs surfaced during triage

These aren't decision-driven REBUILDs — they're real bugs the triage caught. Worth fixing in the
"wiring" phase regardless of subsystem priority:

- `plan/pipeline/phase_evolution.py` rename detection collapses to `("", "", artifact)` for many
  phases (missing label field) → rename will misfire (T2)
- `plan/pipeline/project_lock.py` SQL injection surface (string-concat with `_esc` only escaping
  single quotes) (T2)
- `build/kg/extractors/markdown.yaml` vs `build/kg/doc_parser/` duplication unresolved (T3)
- `verify/.env` plaintext secrets — vault-only violation #9 (T4)
- `verify/docker-compose.override.yml` is Spine-owned policy living inside TRON's subtree — will
  cause merge conflicts on next subtree pull. Move outside `verify/` and symlink at runtime (T4)

---

## Architectural restructure proposal

**T1, T5, and T6 independently converge on the same v3 top-level layout.** This is the most
consequential structural finding in the triage.

### Proposed v3 layout

```
orchestrator/        KEEP+REFACTOR — lifecycle + routing + gate + federation control core
hub/                 BUILD-NEW       — containerized Hub product (#3)
federation/          BUILD-NEW       — Hub-to-Hub sync, registry, update cascade (#4, #10, #16)
devops/              BUILD-NEW       — devops role + 8 control planes (#11)
vault/               BUILD-NEW       — vault adapter library (#9) — also lives as shared/secrets/
keycloak/            BUILD-NEW       — auth + group→role mapping (#25) — also lives as shared/identity/
license/             BUILD-NEW       — feature-flag evaluator + signed bundle verifier (#23)
evidence/            BUILD-NEW       — Evidence Store collectors + Vanta/Drata/Secureframe push (#24)
learning/            BUILD-NEW       — Smart Spine 3-tier loop (#27)
recovery/            BUILD-NEW       — DR backup/restore/auto-recovery (#31, #32)
migration/           BUILD-NEW       — onboarding + portability + version migration (#33)

shared/runtime/      BUILD-NEW       — substrate moved from lib/ (vitals, heartbeat, watchdog, notify, executor, usage-parsers, file-lock, updater, db-outbox)
shared/charters/     BUILD-NEW       — industry-anchored role charters (replaces lib/role-prompts/) (#7)
shared/llm/          BUILD-NEW       — single LLM call surface, multi-provider adapters (#2)
shared/{mcp,audit,standards,calibration,cost,eval,memory,notify,reproducibility,validation,schemas,skills,api,ui}
                     KEEP+REFACTOR — existing substrate (per T1)

plan/                KEEP+REFACTOR — intake + decomposer + pipeline + swarm + templates (per T2)
build/               KEEP+REFACTOR+BUILD-NEW — KG + runtime + bridge + new dispatcher work-item-type support (per T3)
verify/              KEEP+REFACTOR — TRON subtree boundary (per T4)
db/                  KEEP+REFACTOR+BUILD-NEW — Flyway migrations V22-V32 (11 new) for license/federation/Hub registry/Evidence Store/Keycloak link/devops role/work-item types/Smart Spine learning/provider catalog/cloud targets/DR backup log
docs/                MOSTLY REBUILD — landing docs (README/INSTALL/ARCHITECTURE/PRD/positioning/install.sh) per Hub-as-product framing; new operational guides (HUB_OPERATIONS_GUIDE, DEPLOYMENT_SHAPES, FEDERATION_GUIDE, SECURITY_GUIDE, LICENSING_GUIDE, DR_RUNBOOK)
tools/               KEEP+REFACTOR+BUILD-NEW — new tooling for Hub container build, license signing, migration export/import, DR test runner

lib/                 RETIRE entirely after migration to shared/runtime/ and shared/charters/
```

### Open structural question (deferred to build-sequence planning)

T1 puts the 9 new substrate packages under `shared/*` (e.g., `shared/federation/`, `shared/identity/`,
`shared/secrets/`, `shared/license/`). T5+T6 put many of the same things at top level (e.g.,
`federation/`, `keycloak/`, `vault/`, `license/`).

**Trade-off:**
- `shared/*` placement — easier cross-subsystem reuse (federation/identity/learning all called from
  plan + build + verify + orchestrator).
- Top-level placement — clearer ownership boundary; matches the "subsystem" mental model;
  symmetric with `plan/ build/ verify/ orchestrator/`.

**Resolution:** **deferred to build-sequence planning.** Until then, both placements are treated as
the same logical subsystem with the location TBD. The build sequence doc will lock placement so
imports + package names are stable before any BUILD-NEW work begins.

---

## Open architectural questions

These surfaced during triage and need explicit resolution **before** the affected BUILD-NEW work
starts. Not blocking the aggregate doc — blocking the build sequence.

### From T4 — Spine ↔ TRON relationship (10 questions)

1. **Bundle-vs-optional posture for TRON in each deployment shape** — is TRON bundled with Hub in
   BYOC? on-prem? laptop?
2. **Vault migration timing** — when does TRON's secret use migrate to Spine's vault adapter?
3. **Audit-chain federation** — Spine chain ↔ TRON chain: hash-link or parallel-reconcile?
4. **Autonomous-engineer self-verify policy** — does the autonomous tier (per #13) self-verify via
   TRON or always defer to a separate verify role?
5. **License inventory for the 40+ TRON deps under closed-source** — what gets audited / what
   relicensing risk exists?
6. **TRON's own LLM provider posture** vs Spine's #2 LLM-agnostic requirement
7. **TRON sandbox compute attribution** to which cost-meter ledger
8. **TRON upgrade cadence** — does it follow Spine's federation update flow (#16) or stay independent?
9. **Cite-or-Refuse contract enforcement** at TRON boundary (T4 found wrappers don't enforce — fixable)
10. **Calibration outcomes** — capture from TRON results into Spine's `spine_calibration` (currently
    discarded — fixable)

### From T1 — shared/* vs top-level placement

See "Open structural question" above.

### From T3 — KG indexer execution model

Indexer exists but runs on 0 nodes. **When does it fire?** Per-commit hook? Periodic? Driven by
audit-event? Choice affects observability, cost, and consistency model.

### From T2 — Phase pipeline customization at federation tier

Pipeline-as-data design works for project-level customization (#7 + role charters). **Does it also
work for federation-tier customization** (parent Hub mandates phase pipeline for all children)?
Likely yes, but exact mechanism not yet specified.

---

## Build sequence

> **Forthcoming.** Aggregating per-artifact priority (P0/P1/P2) + cross-subsystem dependencies into
> a dependency-ordered execution plan is the next deliverable: `docs/V3_BUILD_SEQUENCE.md`.

Sketch (not committed; placeholder for the next doc):
- **Wave 0 — Foundations:** `shared/secrets/` (vault adapter), `shared/llm/` (provider surface),
  `shared/identity/` (Keycloak client), DB migrations V22-V32. Unblocks everything else.
- **Wave 1 — Substrate wiring:** memory writer hooks, KG indexer execution, calibration sink, audit
  redactor extensions, Cite-or-Refuse middleware in MCP server. Turns on the substrate that already
  exists.
- **Wave 2 — Work-item types:** 6 new role charters, work-item type schemas, intake templates × 6,
  build dispatcher routing. Closes the #19 gap.
- **Wave 3 — Hub product:** `hub/` container, `shared/runtime/` migration from lib/, Hub web SPA
  panels (decision queue / master roles / registry / vault config / integrations / role-chat /
  federation / license), responsive.css. Closes the #3 gap.
- **Wave 4 — Federation + License + Evidence + Learning:** federation registry + update cascade,
  license bundle verifier + feature flags, Evidence Store collectors + Vanta/Drata push, learning
  scope resolver. Closes #4 / #10 / #16 / #23 / #24 / #27 gaps.
- **Wave 5 — DR + Migration + Landing docs:** recovery package (12 layers), migration package
  (onboarding + portability + version), landing docs big-bang rewrite. Closes #31 / #32 / #33 gaps
  + T6's highest-leverage UX bug.
- **Wave 6 — Mobile/Voice/API scaffolds + lib/ retirement.** Closes #28 / #29 / #30 + final
  subtraction.

To be replaced with the full dependency-ordered plan in `docs/V3_BUILD_SEQUENCE.md`.

---

# Part Two: Per-Subsystem Triage Reports

The 6 per-subsystem reports below are the raw output from the triage agents (T1–T6), with their
markdown heading levels demoted by 2 to fit under this aggregate's hierarchy. Each report is the
authoritative source for its subsystem's per-artifact triage decisions.

---

## T1 — shared/

**Scope:** shared/{api,audit,calibration,cost,eval,mcp,memory,notify,reproducibility,schemas,skills,standards,ui,validation}
**Source:** `T1-shared.md` (extracted from `/private/tmp/.../tasks/<agent-id>.output`)

Now I have comprehensive understanding. Let me produce the triage report.

### Triage Report — shared/ subsystem

#### Existing files / directories

##### shared/api/ (FastAPI REST app — STORY-9.9.2)

| Path | Current purpose | Marking | Decision drivers | Depends on | Priority | Notes |
|---|---|---|---|---|---|---|
| shared/api/__init__.py | Package marker | KEEP | — | — | P2 | Trivial. |
| shared/api/app.py | FastAPI factory; CORS, JSON logging, request-id MW, lifespan, /healthz, /readyz, OpenAPI at /api/v2/spec | REFACTOR | #3 (Hub web is front door), #25 (Keycloak SSO), #30 (OpenAPI scaffold heavier), #4 (federation control/data plane), #9 (no env-secrets) | shared/mcp, shared/api/dependencies | P0 | OpenAPI emission is good substrate; needs Keycloak OIDC middleware, RBAC scopes, federation hub-vs-spoke context propagation header, vault-backed config (not env), and stronger CORS (currently env-driven default). |
| shared/api/dependencies.py | DB pool (subprocess psql), in-process MCP client, auth stub | REBUILD | #25 (Keycloak), #15 (self-hosted), #4 (control plane / data plane), #9 (vault) | shared/mcp, shared/secrets (new), shared/llm (new) | P0 | `current_user` is a header stub, not OIDC; DB via subprocess psql is wrong shape for a Hub container's hot path — needs asyncpg pool with vault-fetched DSN. MCP client is in-process only — federation needs remote MCP transport. |
| shared/api/routes/__init__.py | Router aggregation | KEEP | — | — | P2 | Trivial. |
| shared/api/routes/approvals.py | Approval queue REST; shells to `orchestrator/lib/gate.sh` | REFACTOR | #3 (Hub web UI), #5 (active push briefings + decision cards), #6 (multi-channel decision delivery) | orchestrator/lib/gate.sh, shared/notify | P0 | Shape is right (REST -> gate.sh). Needs to emit decision-card events to shared/notify on POST, support polymorphic "decision class" routing (#6), and expose a federation-aware list (parent Hub sees child approvals). |
| shared/api/routes/audit.py | `/api/v2/audit` reads + CSV/JSON export wrapper | REFACTOR | #24 (Evidence Store source of truth), #12 (cite-or-refuse needs auditable substrate) | shared/audit | P0 | Add Evidence Store filters (control_id, framework), pagination beyond LIMIT 200, and signed export (#24 SOC2 evidence). |
| shared/api/routes/projects.py | Projects CRUD + phase-advance + rollback (stub) | REFACTOR | #4 (federation), #10 (hub-as-hub), #19 (7 work-item types) | shared/mcp | P0 | `project_type` Literal is currently 4 values — must extend to 7 (feature/bug/incident/support/refactor/infra/compliance per #19). PATCH + rollback are stubs; need to wire to transition.sh. Add federation project_origin field. |
| shared/api/README.md | API docs | REFACTOR | #25 (Keycloak), #30 (OpenAPI heavier) | — | P1 | Update to v3 architecture. |

##### shared/audit/ (hash-chained audit — STORY-3.1.*)

| Path | Current purpose | Marking | Decision drivers | Depends on | Priority | Notes |
|---|---|---|---|---|---|---|
| shared/audit/audit_record.py | Pydantic AuditRecord with SHA-256 hash chain | KEEP | #12 (cite-or-refuse), #24 (Evidence Store) | spine_audit schema | P0 | Hash-chained ledger is exactly the substrate v3 needs. Subsystem enum (`plan/build/verify/orchestrator/shared`) may need extension for `hub`, `federation`, `integration`. |
| shared/audit/redactor.py | Stateless PII/secret redactor with severity tiers | KEEP | #9 (no secrets), #24 (compliance) | audit_record | P0 | Pattern is right; add Vault-token-pattern + Keycloak-bearer-pattern + federation-attestation-token patterns. |
| shared/audit/exporter.py | CSV/JSON/JSONL/Parquet bulk export to file/S3/stdout/HTTP | REFACTOR | #24 (Evidence Store + Vanta/Drata connector scaffold), #9 (no env-secrets), #20 (AWS+Azure+GCP) | redactor | P0 | S3-only cloud target — add GCS, Azure Blob (#20). S3 credentials should come from shared/secrets adapter, not boto3 default chain. Format substrate is good for compliance connector scaffold (#24). |
| shared/audit/exporter_cli.sh | Bash CLI wrapper | KEEP | — | exporter.py | P1 | Standalone op tool; fine as-is. |
| shared/audit/*_README.md | Subsystem docs | KEEP | — | — | P2 | Update for v3 surfaces. |

##### shared/calibration/ (Platt-scaled calibration — STORY-3.6.*)

| Path | Current purpose | Marking | Decision drivers | Depends on | Priority | Notes |
|---|---|---|---|---|---|---|
| shared/calibration/__init__.py | Package marker | KEEP | — | — | P2 | |
| shared/calibration/calibrator.py | Platt/banded/identity calibration runtime over spine_calibration | KEEP | #27 (Smart Spine learning substrate), #12 (cite-or-refuse confidence) | spine_calibration schema | P0 | Already 3-tier scope friendly (per role+output_type). Per #27 will need scope=cross_org bands + bundle gate for opt-in. |
| shared/calibration/outcome_corpus.py | record_prediction / record_outcome helpers | KEEP | #27 (Smart Spine learning) | spine_calibration | P0 | Add `learning_scope` field (project/hub/cross_org) to support #27 3-tier model. |
| shared/calibration/apply.py | Per-role wrappers (architect risk, decomposer estimate, qa severity, auditor confidence) | KEEP | #12, #27 | calibrator | P1 | Substrate fine; will extend with new role wrappers (devops per #11, scrum_master per #5). |

##### shared/cost/ (router + classifier + team_router — STORY-1.5 / 3.3)

| Path | Current purpose | Marking | Decision drivers | Depends on | Priority | Notes |
|---|---|---|---|---|---|---|
| shared/cost/router.py | Tier router (low/medium/high/premium); budget enforcement; menu + caps + override | REFACTOR | #2 (LLM-agnostic), #23 (feature flags), #9 (no env-secrets) | shared/standards bundle, shared/llm (new) | P0 | Selects a `model_id` string today but doesn't invoke any provider — that's right. Needs to delegate actual calls to new shared/llm/ surface. Bundle loader reads `~/.spine` directly — should go through shared/secrets vault adapter for any provider keys referenced. |
| shared/cost/classifier.py | Per-turn heuristic + LLM-judge tier classifier | REFACTOR | #2 (LLM-agnostic) | router | P1 | LLM-judge call is implicitly Anthropic Haiku-class — must route through shared/llm cheap-tier abstraction (#2). |
| shared/cost/complexity_scorer.py | Pure heuristic 0-1 complexity scorer | KEEP | — | — | P1 | Zero LLM, zero secrets; fine. |
| shared/cost/model_selection_table.py | (role, complexity) → tier lookup, bundle overridable | KEEP | #23 (per-feature flags), #2 | router, bundle | P1 | Substrate aligns with feature-flag licensing — table entries can be feature-gated. |
| shared/cost/team_router.py | Team-of-models router (scorer→table→router) | KEEP | #2 | classifier, scorer, table, router | P1 | Clean composition layer. |
| shared/cost/user_override.py | Power-user tier pin with justification + audit | KEEP | #6 (per-user flexibility), #8 (bounded override) | router | P1 | Aligns with hybrid-authority bounded override (#8); ensure `granted_by` is OIDC-authenticated. |
| shared/cost/prompt_cache.py | Anthropic prompt-cache wrapper | REBUILD | #2 (LLM-agnostic — Anthropic-only is wrong shape) | shared/llm (new) | P1 | Provider-specific. Must move into shared/llm/providers/anthropic.py as a cache-aware adapter; the public `call_with_caching` becomes a generic API over any provider that supports caching. |
| shared/cost/budget_rollup.sh | Bash CLI over V16 cost ledger views | KEEP | — | spine_recording.v_cost_* | P1 | Op tool — fine. |
| shared/cost/router_cli.sh | Bash CLI for router | KEEP | — | router.py | P2 | |
| shared/cost/default_model_selection.yaml | Default (role, complexity) → tier table | KEEP | — | — | P1 | Will need entries for new roles (devops, scrum_master, pm, release_manager per #5, #11). |
| shared/cost/classifier_test_corpus.yaml | Test corpus for classifier accuracy | KEEP | — | — | P2 | |
| shared/cost/*_README.md | Docs | KEEP | — | — | P2 | |

##### shared/eval/ (Eval harness — STORY-3.4.*)

| Path | Current purpose | Marking | Decision drivers | Depends on | Priority | Notes |
|---|---|---|---|---|---|---|
| shared/eval/loader.py | Dataset + rubric loader (YAML + SHA) | KEEP | #27 (Smart Spine learning), #21 (Spine built by Spine) | — | P1 | |
| shared/eval/runner.py | Eval modes (full/regression/ab/smoke); pluggable dispatch | REFACTOR | #2 (LLM-agnostic dispatch), #21 | shared/llm (new), shared/cost/router | P1 | DispatchFn is provider-agnostic by design — wire to shared/llm. DB writes via subprocess psql like the rest; later replace with asyncpg pool. |
| shared/eval/scorer.py | Per-case scoring (judge + rubric) | KEEP | #2, #12 | — | P1 | |
| shared/eval/aggregator.py | Run summary + score diff | KEEP | — | — | P1 | |
| shared/eval/reporter.py | Markdown/JSON eval reports | KEEP | — | aggregator | P1 | |
| shared/eval/cli.py | CLI front-end | KEEP | — | runner | P2 | |
| shared/eval/_dataset_schema.yaml | Dataset schema | KEEP | — | — | P2 | |
| shared/eval/_rubric_schema.yaml | Rubric schema | KEEP | — | — | P2 | |
| shared/eval/example_architect.yaml | Sample dataset (architect) | KEEP | — | — | P2 | |
| shared/eval/example_engineer.yaml | Sample dataset (engineer) | KEEP | — | — | P2 | |
| shared/eval/README.md / runner_README.md / runner_design.md | Docs | KEEP | — | — | P2 | |
| (missing) shared/eval/datasets/ | Real datasets dir | — | — | — | — | Dir does not exist; only examples ship today. Real ones land per role. |

##### shared/mcp/ (Unified MCP server + 27 tools)

| Path | Current purpose | Marking | Decision drivers | Depends on | Priority | Notes |
|---|---|---|---|---|---|---|
| shared/mcp/__init__.py | Package marker | KEEP | — | — | P2 | |
| shared/mcp/server.py | stdio + http transports; JSON-redacted logging; lazy mcp SDK import | REFACTOR | #30 (MCP scaffold heavier), #4 (federation), #25 (Keycloak), #9 (vault) | shared/mcp/tools, shared/secrets (new) | P0 | Transports must add bearer-token auth (Keycloak OIDC), per-tool RBAC via tool tags, and federation forwarding (call a child Hub's MCP for delegated tools). Currently logs `_SECRET_KEYS` redaction is good. |
| shared/mcp/tools/__init__.py | Tool registry + @register_tool decorator + discover_tools | KEEP | #30 | — | P0 | Registry pattern is exactly right; just add `feature_flag` to ToolSpec for #23 licensing. |
| shared/mcp/tools/orchestrator.py | project_create / project_status / phase_advance / approval_grant | REFACTOR | #19 (7 work types), #4 (federation), #5 (active comms), #11 (devops role) | spine_lifecycle, audit | P0 | ProjectType Literal needs all 7 work-item types (#19). approval_grant should fan-out to shared/notify per #5/#6. Add `parent_hub_id` for federation. |
| shared/mcp/tools/plan.py | plan_dispatch — hands intake to plan.runtime.intake_runner | KEEP | — | plan/ | P1 | Thin wrapper; v3-compatible. |
| shared/mcp/tools/build.py | build_dispatch / build_completed wrappers around BuildArtifact | REFACTOR | #13 (engineer is wrapper over Claude Code/Cursor/Aider/OpenHands) | build/, shared/schemas/build | P0 | build_dispatch currently assumes external implementer is "human or LLM"; v3 needs explicit `implementer_kind ∈ {claude_code, cursor, aider, openhands, human}` + autonomy_tier (#13). |
| shared/mcp/tools/verify.py | verify_audit — Verify subsystem entry | KEEP | #12 (cite-or-refuse) | verify/ | P0 | Substrate fine; verify roles are cite-or-refuse class. |
| shared/mcp/tools/auditor.py | verify_build_artifact pre-Verify hook | KEEP | #12, #22 (intelligent triage) | kg.impact_radius | P1 | |
| shared/mcp/tools/iso.py | TRON ISO agents as MCP tools, cost-attributed | KEEP | #11 (devops/compliance planes), #24 (compliance scaffold) | verify/tron | P0 | |
| shared/mcp/tools/sandbox.py | TRON Docker sandbox as MCP tool | KEEP | — | verify/tron/sandbox | P1 | |
| shared/mcp/tools/standards.py | org_standards_get — bundle slice for a project | REFACTOR | #23 (feature flags), #10 (fractal federation) | shared/standards, shared/license (new) | P1 | Bundle resolution must honour signed feature flags (#23) and inherit from parent Hub bundle (#10). |
| shared/mcp/tools/kg.py | 9 KG tools: graph_query, find_callers, impact_radius, trace_dependency, code_neighborhood, doc_for_region, who_owns, find_by_satisfies, hybrid_search | KEEP | #27 (Smart Spine), #22 | spine_kg | P0 | Substrate is exactly what Smart Spine learning sits on. |
| shared/mcp/schemas/__init__.py | Re-exports | KEEP | — | — | P2 | |
| shared/mcp/schemas/envelopes.py | ToolRequest / ToolResponse / ToolError / ToolStatus | KEEP | #30 (MCP scaffold) | — | P0 | Clean envelope. Consider adding `feature_flag_required` + `actor_token_claims` for #23 + #25. |
| shared/mcp/tests/__init__.py | Test package | KEEP | — | — | P2 | |
| shared/mcp/tests/test_server_smoke.py | Smoke test | KEEP | — | — | P2 | |
| shared/mcp/README.md | Subsystem docs | REFACTOR | #30, #25 | — | P2 | Update for auth + federation. |
| shared/mcp/tools/*_README.md | Tool docs | KEEP | — | — | P2 | |

##### shared/memory/ (Vector-backed lessons + playbook — STORY-4.2.*)

| Path | Current purpose | Marking | Decision drivers | Depends on | Priority | Notes |
|---|---|---|---|---|---|---|
| shared/memory/__init__.py | Package marker | KEEP | — | — | P2 | |
| shared/memory/lesson_indexer.py | Parse `memory.md` → `spine_memory.lesson` rows, dedup by SHA, supersede on change | KEEP | #27 (Smart Spine per-project always-on) | spine_memory | P0 | Exactly the substrate for per-project learning (#27 tier 1). |
| shared/memory/lesson_store.py | Vector recall over spine_memory.lesson; pgvector cosine | KEEP | #27 | spine_memory, build/kg/embeddings | P0 | Cross-project penalty already in place — supports #27 tier hierarchy. Needs added `learning_scope` filter for `within_hub` (#27 tier 2). |
| shared/memory/playbook_store.py | Cross-project playbook wrapper (`~/.spine-development/playbook/<role>/lessons.md`) | REFACTOR | #27 (3 tiers: project/within-hub/cross-org) | lesson_store | P0 | Today this is one cross-project bucket — split into `within_hub` (default ON) + `cross_org` (opt-in) per #27. Move from `~/.spine-development/playbook/` to Hub-managed storage; ~/.spine-development is laptop-only. |
| shared/memory/cli.py | CLI to index + recall | KEEP | — | indexer, store | P2 | |
| shared/memory/memory_README.md | Docs | REFACTOR | #27 | — | P2 | Document the 3 tiers. |

##### shared/notify/ (Multi-channel notifier — STORY-1.4.7)

| Path | Current purpose | Marking | Decision drivers | Depends on | Priority | Notes |
|---|---|---|---|---|---|---|
| shared/notify/__init__.py | Re-exports | KEEP | — | — | P2 | |
| shared/notify/notifier.py | Fan-out, rate limit, EventType / Severity envelope | REFACTOR | #5 (active push), #6 (per-user/per-decision-class/per-medium) | channels, shared/secrets | P0 | Event vocabulary (8 types) too narrow for #5 — add `decision_card`, `daily_briefing`, `weekly_briefing`, `incident_pageout`, `release_announcement`. Rate limit is in-memory only — needs persistent (V22+) for federation. Routing must consider per-user prefs (currently a single config). |
| shared/notify/channels.py | Email / Slack / Webhook / Stdout / File / System / NoOp | REFACTOR | #6 (Slack+Email+SMS+WhatsApp+Teams), #20 (PagerDuty for incident class), #11 | shared/secrets, shared/integrations (new) | P0 | Add SMS (Twilio per #29 scaffold), WhatsApp, Teams, PagerDuty (incident routing per #11). Channels currently load creds from `~/.spine/<file>.yaml` — must go through shared/secrets vault adapter (#9). |
| shared/notify/notifier_README.md | Docs | KEEP | — | — | P2 | |

##### shared/reproducibility/ (RunManifest + replay + diff — STORY-3.2.*)

| Path | Current purpose | Marking | Decision drivers | Depends on | Priority | Notes |
|---|---|---|---|---|---|---|
| shared/reproducibility/__init__.py | Package marker | KEEP | — | — | P2 | |
| shared/reproducibility/manifest.py | Capture every input for a directive (RunManifest YAML); ~/.spine/manifests | REFACTOR | #33 (D — Spine version migrations), #31 (DR — replay = restore primitive) | shared/secrets, shared/llm | P0 | Excellent substrate for DR + version migration. Storage in `~/.spine/manifests/` is laptop-only — needs Hub-storage backend (S3/GCS/Blob per #20) abstracted. Add `bundle_version`, `vault_schema_version`, `kg_schema_version` to manifest (#33 D). |
| shared/reproducibility/replay.py | Recreate a run from a manifest; drift detection | KEEP | #33 (D), #31 | manifest | P0 | Core piece of Spine portability (#33 B); drift detection is exactly what version migration needs. |
| shared/reproducibility/diff.py | Manifest-vs-manifest diff | KEEP | #33, #27 | manifest | P1 | |
| shared/reproducibility/cli.py | CLI front-end | KEEP | — | manifest, replay, diff | P2 | |
| shared/reproducibility/manifest_schema.yaml | Schema | KEEP | — | — | P1 | Add fields for federation + bundle/vault/KG versions. |
| shared/reproducibility/reproducibility_README.md | Docs | KEEP | — | — | P2 | |

##### shared/schemas/ (Pydantic schemas)

| Path | Current purpose | Marking | Decision drivers | Depends on | Priority | Notes |
|---|---|---|---|---|---|---|
| shared/schemas/__init__.py | Package marker | KEEP | — | — | P2 | |
| shared/schemas/build/__init__.py | Sub-package marker | KEEP | — | — | P2 | |
| shared/schemas/build/build_artifact.py | Pydantic `build-artifact-v1` (STORY-7.4.1) | REFACTOR | #19 (7 work types), #13 (engineer wrapper) | plan/artifacts/_base | P0 | Schema is correct shape. Needs `work_item_type ∈ {feature,bug,incident,support,refactor,infra,compliance}` (#19) and `implementer_kind` (#13). Schema directory should also house `prd_v1`, `trd_v1`, `decision_card_v1`, `briefing_v1`, etc. — see BUILD-NEW. |

##### shared/skills/ (Auto-triggering skills — STORY-4.1.*)

| Path | Current purpose | Marking | Decision drivers | Depends on | Priority | Notes |
|---|---|---|---|---|---|---|
| shared/skills/__init__.py | Package marker | KEEP | — | — | P2 | |
| shared/skills/registry.py | Skill discovery + Pydantic validation of SKILL.yaml + SKILL.md pairs | KEEP | #23 (feature flags), #21 | — | P0 | Pattern is sound. Add `feature_flag` to SKILL.yaml metadata for #23. |
| shared/skills/trigger_engine.py | Evaluate triggers, sort by priority, fit token budget | KEEP | — | registry | P0 | Substrate complete. |
| shared/skills/cli.py | CLI for listing/inspecting skills | KEEP | — | registry | P2 | |
| shared/skills/skills/brainstorming/{SKILL.md,SKILL.yaml} | Skill: brainstorming | KEEP | — | — | P2 | |
| shared/skills/skills/subagent-driven-development/{SKILL.md,SKILL.yaml} | Skill: subagent-driven dev | KEEP | — | — | P2 | |
| shared/skills/skills/systematic-debugging/{SKILL.md,SKILL.yaml} | Skill: systematic debugging | KEEP | — | — | P2 | |
| shared/skills/skills/using-git-worktrees/{SKILL.md,SKILL.yaml} | Skill: git worktrees | KEEP | — | — | P2 | |
| shared/skills/skills/verification-before-completion/{SKILL.md,SKILL.yaml} | Skill: pre-completion self-check | KEEP | #12 (cite-or-refuse) | — | P2 | |
| shared/skills/skills_README.md | Docs | KEEP | — | — | P2 | |

##### shared/standards/ (Bundle schema + validator + injector + drift)

| Path | Current purpose | Marking | Decision drivers | Depends on | Priority | Notes |
|---|---|---|---|---|---|---|
| shared/standards/bundle-schema.yaml | Org-bundle structural schema v1 | REFACTOR | #10 (fractal federation), #11 (devops+8 planes), #23 (feature flags), #25 (Keycloak), #16 (update flow), #27 (Smart Spine tiers), #6 (comm prefs) | — | P0 | Schema is rich but doesn't yet model: `federation` block (parent_hub, consent policies #10), `feature_flags` block (#23), `licensing` (#23 signed bundle), `learning_scope` policy (#27), `comm_prefs` (#6), `update_policy` (#16 cascade approval), `devops_planes` (#11 8 control planes). Inheritance hooks already exist (`inherits_from`) — good foundation. |
| shared/standards/validator.py | Pydantic v2 mirror of bundle-schema.yaml + cross-section invariants | REFACTOR | (mirrors bundle-schema changes) | bundle-schema | P0 | Must track the schema extensions above; cross-section invariants for federation consent + license-signature verification. |
| shared/standards/prompt_injector.py | Inject bundle slices into role-prompt files; idempotent marker blocks | REFACTOR | #7 (industry-standard charters), #11 (devops role) | bundle-schema, lib/role-prompts | P1 | Slice map currently per-role; add slice mappings for new roles (devops, scrum_master, pm, release_manager per #5, #11) and for hub-master vs project-level (#8 two-tier hierarchy). |
| shared/standards/drift_detector.py | Compare installed bundles vs source URL (http/git/file); SHA-256 | KEEP | #16 (update distribution + approval cascade) | bundle-schema | P0 | Substrate is right; v3 should plug this into the update-distribution flow (vendor → parent Hub → child) and surface drift in the decision queue (#5). |
| shared/standards/install_bundle.sh | Bash CLI: install/validate/list/activate/status/drift-check/remove/inject | REFACTOR | #10 (fractal install), #16, #23 (license verify) | validator, injector, drift_detector | P0 | Needs install-from-parent-hub mode + license/signature verification (#23). |
| shared/standards/bundle-startup-saas.yaml | Reference bundle: startup SaaS | REFACTOR | #14 (3 segments — solo founder bundle missing) | bundle-schema | P1 | Schema-track. Add solo-founder reference bundle separately. |
| shared/standards/bundle-regulated-enterprise.yaml | Reference bundle: regulated enterprise | KEEP | #14 | bundle-schema | P1 | |
| shared/standards/example_org_overrides/lean_iso_agents.yaml | Example partial override (inherits startup-saas) | KEEP | — | — | P2 | |
| shared/standards/example_org_overrides/regulated_iso_agents.yaml | Example partial override | KEEP | — | — | P2 | |
| shared/standards/README.md / install_README.md | Docs | REFACTOR | (per schema changes) | — | P2 | |

##### shared/ui/ (Dashboard + approvals)

| Path | Current purpose | Marking | Decision drivers | Depends on | Priority | Notes |
|---|---|---|---|---|---|---|
| shared/ui/approvals/index.html | Approval-queue static UI | REFACTOR | #3 (Hub web UI), #28 (mobile-responsive Day 1) | shared/api/routes/approvals | P0 | Vanilla static HTML; v3 Hub web app should consolidate it into a single SPA tab (dashboard already links to it). Must be mobile-responsive (#28). |
| shared/ui/approvals/approvals.js | UI logic for approvals | REFACTOR | #3, #5 (decision cards), #25 (OIDC login) | — | P0 | Add decision-card rendering (#5), OIDC login flow (#25). |
| shared/ui/approvals/approvals.css | Styles | REFACTOR | #28 | — | P1 | Add mobile breakpoints. |
| shared/ui/approvals/proxy.py | DEV-ONLY HTTP proxy wrapping gate.sh | DELETE | (superseded by shared/api/routes/approvals.py) | — | P1 | Marked DEV-ONLY in its own header. shared/api supersedes it. Keep until cutover, then delete. |
| shared/ui/approvals/serve.sh | DEV-ONLY serve script | DELETE | (paired with proxy.py) | — | P1 | Delete with proxy.py. |
| shared/ui/approvals/README.md | Docs | KEEP | — | — | P2 | Update at proxy removal. |
| shared/ui/dashboard/index.html | Control Center SPA host (tabs: projects/cost/activity/knowledge) | REFACTOR | #3 (primary Hub surface), #28 (mobile), #5 ("talk to a role" chat) | dashboard.js, panels/* | P0 | Right shell. Needs new tabs/panels: master-roles, registry, audit, vault-config, integrations, decision-queue, role-chat (#3 enumeration). Mobile-responsive (#28). |
| shared/ui/dashboard/dashboard.js | Vanilla-JS SPA host (tab routing, polling, settings) | REFACTOR | #3, #25 (OIDC), #4 (federation) | panels/* | P0 | No framework today — vanilla ES modules. v3 Hub SPA will need richer state mgmt; whether to upgrade to a framework is a v3 design call beyond triage. Either way, add OIDC login, federation hub-switcher. |
| shared/ui/dashboard/dashboard.css | Styles | REFACTOR | #28 | — | P1 | Mobile-responsive. |
| shared/ui/dashboard/serve.sh | Local dev serve script | KEEP | — | — | P2 | Useful for dev. |
| shared/ui/dashboard/panels/projects-grid.js | Projects portfolio panel | KEEP | — | api/v2/projects | P1 | |
| shared/ui/dashboard/panels/cost-meter.js | Unified cost meter panel | KEEP | — | api/v2/audit | P1 | |
| shared/ui/dashboard/panels/activity-stream.js | Live role-activity stream | KEEP | — | api/v2/audit | P1 | |
| shared/ui/dashboard/panels/kg-search.js | KG hybrid_search panel | KEEP | — | api/v2/kg/hybrid_search | P1 | |
| shared/ui/dashboard/dashboard_README.md | Docs | KEEP | — | — | P2 | |

##### shared/validation/ (Cross-LLM consensus — STORY-3.7.*)

| Path | Current purpose | Marking | Decision drivers | Depends on | Priority | Notes |
|---|---|---|---|---|---|---|
| shared/validation/__init__.py | Re-exports | KEEP | — | — | P2 | |
| shared/validation/cross_llm.py | Primary-vs-secondary cross-validation; provider literal | REFACTOR | #2 (LLM-agnostic — adds Bedrock+Vertex+Ollama+Qwen+vLLM) | shared/llm (new) | P0 | Provider Literal is `anthropic / openai / google / local` — must extend to include `bedrock`, `vertex`, `ollama`, `qwen`, `vllm` (#2). Should call providers via shared/llm rather than inline SDK calls. |
| shared/validation/consensus.py | Reduce N verdicts → ConsensusResult with confidence band | KEEP | — | — | P0 | Pure logic; provider-agnostic. |
| shared/validation/config.py | Per-phase (phase, severity) policy | KEEP | — | bundle | P1 | |
| shared/validation/cross_llm_README.md | Docs | KEEP | — | — | P2 | |

#### BUILD-NEW files needed

##### shared/llm/ — Single LLM call surface (per W1 recommendation; required by #2)

| Proposed path | Purpose | Decision drivers | Depends on | Priority |
|---|---|---|---|---|
| shared/llm/__init__.py | Public re-exports | #2 | — | P0 |
| shared/llm/client.py | Single `call(request)` API; routes to provider adapter; threads through prompt-cache, retry, cost-accounting | #2, #9, #27 | shared/cost/router (model selection), shared/secrets, shared/audit | P0 |
| shared/llm/request.py | `LLMRequest` / `LLMResponse` / `Message` Pydantic models | #2 | — | P0 |
| shared/llm/providers/__init__.py | Adapter registry | #2 | — | P0 |
| shared/llm/providers/anthropic.py | Anthropic adapter (absorbs shared/cost/prompt_cache logic) | #2 | shared/secrets | P0 |
| shared/llm/providers/openai.py | OpenAI adapter | #2 | shared/secrets | P0 |
| shared/llm/providers/bedrock.py | AWS Bedrock adapter | #2, #20 | shared/secrets | P0 |
| shared/llm/providers/vertex.py | GCP Vertex adapter | #2, #20 | shared/secrets | P0 |
| shared/llm/providers/ollama.py | Local Ollama adapter | #2, #17 (laptop) | — | P1 |
| shared/llm/providers/qwen.py | Qwen adapter | #2 | shared/secrets | P1 |
| shared/llm/providers/vllm.py | Self-hosted vLLM adapter | #2, #15 (self-hosted) | shared/secrets | P1 |
| shared/llm/streaming.py | SSE/stream multiplexing helper | #2 | — | P1 |
| shared/llm/retry.py | Retry policy (rate-limit, transient) | #2 | — | P1 |
| shared/llm/README.md | Docs | #2 | — | P2 |

##### shared/secrets/ — Vault adapter layer (required by #9)

| Proposed path | Purpose | Decision drivers | Depends on | Priority |
|---|---|---|---|---|
| shared/secrets/__init__.py | Public surface — `get_secret(path)` / `put_secret(path, value)` | #9 | — | P0 |
| shared/secrets/vault.py | OpenBao/Vault adapter (Day-0 wizard-installed) | #9 | — | P0 |
| shared/secrets/aws_secrets_manager.py | AWS Secrets Manager adapter | #9, #20 | — | P1 |
| shared/secrets/azure_keyvault.py | Azure Key Vault adapter | #9, #20 | — | P1 |
| shared/secrets/gcp_secret_manager.py | GCP Secret Manager adapter | #9, #20 | — | P1 |
| shared/secrets/cache.py | In-process TTL cache for secret fetches | #9 | — | P1 |
| shared/secrets/rotation.py | Rotation hooks (vault lease renewal) | #9 | — | P1 |
| shared/secrets/README.md | Docs — vault-only posture, no env://, no built-in store | #9 | — | P2 |

##### shared/integrations/ — External system connectors (required by #11, #20, #33 A)

| Proposed path | Purpose | Decision drivers | Depends on | Priority |
|---|---|---|---|---|
| shared/integrations/__init__.py | Connector registry | #11, #33 | — | P0 |
| shared/integrations/github.py | GitHub: repos, issues, PRs, Actions; migration source | #11, #33 A | shared/secrets | P0 |
| shared/integrations/linear.py | Linear: issues, projects (migration source) | #33 A | shared/secrets | P0 |
| shared/integrations/jira.py | Jira: issues, epics (migration source) | #33 A | shared/secrets | P0 |
| shared/integrations/slack.py | Slack: post/listen for active comms + decision cards | #5, #6 | shared/secrets | P0 |
| shared/integrations/pagerduty.py | PagerDuty: incident-class routing | #6, #11 (incident plane) | shared/secrets | P0 |
| shared/integrations/twilio.py | Twilio: SMS/voice scaffold | #6, #29 | shared/secrets | P1 |
| shared/integrations/teams.py | MS Teams chat | #6 | shared/secrets | P1 |
| shared/integrations/whatsapp.py | WhatsApp Business | #6 | shared/secrets | P2 |
| shared/integrations/aws.py | AWS deploy/IaC helpers | #11, #20 | shared/secrets | P0 |
| shared/integrations/azure.py | Azure deploy helpers | #11, #20 | shared/secrets | P0 |
| shared/integrations/gcp.py | GCP deploy helpers | #11, #20 | shared/secrets | P0 |
| shared/integrations/railway.py | Railway deploy | #20 | shared/secrets | P1 |
| shared/integrations/fly_or_do.py | Fly.io / DigitalOcean deploy | #20 | shared/secrets | P1 |
| shared/integrations/vanta.py | Vanta connector scaffold | #24 | shared/audit/exporter | P1 |
| shared/integrations/drata.py | Drata connector scaffold | #24 | shared/audit/exporter | P1 |
| shared/integrations/secureframe.py | Secureframe connector scaffold | #24 | shared/audit/exporter | P1 |
| shared/integrations/README.md | Docs | — | — | P2 |

##### shared/license/ — Feature-flag licensing (required by #23)

| Proposed path | Purpose | Decision drivers | Depends on | Priority |
|---|---|---|---|---|
| shared/license/__init__.py | Public: `is_feature_enabled(flag)` / `quota_remaining(key)` | #23 | — | P0 |
| shared/license/bundle_verifier.py | Verify signed license bundle (Ed25519); vendor-as-root | #16, #23 | shared/secrets | P0 |
| shared/license/feature_flags.py | Flag evaluation + per-quota counters | #23 | — | P0 |
| shared/license/quota_ledger.py | Quota usage persistence | #23 | spine_audit / new schema | P1 |
| shared/license/README.md | Docs — closed-source v1.0 posture | #18, #23 | — | P2 |

##### shared/migration/ — Portability + version migrations (required by #33)

| Proposed path | Purpose | Decision drivers | Depends on | Priority |
|---|---|---|---|---|
| shared/migration/__init__.py | Public surface | #33 | — | P0 |
| shared/migration/export.py | Full Spine state export (projects, KG, audit, bundles, manifests, vault refs) | #33 B | shared/audit, shared/standards, shared/reproducibility | P0 |
| shared/migration/import_.py | Full Spine state import (validated, idempotent) | #33 B | (export pair) | P0 |
| shared/migration/onboarding.py | Onboarding migration: import projects from GitHub + Linear/Jira | #33 A | shared/integrations | P0 |
| shared/migration/spine_version.py | DB/bundle/role-charter/vault/KG schema-version migrator | #33 D, #16 | shared/standards, shared/reproducibility | P0 |
| shared/migration/version_registry.py | Track every versioned subsystem | #33 D | — | P0 |
| shared/migration/README.md | Docs | #33 | — | P2 |

##### shared/learning/ — Smart Spine 3-tier substrate (required by #27)

| Proposed path | Purpose | Decision drivers | Depends on | Priority |
|---|---|---|---|---|
| shared/learning/__init__.py | Public surface | #27 | — | P0 |
| shared/learning/scope.py | Resolve `learning_scope ∈ {project, within_hub, cross_org}` per directive | #27 | shared/standards bundle | P0 |
| shared/learning/contribute.py | Tier 1+2+3 contribution gates (always-on / default-on / opt-in) | #27 | shared/memory | P0 |
| shared/learning/consent.py | Cross-org opt-in registry | #27, #10 | shared/secrets | P0 |
| shared/learning/vendor_self_improvement.py | Vendor-tier always-on self-improvement channel | #27, #21 | — | P1 |
| shared/learning/README.md | Docs | #27 | — | P2 |

##### shared/recovery/ — Disaster recovery (required by #31)

| Proposed path | Purpose | Decision drivers | Depends on | Priority |
|---|---|---|---|---|
| shared/recovery/__init__.py | Public surface | #31 | — | P0 |
| shared/recovery/backup.py | Continuous backup (Postgres logical, KG, manifests, bundles, vault refs) | #31 | shared/secrets | P0 |
| shared/recovery/restore.py | Tested restore | #31 | backup | P0 |
| shared/recovery/cross_region.py | Active-passive cross-region failover (opt-in per bundle) | #31 | shared/integrations | P1 |
| shared/recovery/auto_recovery.py | Auto-recovery driver + immediate notification | #31, #5 | shared/notify | P0 |
| shared/recovery/health.py | Health probes (DB/Vault/MCP/Keycloak) | #31, #3 | — | P0 |
| shared/recovery/README.md | Docs | #31 | — | P2 |

##### shared/federation/ — Hub-to-Hub coordination (required by #4, #10, #16)

| Proposed path | Purpose | Decision drivers | Depends on | Priority |
|---|---|---|---|---|
| shared/federation/__init__.py | Public surface | #4, #10 | — | P0 |
| shared/federation/hub_registry.py | Track parent + child Hubs; consent records | #10 | shared/secrets | P0 |
| shared/federation/upstream_client.py | Call parent Hub MCP / API with mTLS + bearer | #4, #10 | shared/llm not, shared/secrets | P0 |
| shared/federation/downstream_router.py | Route requests to child Hubs (delegated tools) | #4, #10 | — | P0 |
| shared/federation/update_cascade.py | Vendor → parent → child update distribution + approval gate | #16 | shared/standards/drift_detector | P0 |
| shared/federation/consent.py | Peer-consent default; bounded mandatory upward flows | #10 | bundle | P0 |
| shared/federation/README.md | Docs | #4, #10 | — | P2 |

##### shared/identity/ — Keycloak embedded by default (required by #25)

| Proposed path | Purpose | Decision drivers | Depends on | Priority |
|---|---|---|---|---|
| shared/identity/__init__.py | Public surface | #25 | — | P0 |
| shared/identity/keycloak_client.py | OIDC client + token verification | #25 | shared/secrets | P0 |
| shared/identity/middleware.py | FastAPI dependency for `current_user` (replaces stub in shared/api/dependencies.py) | #25, #3 | keycloak_client | P0 |
| shared/identity/rbac.py | Role/scope checks + bundle-driven policy | #25, #8 | — | P0 |
| shared/identity/feature_flag_lightening.py | Tier-based simplification (single user → SSO) | #25, #14 | shared/license | P1 |
| shared/identity/README.md | Docs | #25 | — | P2 |

##### shared/api/ extensions (new routes for Hub features)

| Proposed path | Purpose | Decision drivers | Depends on | Priority |
|---|---|---|---|---|
| shared/api/routes/decisions.py | Decision queue REST (active push UI / decision cards) | #5, #6 | shared/notify | P0 |
| shared/api/routes/role_chat.py | "Talk to a role" chat endpoint (one of the Hub's 9 enumerated surfaces in #3) | #3 | shared/llm, shared/mcp | P0 |
| shared/api/routes/registry.py | Master role registry + project-level role enumeration | #3, #8 | shared/standards | P0 |
| shared/api/routes/vault_config.py | Vault config UI backend | #3, #9 | shared/secrets | P0 |
| shared/api/routes/integrations.py | Integration config UI backend | #3 | shared/integrations | P0 |
| shared/api/routes/federation.py | Hub-to-Hub config + status | #4, #10 | shared/federation | P0 |
| shared/api/routes/kg.py | Dedicated KG REST surface (proxy MCP today) | #3 | shared/mcp/tools/kg | P1 |
| shared/api/routes/license.py | License/quota status endpoint | #23 | shared/license | P1 |
| shared/api/middleware/oidc.py | OIDC bearer middleware | #25 | shared/identity | P0 |
| shared/api/middleware/feature_flag.py | Feature-flag enforcement middleware | #23 | shared/license | P0 |
| shared/api/openapi_spec.py | Heavier OpenAPI generation (per #30 scaffold-heavier) | #30 | — | P1 |

##### shared/mcp/ extensions

| Proposed path | Purpose | Decision drivers | Depends on | Priority |
|---|---|---|---|---|
| shared/mcp/server_remote.py | Remote MCP transport (mTLS over HTTP) for federation calls + Hub-to-project | #4, #10, #30 | shared/secrets, shared/identity | P0 |
| shared/mcp/tools/federation.py | MCP tools for federation ops (parent/child registry, consent grants) | #4, #10 | shared/federation | P0 |
| shared/mcp/tools/integrations.py | MCP tools for integration ops (test connection, list configured) | #3, #11 | shared/integrations | P1 |
| shared/mcp/tools/migration.py | MCP tools for portability + onboarding migration | #33 | shared/migration | P0 |
| shared/mcp/tools/recovery.py | MCP tools for DR (snapshot, restore, health) | #31 | shared/recovery | P0 |
| shared/mcp/tools/license.py | MCP tools for license inspection | #23 | shared/license | P1 |

##### shared/schemas/ extensions

| Proposed path | Purpose | Decision drivers | Depends on | Priority |
|---|---|---|---|---|
| shared/schemas/plan/prd_v1.py | Canonical PRD Pydantic | #5, #19 | — | P0 |
| shared/schemas/plan/trd_v1.py | Canonical TRD Pydantic | — | — | P0 |
| shared/schemas/plan/decision_card_v1.py | Decision card emitted by master roles to business user (per #5) | #5 | — | P0 |
| shared/schemas/plan/briefing_v1.py | Briefing (daily / weekly / incident) | #5 | — | P0 |
| shared/schemas/build/work_item.py | Work item base; subclasses for each of 7 types | #19 | — | P0 |
| shared/schemas/verify/findings_v1.py | VerifyFindings canonical | #12 | — | P1 |
| shared/schemas/federation/consent_v1.py | Federation consent record | #10 | — | P0 |
| shared/schemas/license/bundle_v1.py | Signed license bundle | #23 | — | P0 |

##### shared/ui/ expansion (Hub web SPA)

| Proposed path | Purpose | Decision drivers | Depends on | Priority |
|---|---|---|---|---|
| shared/ui/dashboard/panels/decision-queue.js | Decision queue (active push) panel | #5 | api/decisions | P0 |
| shared/ui/dashboard/panels/master-roles.js | Hub master roles management panel | #3, #8 | — | P0 |
| shared/ui/dashboard/panels/registry.js | Role + integration registry panel | #3 | api/registry | P0 |
| shared/ui/dashboard/panels/audit.js | Audit explorer panel | #24 | api/audit | P0 |
| shared/ui/dashboard/panels/vault-config.js | Vault config panel | #3, #9 | api/vault_config | P0 |
| shared/ui/dashboard/panels/integrations.js | Integration config panel | #3 | api/integrations | P0 |
| shared/ui/dashboard/panels/role-chat.js | "Talk to a role" chat panel | #3 | api/role_chat | P0 |
| shared/ui/dashboard/panels/federation.js | Federation hub topology panel | #4, #10 | api/federation | P0 |
| shared/ui/dashboard/panels/license.js | License/quota panel | #23 | api/license | P1 |
| shared/ui/dashboard/responsive.css | Mobile breakpoints (#28 web-mobile-responsive Day 1) | #28 | — | P0 |
| shared/ui/login/index.html | OIDC login page | #25 | shared/identity | P0 |
| shared/ui/onboarding/* | Onboarding wizard (3 SKU variants) | #14, #17 | api/migration | P1 |

##### shared/notify/ extensions

| Proposed path | Purpose | Decision drivers | Depends on | Priority |
|---|---|---|---|---|
| shared/notify/preferences.py | Per-user per-decision-class per-medium preference store | #6 | shared/identity | P0 |
| shared/notify/decision_cards.py | DecisionCard event factory + routing | #5, #6 | preferences | P0 |
| shared/notify/briefings.py | Daily/weekly briefing scheduler + composer | #5 | preferences | P0 |
| shared/notify/persistence.py | Persistent rate-limit log (V22+ schema) | #4, #31 | — | P1 |

#### Summary

- **Files reviewed:** ~104 files (excluding `__pycache__`, READMEs counted as 1 row per dir where uniform).
- **KEEP:** 56, **REFACTOR:** 30, **REBUILD:** 3 (prompt_cache, api/dependencies, ui/approvals/proxy logic — proxy itself is DELETE), **DELETE:** 2 (proxy.py + serve.sh in ui/approvals after API cutover), **BUILD-NEW (proposed):** ~110 across 9 new sub-packages + extensions.

##### Biggest themes (what most files share)
- **Substrate-correct, surface-incorrect.** The dominant pattern: a file's *concept* is right for v3, but its *surface* assumes a laptop-only single-user posture (env vars for secrets, `~/.spine/...` for state, in-process MCP only, no auth, single-LLM provider hard-coding).
- **Vault gap.** Almost every file that touches secrets reads from environment variables or `~/.spine/*.yaml` instead of going through a vault adapter (which doesn't yet exist) — violates #9.
- **Single-provider gravity.** Anthropic is implicit throughout (prompt_cache.py, classifier LLM-judge, cross_llm.py provider literal). Real LLM-agnosticism per #2 needs the new shared/llm/ surface.
- **Federation-blind.** No file currently anticipates parent/child Hub topology (#4, #10). All identifiers and lookups are local-Hub-only.
- **Excellent envelope/registry hygiene.** ToolSpec + ToolResponse + RunManifest + AuditRecord + bundle-schema are all clean Pydantic — easy to extend.

##### Biggest debts (artifacts most pulling against locked design)
1. **shared/cost/prompt_cache.py** — Anthropic-only; must become a provider trait inside shared/llm/.
2. **shared/api/dependencies.py** — header-stub auth + subprocess psql + in-process-only MCP = all three are wrong shape for the Hub-as-product (#3, #25, #4).
3. **shared/notify/channels.py** — loads creds from `~/.spine/<name>.yaml`; channel set missing PagerDuty/SMS/Teams/WhatsApp; rate-limit is in-memory.
4. **shared/standards/bundle-schema.yaml** — missing federation, feature_flags, licensing, learning_scope, comm_prefs, update_policy, devops_planes sections.
5. **shared/ui/dashboard/index.html** — only 4 tabs; Hub-as-product enumerates ~9 surfaces.
6. **shared/memory/playbook_store.py** — single cross-project bucket; #27 mandates 3 distinct tiers with different defaults.
7. **shared/mcp/tools/orchestrator.py** — ProjectType Literal is 4 values; #19 mandates 7 work-item types.
8. **No shared/llm/, no shared/secrets/, no shared/integrations/, no shared/license/, no shared/migration/, no shared/learning/, no shared/recovery/, no shared/federation/, no shared/identity/** — nine substrate-level packages required by locked decisions that don't yet exist.

##### Biggest wins (substrate already perfect for v3)
- **shared/audit/audit_record.py** + **redactor.py** — hash-chained, redactor-pluggable, exactly what compliance (#24) and cite-or-refuse (#12) demand.
- **shared/mcp/tools/__init__.py** registry pattern with ToolSpec — clean decorator-driven discovery; trivially extensible with feature-flag tag for #23.
- **shared/reproducibility/manifest.py** + **replay.py** — already the right primitive for DR (#31) and version migration (#33 D); just needs storage abstraction.
- **shared/calibration/calibrator.py** — Platt-scaled per (role, output_type) is precisely the Smart Spine learning substrate (#27).
- **shared/memory/lesson_indexer.py** + **lesson_store.py** — pgvector-cosine recall is exactly what Smart Spine tier 1 needs.
- **shared/skills/registry.py** + **trigger_engine.py** — auto-trigger skill pattern can absorb v3 additions with `feature_flag` field only.
- **shared/standards/drift_detector.py** — substrate matches the #16 update-cascade approval flow.
- **shared/eval/runner.py** DispatchFn — already provider-agnostic by design; pluggable today.

##### Risks (things that might surprise the build)
- **Subprocess `psql` everywhere.** ~12 files shell out to `psql` for DB access (deliberate "no psycopg dep"). For a containerized Hub (#3) hot path this becomes a real perf + observability burden; budget for an asyncpg pool migration (single chokepoint via DbHandle is right, just swap the body).
- **`~/.spine/` filesystem state.** Bundle resolution (cost/router.py), manifest storage (reproducibility/manifest.py), playbook (memory/playbook_store.py), notify configs (notify/channels.py) all use `~/.spine/...`. A multi-tenant Hub container needs every one of these abstracted behind a `SharedStorage` adapter — easy to miss because the env var indirection makes the dependency invisible.
- **Vanilla-JS dashboard.** shared/ui/dashboard/ deliberately ships no framework. The v3 Hub SPA's surface area (9 enumerated panels in #3) will eventually outgrow vanilla ES modules — but adopting a framework is a v3 architecture decision beyond triage scope; flagging only.
- **shared/cost/router.py imports.** Many files (`classifier`, `team_router`, `model_selection_table`, `user_override`) reach into private helpers like `_load_active_bundle`. When we move bundle loading into a Hub-aware service, these private imports will all break — plan for a single public bundle-loader API.
- **Cross-LLM provider literal is exhaustive.** `shared/validation/cross_llm.py` uses a Pydantic `Literal[...]` for providers — adding bedrock/vertex/ollama/qwen/vllm is a breaking schema change for any persisted ValidationRequest.
- **No `shared/db/` directory yet.** README anticipates it (Phase 2 per STORY-8.3.3); files currently embed DSN constants. When `shared/db/` lands it will touch ~15 files.
- **No `shared/realtime/` or `shared/infra/` directories yet.** Also anticipated by README but absent — will be needed for live dashboard updates (WebSocket per shared/api README "future work") and Vault container management.
- **MCP `discover_tools` re-imports on every empty registry check.** `app.py` lifespan + `healthz` both call it; harmless today but a federation Hub spinning up child MCP connections needs registry warming to be explicit (not lazy on first call).
- **build_artifact.py imports `plan.artifacts._base`** — couples shared/ to plan/. Acceptable but worth documenting in the v3 dependency graph.
- **Some files marked KEEP will need extension fields** (e.g. AuditRecord.subsystem enum, ProjectType enum). They keep their structure but need additive evolution; tracking these as KEEP-with-extensions might be clearer than KEEP for the build agents.

---

## T2 — plan/

**Scope:** plan/{artifacts,pipeline,runtime,swarm,templates,decomposer}
**Source:** `T2-plan.md` (extracted from `/private/tmp/.../tasks/<agent-id>.output`)

I now have full visibility into the plan/ subsystem. Let me produce the triage report.

---

### Triage Report — plan/ subsystem

#### Existing files / directories

| Path | Current purpose | Marking | Decision drivers | Depends on | Priority | Notes |
|---|---|---|---|---|---|---|
| `plan/README.md` | Subsystem overview (intake → PRD → TRD → Roadmap) | REFACTOR | #2, #5, #7, #11, #19, #21, #25, #33 | docs/ARCHITECTURE.md | P1 | Says "Phase 0, empty" — stale. Add: LLM-agnostic note, 5-move LLM runner, 7 work-item types, importers, devops 6th-corner role, federation/Hub coordination touchpoints. |
| `plan/artifacts/_base.py` | Shared Pydantic types (Goal, OpenQuestion, AcceptanceCriterion, ApprovalRecord, ArtifactMetadata, enums) | KEEP | #18, #19 | pydantic | P2 | Solid foundation. `ProjectType` enum is OK but should be marked extensible — `CUSTOM` already there. Need to add `work_item_type` discriminator field on PRD/etc later (#19). No structural rework required. |
| `plan/artifacts/prd_v1.py` | PRDv1 Pydantic schema + refuse-to-advance gate + to_markdown | REFACTOR | #5, #19, #27, #33A | _base.py | P1 | Solid bones. Needs (a) optional `work_item_type` field for the 7 work-item types (#19), (b) optional `briefing_log` reference for AI-PM push-briefing decisions (#5), (c) `imported_from` provenance for importer flows (#33A), (d) `memory_refs` for KG/memory lookups (#27). Don't rewrite — extend. |
| `plan/artifacts/trd_v1.py` | TRDv1 Pydantic schema | REFACTOR | #2, #9, #12, #20, #25 | _base.py | P1 | Needs additions: `llm_choices` section for #2 model/provider selection per role; `secrets_strategy` referencing Vault/OpenBao (#9); `compliance_evidence_refs` for #24; `cloud_target` enum incl AWS/Azure/GCP/Railway/Fly/DO (#20); `identity_provider` defaulting to Keycloak (#25). Cite-or-refuse (#12) should attach a `citations: List[Citation]` to verify-class fields. |
| `plan/artifacts/roadmap_v1.py` | RoadmapV1 Pydantic schema + Jira CSV export | REFACTOR | #19, #33A | _base.py | P1 | Story model needs `work_item_type` field (one of 7 per #19). `to_jira_csv` is a half-baked exporter — generalize into an importer/exporter contract (Linear/Jira/GitHub Projects) under `plan/importers/` per #33A. INIT/EPIC/STORY id scheme is fine; consider also exposing initiative-level work_item_type for backlog imports. |
| `plan/artifacts/sdlc-pipeline-default.yaml` | Default 11-phase SDLC manifest | REFACTOR | #7, #11, #12, #16, #19, #24 | sdlc-pipeline-schema.yaml | P0 | Strong foundation. Needs: (a) new `devops` role distinct from `operator` (#11); (b) work_item-type-aware phase variants or branches for the 7 item types (#19); (c) cite-or-refuse gate config on verify-class phases (#12); (d) federation-tree update phase / handoff hooks (#16); (e) compliance phase template referencing Evidence Store (#24); (f) industry-standard anchors per phase (Scrum/PMBOK/SRE/ITIL/NIST) (#7). |
| `plan/artifacts/sdlc-pipeline-schema.yaml` | Manifest *shape* schema | REFACTOR | #11, #12, #19, #16 | — | P0 | Schema is sound. Add: `work_item_type` enum (7 values per #19); `devops` to role enum implicitly; `citation_required` boolean on phase/gate; `federation_update` hook block (#16); `industry_standard_ref` field per phase (#7). |
| `plan/artifacts/sdlc-pipeline-README.md` | Docs for the manifest | REFACTOR | #7, #11, #19 | sdlc YAMLs | P2 | Update to document new fields above + show worked example for work-item-typed pipelines. |
| `plan/pipeline/__init__.py` | Package surface | KEEP | — | submodules | P2 | Re-exports only. Will need new exports as importers/work-item-type loaders land. |
| `plan/pipeline/manifest_loader.py` | Resolve effective pipeline (default → org bundle → team → project) with merge semantics | KEEP | #4, #7, #10, #16 | yaml, default YAML | P2 | Already implements layered overlay with capability narrowing + sha256 versioning. Maps nicely to Hub-federation (#4, #10) and federation-tree updates (#16). Minor: add Hub-tier overlay above org-bundle for fractal federation (#10) — could be a thin extension, not a rewrite. |
| `plan/pipeline/capability_checker.py` | `can_*` capability enforcement, rationale-required gate | KEEP | #7, #8 | manifest_loader | P2 | Closed-by-default, principal-based grants; already aligned with two-tier role hierarchy (#8) via `role:`/`user:`/`group:` principals. Add new capability key `can_modify_work_item_types` for #19 governance once work-item-type config lands. |
| `plan/pipeline/versioning.py` | sha256 versions + git-committed edits + history walk | KEEP | #16 | git, capability_checker | P2 | Solid; commit-with-required-rationale model is exactly the audit anchor needed. May extend trailer to include federation-tree distribution hop info (#16). |
| `plan/pipeline/project_lock.py` | Pin a project to a pipeline version; DB-backed snapshot + migration | KEEP | #4, #33D | psql, manifest_loader, versioning | P2 | Migration with diff preview is the substrate for Spine-version-migration (#33D). Lock + restore pattern is correct. Will need extension when Hub-mediated migrations land (#4). |
| `plan/pipeline/phase_evolution.py` | Detect/classify/plan pipeline-manifest changes (rename/remove/reorder/gate-change) | KEEP | #33D, #16 | manifest_loader, project_lock | P2 | Exactly what #33D Spine version migrations need. The detection-classify-plan-execute pattern is reusable for inter-version Spine upgrades and federation rollouts. |
| `plan/pipeline/phase_evolution_README.md` | Phase evolution docs | KEEP | — | — | P3 | Accurate; minor update once federation hop semantics added. |
| `plan/pipeline/pipeline_README.md` | Pipeline subsystem docs | REFACTOR | #11, #19 | — | P2 | Update for new capabilities (work-item types, federation overlay) once code changes land. |
| `plan/pipeline/cli.py` | `spine pipeline {show\|edit\|migrate\|history\|lock-status\|diff}` CLI | KEEP | #30 | manifest_loader, project_lock, versioning | P2 | Clean CLI surface; will be wrapped by REST + MCP per #30. No structural change needed; add `import` subcommand later when importers land (#33A). |
| `plan/runtime/__init__.py` | Package marker | KEEP | — | — | P3 | Trivial. |
| `plan/runtime/intake_runner.py` | Deterministic question-loop intake — reads YAML template, asks Qs, synthesizes draft PRD, persists to DB, audits | REFACTOR | #5, #21, #27 | DB, templates, prd_v1, audit | P0 | Keep as the *deterministic fallback* runner — it covers EOF/non-tty paths cleanly. Module docstring already says LLM runner will live alongside. Light refactor: extract `synthesize_prd_draft()` into a shared helper so the LLM runner reuses identical persistence/audit code paths. Do NOT delete; per docs it's the back-stop. |
| `plan/runtime/intake_runner_README.md` | Intake runner docs | REFACTOR | #5, #21 | — | P2 | Already foreshadows the LLM runner. Update to point at the BUILD-NEW `intake_runner_llm.py` and clarify selector logic (project setting + CLI flag override). |
| `plan/swarm/__init__.py` | Package surface | KEEP | — | submodules | P3 | Minor re-exports. |
| `plan/swarm/composition_rules.py` | Per-project-type swarm composition (LRU-cached YAML load) | REFACTOR | #2, #11, #19 | sdlc YAML, ScoutRole | P1 | (a) Add `devops` as a ScoutRole option for #11. (b) Add work-item-type composition layer alongside project-type composition (#19 — bug/incident/refactor swarms may differ). (c) Compositions should be parameterizable per LLM provider tier (#2) for cost control. |
| `plan/swarm/swarm_engine.py` | LangGraph subgraph (compose → dispatch → wait → synthesize → validate, with retry) | REFACTOR | #2, #12, #21 | scout_contribution, composition_rules, synthesis | P1 | Architecture is right (LangGraph optional + linear fallback is exactly the "LangChain/LangGraph optional per-role only" tech-stack decision from memory). Needs: (a) per-scout LLM-provider routing hook (#2 — Anthropic/OpenAI/Bedrock/Vertex/Ollama/Qwen/in-house); (b) cite-or-refuse enforcement injection into the dispatcher contract (#12); (c) "ALL AI ALL THE TIME" autonomous mode flag (#21) wiring so the swarm can run without human-in-the-loop when policy permits. FileDispatcher stub stays useful for tests. |
| `plan/swarm/scout_contribution.py` | Per-scout Pydantic contribution schema (Finding/RiskItem/OpenQuestion/lens binding) | REFACTOR | #2, #11, #12 | pydantic | P1 | Add: (a) `DEVOPS` to `ScoutRole` enum + `DELIVERY` to `ScoutLens` (#11); (b) `citations: List[Citation]` field on `Finding` to make cite-or-refuse a schema-level invariant (#12); (c) `provider_used` alongside `model_used` (#2). Small, additive. |
| `plan/swarm/synthesis.py` | Architect synthesis: deterministic merge + optional LLM prose pass | REFACTOR | #2, #11, #12 | scout_contribution, trd_v1 | P1 | (a) Wire prose pass through provider-agnostic router (#2). (b) Map new `devops` lens to TRD `nfrs.observability` / runbook section (#11). (c) Propagate citations through to TRD fields (#12). Structure (two-pass, deterministic-first) is correct. |
| `plan/swarm/swarm_README.md` | Swarm docs | REFACTOR | #11 | — | P2 | Update lens table once devops added. |
| `plan/decomposer/__init__.py` | Package surface | KEEP | — | submodules | P3 | Trivial. |
| `plan/decomposer/decomposer.py` | PRD+TRD → RoadmapV1 with stable ids, sizing, dependencies, sprint sequencing | REFACTOR | #19, #27 | prd_v1, trd_v1, roadmap_v1, sizing, dependency_detection, id_allocator | P1 | (a) Accept work-item-type at story level so the decomposer emits typed stories (#19). (b) Sprint sequencer should consult Smart Spine memory for prior dependency edges in similar projects (#27). (c) Hard-coded `_MAX_STORIES_PER_SPRINT=8` / `_DEFAULT_SPRINT_COUNT=3` should be pipeline-config-driven, not source-pinned (flexibility principle from memory). |
| `plan/decomposer/dependency_detection.py` | KG `impact_radius` primary + text-overlap fallback + DFS cycle find | KEEP | #27 | shared.mcp.tools.kg | P2 | Substrate is right — uses KG when reachable, degrades gracefully. Smart Spine memory queries (#27) plug in naturally as an additional signal. No structural change. |
| `plan/decomposer/id_allocator.py` | Stable INIT/EPIC/STORY id minting via canonical hashing | KEEP | #33B | roadmap_v1 | P3 | Idempotency + retired-id surfacing supports Spine portability/round-trip (#33B). Pristine. |
| `plan/decomposer/sizing.py` | T-shirt sizing heuristic + cost/duration projection | REFACTOR | #23, #27 | _base.Size | P1 | Placeholder rates noted in docstring. Per #23 (feature-flag licensing built Day 1) + #27 (Smart Spine learning), this should pull sizing rates from per-project/per-org history rather than hardcoded constants. Keep heuristic; rewire data source. |
| `plan/decomposer/decomposer_README.md` | Decomposer docs | REFACTOR | #19, #27 | — | P2 | Update for typed stories + learned sizing once code changes land. |
| `plan/templates/intake/web-app.yaml` | Project-type intake template | KEEP | #19 | intake_runner | P2 | All 6 are well-shaped project-type templates. They stay as-is (web-app, internal-tool, data-pipeline, mobile, api-service, cli-tool). Per #19, these are PROJECT-type templates; new WORK-ITEM-type templates are a separate axis (see BUILD-NEW). |
| `plan/templates/intake/cli-tool.yaml` | Project-type intake template | KEEP | #19 | intake_runner | P2 | Same. |
| `plan/templates/intake/data-pipeline.yaml` | Project-type intake template | KEEP | #19 | intake_runner | P2 | Same. |
| `plan/templates/intake/internal-tool.yaml` | Project-type intake template | KEEP | #19 | intake_runner | P2 | Same. |
| `plan/templates/intake/mobile.yaml` | Project-type intake template | KEEP | #19 | intake_runner | P2 | Same. |
| `plan/templates/intake/api-service.yaml` | Project-type intake template | KEEP | #19 | intake_runner | P2 | Same. |

#### BUILD-NEW files needed

| Proposed path | Purpose | Decision drivers | Depends on | Priority |
|---|---|---|---|---|
| `plan/runtime/intake_runner_llm.py` | LLM-driven 5-move conductor (naive cast → provoke → reframe → tier → artifact). Reads same template format; produces same `metadata.intake` + `metadata.prd_draft` shape; selectable via project setting / CLI flag. Implements the actual dialogue protocol that today only lives in role-prompt text. | #5, #21, #27 | intake_runner (shared synth helpers), shared/llm router, KG/memory | P0 |
| `plan/runtime/briefing_pusher.py` | Push-briefing + decision-card emitter for AI PM / Scrum Master / Release Manager → business user. Per-user/decision-class/medium preferences. | #5, #6 | shared notify, user prefs, audit | P0 |
| `plan/runtime/comm_preferences.py` | Resolve per-user × per-decision-class × per-medium preferences for outbound briefings/cards (email/slack/dashboard/sms/voice scaffold). | #6, #29 | identity (Keycloak), notify | P1 |
| `plan/templates/work_items/feature.yaml` | Work-item-type intake template — feature. | #19 | intake_runner(s) | P0 |
| `plan/templates/work_items/bug.yaml` | Work-item-type intake template — bug (repro, severity, regression scope). | #19 | intake_runner(s) | P0 |
| `plan/templates/work_items/incident.yaml` | Work-item-type intake — incident (impact, blast radius, MTTR target) anchored on SRE practice. | #7, #19 | intake_runner(s) | P0 |
| `plan/templates/work_items/support.yaml` | Work-item-type intake — support ticket (user-reported, ITIL-anchored). | #7, #19 | intake_runner(s) | P0 |
| `plan/templates/work_items/refactor.yaml` | Work-item-type intake — refactor (no behavior change, risk envelope). | #19 | intake_runner(s) | P0 |
| `plan/templates/work_items/infra.yaml` | Work-item-type intake — infra (cloud target, cost cap, blast radius). | #19, #20 | intake_runner(s) | P0 |
| `plan/templates/work_items/compliance.yaml` | Work-item-type intake — compliance work (control, framework, evidence target). | #7, #19, #24 | intake_runner(s), Evidence Store | P0 |
| `plan/templates/work_items/README.md` | Index + anchor citations (Scrum/PMBOK/SRE/ITIL/NIST) per item type. | #7, #19 | — | P1 |
| `plan/importers/__init__.py` | Importer package init. | #33A | — | P0 |
| `plan/importers/_base.py` | Shared importer contract: external doc → draft `PRDv1`/`TRDv1`/`RoadmapV1` + provenance trail. | #33A, #33B | artifacts/ | P0 |
| `plan/importers/confluence.py` | Confluence PRD/spec page importer. | #33A | _base, Confluence API | P0 |
| `plan/importers/notion.py` | Notion page/database importer. | #33A | _base, Notion API | P0 |
| `plan/importers/linear.py` | Linear projects/issues → INIT/EPIC/STORY importer. | #33A | _base, Linear API | P0 |
| `plan/importers/jira.py` | Jira epics/stories importer. | #33A | _base, Jira API | P0 |
| `plan/importers/github_projects.py` | GitHub Projects/Issues importer (also feeds #33A onboarding). | #33A | _base, gh API | P1 |
| `plan/importers/google_docs.py` | Google Docs PRD/TRD importer. | #33A | _base, Drive API | P1 |
| `plan/importers/spine_portable.py` | Roundtrip importer for Spine portability — load `RoadmapV1` JSON exports from another Spine instance. | #33B | artifacts/ | P0 |
| `plan/exporters/spine_portable.py` | Companion exporter: `RoadmapV1` + PRD + TRD → portable Spine archive (vendor-neutral). | #33B | artifacts/ | P0 |
| `plan/exporters/jira_csv.py` | Pull `RoadmapV1.to_jira_csv` into a real exporter module; add Linear + GitHub Projects dialects. | #33A | roadmap_v1 | P1 |
| `plan/runtime/memory_hooks.py` | Smart Spine query hooks — intake/decomposer ask memory + KG: "what did this org decide last time on X?" before asking the user. Per-project always; within-Hub default ON; cross-org default OFF. | #27 | KG, vector store | P0 |
| `plan/runtime/llm_router.py` | Plan-subsystem-local wrapper over the shared LLM router enforcing #2 LLM-agnostic constraint for product/architect/planner roles (Anthropic + OpenAI + Bedrock + Vertex + Ollama + Qwen + vLLM). Thin facade. | #2 | shared/cost/router | P0 |
| `plan/swarm/citation.py` | `Citation` Pydantic model + `cite_or_refuse(finding)` validator for verify-class scouts. Schema-level enforcement of #12. | #12 | scout_contribution | P0 |
| `plan/runtime/autonomy_policy.py` | Per-bundle opt-in autonomy controller for ALL-AI mode (#21) + thin-wrapper engineer (#13). Decides which steps run unattended vs gate to user. | #13, #21 | pipeline manifest, capability_checker | P1 |
| `plan/pipeline/work_item_types.py` | Pipeline-as-data loader for the 7 work-item types (templates + per-type SDLC phase variants + per-type swarm composition). Mirrors `composition_rules.py` along the work-item-type axis. | #19 | manifest_loader, composition_rules | P0 |
| `plan/pipeline/federation_overlay.py` | Hub-tier overlay above org-bundle in the resolve chain — supports fractal Hub federation (each Hub may overlay its parent). | #4, #10, #16 | manifest_loader | P1 |
| `plan/tests/` | Pytest harness for everything above. Currently absent from the `plan/` tree shown — tests need to land alongside the new modules. | all | pytest | P0 |
| `plan/README.md` (overhaul section) | Not a new file — but the README needs new sections (LLM runner, importers, work-item types, federation overlay, autonomy policy). Tracked under existing REFACTOR row. | — | — | — |

#### Summary

- **Files reviewed:** 35 existing artifacts (6 in `artifacts/`, 7 in `pipeline/`, 3 in `runtime/`, 5 in `swarm/`, 5 in `decomposer/`, 6 intake templates, 3 READMEs/docs spread across, plus the top-level `plan/README.md` and 4 `__init__.py`s).
- **Markings tally:** 17 KEEP, 17 REFACTOR, 0 REBUILD, 0 DELETE, 30 BUILD-NEW.
- **Biggest themes:**
  1. **Schema-level extension over rewrite.** The Pydantic artifact tree (`_base`, `prd_v1`, `trd_v1`, `roadmap_v1`, `scout_contribution`) needs additive fields for work-item types, citations, provider/model provenance, importer provenance, and memory refs — never a rewrite. The "refuse-to-advance" + sealed-status discipline is exactly the substrate v3 wants.
  2. **Pipeline-as-data already correct.** `sdlc-pipeline-{schema,default}.yaml` + `manifest_loader` + `capability_checker` + `versioning` + `project_lock` + `phase_evolution` together are a coherent, layered, audited, versioned, capability-gated, federation-ready system. Only data shape additions (work_item_type axis, federation overlay, devops role) are needed — the runtime is already shaped right.
  3. **The intake runner truly is a deterministic stub.** The drift between the 5-move dialogue protocol (in role-prompt text) and `intake_runner.py` (a basic question loop) is the single biggest planned change in `plan/`. BUILD-NEW `intake_runner_llm.py` is the headline P0.
  4. **Two missing axes:** (a) 7 work-item-type templates per #19 — a completely missing dimension; (b) importer/exporter infrastructure per #33A/B — also missing. Both are P0.
- **Biggest debts:**
  - No `plan/tests/` directory anywhere in scope shown — yet `plan/README.md` lists it as target structure. Test coverage is invisible from outside.
  - `intake_runner.py` synthesizes a draft PRD inline (`synthesize_prd_draft`) with project-type-specific answer keys hardcoded — that helper needs extraction so the LLM runner reuses it.
  - `sizing.py` cost/duration tables are placeholder constants — per #27 Smart Spine, these must come from history.
  - `decomposer.py` has hardcoded sprint shape constants (`_MAX_STORIES_PER_SPRINT=8`, `_DEFAULT_SPRINT_COUNT=3`) — violates the flexibility-principle for an org that runs different cadence.
  - `roadmap_v1.to_jira_csv` is a half-baked exporter sitting on the model — should move to `plan/exporters/` and grow Linear + GitHub dialects.
  - No `devops` role anywhere in the swarm yet, despite #11 explicitly distinguishing it from `operator`.
  - No citation model in `scout_contribution.py` — `Finding.recommendation` is free text; cite-or-refuse (#12) needs schema teeth.
  - No LLM-provider routing in the swarm engine — currently `FileDispatcher` returns a stub `model_used="stub"`; no provider abstraction (#2).
- **Biggest wins (substrate already right for v3):**
  - **Pipeline subsystem.** `manifest_loader` (4-layer overlay), `capability_checker` (closed-by-default capability grants), `versioning` (git-trailer required rationale), `project_lock` (DB-snapshotted lock + diff-preview migration), `phase_evolution` (detect/classify/plan/execute for manifest changes). This is *already* the substrate for #4 federation, #16 federation-tree updates, #33D Spine-version migrations, and #7 industry-standard anchors. Almost zero rework; only additive overlays.
  - **Artifact schemas.** Pydantic v2 with refuse-to-advance gates + ApprovalRecord + ArtifactMetadata are the right shape for enterprise audit (#24) and compliance evidence flow.
  - **Swarm engine.** LangGraph-optional with linear fallback is exactly the memory'd tech-stack decision ("LangChain/LangGraph optional per-role only"). FileDispatcher stub + clean ScoutDispatcher protocol means provider routing slots in cleanly.
  - **Decomposer.** ID stability via canonical hashing + KG-first dependency detection + topological sprint sequencing is a high-quality core. Incremental mode + retired-ids is exactly what #33B portability roundtrips need.
  - **Phase evolution.** This module's detect-classify-plan-execute is reusable for Spine-version migrations (#33D) almost verbatim.
- **Risks:**
  - **Two intake runners diverging.** Without disciplined sharing (`synthesize_prd_draft` extraction, identical persistence/audit code paths), `intake_runner.py` and `intake_runner_llm.py` will drift, leaving the non-tty fallback subtly different from the primary path.
  - **Work-item-type explosion.** Adding the 7 work-item-type templates alongside the 6 project-type templates creates a 7×6=42 latent combination matrix. Need either (a) a composition rule that picks one axis as primary, or (b) explicit per-(project-type, work-item-type) overrides — must be a deliberate design call before templates land.
  - **`composition_rules.py` LRU caching** with `lru_cache(maxsize=4)` will mask hot-reload issues if the pipeline YAML is edited while a daemon runs. Already fragile; the additional axes will make it worse.
  - **`phase_evolution.py` rename detection** uses `_signature = (label, subsystem, artifact)` but the current YAML phases don't carry a `label` field — only `id`/`ownership`/`role_lead`/`artifact`. The signature is collapsing to `("", "", artifact)` for many phases, meaning rename detection will misfire (many phases will look like the "same" phase). Quiet bug worth flagging.
  - **`project_lock.py` SQL injection surface** — `_psql` builds SQL by string concatenation with `_esc` only escaping single quotes. The lock writer concatenates `version`, `project_id`, and JSON snapshot directly into SQL. If `version` or `project_id` ever flow from a user-controlled field, this is exploitable. Worth a tightening pass before v3.
  - **Importer infrastructure (#33A) is greenfield** — no abstraction exists yet for "PRD draft from external source." Risk that each importer reinvents provenance/diff/conflict handling. The `plan/importers/_base.py` contract needs to land before any single importer.
  - **No briefing/decision-card surface yet** — #5 ("AI Scrum Master / PM / Release Manager actively communicate with business user — push briefings + decision cards") has no code anchor anywhere in `plan/`. This is a P0 BUILD-NEW that's currently missing entirely from the subsystem.
  - **Memory/KG hooks for intake (#27 Smart Spine)** are not wired into either intake runner — the LLM runner needs them at design time, not retrofitted, or it will ask questions whose answers Spine already knows.

---

## T3 — build/

**Scope:** build/{kg,runtime,bridge,migration}
**Source:** `T3-build.md` (extracted from `/private/tmp/.../tasks/<agent-id>.output`)

I have a comprehensive view of the entire `build/` subsystem. Let me now produce the triage report.

### Triage Report — build/ subsystem

#### Existing files / directories

| Path | Current purpose | Marking | Decision drivers | Depends on | Priority | Notes |
|---|---|---|---|---|---|---|
| `/Users/khashsarrafi/Projects/Apps/SpineDevelopment/build/README.md` | Subsystem boundary doc | REFACTOR | #11 (devops), #13 (thin wrapper), #21 (all-AI), #33 (migration BUILD) | none | P1 | Sub-structure target (`roles/`, `daemons/`, `workers/`) reflects v1 SDLC, not v3's 8-control-planes. Add agent_wrappers + iac extractors to the target tree; clarify Build is agnostic to coding agent |
| `/Users/khashsarrafi/Projects/Apps/SpineDevelopment/build/runtime/__init__.py` | Package marker | KEEP | n/a | none | P2 | Doc references `lib/role-prompts/*.md` — update once migration runs |
| `/Users/khashsarrafi/Projects/Apps/SpineDevelopment/build/runtime/build_dispatcher.py` | Build Brief synthesis + BuildArtifact ingest; PRD→EG bridge; psql-direct | KEEP | #21 (all-AI orchestration), #19 (7 work-item types) | `plan.artifacts.prd_v1`, `shared.schemas.build.build_artifact`, `shared.audit.audit_record`, psql | P0 | The "handoff is the BuildArtifact" comment is exactly right per #13 — agent-agnostic. Only debt: `_DEFAULT_SQUAD = (engineer, qa)` hardcodes a 2-role squad; should resolve from intake or a feature-flagged squad registry per #23. Engineering goals only support MUST/SHOULD — no `bug/incident/support/refactor/infra/compliance` work-item-type awareness yet (#19) |
| `/Users/khashsarrafi/Projects/Apps/SpineDevelopment/build/runtime/kg_caller.py` | Per-role daemon KG hooks (engineer/operator/datawright) | REFACTOR | #11 (new devops role), #12 (cite-or-refuse), #13 (agent-agnostic) | `shared.mcp.tools.kg`, `shared.schemas.build.build_artifact`, psql, mcp CLI | P0 | Per #11 a new `devops` role needs a hook here (probably `DevOpsKGHook` calling `who_owns` + IaC-aware impact). Per #12 cite-or-refuse contract isn't enforced here; refactor to also call cite-or-refuse verifier. Datawright raw SQL string-interp at lines 185-198 is brittle but functional |
| `/Users/khashsarrafi/Projects/Apps/SpineDevelopment/build/runtime/enrich_artifact.py` | Post-process artifact to fill kg_impact | KEEP | #12 (cite-or-refuse fallback), #13 (works for any agent's artifact) | `build.runtime.kg_caller`, `shared.schemas.build.build_artifact` | P1 | Already agent-agnostic — works whether artifact came from Spine's engineer, Claude Code, Cursor, etc. Add devops branch once devops role lands |
| `/Users/khashsarrafi/Projects/Apps/SpineDevelopment/build/runtime/cli.py` | CLI for enrich / find-owner / register-output / pre-build-check | KEEP | #13 (CI gate works for any agent) | enrich_artifact, kg_caller | P1 | Solid. Add `agent-wrapper-info` subcommand once wrappers exist |
| `/Users/khashsarrafi/Projects/Apps/SpineDevelopment/build/runtime/runtime_README.md` | Daemon-side KG hooks doc | REFACTOR | #11 (devops), #13 (wrappers) | none | P2 | Update for devops role + wrapper-agnostic phrasing once those exist |
| `/Users/khashsarrafi/Projects/Apps/SpineDevelopment/build/runtime/__pycache__/*` | Bytecode artifacts | DELETE | hygiene | none | P2 | Add to `.gitignore`; not source of truth |
| `/Users/khashsarrafi/Projects/Apps/SpineDevelopment/build/bridge/__init__.py` | Package marker (v1→v2 bridge) | KEEP | #13 (interim), #22 (intelligent triage) | none | P1 | Docstring promises "retired once every role daemon emits native BuildArtifact" — per #13, "native daemon" largely means "external coding agent producing artifact directly", so bridge could be retired sooner |
| `/Users/khashsarrafi/Projects/Apps/SpineDevelopment/build/bridge/bridge_README.md` | Phase A/B/C migration plan | REFACTOR | #13 (rewrites "native v2 daemon" definition), #22 (per-artifact triage) | none | P1 | Phase B "replace with v2-native daemon" needs reframing: v3 native = a typed BuildArtifact emitter, which could be the external coding-agent wrapper. Rewrite to align with thin-wrapper model |
| `/Users/khashsarrafi/Projects/Apps/SpineDevelopment/build/bridge/v1_dispatcher.sh` | MCP→file-bus dispatch to v1 bash daemons | REFACTOR→DELETE | #13 (thin wrapper supersedes), #22 (per-artifact triage) | psql, `orchestrator/lib/_env_loader.sh`, v1 file layout | P1 | Bridge tactically useful while Spine's own engineer daemon coexists with external coding agents. Once `agent_wrappers/claude_code.py` etc. exist + bridge Phase C completes, this becomes obsolete. Keep through one release; delete in v3.1 |
| `/Users/khashsarrafi/Projects/Apps/SpineDevelopment/build/bridge/v1_report_collector.sh` | Poll v1 directive.md files, parse → BuildArtifact, emit | REFACTOR→DELETE | #13 (wrappers emit BuildArtifact directly) | report_parser.py, mcp/curl, psql | P1 | Same retirement path as v1_dispatcher.sh. Polling-based with 8s lag — wrappers can emit synchronously per #13 |
| `/Users/khashsarrafi/Projects/Apps/SpineDevelopment/build/bridge/report_parser.py` | v1 markdown report → BuildArtifact-shaped dict | KEEP (during transition) | #22 (artifacts get same triage), #13 | `enrich_artifact`, `BuildArtifact` schema | P2 | Auto-enrichment integration is solid. After bridge retirement, this stays useful as a generic "parse free-form markdown → typed artifact" helper for legacy/imported codebases per #33A |
| `/Users/khashsarrafi/Projects/Apps/SpineDevelopment/build/kg/indexer/__init__.py` | Package marker + public API | KEEP | #27 (Smart Spine 3-tier), #6 (KG is foundation) | indexer.py | P0 | |
| `/Users/khashsarrafi/Projects/Apps/SpineDevelopment/build/kg/indexer/indexer.py` | Cold-start + incremental + reindex; psql writes to spine_kg.kg_node/edge | KEEP | #27 (Smart Spine), #33A (import existing codebase mechanism) | parser_runtime, diff_engine, git, psql | P0 | Current ground-truth audit says 0 nodes — the code is fine, it's the WIRING that's broken. Cold-start is the on-ramp for "import existing codebase" per #33A. Ensure DATABASE_URL resolution mirrors `build_dispatcher._db_url()` precedence so installer-time + runtime agree |
| `/Users/khashsarrafi/Projects/Apps/SpineDevelopment/build/kg/indexer/cli.py` | `kg-index` CLI (cold-start / incremental / status / reindex-file / extractors) | KEEP | #27, #33A | indexer, parser_runtime | P0 | This is the entry point for the P0 wiring fix. Add a `--all-repos` mode for federation (#10) later |
| `/Users/khashsarrafi/Projects/Apps/SpineDevelopment/build/kg/indexer/diff_engine.py` | Pure-data supersede-pattern diff | KEEP | #27 (3-tier learning needs point-in-time) | none (stdlib only) | P0 | Clean, schema-aware, tested implicitly via indexer. No changes needed |
| `/Users/khashsarrafi/Projects/Apps/SpineDevelopment/build/kg/indexer/parser_runtime.py` | YAML-driven tree-sitter walker → nodes/edges | KEEP | #2 (LLM-agnostic implies parser-agnostic), #27 | tree_sitter (lazy), pyyaml | P0 | Graceful degradation to file-root-only when grammar missing is correct. Critical that this stays language-agnostic — per Decision #11/W2, new IaC extractors (Terraform/K8s) drop in as YAML; this runtime needs zero changes |
| `/Users/khashsarrafi/Projects/Apps/SpineDevelopment/build/kg/indexer/watcher_extension.py` | kg_tick callback for `db/watcher/` + post-commit hook generator | KEEP | #27 (continuous learning), #16 (federation update distribution) | indexer, git, ~/.spine/kg cursor cache | P1 | Right pattern. Currently only registers as one tick callback for the local watcher; for federation (#10/#16) needs `hub_tick` that the hub-side worker calls. Add later — current code is fine |
| `/Users/khashsarrafi/Projects/Apps/SpineDevelopment/build/kg/indexer/indexer_README.md` | Indexer ops doc | KEEP | n/a | none | P2 | Add a "federation tier" note once #10/#16 lands |
| `/Users/khashsarrafi/Projects/Apps/SpineDevelopment/build/kg/extractors/_schema.yaml` | Extractor config schema (informative) | KEEP | #2/#3 (declarative drops in for any new tech) | none | P0 | Per Decision #11/W2, this is the contract for new IaC extractors. Schema accommodates them as-is (`node_kind` is open-set per FR-1 catalog) — verify Terraform/K8s extractors can express their needs without schema changes |
| `/Users/khashsarrafi/Projects/Apps/SpineDevelopment/build/kg/extractors/bash.yaml` | Bash AST → KG | KEEP | #27 | tree_sitter_bash | P0 | Solid |
| `/Users/khashsarrafi/Projects/Apps/SpineDevelopment/build/kg/extractors/markdown.yaml` | Markdown AST → KG (headings, links, Spine-IDs) | KEEP | #27 (docs in graph) | tree_sitter_markdown | P0 | Note: shadowed by `doc_parser/` for `.md` per doc_parser README — extractor file kept for documentation only. Choose one path before v3.0 |
| `/Users/khashsarrafi/Projects/Apps/SpineDevelopment/build/kg/extractors/python.yaml` | Python AST → KG | KEEP | #27 | tree_sitter_python | P0 | |
| `/Users/khashsarrafi/Projects/Apps/SpineDevelopment/build/kg/extractors/typescript.yaml` | TS/JS/TSX/JSX AST → KG | KEEP | #27 | tree_sitter_typescript, tree_sitter_javascript | P0 | |
| `/Users/khashsarrafi/Projects/Apps/SpineDevelopment/build/kg/extractors/README.md` | Extractor authoring guide | KEEP | n/a | none | P2 | V1 language set lists go/rust/sql as backlog; add iac/terraform/k8s/dockerfile to the planned list per #11/W2 |
| `/Users/khashsarrafi/Projects/Apps/SpineDevelopment/build/kg/doc_parser/__init__.py` | Package marker | KEEP | #27 | submodules | P1 | |
| `/Users/khashsarrafi/Projects/Apps/SpineDevelopment/build/kg/doc_parser/cli.py` | `spine doc-parse` CLI | KEEP | #27, #33A | parsers, resolver | P1 | Solid CLI surface. Eventual merge with `kg-index` CLI is a future cleanup |
| `/Users/khashsarrafi/Projects/Apps/SpineDevelopment/build/kg/doc_parser/markdown_parser.py` | Generic markdown → ParsedDoc | KEEP | #27 (docs as graph nodes) | spine_id_resolver | P1 | Regex-driven, no tree-sitter — fine for the heading-and-link layer. Overlaps `extractors/markdown.yaml`; one needs to be canonical |
| `/Users/khashsarrafi/Projects/Apps/SpineDevelopment/build/kg/doc_parser/role_prompt_parser.py` | Role prompts + memory.md → Role/Constraint/MemoryLesson | REFACTOR | #7 (industry-standard charters), #8 (two-tier hierarchy), #11 (devops role) | markdown_parser, spine_id_resolver | P1 | The Role+Constraint nodes will need a `tier` property per #8 (two-tier role hierarchy) and a `subsystem` property per #11 (8 control planes). Also needs to handle the new `devops` role automatically (it already does — role-agnostic walker) |
| `/Users/khashsarrafi/Projects/Apps/SpineDevelopment/build/kg/doc_parser/spine_doc_parser.py` | REQ/PRD/TRD/ROADMAP/ADR/CHANGELOG parsers | REFACTOR | #19 (7 work-item types), #24 (compliance scaffold) | markdown_parser, spine_id_resolver | P1 | Roadmap bullet parser handles STORY/EPIC/INIT only; per #19 needs `BUG-`, `INCIDENT-`, `SUPPORT-`, `REFACTOR-`, `INFRA-`, `COMPLIANCE-` ID prefixes. Add a `parse_compliance` for #24 scaffold (Vanta/Drata-shape control docs) |
| `/Users/khashsarrafi/Projects/Apps/SpineDevelopment/build/kg/doc_parser/spine_id_resolver.py` | Spine-ID regex + KG lookup | REFACTOR | #19 (more ID kinds) | psql | P1 | Add patterns for `BUG-N`, `INCIDENT-N`, `SUPPORT-N`, `REFACTOR-N`, `INFRA-N`, `COMPLIANCE-N`, `BUNDLE-N` (#23 feature flags), `HUB-N` (#3 federation) |
| `/Users/khashsarrafi/Projects/Apps/SpineDevelopment/build/kg/doc_parser/doc_parser_README.md` | Doc parser doc | KEEP | n/a | none | P2 | |
| `/Users/khashsarrafi/Projects/Apps/SpineDevelopment/build/kg/embeddings/__init__.py` | Package marker + public API | KEEP | #2 (LLM-agnostic embedding too), #27 | embedder | P0 | |
| `/Users/khashsarrafi/Projects/Apps/SpineDevelopment/build/kg/embeddings/embedder.py` | Provider abstraction (local/anthropic/openai) + EmbedderRunner + cosine_search | REFACTOR | #2 (Bedrock/Vertex/Ollama/Qwen/vLLM) | sentence-transformers (lazy), anthropic (lazy), openai (lazy), psql | P0 | Per #2, providers needed: Bedrock, Vertex, Ollama, Qwen, in-house OSS via vLLM. Current 3-provider set is insufficient. Add `BedrockEmbeddingProvider`, `VertexEmbeddingProvider`, `OllamaEmbeddingProvider`, `OpenAICompatibleProvider` (covers vLLM/Qwen-served-OpenAI-API). Provider selection should consult org bundle + per-role override per #6 |
| `/Users/khashsarrafi/Projects/Apps/SpineDevelopment/build/kg/embeddings/embedder_README.md` | Embedder doc | REFACTOR | #2 | none | P1 | Expand provider table to all 6 categories per #2 |
| `/Users/khashsarrafi/Projects/Apps/SpineDevelopment/build/migration/__init__.py` | Package marker | KEEP | #33B (portability), #33C (version migrations) | none | P2 | |
| `/Users/khashsarrafi/Projects/Apps/SpineDevelopment/build/migration/migration_README.md` | Operational runbook | KEEP | #33B/C | none | P1 | Reframe: lib→build was a v2 internal move; v3 needs project-version-migration tooling per #33C |
| `/Users/khashsarrafi/Projects/Apps/SpineDevelopment/build/migration/migrate_inventory.md` | Authoritative move-list | KEEP→archive | #33C (becomes one of many version migrations) | none | P1 | This is the v2 migration. Promote to `build/migration/v2_to_v3/inventory.md` and keep it as an example for the version-migration framework |
| `/Users/khashsarrafi/Projects/Apps/SpineDevelopment/build/migration/migrate_daemons.sh` | Phased lib→build mover | KEEP→generalize | #33C | git, tar | P1 | The 6-phase pattern (preparation, move, refs, shim, verify, rollback) is exactly the right shape for a generic version-migration framework per #33C. Refactor into a generic `version_migration.sh` that takes an inventory.md as input |
| `/Users/khashsarrafi/Projects/Apps/SpineDevelopment/build/migration/compat_shim.sh` | Legacy symlink installer | KEEP | #33C (every version migration needs shim option) | none | P2 | Generic enough to keep |
| `/Users/khashsarrafi/Projects/Apps/SpineDevelopment/build/migration/update_protocol_refs.sh` | sed-edit doc/test references | KEEP | #33C | sed | P2 | Generic enough — could be parameterized for any path-rewrite migration |

#### BUILD-NEW files needed

| Proposed path | Purpose | Decision drivers | Depends on | Priority |
|---|---|---|---|---|
| `build/runtime/agent_wrappers/__init__.py` | Package for thin coding-agent wrappers | #13 | none | P0 |
| `build/runtime/agent_wrappers/_base.py` | Abstract `CodingAgentWrapper` protocol — `dispatch(directive) → BuildArtifact` | #13 (agent-agnostic interface) | shared schemas | P0 |
| `build/runtime/agent_wrappers/claude_code.py` | Thin wrapper invoking Claude Code with directive, parsing its output into BuildArtifact | #13 | _base, BuildArtifact, KG hooks | P0 |
| `build/runtime/agent_wrappers/cursor.py` | Cursor agent wrapper | #13 | _base | P1 |
| `build/runtime/agent_wrappers/aider.py` | Aider wrapper | #13 | _base | P1 |
| `build/runtime/agent_wrappers/openhands.py` | OpenHands wrapper | #13 | _base | P1 |
| `build/runtime/agent_wrappers/spine_engineer.py` | Wrapper around Spine's own engineer daemon (for tier-low autonomous mode) | #13, #8 (two-tier hierarchy) | _base, existing engineer daemon | P0 |
| `build/runtime/agent_selector.py` | Resolve which wrapper to use per (project bundle config, role tier, work-item type) | #6 (per-user/decision-class preferences), #8 (tier), #13 | agent_wrappers, bundle config | P0 |
| `build/runtime/devops_runtime.py` | Devops-role hooks (provision/destroy IaC, blast-radius checks, approval routing) | #11 (new devops role, INIT-10) | kg_caller, BuildArtifact | P0 |
| `build/kg/extractors/iac/_iac_schema.yaml` | Shared IaC extractor conventions (Component/Resource/Policy types) | #11/W2 infra-KG | _schema.yaml | P0 |
| `build/kg/extractors/iac/terraform.yaml` | Terraform `.tf` AST → KG (Resource/Module/Provider nodes; DEPENDS_ON edges) | #11/W2, #20 (5-cloud breadth) | tree_sitter_hcl | P0 |
| `build/kg/extractors/iac/terraform_state.py` | Terraform state JSON → KG (post-apply reality vs declared) | #11 (devops needs actual state) | psql | P1 |
| `build/kg/extractors/iac/k8s.yaml` | K8s YAML/Helm manifest → KG (Deployment/Service/NetworkPolicy nodes) | #11/W2 | tree_sitter_yaml | P0 |
| `build/kg/extractors/iac/dockerfile.yaml` | Dockerfile → KG (BaseImage/Layer/EntryPoint nodes; BUILDS_FROM edges) | #11/W2 | tree_sitter_dockerfile | P0 |
| `build/kg/extractors/iac/github_actions.yaml` | `.github/workflows/*.yml` → KG (Workflow/Job/Step + USES edges) | #11 (CI as infra) | tree_sitter_yaml | P1 |
| `build/kg/extractors/iac/iam_policy.yaml` | AWS/Azure/GCP IAM policy JSON/YAML → KG (Principal/Action/Resource + GRANTS edges) | #11/W2, #20 | tree_sitter_json/yaml | P1 |
| `build/kg/extractors/go.yaml` | Go tree-sitter extractor | #19 (refactor/infra work-item types likely Go in infra) | tree_sitter_go | P1 |
| `build/kg/extractors/rust.yaml` | Rust tree-sitter extractor | #19 | tree_sitter_rust | P2 |
| `build/kg/extractors/sql.yaml` | SQL tree-sitter extractor (table/view/migration tracking) | #11 (DDL is infra) | tree_sitter_sql | P1 |
| `build/kg/importer/__init__.py` | "Import existing codebase" onramp per #33A | #33A | indexer, doc_parser | P0 |
| `build/kg/importer/codebase_importer.py` | One-shot import-existing-repo: detect stack, install extractors, run cold-start, classify roles | #33A (onboarding scaffold) | indexer, language detection | P0 |
| `build/kg/importer/legacy_doc_importer.py` | Best-effort PRD/architecture-doc import from unstructured markdown | #33A | doc_parser | P1 |
| `build/kg/embeddings/providers/bedrock.py` | AWS Bedrock embedding provider | #2 | boto3 (lazy) | P1 |
| `build/kg/embeddings/providers/vertex.py` | GCP Vertex embedding provider | #2 | google-cloud-aiplatform (lazy) | P1 |
| `build/kg/embeddings/providers/ollama.py` | Ollama local-LLM embedding provider | #2 | httpx (lazy) | P1 |
| `build/kg/embeddings/providers/openai_compatible.py` | Covers vLLM/Qwen-served-via-OpenAI-API | #2 | openai SDK | P1 |
| `build/runtime/bundle_loader.py` | Resolve org-bundle config (#10) for build-side decisions (agent choice, embedding provider, KG redactors) | #10 (federation), #23 (feature-flag licensing) | yaml, bundle dir | P0 |
| `build/runtime/feature_flags.py` | Day-1 feature-flag licensing surface (gate per-feature on bundle entitlement) | #23 | bundle_loader | P0 |
| `build/runtime/work_item_router.py` | Route directives by work-item-type → squad composition (feature vs bug vs incident vs support vs refactor vs infra vs compliance) | #19 | bundle, agent_selector | P1 |
| `build/migration/version_migration.sh` | Generic phased version-migration runner (parameterized by inventory.md) | #33C | tar, git | P1 |
| `build/migration/codebase_onboarding.sh` | One-shot script for #33A: install Spine into existing repo + run importer | #33A | importer, indexer | P0 |
| `build/migration/portability/export.py` | Export project state (audit log, KG, artifacts) for #33B portability | #33B (BUILD properly) | psql, KG | P1 |
| `build/migration/portability/import.py` | Import previously exported project into a new Spine instance | #33B | psql, KG | P1 |
| `build/runtime/cite_or_refuse.py` | Verify-class enforcement helper invoked by hooks before sealing | #12 | shared.audit, BuildArtifact | P1 |
| `build/tests/` directory | Unit tests for everything in build/ — currently NO tests exist under build/ | (all decisions) | pytest | P0 |

#### Summary

- **Files reviewed:** 42 (excluding `__pycache__` bytecode)
- **Markings tally:** KEEP 22, REFACTOR 11, REFACTOR→DELETE 2 (bridge dispatcher + collector), KEEP→generalize 2 (migration scripts), DELETE 1 (pycache), REBUILD 0, BUILD-NEW 31 proposed
- **Biggest themes:**
  - **KG indexer is the load-bearing P0 fix.** Per Decision #27 Smart Spine, every learning tier depends on the KG being populated. The code in `build/kg/indexer/` is well-built — current 0-nodes audit is a *wiring* problem (DATABASE_URL precedence, post-commit hook install, cold-start invocation), not a code problem. Fix the wiring before adding new extractors.
  - **build_dispatcher.py is exemplary for Decision #13.** Its docstring explicitly says "We are NOT spawning Claude Code or running engineer daemons here. Spine plans, an external party (human or LLM) builds, Spine ingests + verifies — that handoff is the BuildArtifact." That IS the v3 model. Everything new in `runtime/` should preserve that contract.
  - **Bridge is tactical not strategic.** `build/bridge/` was designed to wrap v1 bash daemons. Per Decision #13, those daemons are largely superseded by external-coding-agent wrappers. Keep through one release for legacy installs; plan retirement at v3.1.
  - **Infra-KG is the biggest new surface.** Decision #11's `devops` role needs Terraform/K8s/Dockerfile/IAM/GitHub-Actions extractors — all expressible in the existing YAML extractor format with no parser_runtime changes. Five new YAML extractor files cover ~80% of v1 IaC indexing per Decision #20's 5-cloud breadth.
  - **Embeddings are LLM-locked-in.** Per Decision #2 (LLM-agnostic), the current 3-provider (local/anthropic/openai) embedder is insufficient. Need Bedrock + Vertex + Ollama + OpenAI-compatible (covers vLLM/Qwen) — 4 new providers.
- **Biggest debts:**
  - **Zero tests under `build/`.** Tests live in `lib/tests/`, none under `build/`. P0 to address — every BUILD-NEW file proposed above needs test coverage from day 1.
  - **`role-prompts/*.md` path is hardcoded everywhere.** kg_caller, runtime_README, migration toolkit all reference `lib/role-prompts/*.md`. Once migration runs, these are stale.
  - **Work-item types beyond feature/SHOULD/MUST not modeled.** Decision #19 requires all 7 types; doc parser only recognizes STORY/EPIC/INIT, dispatcher only routes feature work.
  - **`_DEFAULT_SQUAD = (engineer, qa)` is hardcoded** in `build_dispatcher.py`. Decision #6 (flexible per-user preferences) + Decision #8 (two-tier hierarchy) demand bundle-driven squad composition.
  - **No `devops` role anywhere in build/.** Decision #11's INIT-10 Operate Subsystem needs first-class build/runtime support; today operator KG hook covers part of it but devops-specific impact-radius (blast-radius, IAM drift, cost delta) is missing.
- **Biggest wins:**
  - **`build_dispatcher.py` and `enrich_artifact.py` already encode the agent-agnostic v3 model.** No refactor needed for the core handoff.
  - **The YAML-driven extractor schema is org-bundle-friendly out of the box.** Decision #10 (federation/fractal Hub) and Decision #11 (new role/subsystem) can ship new extractors without touching Spine source.
  - **Migration toolkit is a reusable framework** for Decision #33C version migrations — the 6-phase pattern is exactly what every Spine-version-bump migration will need.
  - **diff_engine.py + supersede-pattern KG schema** give Decision #27's Smart Spine the point-in-time queries it needs cheaply; no rework needed.
  - **Embedding pipeline lazy-loads optional deps**, so adding 4 new providers won't bloat the base install.
- **Risks:**
  - Bridge retirement (Decision #13 implications) requires careful coordination with downstream consumers running `--pull-knowledge-only`. If they rely on the v1 file-bus, premature deletion breaks them. Recommend feature-flag the bridge per #23 and let bundles opt out.
  - Adding IaC extractors without first wiring the indexer (P0 fix above) means new YAML files won't actually index anything. Sequence: fix indexer wiring → IaC extractors → devops role hooks.
  - Decision #2's "LLM-agnostic" mandate may push the embedder package into LangChain territory (per the user's `spine_tech_stack_decisions.md` memory: "LangChain/LangGraph optional per-role only"). Hold the line: keep `build/kg/embeddings/` stdlib-and-direct-SDK; don't import LangChain into the build core.
  - Per Decision #18 (closed-source v1.0), the agent_wrappers package needs careful licensing review — wrapping Claude Code / Cursor / Aider may have terms-of-service implications; coordinate with whoever owns the bundle licensing model (#23).
  - The `build/kg/extractors/markdown.yaml` vs `build/kg/doc_parser/` duplication is unresolved. Doc parser README says "indexer routing switch is a follow-up" — that follow-up needs to land before v3.0 or the graph will have inconsistent markdown coverage.

---

## T4 — verify/

**Scope:** verify/ subsystem boundary (TRON subtree internals NOT in scope)
**Source:** `T4-verify.md` (extracted from `/private/tmp/.../tasks/<agent-id>.output`)

No license file in verify/ — also worth flagging. Now let me deliver the triage report.

---

### Triage Report — verify/ BOUNDARY (not TRON internals)

#### Existing files (BOUNDARY scope only)

| Path | Current purpose | Marking | Decision drivers | Depends on | Priority | Notes |
|---|---|---|---|---|---|---|
| `/Users/khashsarrafi/Projects/Apps/SpineDevelopment/verify/SUBSYSTEM_BOUNDARY.md` | Spine-side boundary doc; documents in-scope/out-of-scope, stack, standalone-deployability promise (G-8), TRON startup sequence, env vars, PYTHONPATH gotcha | REFACTOR | #11 (mentions Operate subsystem but doesn't reconcile it with TRON), #15 (NOT SaaS), #17 (4 deployment shapes — doc doesn't address which shapes include TRON), #18 (closed-source — no license note on the TRON subtree), #21 (ALL AI — silent on auto-Verify policy for autonomous engineer), #27 (Smart Spine — silent on Verify outputs being calibration-grade signal) | All other boundary files | P0 | Doc is well-written for the Phase-1 plumbing it describes, but it's an *integration manual*, not a boundary *contract*. Needs sections: (a) which deployment shapes bundle TRON, (b) optional vs required, (c) Smart Spine calibration sink, (d) federation of audit chains (#16), (e) vault-only secrets migration plan (#9), (f) license posture of the subtree under #18 |
| `/Users/khashsarrafi/Projects/Apps/SpineDevelopment/verify/.env` | Plaintext dev-only Postgres/Redis/MinIO/Grafana passwords for TRON's compose stack | REBUILD | #9 (vault-only secrets — direct violation), #15 (NOT SaaS — fine, but per-customer install means this template ships to enterprises), #17 (deployment shapes) | Spine vault wiring, `shared/secrets/` (which doesn't exist yet) | P0 | Even with the "dev only" comment, this file ships in-tree. Per #9 there is **no acceptable plaintext secret store**. Should be replaced with a vault-reference manifest (e.g., `verify/.env.vault.yaml` listing `tron/db/password` → vault path) plus a bootstrap helper that materializes a tmpfs-only `.env` at `compose up` time. The `verify/.env.example` already documents the keyvault paths TRON natively supports (`tron/db/password`, `tron/llm/anthropic-key`, etc.) — Spine just isn't wiring them. |
| `/Users/khashsarrafi/Projects/Apps/SpineDevelopment/verify/.env.example` | Documents every TRON env var + the vault-key-path convention TRON natively uses (`tron/db/password`, `tron/llm/anthropic-key`, etc.) | KEEP | #9 (this file is actually #9-compliant — it explicitly says "ONLY non-secret config", lists vault paths), #17 | TRON's hvac client | P2 | This is the *good* one. Per-deployment-shape variants may be needed (e.g., `verify/.env.example.standalone` vs `verify/.env.example.spine-managed`) — see open questions. |
| `/Users/khashsarrafi/Projects/Apps/SpineDevelopment/verify/docker-compose.yml` | TRON's full 16-service prod stack (postgres, pgbouncer, redis, minio, temporal, temporal-ui, tron-api, tron-worker, tron-sandbox, nginx, otel-collector, prometheus, grafana, tempo, loki, tron-backup, alertmanager) | KEEP | #15 (NOT SaaS — this *is* per-customer infra), #17 (deployment shape #?), G-8 standalone | TRON subtree | P2 | Owned by TRON's lifecycle (subtree-merged). Spine MUST NOT edit this. It's the canonical standalone-TRON deployment. |
| `/Users/khashsarrafi/Projects/Apps/SpineDevelopment/verify/docker-compose.override.yml` | Spine overlay: renames containers to `spine_tron_*`, remaps postgres host port to 33010 | REFACTOR | #15, #17, G-8 (the rename does NOT break G-8 because base compose is unmodified, but the rename is a *Spine* concern — file location is wrong), #10 (federation — Spine port allocation 33xxx is hardcoded in TRON-owned directory) | docker compose, port allocation policy | P1 | Two problems: (1) it lives inside `verify/` (TRON's lifecycle) but is Spine-owned — when TRON's next subtree pull happens this could become awkward; (2) hardcoded `127.0.0.1:33010` and `spine_tron_*` names are Spine policy, not TRON's. Move to `orchestrator/deploy/verify-overlay/docker-compose.override.yml` and symlink, OR add a Spine-side wrapper command `spine verify up` that copies/templates an overlay outside the TRON tree. The file header is honest about it; the location isn't. |
| `/Users/khashsarrafi/Projects/Apps/SpineDevelopment/verify/docker-compose.dev.yml` | TRON dev compose | KEEP | G-8 | TRON | P2 | TRON's lifecycle |
| `/Users/khashsarrafi/Projects/Apps/SpineDevelopment/verify/docker-compose.prod.yml` | TRON prod compose | KEEP | G-8 | TRON | P2 | TRON's lifecycle |
| `/Users/khashsarrafi/Projects/Apps/SpineDevelopment/verify/Makefile` | TRON's `e2e`, `prod-static`, `prod-images`, `prod-up` targets | KEEP | G-8 | TRON | P2 | TRON-owned. Don't pollute with Spine targets. Spine targets belong in the umbrella `Makefile`. |
| `/Users/khashsarrafi/Projects/Apps/SpineDevelopment/verify/requirements.txt` | TRON's Python deps (~40 pkgs incl. FastAPI, SQLAlchemy, Temporal, OpenAI/Anthropic clients, semgrep, bandit, mcp[cli]==1.2.0, playwright, locust) | REFACTOR | #18 (closed-source — **need license audit on every transitive dep**; semgrep CE is LGPL-2.1, locust is MIT, playwright is Apache-2.0, hvac is Apache-2.0, sqlalchemy is MIT; but no license manifest exists), #15 (these deps ship per-customer) | TRON | P0 (licensing) / P2 (code) | The code is TRON-owned (KEEP), but Spine's closed-source legal posture (#18) demands a **SBOM + license inventory** for what we ship inside `verify/`. Add `verify/LICENSE-INVENTORY.md` (Spine-owned) at the boundary, regenerated by CI from `pip-licenses`. Several deps are pinned to old versions (e.g., `pydantic==2.10.6`, `httpx==0.27.2`, `mcp[cli]==1.2.0`) — version skew with shared/ Spine deps is a Phase-2 problem worth flagging. |
| `/Users/khashsarrafi/Projects/Apps/SpineDevelopment/verify/requirements-mcp.txt` | One-line alias to requirements.txt (deprecated, kept for back-compat) | KEEP | — | — | P2 | Harmless. |
| `/Users/khashsarrafi/Projects/Apps/SpineDevelopment/shared/mcp/tools/verify.py` | Spine's MCP wrapper for TRON's `AuditManager.run_audit`. Schemas: `VerifyAuditInput`/`VerifyFindings`. Loads file contents, registers six ISO agents in-process, maps `FindingOutput` → Spine `Finding`, writes audit rows (summary + per-finding), enforces sealed-artifact gate, degraded mode when Docker unavailable | REFACTOR | #12 (Cite-or-Refuse — **NOT enforced**: findings don't carry citations; mapping drops standards-pack-id references TRON may have surfaced), #21 (ALL AI — wrapper is fine for invocation, but no callback for the autonomous engineer to consume verdicts), #27 (Smart Spine — **no calibration capture**: `calibration_band` is pulled from `audit_result` but never persisted to the calibration outcomes table; cross-LLM consensus signal also dropped onto the floor), #16 (no chain link from this audit to upstream BuildArtifact's audit_id beyond a `subject_id` string) | `verify.tron.agents.manager.AuditManager`, `shared.audit.audit_record.AuditRecord`, `shared.cost.router` | P0 | The wrapper is **structurally complete** but **semantically thin** for the v2 design decisions. Specifically: (a) add a `calibration_outcome` writer that lands every audit's `(finding_id, calibrated_confidence, cross_llm_consensus, calibration_band, ground_truth_label_pending)` into a `spine_smart.calibration_outcomes` table per #27; (b) add Cite-or-Refuse enforcement — when TRON returns a `policy_id`/`standard_id` reference, propagate it into the Spine `Finding.layers_vouched` *with* an explicit citation field, and refuse findings that lack one when the project's bundle says citations are required; (c) wire `correlation_id` to the BuildArtifact's audit_id rather than ad-hoc `subject_id`; (d) the in-process ISO registration ignores org-level ISO selection from the bundle (always registers all six). |
| `/Users/khashsarrafi/Projects/Apps/SpineDevelopment/shared/mcp/tools/iso.py` | Six per-agent + one core `iso_invoke` MCP tools for early-detect from Build. Cost attribution split (`pre_verify` charges Build, `verify_phase` charges Verify) | REFACTOR | #12 (same Cite-or-Refuse gap as `verify.py` — findings don't carry standards-pack citations), #13 (engineer hybrid by tier — **good**: this is the exact tool an autonomous engineer would use to self-verify before sealing), #21 (ALL AI), #27 (Smart Spine — same calibration capture gap; each iso_invoke is a learning signal lost) | TRON ISO agent classes | P0 | The cost attribution split is excellent design — keep it. The wrapper duplicates `_tron_secrets_from_env`, `_run_async`, `_map_tron_finding`, `_load_*` from `verify.py` (acknowledged in comments to avoid circular imports). REFACTOR target: extract a `shared/mcp/tools/_tron_bridge.py` private helper so the two wrappers share code, then add the Cite-or-Refuse + calibration-capture hooks **once**. Also: `Blueprint`, `CodeRegion`, `Finding` should be promoted to `shared/schemas/verify/` per the file's own TODO. |
| `/Users/khashsarrafi/Projects/Apps/SpineDevelopment/shared/mcp/tools/auditor.py` | Pre-Verify hook (`verify_build_artifact`): schema re-validation → optional path scope → KG-impact diff against `impact_radius` per changed file. Returns `Verdict`. Cheap (no LLM tokens). | KEEP | #12 (this **is** a Cite-or-Refuse-style gate in spirit — it enforces that the engineer's self-claimed kg_impact citation matches reality), #13 (autonomous engineer's contract gate), #21 (ALL AI — gate is purely deterministic, runs before any TRON spend) | `shared.mcp.tools.kg.impact_radius`, `BuildArtifact`, `AuditRecord` | P1 | Genuinely well-designed. The only nit at the boundary: when verdict ≠ `approved`, the `remediation_directive` is text, not a structured directive — for an autonomous engineer loop (#13) we may want a typed `RemediationDirective` so the engineer daemon doesn't have to parse markdown to act on it. Otherwise leave alone. |
| `/Users/khashsarrafi/Projects/Apps/SpineDevelopment/verify/tron/**` | All TRON-internal code (agents/, verification/, sandbox/, workflows/, api/, schemas/, services/, standards/, mcp/, memory/, parsers/, infra/, realtime/) | KEEP (out-of-scope) | — | — | — | TRON's own lifecycle. Per scope instructions, not audited. |
| `/Users/khashsarrafi/Projects/Apps/SpineDevelopment/verify/{admin-ui,frontend,alembic,config,docker,docs,scripts,tests,AGENTS.md,README.md,trivy.yaml,.cursor,.dockerignore,.gitignore,.trivyignore,alembic.ini,pyproject.toml}` | TRON internals (UI, migrations, configs, tests, project docs) | KEEP (out-of-scope) | — | — | — | TRON's own lifecycle. |

#### BUILD-NEW files needed at the boundary

| Proposed path | Purpose | Decision drivers | Priority |
|---|---|---|---|
| `/Users/khashsarrafi/Projects/Apps/SpineDevelopment/verify/SPINE_SECRETS_MAP.yaml` (Spine-owned, in verify/) | Mapping of TRON env vars → Spine vault paths. Replaces `verify/.env` as the source of truth. A Spine helper (`spine verify secrets bootstrap`) materializes a tmpfs `.env` at `compose up` time from vault | #9 vault-only | P0 |
| `/Users/khashsarrafi/Projects/Apps/SpineDevelopment/orchestrator/deploy/verify-overlay/docker-compose.override.yml` (NEW location) | Same content as today's `verify/docker-compose.override.yml`, but **outside** the TRON subtree so subtree pulls don't conflict. Spine wrapper (`spine verify up`) symlinks/copies it into verify/ at runtime | #10 standalone-deployability, #16 update distribution | P0 |
| `/Users/khashsarrafi/Projects/Apps/SpineDevelopment/verify/LICENSE-INVENTORY.md` (Spine-owned, in verify/) | Generated SBOM + license manifest for everything TRON ships. Reviewed legally for #18 closed-source compliance. CI-regenerated on each TRON subtree pull | #18 closed-source v1.0 | P0 |
| `/Users/khashsarrafi/Projects/Apps/SpineDevelopment/shared/mcp/tools/_tron_bridge.py` | Shared helpers for `verify.py` + `iso.py`: `_tron_secrets_from_env`, `_run_async`, `_map_tron_finding`, `_load_file_contents`, `_build_iso_agent`. De-dupes today's intentional copy-paste | — (code hygiene; unblocks #12 + #27 wiring in one place) | P1 |
| `/Users/khashsarrafi/Projects/Apps/SpineDevelopment/shared/smart_spine/calibration_sink.py` | The Smart Spine learning hook. Called by `verify.py` and `iso.py` after every audit/invoke. Writes one row per `(finding, calibrated_confidence, cross_llm_consensus, calibration_band, ground_truth_label?)` into `spine_smart.calibration_outcomes`. Cross-LLM consensus + Platt-band become tier-3 learning signal | #27 Smart Spine 3-tier | P0 |
| `/Users/khashsarrafi/Projects/Apps/SpineDevelopment/shared/mcp/tools/_cite_or_refuse.py` | Citation enforcement helper. When the active bundle says verify-class roles must cite, every `Finding` returned by `verify.py`/`iso.py` is checked for a `citation_ref` (standards-pack ID, CWE ID, OWASP ID, etc.) and refused otherwise | #12 Cite-or-Refuse | P0 |
| `/Users/khashsarrafi/Projects/Apps/SpineDevelopment/verify/SPINE_DEPLOYMENT_MODES.md` (Spine-owned, in verify/) | Explicit matrix of the 4 deployment shapes (#17) × whether TRON is `required` / `bundled-default` / `optional` / `excluded`. Covers the question that's currently silent in SUBSYSTEM_BOUNDARY.md | #17, #15, G-8 | P1 |
| `/Users/khashsarrafi/Projects/Apps/SpineDevelopment/orchestrator/devops/` (directory placeholder) | Home of the new `devops` role (#11) which would own the relationship to TRON's ops-side outputs (audits, alerts, prometheus rules, grafana dashboards). Note: do NOT collapse this into TRON — TRON's ops surface is *its own* product surface; Spine's `devops` role observes + acts on it | #11 Operate 6th corner | P1 |
| `/Users/khashsarrafi/Projects/Apps/SpineDevelopment/verify/SPINE_AUDIT_CHAIN_LINK.md` | Boundary spec explaining how TRON's internal audit log (its own postgres-backed audit table, see TRON's docs) federates with Spine's main hash-chained audit. Decision needed: does Spine's audit chain include hashes of TRON's audit rows, or do we run two parallel chains and reconcile? | #16 update distribution federation, #24 compliance scaffold | P0 |
| `/Users/khashsarrafi/Projects/Apps/SpineDevelopment/verify/SPINE_VANTA_DRATA_ADAPTER.md` + scaffold under `shared/compliance/adapters/` | TRON's audit + sandbox + Platt-calibrated findings are the highest-quality evidence Spine can ship to Vanta/Drata. Spec the export contract at the boundary | #24 compliance scaffold | P1 |

#### Open questions for the Spine-TRON relationship

These are architecture-level questions the user/architect needs to answer; I'm surfacing rather than assuming.

1. **Bundle vs optional vs required.** Per #15 (NOT SaaS) and #17 (4 deployment shapes), is TRON: (a) always shipped with Spine? (b) selectable at install time? (c) required for some shapes (e.g., enterprise) and excluded for others (e.g., solo-vibecoder)? Today's `SUBSYSTEM_BOUNDARY.md` treats TRON as bundled-by-default but never says so explicitly. The install/distribution implications differ wildly (and the licensing scope under #18 differs with them).

2. **Secret-store migration timing.** Per #9 (vault-only), `verify/.env` is a violation today even with the "dev-only" comment. When does the cutover happen? Phase 1 lets it slide; Phase 2 must not. Who owns the vault-bootstrap helper? Does TRON's existing `hvac`-based keyvault count as the Spine vault, or are they two distinct vaults that need to federate?

3. **Standalone deployability vs Spine overlay placement.** `verify/docker-compose.override.yml` is the *cleanest* compose pattern (auto-merge), but it puts Spine-owned policy inside TRON's tree. When the next TRON subtree pull happens, what's the merge strategy? Should the overlay live under `orchestrator/deploy/` and be copied/symlinked into `verify/` at deploy time?

4. **Autonomous engineer's relationship to Verify.** Per #13 (engineer hybrid by tier) and #21 (ALL AI), should the autonomous engineer:
   - (a) **Self-verify** by calling `iso_invoke` mid-Build, iterate until clean, then seal? (current `iso.py` design supports this via `cost_attribution='pre_verify'`)
   - (b) Seal first, then wait for `verify_audit` to come back via the orchestrator?
   - (c) Both, with a tier gate (T1 autonomous engineers can self-verify; T0 must wait for human approval)?
   - The wrappers technically support all three; the *policy* is undecided.

5. **Smart Spine calibration sink.** Per #27, TRON's cross-LLM consensus + Platt-scaled confidence is **the** highest-signal training/calibration input the Spine has. Today `verify.py` extracts both but discards them. Spec needed: schema for `calibration_outcomes`, ground-truth label loop (human-labels-finding-as-true-positive-or-false-positive), retention policy, federation across customer instances (do we aggregate across orgs for the Spine-wide calibration, or strict per-org?).

6. **Audit-chain federation.** Per #16, Spine's hash-chained audit chain is the legal record. TRON has its own audit table (per TRON's docs). Do we:
   - (a) Treat TRON's audit table as Spine's primary and abandon the parallel chain? (probably wrong — Spine's audit chain pre-dates TRON integration and covers more than verify)
   - (b) Hash-link Spine's audit entries to TRON's audit row UUIDs? (current `verify.py` writes a Spine summary row + per-finding rows but doesn't reference TRON's own audit rows)
   - (c) Run them in parallel and reconcile in the compliance adapter? (most defensible; needs a spec)

7. **Cite-or-Refuse for verify-class outputs.** Per #12, verify-class roles must cite. TRON's `FindingOutput` carries `vulnerability_type` (e.g., CWE-ish) and `description`, but does TRON consistently emit a standards-pack ID (OWASP/CWE/CIS/etc.)? If not, we need a TRON-side feature request OR a Spine-side mapping table. Today's `_map_tron_finding` drops whatever standards reference exists and produces a `rule` field that's just the enum value.

8. **License posture under closed-source v1.0 (#18).** TRON ships ~40 Python deps. Some (semgrep CE = LGPL-2.1, certain Temporal client modules) have licenses Spine's legal posture must explicitly accept. No `LICENSE-INVENTORY.md` exists in `verify/`. Who owns the legal sign-off, and at what cadence does CI re-check on TRON subtree pulls?

9. **devops role (#11) vs TRON's operate-class outputs.** TRON ships Prometheus, Grafana, Loki, Tempo, Alertmanager, OpenTelemetry — that's an entire ops stack. Does Spine's new `devops` role:
   - (a) Drive *TRON's* ops stack as the operate substrate (Spine wraps; TRON provides)?
   - (b) Stand up a separate Spine-owned ops stack and only ingest TRON's audit findings as one input among many?
   - (c) Replace TRON's ops stack with a Spine-owned one and shrink the TRON subtree's compose?
   - The choice cascades into ~10 stories under INIT-10.

10. **Service subset for first integration vs Verify-at-scale.** Today only `postgres` is brought up from TRON's 16-service stack. For real production Verify (concurrent audits, Temporal-orchestrated workflows, sandbox isolation, MinIO artifact store), we need most of the stack. What's the trigger to bring up the rest? Cost? Customer deployment shape? An ops-readiness checklist?

#### Summary

- **Files reviewed (boundary only):** 13 files explicitly evaluated (+ TRON internals correctly marked KEEP-out-of-scope as a batch).
- **Markings tally:** KEEP 6 (4 TRON-owned out-of-scope + `verify/.env.example` + `verify/requirements-mcp.txt` + `auditor.py`), REFACTOR 5 (`SUBSYSTEM_BOUNDARY.md`, `docker-compose.override.yml`, `requirements.txt` for the license-inventory part, `verify.py`, `iso.py`), REBUILD 1 (`verify/.env`), BUILD-NEW 9, DELETE 0.
- **Biggest themes:**
  1. The boundary wrappers are **structurally complete but semantically thin** w.r.t. v2 design decisions (#12 Cite-or-Refuse, #27 Smart Spine calibration). They successfully invoke TRON; they don't *learn from* TRON or *constrain* TRON in the ways the locked decisions require.
  2. **Spine-owned policy is leaking into the TRON subtree** (the override compose, the `.env`, the Spine port allocation). Subtree pulls will get awkward.
  3. **Vault-only (#9) is violated today** in `verify/.env` even with the "dev-only" comment.
  4. The **architectural relationship** between Spine and TRON (bundled? optional? required? federated audit? federated ops?) is **undecided** — Phase 1 punted on every one of these.
- **Biggest debts (boundary-level):** (a) No calibration sink wiring TRON output → Smart Spine (#27). (b) No Cite-or-Refuse enforcement on findings (#12). (c) `verify/.env` plaintext secrets (#9). (d) Spine overlay inside TRON tree (#10/G-8 hygiene). (e) No license inventory for closed-source posture (#18). (f) No spec for audit-chain federation (#16/#24).
- **Biggest wins:**
  1. `verify/SUBSYSTEM_BOUNDARY.md` is **genuinely excellent** integration documentation — the PYTHONPATH gotcha, the service-subset rationale, the env-var table, the reproducible-restart recipe are model boundary-doc craft. Only its *content scope* (architectural decisions) is incomplete; its writing is exemplary.
  2. `shared/mcp/tools/auditor.py` (`verify_build_artifact`) is a **first-class** pre-Verify gate — cheap, deterministic, well-tested in design, and exactly the kind of mechanical contract enforcement the autonomous engineer (#13) needs.
  3. `iso.py`'s **cost-attribution split** (`pre_verify` charges Build, `verify_phase` charges Verify) is a small but important design call that prevents double-billing while preserving early-detect — keep it.
  4. The **degraded-mode design** in `verify.py` (Docker probe at import → force `sandbox_layer=False`) is appropriately defensive for the "TRON optional" deployment shape (whichever we choose).
  5. **G-8 standalone deployability** has been correctly preserved — base `docker-compose.yml` and `Makefile` are unmodified, all Spine changes are overlays.
- **Risks:**
  1. **Subtree-pull conflicts** on the next TRON update because Spine policy lives inside the TRON tree (override compose, `.env`).
  2. **Calibration data loss** every audit that runs without the Smart Spine sink wired (#27) — and we're already shipping the wrappers.
  3. **Compliance/legal risk** from no license inventory on a closed-source product shipping 40+ TRON-transitive deps (#18, #24).
  4. **Architectural ambiguity** on the 10 open questions above will create rework when v2 contracts solidify — every wrapper currently assumes "bundled, optional later" without saying so.
  5. **Cite-or-Refuse silently un-enforced** on TRON outputs means verify-class roles in Spine produce findings that wouldn't survive the contract — a discoverability bomb when a downstream role (qa, product, operator) starts consuming them under #12.

---

## T5 — orchestrator/ + lib/

**Scope:** orchestrator/{lib,bin,state} + lib/* (v1-era daemon system + role-prompts)
**Source:** `T5-orch.md` (extracted from `/private/tmp/.../tasks/<agent-id>.output`)

I have enough context now to produce the triage report. Let me write it up.

### Triage Report — orchestrator/ + lib/ subsystems

#### orchestrator/ — existing files

| Path | Current purpose | Marking | Decision drivers | Depends on | Priority | Notes |
|---|---|---|---|---|---|---|
| `orchestrator/README.md` | Boundary doc for orchestrator scaffold | REFACTOR | #3, #11, #19 | — | P1 | Out-of-date with v3: claims "Phase 0, awaiting Sprint 1" but lib/ is now substantial. Re-describe as power-user CLI shell over MCP, federation-aware, 7 pipelines, Hub front door. |
| `orchestrator/bin/spine` | Bash CLI: project new/status/approve/reject/rollback/list/intake/build/doctor | KEEP+REFACTOR | #3, #4, #11, #19 | `_env_loader.sh`, MCP transports, `spine_lifecycle` schema | P1 | Architecture is sound — thin wrapper over MCP, multi-transport (stdio/in-process/HTTP). Demote to power-user surface per #3; Hub web UI is the primary. Add commands for federation (`spine federation join/list`), devops phase (`spine ops dispatch`), per-work-item-type intake (`spine project new --type bug|incident|...`). Doctor checks need extension for Vault (#9), Keycloak (#25), federation health (#10). |
| `orchestrator/bin/README.md` | CLI reference doc | REFACTOR | #3 | bin/spine | P2 | Reposition as power-user reference; mention Hub for primary use. |
| `orchestrator/state/phases.yaml` | Canonical 10-phase SDLC pipeline + verify_config + retry policies | REFACTOR | #11, #19, #12 | transition.sh, gate.sh, verify_dispatcher.sh | **P0** | Single-pipeline assumption is the biggest v3 gap. Per #11, need new phases `deploying`/`operating`/`incident_open` plus operate-corner edges. Per #19, this needs to become 7 work-item-type variants (or one parameterized pipeline keyed by `project_type`). Per #12, verify_config needs `cite_or_refuse: true`. Current verify_config block is the right shape; expand it. |
| `orchestrator/state/multi_approver_examples.yaml` | Reference snippets for `multi_approver` gate | KEEP | #7, #8, #24 | gate.sh | P2 | Already supports `role:`/`user:`/`group:` principals — aligns with #8 two-tier hierarchy. Add examples for #24 compliance gates (Compliance Officer + Security Engineer signing release), #11 devops gates. |
| `orchestrator/state/README.md` | State dir doc | REFACTOR | #19 | — | P2 | Document the per-work-item-type pipeline layout when introduced. |
| `orchestrator/lib/_env_loader.sh` | Shared Postgres connection-string loader | REFACTOR | #9, #25 | — | P1 | Reads `db/.env` with plaintext POSTGRES_PASSWORD — directly violates #9 (vault-only, no env, no plain-text). Must be rewired to fetch credentials from Vault (Vault DB secret engine, dynamic creds preferred). Keep the precedence model but swap source. |
| `orchestrator/lib/transition.sh` | State-machine engine: validate/gate-check/execute/rollback. Reads phases.yaml, writes spine_lifecycle | KEEP+REFACTOR | #4, #19, #27 | _env_loader.sh, approval.py, spine_lifecycle | **P0** | Core engine, well-architected (treats YAML as data, gate on BASH_SOURCE for safe sourcing, structured JSON errors). Refactors needed: (a) federation-aware — transitions involving cross-Hub authority need a federation handshake (#4/#10); (b) emit calibration outcome events per transition (#27 Smart Spine 3-tier learning needs every transition to feed back); (c) per-work-item-type manifest selection (#19). |
| `orchestrator/lib/transition_test.sh` | Smoke test for transition.sh | KEEP+REFACTOR | — | transition.sh, spine_lifecycle | P2 | Hardcoded `localhost:33000` but the runtime is `33001` (per `_env_loader.sh`). Test will SKIP rather than detect drift. Switch to `_env_loader.sh`. Extend to cover federation transitions and rollback paths. |
| `orchestrator/lib/gate.sh` | Phase-gate engine: status / approve / reject / request-changes / list-pending. STORY-1.4.6 multi-approver | KEEP+REFACTOR | #7, #8, #9, #12, #24 | transition.sh, router.sh, approval.py, _env_loader.sh | **P0** | Excellent core (principal patterns, dedup, atomic HMAC + transition). Refactors: (a) Vault Transit for HMAC keys (#9); (b) role principal lookup must integrate Keycloak group membership (#25); (c) add cite-or-refuse gate type for verify-class artifacts (#12); (d) communication preference hook on `gate_status` so AI scrum master can broadcast per-user/per-decision-class (#5/#6). |
| `orchestrator/lib/gate_README.md` | Gate engine reference | REFACTOR | #6, #7 | gate.sh | P2 | Document new gate types (cite_or_refuse, federation_handshake). |
| `orchestrator/lib/router.sh` | MCP dispatch chokepoint to plan/build/verify. Records route_history. Single-Hub | KEEP+REFACTOR | #4, #10, #11 | _env_loader.sh, MCP tools | **P0** | Sound single-Hub design. v3 needs: (a) `SPINE_MCP_TOOL[devops]=devops_dispatch` per #11 (new 6th corner role); (b) federation-aware routing — when a directive must run on a downstream Hub per #4/#10, route via federation client not local MCP; (c) `SPINE_MCP_TOOL` should be loaded from the work-item manifest (#19), not hardcoded for the 3 v2 subsystems. |
| `orchestrator/lib/router_README.md` | Router reference | REFACTOR | #4, #10, #11 | router.sh | P2 | Update for devops + federation routing. |
| `orchestrator/lib/approval.py` | HMAC-SHA256 signed phase-gate tokens; key at `~/.spine/secrets/hmac.key` mode 0600 | **REBUILD** | #9, #25 | psql, spine_lifecycle.approval | **P0** | **Direct violation of #9.** File-on-disk key, even mode 0600, is not vault-only. Per locked decision the key must live in Vault Transit (sign/verify operations happen inside Vault, key never leaves). Rebuild as `approval.py` that calls Vault's `transit/sign/<key>` and `transit/verify/<key>` endpoints. Also integrate Keycloak identity for `approver` (#25) instead of bare string. Header docs even call out "Non-goals: key rotation, per-approver asymmetric keypairs" — both are now P0 per #9/#25. |
| `orchestrator/lib/approval_README.md` | Approval reference | REFACTOR | #9, #25 | approval.py | P1 | Rewrite for Vault Transit. |
| `orchestrator/lib/verify_dispatcher.sh` | Loads verify_config from manifest, applies bundle overrides, dispatches `verify_audit` MCP, applies severity→transition rules | KEEP+REFACTOR | #12, #14, #24 | router.sh, transition.sh, remediation.sh, pipeline manifest, bundle | P1 | Right architecture (policy layer over MCP). Refactors: (a) #12 cite-or-refuse semantics — if a verify-class artifact lacks citations, force `on_critical` regardless of severity rollup; (b) #24 internal Evidence Store wiring — verify findings must land in Evidence Store rows; (c) #14 means verify needs to run for backlog of ALL three segments (managed-cloud, customer-cloud, on-prem) — config must select stricter ISO sets for regulated segments. |
| `orchestrator/lib/verify_dispatcher_README.md` | Verify dispatcher reference | REFACTOR | #12, #24 | verify_dispatcher.sh | P2 | Update for cite-or-refuse + Evidence Store. |
| `orchestrator/lib/remediation.sh` | Verify-fail → Build remediation loop, retry budget, findings summarizer | KEEP+REFACTOR | #11, #19, #27 | router.sh, transition.sh, _env_loader.sh | P1 | Solid policy layer with retry-budget audit-as-source-of-truth pattern. Refactors: (a) remediation target is hardcoded `build` — per #11 + #19, also needs `devops` (incident remediation) and per-work-item-type defaults (a `bug` work-item remediates differently than a `feature`); (b) #27 calibration — store remediation outcomes as training signal. |
| `orchestrator/lib/remediation_README.md` | Remediation reference | REFACTOR | #11, #19 | remediation.sh | P2 | Update for multi-target remediation. |
| `orchestrator/lib/build_failure_router.sh` | Build → Plan re-route engine with 4 enumed reasons (scope_unclear, etc.) | KEEP+REFACTOR | #5, #11, #19 | router.sh, transition.sh, _env_loader.sh | P1 | Mirror of remediation.sh for build-fail edge. Refactors: (a) per #5 the AI scrum master should be the first responder before re-routing to planner (some "scope_unclear" cases are clarifications the scrum master can handle by asking the user); (b) #19 needs reason set per work-item-type (incidents have different blockers than features). |
| `orchestrator/lib/build_failure_router_README.md` | Reference | REFACTOR | #5, #19 | build_failure_router.sh | P2 | Update for new reasons. |
| `orchestrator/lib/portfolio.sh` | Multi-project capacity gating, queue, rollups, set-limit, blocked | KEEP+REFACTOR | #4, #10, #14 | router.sh, transition.sh, spine_recording.costs | P1 | Good design. Per-project limit pattern works. Refactors: (a) #4/#10 — portfolio should aggregate across federated Hubs; (b) per-segment quotas (#14): managed-cloud customers may have different concurrency limits than on-prem; (c) #23 feature-flag licensing should gate `max_parallel_directives` (license tier determines cap). |
| `orchestrator/lib/portfolio_README.md` | Reference | REFACTOR | #4, #23 | portfolio.sh | P2 | Update for federation + licensing. |
| `orchestrator/lib/rollback.sh` | Project-level rollback orchestration: preview, rollback (with rationale + capability + side-effect cleanup) | KEEP | #8, #31 | transition.sh, capability_checker.py, spine_lifecycle | P1 | Strong design (preview vs commit, ≥8 char rationale, capability check, side-effect cleanup in own TX). Light refactor: per #31 DR, rollback should be one of the recovery primitives; ensure preview JSON is consumable by Hub UI. |
| `orchestrator/lib/rollback_README.md` | Reference | KEEP | — | rollback.sh | P2 | |
| `orchestrator/lib/__pycache__/` | Python bytecode | DELETE | — | — | P2 | Should be in `.gitignore`. |

#### lib/ — existing files (v1-era daemon system)

##### Daemon orchestration core (file-bus model)

| Path | Current purpose | Marking | Decision drivers | Depends on | Priority | Notes |
|---|---|---|---|---|---|---|
| `lib/team-agent-daemon.sh` (1001 lines) | Per-role manager + worker daemon. Reads `directive.md` (markdown file-bus), invokes executor, writes `# Report`, manages workers, costs.csv, outbox.jsonl, scratch, locks | **REBUILD** | #1, #3, #13, #21 | roles.sh, costs-csv.sh, db-outbox.sh, usage-parsers.sh, executor.sh, file-lock.sh, engagement-hook.sh | **P0** | Architectural mismatch with v3. The "directives in markdown files watched by polling daemons" model worked for the v1 file-bus, but Hub web UI (#3) + MCP dispatch (orchestrator/lib/router.sh) is the canonical surface in v3. Per #21 "all AI all the time" the role process still needs to exist, but it should be a thin LangChain/LangGraph-style runner that pulls work from `spine_lifecycle.route_history` via MCP, not from a markdown file. Per #13 engineer becomes thin wrapper over Claude Code/Cursor/Aider/OpenHands — executor.sh is the right substrate but the surrounding daemon machinery is overbuilt. Keep the cost/usage parsing logic, the worker pool concept, and the file-lock; drop the markdown directive bus. |
| `lib/team.sh` (1087 lines) | Manager/worker spawner: `team.sh up/down/status/restart` | **REBUILD** | #3, #11, #1 | roles.sh, team-agent-daemon.sh, heartbeat.sh, watchdog.sh, updater.sh | **P0** | Same fate as the daemon. The right v3 replacement is process supervision via Hub's containerized PRODUCT (#3) — Docker/Kubernetes managing role workers, not a bash spawner. Some `team_pids_for` / status-rollup logic should move into the Hub backend as a status MCP tool. |
| `lib/roles.sh` | Canonical role ID list (13 roles) | REFACTOR | #7, #11 | — | **P0** | Cull-and-extend. Existing list mixes v1 admin roles (`memory`, `seer`) with SDLC roles. Per #11 add `devops` (6th corner, distinct from operator). Per W3/charter work add `customer_support`, `compliance_officer`, `security_engineer`, `tech_writer`, `release_manager`. Consider whether `seer` (observability) and `memory` (cross-session synthesis) survive as roles in v3 or get absorbed into Hub features. |
| `lib/team-clean.sh` | Cleanup scratch/logs/archive/all/nuclear for v1 file-bus footprint | DELETE | #3 | roles.sh | P2 | Cleanup logic specifically for the v1 file-bus layout (`teams/<role>/scratch`, `teams/<role>/log/*.log`, `teams/<role>/workers/archive`). When the bus dies, this dies. The 5MB log rotation + archive-keep ideas could be lifted into the v3 Hub's housekeeping job. |
| `lib/seer-tick.sh` | Periodic nudge writing refresh directive to `seer/directive.md` | DELETE | #3 | — | P2 | Pure file-bus glue. Status refresh in v3 is a Hub web UI cron + WebSocket push. |
| `lib/serve-dashboard.sh` | `python3 -m http.server` serving `lib/dashboard.html` statically | DELETE | #3 | dashboard.html | P2 | Per #3, Hub is a real containerized SPA, not a static page on port 61105. |
| `lib/dashboard.html` (1262 lines) | Static SPA-like dashboard with custom CSS, polls JSON files | DELETE / **REBUILD** as Hub | #3 | serve-dashboard.sh | **P0** | Direct conflict with #3. The Hub web UI is the v3 PRIMARY surface and must be a real SPA (React/Svelte/etc.) talking to Hub backend via REST + WebSocket + MCP. Salvage value: design tokens (CSS variables), layout patterns, polling cadence, and the chosen information architecture (panels for managers, workers, costs) are good UX research and should inform the new Hub. The HTML itself goes. |

##### Substrate / DR / observability (largely keepable)

| Path | Current purpose | Marking | Decision drivers | Depends on | Priority | Notes |
|---|---|---|---|---|---|---|
| `lib/watchdog.sh` | Supervises per-role manager daemons via heartbeat file mtime; restarts dead processes; supervises heartbeat + watcher | KEEP+REFACTOR | #31, #10 | roles.sh, team-agent-daemon.sh, heartbeat.sh, notify.sh | P1 | Substrate for #31 DR. The "PID file = live intent; missing PID = operator stopped" semantics are well-thought-through. v3 use: supervise containerized role workers (replace `pgrep` with container health checks); add federation peer health (#10). Could become a Hub backend service rather than a bash loop. |
| `lib/heartbeat.sh` | Background loop emitting `InstanceHeartbeat` events to outbox every 60s with vitals + channel; parent-PID watch for orphan safety | KEEP+REFACTOR | #31, #27 | db-outbox.sh, vitals.sh | P1 | Right concept for #31 DR (instance liveness signal). v3 refactor: emit to Hub via MCP/REST, not file-bus outbox. The vitals payload feeds Smart Spine learning (#27) — keep it rich. |
| `lib/vitals.sh` (439 lines) | Captures host CPU/mem/disk/load + Spine-attributed totals as one-line JSON; psutil-preferred with CLI fallbacks | KEEP | #27, #31 | — | P1 | Solid utility with good engineering (psutil-optional, hard deadline, "never crashes parent" contract, opt-in install). Per #27 vitals feed calibration. Per #31 vitals feed recovery decisions. Mostly portable to v3 as-is; just point output at the new event sink. |
| `lib/notify.sh` | Default notification dispatcher: macOS osascript + ntfy + Pushover + Slack + Discord + email | KEEP+REFACTOR | #5, #6 | — | P1 | Foundational substrate for #6 communication preferences. The multi-channel structure is exactly right. v3 refactor: (a) channels become PER-USER configurable via Hub UI per #6; (b) drive from a `communication_preferences` table not env vars; (c) #5 AI scrum master uses this as the outbound layer. Lives in `~/.spine-development/notify.sh` (user-customizable) — keep that escape hatch. |
| `lib/file-lock.sh` | Atomic symlink lock with PID+host encoding for stale-lock reaping | KEEP | — | — | P2 | Clean little utility. Useful for any v3 path that needs file-level coordination on a shared filesystem. Cross-host limitation is honest. |
| `lib/preflight.sh` | Host capability check (bash, jq, agent CLIs, platform) | KEEP+REFACTOR | #1, #17 | — | P2 | Right idea. Per #17 four deployment shapes (laptop + BYOC managed + customer-cloud + on-prem) need shape-aware preflight. Per #1 the laptop install is the only one needing this — managed/cloud shapes use the Hub's pre-baked container. |
| `lib/executor.sh` | Pluggable AI CLI dispatcher: cursor-agent/cursor/claude/aider/opencode/codex/generic | KEEP+REFACTOR | #13, #2 | — | **P0** | This IS the right substrate for #13 (engineer as thin wrapper over Claude Code/Cursor/Aider/OpenHands). Per #2 LLM-agnostic — already structured for it. Refactors: (a) explicitly add OpenHands per #13; (b) per #9 vault-only, API keys must come from Vault not env (currently relies on whatever the child CLI reads from environment); (c) per #21 the executor model needs a tier policy hook ("tier-low → autonomous, tier-high → human-with-AI"). |
| `lib/updater.sh` | Periodic puller for SpineDevelopment template via git fast-forward; modes off/pull/pull-pin from `spine_release` channel | KEEP+REFACTOR | #16, #18 | db-outbox.sh, git | P1 | Substrate for #16 federation update distribution. Refactors: instead of pulling the template repo via git, v3 fetches release tarballs from the federation tree (the parent Hub). Per #18 closed-source, the git-pull-from-public-template path is wrong — use authenticated artifact downloads. Channel concept (stable/beta/canary) is good, keep it. |
| `lib/usage-parsers.sh` (426 lines) | Extract tokens/cost/model from agent log per CLI (claude, cursor-agent, aider) | KEEP | #2, #13 | — | P1 | Reusable utility for cost tracking across LLM CLIs. Per #2/#13 just keep extending with new CLIs (OpenHands, opencode, codex). Embedded python3 parser is the right design (bash regex would be fragile). |
| `lib/costs-csv.sh` | One-time migration: add `outcome` column to legacy 8-col costs.csv | DELETE | — | — | P2 | One-shot migration helper for v1.4.3+ users. Migration target table is `spine_recording.costs`; CSV is being retired. Once v2/v3 ships the in-Postgres ledger as canonical, this is dead code. |
| `lib/db-outbox.sh` (490 lines) | JSONL outbox emitter: cost rows + lifecycle events appended atomically (flock/mkdir-as-mutex), drained by separate Python watcher | KEEP+REFACTOR | #4, #16, #27 | — | P1 | Excellent durability pattern (file-as-source-of-truth, watcher drains later). v3 use: still valuable for offline-tolerant operation (#16 federation update propagation, #27 Smart Spine event capture during network blips). Refactor: outbox should ALSO go to Hub's local event broker; the file becomes the "spool while offline" fallback. |

##### Engagement-flow / v1-specific overlays (largely doomed)

| Path | Current purpose | Marking | Decision drivers | Depends on | Priority | Notes |
|---|---|---|---|---|---|---|
| `lib/engagement-hook.sh` (349 lines) | Post-invocation hook parsing `## Spine-Hub:` markdown lines from directives into `EngagementStatusChanged` / `EngagementMessage` / `ArtifactCreated` events | DELETE | #3 | db-outbox.sh | **P0** | Pure file-bus glue — translates markdown comment lines into outbox events. v3 has proper MCP tools for status transitions, messages, artifacts. The PARSER pattern (extract structured data from agent output) might transfer to a different surface (Claude's tool calls vs markdown comments) but this specific bash script is obsolete. |
| `lib/spine-connect.sh` | Bootstrap on Machine B to join workspace to a remote Spine hub; resolves DB URL, starts watcher, runs `team.sh up` | **REBUILD** | #4, #10, #17 | run-standalone-watcher.sh, team.sh | P1 | The right *idea* for #4/#10 federation — register an instance with a Hub. v3 should rewrite as `spine federation join <hub-url>` that handshakes via Keycloak (#25) + receives a federation token, NOT a raw Postgres DSN. Current model leaks DB credentials to joining machines (violates #9 vault-only). |
| `lib/spine-disconnect.sh` | Companion to spine-connect | **REBUILD** | #4 | spine-connect.sh, team.sh | P1 | Rewrite as `spine federation leave`. |
| `lib/share-pg.sh` | Print copy-paste env block sharing Postgres DSN for a Machine B to connect | DELETE | #9 | db/.env | **P0** | Directly violates #9: prints `POSTGRES_PASSWORD` and binds DB to 0.0.0.0. v3 federation must use authenticated MCP/REST + Vault-issued tokens, never a shared DB password. |
| `lib/run-standalone-watcher.sh` | Run `db/watcher/spine_watcher.py` outside Docker pointing at remote Postgres | DELETE | #9, #3 | db/watcher/spine_watcher.py | P1 | Same problem — relies on shared DB credentials. Replace with federation client that posts to the parent Hub via MCP. |
| `lib/spine-migrate.py` (782 lines) | v1 → v2 migration: reads filesystem v1 layout, seeds SQLite `spine.db` with Team/Worker/Assignment/Directive/CostRow rows | KEEP (as historical) | #33 | sqlite3 | P2 | One-shot migration tool. #33 mandates BUILT version migrations — this is the v1→v2 instance. KEEP as the canonical example/template for future v2→v3 migration. Don't expect to run it again, but the pattern (idempotent, stable IDs from path+content hash, never modify source v1 layout) is reusable. |
| `lib/verify.sh` | Syntax+selftest runner: `bash -n` on *.sh, `py_compile` on *.py, `pglast` on migrations, exec `lib/tests/test-*.sh` | KEEP+REFACTOR | — | bash, python3, pglast | P2 | Good CI utility — orthogonal to v1/v2 split. Rename to `lib/syntax-check.sh` to avoid confusion with `verify/` subsystem (per #12) and `verify_dispatcher.sh`. Otherwise keep. |

##### Role prompts (`lib/role-prompts/*.md`) — characterized as a group

13 prompts total: `product` (front-door PRD via 5-move dialogue), `planner` (multi-specialist orchestration), `architect` (TRD/ADRs with KG citations), `conductor` (squad dispatch), `engineer` (code with KG impact_radius), `researcher` (read-only with KG-first), `ux`, `qa`, `auditor` (KG verification of engineer claims), `operator`, `datawright` (ML/data), `seer` (observability), `memory` (cross-session synthesis). Plus archived `_archived/engineering-{backend,frontend}.md`.

| Group | Current shape | Marking | Decision drivers | Priority | Notes |
|---|---|---|---|---|---|
| `lib/role-prompts/*.md` (13 files) | Markdown role prompts: "You may / You may NOT / Output shape / Tier hint / Memory / File hygiene / Engagement protocol" sections. Heavy file-bus references (`teams/<role>/directive.md`, `## Spine-Hub:`, `## Files touched`). | **REBUILD** | #7, #8, #11, #12, #13 | **P0** | Per #7 every prompt must be REWRITTEN as an industry-anchored role charter (Scrum Guide, PMBOK, SRE handbook, ITIL, NIST). Current prompts are great empirical playbooks but lack the framework anchors decision #7 demands. Per #8 two-tier hybrid authority (lead vs contributor flavors) needs to be expressed. Per #11 add NEW devops charter (SRE+ITIL anchor). Per #12 cite-or-refuse rules belong in verify-class charters (auditor, qa, researcher). Per #13 engineer charter needs tier-low (autonomous) vs tier-high (human-in-the-loop) bifurcation. The KG-citation discipline (in architect/engineer/researcher/auditor) is excellent and should survive — it's the practical instantiation of #12. |
| `lib/role-prompts/_archived/engineering-{backend,frontend}.md` | Retired v2 split | DELETE | — | P2 | Already archived; safe to remove once history is preserved in git. |
| `lib/role-prompts/memory.md`, `lib/role-prompts/seer.md` | v1 observability/memory roles | REBUILD or DELETE | #3, #27 | P1 | Per #3 + #27, "observability" and "memory" become Hub features (Smart Spine 3-tier learning, dashboard), not separate AI roles consuming tokens. Either delete both or refactor `memory` into a charter focused on knowledge graph curation. |
| **NEW** charters to author | `devops`, `customer_support`, `compliance_officer`, `security_engineer`, `tech_writer`, `release_manager` | BUILD-NEW | #11, #19, #24 | **P0** | See BUILD-NEW table. |
| `lib/playbook-defaults/{datawright,engineer,operator}.md` | Seeded "lessons learned" packs installed under `~/.spine-development/playbook/<role>/lessons.md` | KEEP+REFACTOR | #27 | P2 | Decent cross-project lesson seed pattern. Per #27 Smart Spine 3-tier learning, this becomes the seed corpus for the org-tier learning database. Keep, expand with the new roles' starter lessons. |

##### Tests (`lib/tests/test-*.sh`) — characterized as a group

| Group | Coverage | Marking | Priority | Notes |
|---|---|---|---|---|
| `lib/tests/test-{daemon-stub-smoke,engagement-{hook,approve},artifact-hook,instance-outbox,outbox-events,pid-files}.sh` | File-bus daemon + engagement + outbox tests | DELETE (after the substrate they cover dies) | P2 | These cover the v1 daemon architecture being retired. Recreate equivalents for the v3 model. |
| `lib/tests/test-{costs-migrate,roles-sh,updater-pin,usage-parsers,share-pg,vitals,lib-scripts-sync}.sh` | Cross-cutting utilities | KEEP+REFACTOR | P2 | These cover utilities marked KEEP above (vitals, usage-parsers, updater, roles, costs migrate). Keep, retarget at v3 surfaces. `test-share-pg` should be deleted when `share-pg.sh` is. `test-lib-scripts-sync.sh` (only 15 lines) probably enforces parity between `lib/` and installed `scripts/` — relevant only while two install paths exist. |

#### BUILD-NEW files needed

| Proposed path | Purpose | Decision drivers | Priority |
|---|---|---|---|
| `orchestrator/state/work_items/feature.yaml` | Pipeline shape for new features (current `phases.yaml` is roughly this) | #19 | **P0** |
| `orchestrator/state/work_items/bug.yaml` | Bug pipeline (skips intake, lighter planning, mandatory regression test gate) | #19 | **P0** |
| `orchestrator/state/work_items/incident.yaml` | Incident pipeline (fast-path to `incident_open` phase, post-incident retro) | #11, #19 | **P0** |
| `orchestrator/state/work_items/support.yaml` | Support ticket pipeline (customer_support lead, lightweight) | #14, #19 | P1 |
| `orchestrator/state/work_items/refactor.yaml` | Refactor pipeline (heavy verify, no acceptance phase) | #19 | P1 |
| `orchestrator/state/work_items/infra.yaml` | Infra change pipeline (devops lead, change-management gate) | #11, #19 | **P0** |
| `orchestrator/state/work_items/compliance.yaml` | Compliance work pipeline (compliance_officer lead, multi_approver gate, Evidence Store mandatory) | #19, #24 | P1 |
| `orchestrator/lib/federation.sh` | Hub-to-Hub registration, heartbeat, capability advertise/discover, cross-Hub directive dispatch via authenticated MCP | #4, #10 | **P0** |
| `orchestrator/lib/federation_client.py` | Token-based federation auth (Keycloak-issued JWT), parent/child Hub handshake, federation tree state | #4, #10, #25 | **P0** |
| `orchestrator/lib/devops_dispatcher.sh` | Mirror of `verify_dispatcher.sh` for devops phase: load deploy config, dispatch `devops_dispatch` MCP, apply deploy-outcome→transition rules | #11 | **P0** |
| `orchestrator/lib/incident_router.sh` | Mirror of `build_failure_router.sh` for `operate → incident_open` edge: triage by severity, page on-call, route to devops or engineer | #11 | P1 |
| `orchestrator/lib/license.sh` | Feature-flag enforcement: gate phases / role bundles / portfolio caps by license tier | #23 | **P0** |
| `orchestrator/lib/vault_client.py` | Vault Transit sign/verify wrapper (replaces approval.py's local key), Vault DB dynamic creds wrapper (replaces _env_loader.sh's plaintext) | #9 | **P0** |
| `orchestrator/lib/identity.py` | Keycloak group/role → principal-pattern resolver used by `gate.sh _match_principal` | #8, #25 | **P0** |
| `orchestrator/lib/comms_dispatcher.sh` | AI-scrum-master communication engine: reads per-user/per-decision-class prefs from `spine_comms.preferences`, dispatches via lib/notify.sh's multi-channel substrate | #5, #6 | **P0** |
| `orchestrator/lib/cite_or_refuse.py` | Verify-class artifact citation enforcer (rejects empty `citations` field) | #12 | P1 |
| `orchestrator/lib/evidence_store.py` | Insert verify findings, compliance attestations, approval rationales into `spine_evidence` schema | #24 | P1 |
| `orchestrator/lib/calibration_emitter.sh` | Smart Spine event sink — every transition/gate/dispatch emits a calibration outcome row | #27 | P1 |
| `orchestrator/state/phases.yaml` extensions: phases `deploying`, `operating`, `incident_open`; edges `released→deploying→operating`, `operating→incident_open→build_in_progress` | New 6th-corner phases | #11 | **P0** |
| `orchestrator/api/rest.py` | REST surface for Hub UI consumption (project CRUD, phase status, gate ops) | #3, #30 | **P0** |
| `orchestrator/api/mcp_server.py` | MCP surface (already partially in `shared/mcp/`); ensure orchestrator-owned tools are registered | #3, #30 | P1 |
| `orchestrator/lib/dr_snapshot.sh` | Snapshot/restore primitives for #31 DR | #31 | P1 |
| `orchestrator/lib/migration_runner.py` | Version migration framework (v2→v3, future v3→v4); generalises the `spine-migrate.py` pattern | #33 | P1 |
| `orchestrator/lib/onboarding.sh` | Onboarding scaffold per #33 (project intake → first PRD → first build) | #33 | P2 |
| `orchestrator/lib/portability_export.py` | Project export bundle for portability per #33 | #33 | P1 |

#### Summary

- **Files reviewed:** 79 (orchestrator: 24 — 11 code + 8 README + 2 state YAML + 1 CLI + 1 test + 1 _env_loader; lib: 55 — 24 sh/py/html + 16 role-prompts incl. 2 archived + 3 playbook-defaults + 14 tests + 1 tests/support dir noted)
- **Markings tally:**
  - orchestrator/: 1 DELETE (`__pycache__`), 2 KEEP, 16 REFACTOR (incl. KEEP+REFACTOR), 1 REBUILD (`approval.py`), 0 BUILD-NEW (covered separately)
  - lib/: 7 DELETE, 6 KEEP, 9 REFACTOR/KEEP+REFACTOR, 4 REBUILD, plus 13 role-prompts as group REBUILD and 14 tests as group cull/keep
- **BUILD-NEW counts:** 24 new orchestrator-side files identified across 8 themes (7 work-item pipelines, federation, devops, incidents, license, vault, identity, comms, cite-or-refuse, evidence, calibration, REST/MCP, DR, migration, onboarding, portability)

##### Biggest themes
1. **The v3 boundary cuts straight through `lib/`.** The transition.sh/gate.sh/router.sh family in `orchestrator/lib/` is the right architectural shape for v3. The `team-agent-daemon.sh`/`team.sh`/file-bus stack in `lib/` is the wrong shape. The cleanest mental model: **orchestrator/lib/ is keep-and-extend; lib/ is mostly cull**.
2. **Vault-only (#9) is violated in 5 places** that touch credentials: `approval.py` (HMAC key on disk), `_env_loader.sh` (DB password from `.env`), `share-pg.sh` (prints DB password), `run-standalone-watcher.sh` (uses shared DB DSN), `spine-connect.sh` (accepts raw DSN). All need Vault wiring before #18 closed-source v1.0 ships.
3. **Hub web UI (#3) replaces the entire `lib/dashboard.html` + `serve-dashboard.sh` + `seer-tick.sh` + `team-clean.sh` axis.** Don't refactor — rebuild as part of Hub.
4. **Federation (#4/#10) is structural, not bolt-on.** Every orchestrator script that talks to `spine_lifecycle` assumes a single Hub. `router.sh` is the natural insertion point; `portfolio.sh` is the second. New `federation.sh` + `federation_client.py` are P0.
5. **The 13 role prompts need full rewrite per #7** to anchor in Scrum/PMBOK/SRE/ITIL/NIST. The current prompts are excellent empirical playbooks (especially the KG-citation discipline in architect/engineer/auditor/researcher) and those bits transfer — but the framing must change. Plus 6 NEW charters per #11 + W3.

##### Biggest debts
- **~60% of `lib/` (by file count, ~70% by LOC) needs deletion or rebuild.** Concretely: `team-agent-daemon.sh` (1001 LOC), `team.sh` (1087), `dashboard.html` (1262), `engagement-hook.sh` (349), `team-clean.sh` (250), `seer-tick.sh`, `serve-dashboard.sh`, `share-pg.sh`, `run-standalone-watcher.sh`, `spine-connect.sh`/`disconnect.sh`. Plus 13 role prompts rewritten. That's ~5000 LOC of bash + 1262 LOC of HTML going to the chopping block.
- **`orchestrator/state/phases.yaml` is a single-pipeline + single-Hub assumption** baked into the foundation. The transition engine handles this gracefully (YAML-as-data), but until #19 (7 pipelines) lands as work-item-typed manifests and #11 (operate corner) is wired, every new project pretends to be a "feature" with a "release" terminus.
- **`approval.py` HMAC key on disk** is the most user-visible #9 violation — first thing any security audit will flag.
- **No federation primitives exist anywhere.** Decision #10 (Fractal Hub) is brand-new structure that the v2 architecture didn't anticipate.

##### Biggest wins (substrate already right for v3)
- `orchestrator/lib/{transition,gate,router,remediation,verify_dispatcher,build_failure_router,portfolio,rollback}.sh` — the policy-layer-over-MCP pattern, the YAML-as-data manifest, the JSON-error contracts, source-with-BASH_SOURCE-guard, and the multi-approver principal-pattern engine are all v3-ready. This is a high-quality v2 core.
- `lib/{vitals,heartbeat,watchdog,notify,executor,usage-parsers,file-lock,updater,db-outbox}.sh` — pure substrate that survives the v1→v3 cull. `executor.sh` in particular IS the right thing for #13 (thin wrapper over Claude Code/Cursor/Aider/OpenHands).
- `lib/spine-migrate.py` — the migration playbook that future v2→v3 (and v3→v4) migrations should mimic (idempotent, stable IDs, never modify source).
- `orchestrator/bin/spine` MCP-first transport precedence (stdio CLI → in-process Python → HTTP) is exactly the right shape for a power-user CLI; just demote per #3.

##### Risks
- **Cross-overlap between `orchestrator/lib/` and `lib/`.** `lib/team-agent-daemon.sh` already references `db-outbox`, `usage-parsers`, `costs-csv`, `engagement-hook`. If we rebuild the daemon but those siblings stay, the dependency wiring needs careful sequencing — don't delete `db-outbox.sh` before the new role-worker runtime is consuming a replacement.
- **Bash 3.2 / macOS portability assumptions** are everywhere in the orchestrator scripts (explicit `declare -A SPINE_MCP_TOOL=()`, IFS guards, `${arr[@]+...}` empty-array tricks). Worth preserving — laptop deployment shape (#17) means macOS support is permanent.
- **Approval-key migration is destructive.** Existing approval rows reference the on-disk HMAC key. Moving to Vault Transit requires either (a) re-signing all live approvals, (b) keeping a legacy verifier for already-issued tokens, or (c) accepting that all in-flight approvals are voided on upgrade. Per #33 (version migrations BUILT), this is the kind of migration the framework must handle gracefully.
- **Per-work-item-type pipelines** introduce a 7× explosion in pipeline manifests; the transition engine handles it (YAML-as-data) but operators need tooling to diff/lint/version per-type pipelines — otherwise drift will be invisible.
- **Closed-source (#18) + git-pull-from-template `updater.sh`** is a contradiction. The federation tree distribution model (#16) is the right replacement; until then, updates leak the template repo URL.

##### Specific recommendation: orchestrator/ vs lib/

**Subsume most of `lib/` into the v3 layout, keep `orchestrator/` as the lifecycle authority, but split substrate out.** Concretely:

1. **`orchestrator/`** remains the lifecycle + routing + gate + federation authority. Everything currently in `orchestrator/lib/` stays; new files (federation.sh, devops_dispatcher.sh, license.sh, vault_client.py, identity.py, comms_dispatcher.sh, cite_or_refuse.py, evidence_store.py) join there.

2. **Create `shared/runtime/`** (or `lib/runtime/`) for the v3 substrate that's neither orchestrator-specific nor subsystem-specific: `vitals.sh`, `heartbeat.sh`, `watchdog.sh`, `notify.sh`, `executor.sh`, `usage-parsers.sh`, `file-lock.sh`, `updater.sh`, `db-outbox.sh`. These are used by role workers, Hub backend, and orchestrator alike.

3. **Create `hub/` as the new top-level subsystem** for the containerized PRODUCT (#3). `lib/dashboard.html` does NOT migrate — Hub is a real SPA. `lib/serve-dashboard.sh` does NOT migrate — Hub has its own server.

4. **Retire `lib/` entirely** after the migration: `lib/team-agent-daemon.sh`, `lib/team.sh`, `lib/team-clean.sh`, `lib/seer-tick.sh`, `lib/serve-dashboard.sh`, `lib/dashboard.html`, `lib/engagement-hook.sh`, `lib/share-pg.sh`, `lib/spine-{connect,disconnect}.sh`, `lib/run-standalone-watcher.sh`, `lib/costs-csv.sh`, and all the v1-bus tests under `lib/tests/`. Move the keepers to `shared/runtime/`. The role-prompts directory moves to `shared/charters/` (or `shared/role-charters/`) and gets a full rewrite per #7.

5. **Replace `lib/role-prompts/` with `shared/charters/`** — industry-anchored, named per the v3 role set including the 6 new charters. The KG-citation discipline, file-hygiene contract, and tier-hint heuristics from today's prompts are the parts worth preserving.

The net result: a smaller, sharper v3 tree where `orchestrator/` owns lifecycle, `shared/runtime/` owns substrate, `hub/` owns the front door, and the v1 file-bus is fully gone.

---

## T6 — db/ + tools/ + docs/ + root

**Scope:** db/, tools/, docs/, recipes/, lite/, .planning/, top-level files
**Source:** `T6-docs.md` (extracted from `/private/tmp/.../tasks/<agent-id>.output`)

I have enough. Now I'll compose the triage report.

### Triage Report — db/ + tools/ + docs/ + root

#### db/ — existing

| Path | Current purpose | Marking | Decision drivers | Depends on | Priority | Notes |
|---|---|---|---|---|---|---|
| `db/docker-compose.yml` | Postgres + Flyway + watcher local compose | REFACTOR | #9, #15, #17, #25, #31 | docker, .env | P0 | Laptop-only; needs Vault sidecar, optional Keycloak, must work for all 4 deploy shapes (laptop / BYOC / cust-cloud / on-prem). Strip `.env` plaintext; pull creds from Vault. |
| `db/.env`, `db/.env.bak` | Plaintext dev credentials | DELETE | #9 | – | P0 | Vault-only secrets policy explicitly forbids plaintext env. Migration shim only. |
| `db/.env.example` | Template for `.env` | REBUILD | #9 | – | P1 | Replace with `vault-bootstrap.example.hcl` (or equivalent) documenting which Vault paths the stack reads. |
| `db/.gitignore` | Excludes `.env` and `pg-snapshot.json` | KEEP | – | – | P2 | Still useful for the new layout. |
| `db/Makefile` | Dev convenience targets (up/migrate/psql/snapshot/dashboard) | REFACTOR | #9, #15, #17, #25, #31 | docker-compose | P1 | Strip `.env` reads, add Vault wiring, add `make backup` / `make restore` (DR #31), wire optional Keycloak target. |
| `db/README.md` | DB how-to | REBUILD | #1–33 (most) | all of `db/` | P0 | Predates the 33 decisions; assumes Spine is "primarily file-based" and DB is "recording layer". v3 makes Postgres + Hub primary. |
| `db/PGVECTOR_NOTE.md` | Documents image swap to pgvector/pg16 | KEEP | #21, #27 (Smart Spine learning needs vectors) | – | P2 | Foundational; absorb into REBUILT README and delete. |
| `db/multi-schema-layout.md` | Schema ownership map | REFACTOR | #4, #8, #11, #23, #24 | flyway sql | P1 | Add new schemas for license (#23), Evidence Store (#24), federation registry (#4/#10/#16), devops (#11). |
| `db/migration-survey.md` | TRON Alembic→Flyway port plan | KEEP | #5 (TRON integrated), #33 | – | P2 | Historical record of V21 port — still useful, but stamp as "historical/closed". |
| `db/migrate-to-shared.sh` + `db/migrate-to-shared_README.md` | One-shot mover of `db/` → `shared/db/` | DELETE (after run) or KEEP-FROZEN | #15 | – | P2 | This is a STORY-8.3.3 helper. If `db/` will move to `shared/db/` in v3 — run it once, then delete. Otherwise freeze. |
| `db/flyway/conf/flyway.toml` | Flyway 10 connection config | KEEP | #33D | – | P2 | Foundational. |
| `db/flyway/sql/V1__init_core_schema.sql` | 19-table v1 recording (workers, tasks, assignments, costs, events) | KEEP | #5, #19, #27 | – | P0 | Core recording — still needed even if Hub becomes primary. Costs/events feed Smart Spine learning and the AI scrum master. |
| `db/flyway/sql/V2__spine_kg_schema.sql` | Knowledge Graph nodes/edges + pgvector | KEEP | #21, #27 | pgvector | P0 | Cross-cutting infra; needed for KG queries + Smart Spine learning. |
| `db/flyway/sql/V3__multi_host.sql` | host_id + instance_id on worker/assignment | KEEP | #10 (Fractal Hub federation), #17 | – | P1 | Foundational for multi-host; will be extended by federation registry. |
| `db/flyway/sql/V4__views.sql` | Read-side reporting views | KEEP | – | V1 | P1 | Cost/role rollups; reused by Hub UI. |
| `db/flyway/sql/V5__invocation_durations.sql` | Invocation duration analytics | KEEP | #5, #27 | V1 | P2 | Foundational. |
| `db/flyway/sql/V6__spine_instance.sql` | Instance registry / heartbeat | KEEP | #10, #17 | – | P1 | Federation needs instance discovery — extend not rebuild. |
| `db/flyway/sql/V7__engagement.sql` | First-class "engagement" entity | REFACTOR | #1, #19 | – | P1 | "Engagement" is essentially a v1 noun for "project"; map to v3 `spine_lifecycle.project` to avoid two parallel hierarchies. Either deprecate or rename. |
| `db/flyway/sql/V8__engagement_artifacts.sql` | Engagement artifact URIs | REFACTOR | same as V7 | V7 | P1 | Same consolidation; or fold into V14 lifecycle metadata. |
| `db/flyway/sql/V9__engagement_links.sql` | engagement_id FKs on cost_row + event | REFACTOR | same as V7 | V7 | P1 | Same consolidation. |
| `db/flyway/sql/V10__artifacts_index.sql` | Artifact tracking | KEEP | #19, #24 | V1 | P1 | Useful as evidence-store backing. |
| `db/flyway/sql/V11__tenant_scoping.sql` | tenant_id on hot tables | KEEP | #4, #14, #17 | V1 | P0 | Multi-tenancy is the baseline for Hub + BYOC + on-prem. |
| `db/flyway/sql/V12__spine_releases.sql` | Release channel data (stable/beta/canary) | KEEP | #16 (federation update tree) | – | P1 | Pillar 2 of v1 Hub — directly maps to the federation update distribution model. |
| `db/flyway/sql/V13__machine_vitals.sql` | Per-host vitals | KEEP | #10, #27 | V6 | P2 | Useful for fleet ops + Smart Spine. |
| `db/flyway/sql/V14__spine_lifecycle_schema.sql` | Project / phase_history / transition / approval | KEEP | #1, #19, #22 | – | P0 | Heart of orchestrator state. |
| `db/flyway/sql/V15__spine_audit_schema.sql` | Append-only audit_event | KEEP | #24, compliance | – | P0 | Evidence Store relies on this as the chronological core. |
| `db/flyway/sql/V16__unified_cost_ledger.sql` | Unified cost ledger | KEEP | #2 (LLM-agnostic), #15 | V1 cost_row | P0 | LLM-agnostic accounting needed for multi-provider Day 1. |
| `db/flyway/sql/V17__portfolio_views.sql` (+ README) | Portfolio queue + views | KEEP | #1 (AI company), #19 | V14, V16 | P1 | Multi-project ops; needed by AI scrum master (#5). |
| `db/flyway/sql/V18__calibration_corpus.sql` (+ README) | Confidence calibration corpus | KEEP | #12 (Cite-or-Refuse), #27 | – | P1 | Calibrated confidence is structurally tied to Cite-or-Refuse and 3-tier learning. |
| `db/flyway/sql/V19__spine_eval_schema.sql` (+ README) | Role-prompt eval harness | KEEP | #27, #21 | – | P1 | Eval underpins the Smart Spine learning loop. |
| `db/flyway/sql/V20__spine_memory_schema.sql` | Vector memory / lessons | KEEP | #21, #27 | pgvector | P0 | Memory loop is part of "ALL AI ALL THE TIME" + 3-tier learning. |
| `db/flyway/sql/V21__spine_verify_schemas.sql` (+ README) | TRON verify-internal port | KEEP | #5 implied (verify integrated) | – | P0 | TRON squashed baseline. |
| `db/flyway/sql/R__1_seed_lookups.sql` | Reference data seeds (tiers, levels, disciplines, roles) | REFACTOR | #7 (industry-anchored charters), #11 (devops role), #8 (hybrid auth) | – | P0 | Add `devops` role; align job_family/discipline to industry-anchored charters; add 2-tier hierarchy columns. |
| `db/flyway/sql/R__2_model_pricing.sql` | Provider/model pricing | REFACTOR | #2 (LLM-agnostic), #20 (multi-cloud) | – | P0 | Currently a small allow-list; needs to enumerate Anthropic + OpenAI + Google + Azure + Bedrock + local (LLM-agnostic). |
| `db/flyway/sql/.sqlfluff` | Lint config | KEEP | – | – | P2 | Foundational. |
| `db/dashboard/` (index/about/machines/engagement/tech/versions HTMLs + serve.py + build-snapshot.py) | Static dashboard reading `pg-snapshot.json` | REBUILD | #3 (Hub product), #1, #5, #28 mobile scaffold, #29 voice scaffold | V4 views | P0 | This dashboard is a snapshot-driven dev tool; v3 Hub is a real, multi-tenant web product. Keep only build-snapshot.py as a JSON exporter shim; reimplement UI in `hub/`. |
| `db/dashboard/tests/` | Approval/HTTP/connection tests | KEEP | – | – | P2 | Reuse patterns in Hub. |
| `db/dashboard/pg-snapshot.json` | Generated artifact | DELETE | – | – | P2 | Build output; shouldn't be committed. |
| `db/watcher/` (Dockerfile + requirements.txt + spine_watcher.py 82k LOC) | Drains role outbox.jsonl → Postgres | REFACTOR | #3 (Hub product), #4, #11 (devops emits events) | V1, V11 | P1 | Logic is sound (cursor-tracked, idempotent UUIDs). v3 needs: multi-tenant cursor namespacing, federation event forwarding to parent Hub (#10/#16), Vault creds (#9). 82k LOC python is a lot — consider extracting a `shared/watcher/` module so Hub server reuses it. |

#### tools/ — existing

| Path | Current purpose | Marking | Decision drivers | Depends on | Priority | Notes |
|---|---|---|---|---|---|---|
| `tools/bootstrap.sh` | One-command cold-start (preflight→venv→pip→pg×2→flyway→alembic→smoke) | REFACTOR | #9, #15, #17, #25 | docker, db/, verify/ | P0 | Needs new steps: Vault setup wizard (#9), optional Keycloak install (#25), build Hub container (#3), wire deployment-shape choice (#17). Two-postgres assumption may simplify when TRON's alembic is dropped (#33D follow-up). |
| `tools/spine-flyway-sync.sh` | Reconciles `flyway_schema_history` post-wave-9 drift | KEEP | #33D | postgres | P2 | One-shot hygiene fix; idempotent; harmless to keep around. |
| `tools/smoke-test.sh` (56KB, 12 phases) | Integration smoke harness | REFACTOR (extend) | #9, #25, #4, #16, #27, #11, #23, #24, #28-30 | everything | P0 | Phases 1–12 stay; need new phases: 13 Vault, 14 Keycloak/SSO (#25), 15 Federation handshake (#4/#16), 16 License/feature-flags (#23), 17 Evidence Store ingestion (#24), 18 Smart Spine 3-tier learning loop (#27), 19 devops role (#11), 20 mobile + voice + API/MCP scaffolds (#28/#29/#30). |
| `tools/smoke-test_README.md` | Smoke harness doc | REFACTOR | with smoke-test.sh | – | P1 | Update phase table. |
| `tools/check-module-boundaries.sh` | Cross-subsystem boundary lint | KEEP | #4 (federation), #11 | _boundary_parser.py | P1 | Add `hub/`, `federation/`, `devops/`, `vault/`, `keycloak-adapter/` subsystems to `boundary-rules.yaml`. |
| `tools/_boundary_parser.py` | Python/bash/JS import scanner | KEEP | same | yaml | P2 | Logic is sound; just feed it the new rules. |
| `tools/boundary-rules.yaml` | Subsystems + exceptions | REFACTOR | #4, #11, #25 | – | P1 | Add v3 subsystems (hub, federation, devops, license, evidence-store, keycloak-adapter, vault-adapter). |
| `tools/check-boundaries-README.md` | Boundary CI doc | REFACTOR | – | – | P2 | Update table when rules expand. |
| `tools/_tron_alembic_upgrade.py` | Runs TRON alembic at head | KEEP-FROZEN, then DELETE | #5, #33D | verify/alembic | P2 | Per migration-survey.md plan, Alembic decommissions once TRON code targets Spine schemas. Schedule deletion. |
| `tools/_tron_dogfood_probe.py` | TRON verify_audit probe | KEEP | #5 | tron, mcp | P2 | Diagnostic; still useful. |
| `tools/_smoke_phase11_tron.py` | Phase 11 TRON helper for smoke-test | KEEP | #5 | tron | P2 | Co-evolves with smoke. |
| `tools/backlog_to_jira_csv.py` (+ README) | docs/BACKLOG.md → CSV for Jira/Linear/GH | KEEP | #26 (biz-ops deferred — but PM-tool export is useful) | – | P2 | Cheap, stdlib, useful for PM-tool projection. Not strategic. |

#### docs/ — existing

| Path | Current purpose | Marking | Decision drivers | Depends on | Priority | Notes |
|---|---|---|---|---|---|---|
| `docs/ARCHITECTURE.md` (24k) | v2 unified architecture, 8 locked decisions, repo layout | REBUILD | All 33 | – | P0 | Predates v3. Currently says "Plan + Build + Verify + Orchestrator + Shared monorepo, bash core, single Postgres, TRON subtree." v3 adds Hub container, federation, Vault, Keycloak, devops role, 4 deployment shapes, licensing, Evidence Store, Smart Spine. The 8 "locked decisions" need to be replaced by the 33. Write `V3_ARCHITECTURE.md` and supersede this. |
| `docs/PRD.md` (68k) | Master PRD with REQ-INIT-1/6/7/8/9 | REBUILD | All 33 | ARCHITECTURE | P0 | Built around 5 INITs; v3 adds at least: INIT-10 Hub product, INIT-11 Federation, INIT-12 Vault, INIT-13 Keycloak, INIT-14 Licensing, INIT-15 Evidence Store, INIT-16 Smart Spine learning, INIT-17 devops, INIT-18 mobile/voice/API scaffolds, INIT-19 DR, INIT-20 migration. Best path: write a v3 PRD doc keyed off the 33 decisions and supersede this. |
| `docs/BACKLOG.md` (66k) | INIT/EPIC/STORY tracker (180 stories, 73% done) | REBUILD | All 33 | PRD | P0 | The story tree maps to v2 INITs. The 33 v3 decisions reorder priorities and add 50+ new stories. Either fork into `V3_BACKLOG.md` (recommended) or do a destructive rewrite with v2 archived. |
| `docs/STATUS.md` (24k) | "Where are we / what's next" wave-history | REFACTOR | – | – | P0 | This is a *living* doc; refresh with current state (v2 → v3 transition, 33 decisions locked, what shipped vs pending). Don't archive — rewrite the TL;DR and append a "v3 transition" section. |
| `docs/PRACTICES.md` (11k) | Operating practices (drift prevention, SDLC flow, extension status) | REFACTOR | #5 (AI scrum master), #11 (devops), #7, #8 | – | P1 | Mostly v1 practice. Update for v3: AI scrum master as active participant, devops role, hybrid auth tiers, role charters anchored to industry. |
| `docs/IMPROVEMENT_CHECKLIST.md` (3k) | Maintenance/release-hygiene checklist for v1 template | DELETE (or archive) | #1, #15 | – | P2 | v1-template focused. v3 is a product, not a template. Archive or fold the few still-relevant items into PRACTICES. |
| `docs/positioning.md` (13k) | One-page positioning ("local-deployed virtual eng team for vibecoders") | REBUILD | #1, #3, #14, #18 | comparison.md, research | P0 | "Vibecoders" framing is too narrow. Decision #14 = ALL three segments (vibecoder + enterprise + solo founder). Six-corner moat is fine but needs Hub + Federation + Vault as additional structural moats. Rewrite. |
| `docs/comparison.md` (13k) | vs Devin/Factory/Cursor/ruflo/MetaGPT/superpowers/LangGraph matrix | REFACTOR | #1, #18 (closed-source v1.0), #14 | research | P1 | Matrix is still accurate; needs new rows: Hub federation, Vault-native, Keycloak SSO, Evidence Store, deployment shapes. License row currently TBD — set per #18 (closed-source v1.0). |
| `docs/naming-decision.md` (10k) | ADR for keeping "Spine" name | KEEP | – | – | P2 | If a real product decision occurred since this ADR, supersede; otherwise keep. |
| `docs/landing/index.html` (+ landing.css/js/demo-script.json/README.md) | Public landing page | REFACTOR | #14, #18, positioning | positioning.md | P1 | Copy needs to follow rewritten positioning. Demo script (5-move dialogue) is still on-strategy — just needs current segment framing. |
| `docs/diagrams/lifecycle.md` | ASCII + mermaid lifecycle diagram | REFACTOR | #11 (devops adds a phase), #1 (Hub adds an entry point) | phases.yaml | P2 | Add devops phase + Hub front-door view. |
| `docs/research/COMPETITIVE_LANDSCAPE.md` (8.5k) | Source-of-truth research | KEEP | – | – | P1 | Foundational research; the Tier-list at §4 mostly anticipated decisions 23/24/26/27. Append a "v3 update" section reflecting locked decisions. |

#### Top-level + meta — existing

| Path | Current purpose | Marking | Decision drivers | Depends on | Priority | Notes |
|---|---|---|---|---|---|---|
| `README.md` (21k) | Landing for new users; mixes v1 template install + v2 dev bootstrap | REBUILD | #1, #3, #18, #22 | – | P0 | Currently leads with v1 template install (`bash install.sh <project>`), buries v2 bootstrap. v3 needs a single, clear front door: "Spine is an AI software company in a box; deploy via Hub". Move v1-template install to ARCHIVE.md or delete. |
| `INSTALL.md` (4k) | v1 template install steps | REBUILD | #1, #15, #17 | install.sh | P0 | v3 install ≠ v1 template install. New INSTALL needs to describe Hub install + 4 deployment shapes + Vault wizard + Keycloak option. |
| `PROTOCOL.md` (33k) | v1 role/daemon contract | REFACTOR | #5 (AI scrum master), #7 (charters), #8 (hybrid auth), #11 (devops), #19 (7 work-item types) | roles.sh | P1 | Core file-bus protocol survives, but: AI scrum master needs first-class section, devops role needs entry, 7 work-item types need definition, two-tier auth needs gate language. |
| `REQUIREMENTS.md` (9k) | Host prerequisites for v1 template | REFACTOR | #2, #17, #20, #25 | – | P0 | v3 prerequisites differ per deployment shape (laptop vs BYOC vs cust-cloud vs on-prem). Add Vault, Keycloak (optional), Docker/Compose vs K8s/Helm, multi-cloud SDKs for #20. |
| `CHANGELOG.md` (32k) | Release notes back to v1.0 | KEEP | – | – | P1 | Append, don't rewrite. Add "v3.0 — 33 design decisions locked" entry when shipping. |
| `Makefile` (top-level, 7.7k) | Mixes v2 bootstrap + v1 team commands + lint + db-migrate | REFACTOR | #22 | many | P0 | Currently both v2 and v1 targets coexist. Pick a side: v3 product makefile should expose only `bootstrap`, `up`, `down`, `doctor`, `smoke`, `hub-up`, `vault-init`, `keycloak-init`. Move v1 `team-*` targets into legacy section or drop. |
| `Makefile.v2` (11k) | Umbrella makefile dispatching to subsystems | REFACTOR → MERGE INTO `Makefile` | #22 | – | P0 | Two makefiles is the v2→v3 cutover artifact. Per ARCHITECTURE §6 plan, rename to `Makefile`. The current top-level `Makefile` is the older one. Resolve before v3 ship. |
| `requirements.txt` (2.6k, 22 pins) | Python runtime deps for `make bootstrap` | REFACTOR | #2 (LLM-agnostic), #20 (multi-cloud), #25 (Keycloak/OIDC), #30 (API/MCP) | bootstrap.sh | P0 | Add: multi-provider LLM SDKs (openai, google-generativeai, vertexai, boto3 for Bedrock), OIDC client for Keycloak (e.g. `authlib`, `python-keycloak`), HashiCorp Vault client (`hvac` or OpenBao equivalent), cloud SDKs for #20 (azure-mgmt, google-cloud, boto3, fly.io api, railway sdk). |
| `install.sh` (18k) | v1 template installer | REBUILD or DELETE | #1, #3, #15, #18, #22 | lib/, recipes/ | P0 | This is the v1 template installer (copies role prompts, recipes, makefile snippet into a target project). v3 is not a template; it's a product installed via Hub. Either delete entirely or rebrand as `install-legacy-template.sh`. The actual v3 install path is `tools/bootstrap.sh` (and a new `install-hub.sh`). |
| `.gitignore` | Excludes .planning, scripts/, .venv | KEEP | – | – | P2 | Sound. |
| `.markdownlint.json` | MD lint config | KEEP | – | – | P2 | Sound. |
| `.claude/settings.local.json` | Claude Code local settings | KEEP | – | – | P2 | Per-dev; no policy implication. |
| `.planning/orchestration/` (29 files, AGENT_TEAM_PROTOCOL/REQUIREMENTS, DECISIONS, ADR_TEMPLATE, dashboard/, schema/, state/, agent-handoff/, recipes/, program/, docs/) | Working tree for the Spine-on-Spine dogfood; gitignored but exists | KEEP (live dogfood scratch) | – | – | P2 | Per .gitignore line 7. This is dogfood scratch, not shipped artifacts. Don't ship to users. |
| `recipes/batch-process-data.md` | Datawright fan-out recipe | KEEP | #5, #14 | – | P1 | Still on-strategy. |
| `recipes/dependency-bump.md` | Dependency-bump recipe | KEEP | – | – | P2 | Useful. |
| `recipes/host-side-llm-pipeline.md` | Operator/engineer recipe for host GPU + dockerized rest | KEEP | #2, #20 | – | P1 | Still on-strategy for local-deploy. |
| `recipes/investigate-bug.md` | Researcher recipe | KEEP | – | – | P2 | – |
| `recipes/performance-investigation.md` | Performance recipe | KEEP | – | – | P2 | – |
| `recipes/postmortem.md` | Memory role recipe | KEEP | #27 (Smart Spine learning feeds on postmortems) | – | P1 | – |
| `recipes/refactor-plan.md` | Architect recipe | KEEP | – | – | P2 | – |
| `recipes/safe-db-script.md` | Engineer recipe (DB scripts) | KEEP | – | – | P2 | – |
| `recipes/security-audit.md` | QA/auditor recipe | KEEP | #12, #24 | – | P1 | Maps to Evidence Store. |
| `recipes/ship-feature.md` | Engineer recipe | KEEP | – | – | P2 | – |
| `lite/install-lite.sh` (11k) | Claude Code plugin install path | REFACTOR | #3 (Hub), #14, #23 (feature flags) | manifest.yaml | P1 | "Lite" is a v2 feature-pruned bundle. In v3 with feature-flag licensing (#23), the lite/full split becomes a license flag rather than a separate install. Keep the plugin path (#14 — all three segments), but rewire to fetch from Hub. |
| `lite/upgrade-to-full.sh` | Lite→full upgrade helper | REFACTOR | same | install.sh | P2 | Same — becomes "claim full license tier". |
| `lite/manifest.yaml` | Declarative lite component spec | REFACTOR | #23 | – | P1 | Becomes a feature-flag manifest. |
| `lite/feature_matrix.md` | Lite vs full table | REFACTOR | #23 | manifest | P2 | Becomes "tier 1 / tier 2 / tier 3 license feature matrix". |
| `lite/lite_README.md` | Lite path docs | REFACTOR | same | – | P2 | – |
| `lite/claude-code-plugin/spine.json` | Plugin manifest | KEEP | #14 | – | P1 | The plugin install path is strategic per #14. |
| `lite/claude-code-plugin/README.md` | Plugin docs | KEEP | – | – | P2 | – |

#### BUILD-NEW files needed

| Proposed path | Purpose | Decision drivers | Priority |
|---|---|---|---|
| `docs/V3_DESIGN_DECISIONS.md` | The 33 locked decisions, with rationale per decision and links to the INITs/stories they generate | #22 | P0 |
| `docs/V3_ARCHITECTURE.md` | New architecture doc reflecting Hub container, federation, Vault, Keycloak, devops, 4 deployment shapes; supersedes ARCHITECTURE.md | All 33 | P0 |
| `docs/V3_PRD.md` (or PRD rewrite) | PRD keyed to the 33 decisions with REQ-V3-1..N | All 33 | P0 |
| `docs/V3_BACKLOG.md` (or BACKLOG rewrite) | Story tree for the 33 decisions | All 33 | P0 |
| `docs/V3_TRIAGE.md` | Aggregated triage report (output of this T1–T6 exercise) | #22 | P0 |
| `docs/V3_MIGRATION_FROM_V2.md` | Step-by-step v2→v3 upgrade for Spine itself (db migrations, env→Vault, file moves, role-prompt updates) | #33 | P0 |
| `docs/HUB_OPERATIONS_GUIDE.md` | Operator runbook for the Hub container (start/stop/backup/restore/upgrade/license/federation) | #3, #17, #31 | P0 |
| `docs/DEPLOYMENT_SHAPES.md` | Side-by-side guide: laptop / BYOC / customer-cloud / on-prem | #17, #20 | P0 |
| `docs/FEDERATION_GUIDE.md` | How a child Hub registers with a parent, how updates flow through the federation tree | #4, #10, #16 | P0 |
| `docs/SECURITY_GUIDE.md` | Vault-only secrets, Keycloak SSO, hybrid auth tiers, audit/evidence | #9, #25, #8, #24 | P0 |
| `docs/LICENSING_GUIDE.md` | Feature-flag tier matrix, how licenses are checked, offline grace, on-prem activation | #23 | P0 |
| `docs/COMPLIANCE_AND_EVIDENCE.md` | Evidence Store architecture, what's collected, retention, export | #24 | P1 |
| `docs/SMART_SPINE_LEARNING.md` | 3-tier learning loop (per-instance / per-tenant / per-federation) | #27 | P1 |
| `docs/ROLE_CHARTERS.md` | Industry-anchored charters for all 14 roles (existing 13 + devops); supersedes scattered prompts | #7, #11 | P0 |
| `docs/API_AND_MCP_SURFACE.md` | API + MCP scaffold contract; OpenAPI + tool registry | #30 | P1 |
| `docs/MOBILE_AND_VOICE.md` | Mobile + voice scaffold spec (read-only ops in v1.0) | #28, #29 | P2 |
| `docs/DR_RUNBOOK.md` | Disaster-recovery: backup, restore, RTO/RPO, failover | #31 | P0 |
| `db/flyway/sql/V22__license_registry.sql` | License catalog + tenant feature flags + activation history | #23 | P0 |
| `db/flyway/sql/V23__federation_registry.sql` | Parent/child Hub edges, tenant federation tree, replication cursors | #4, #10, #16 | P0 |
| `db/flyway/sql/V24__hub_project_registry.sql` | Hub-level project catalog (across tenants), tenant boundaries enforced at row level | #3, #11 | P0 |
| `db/flyway/sql/V25__evidence_store.sql` | Evidence Store schema (compliance artifacts, hash chains, retention) | #24 | P0 |
| `db/flyway/sql/V26__keycloak_link.sql` | User/tenant linkage table for Keycloak subjects (group → role mapping) | #25, #8 | P0 |
| `db/flyway/sql/V27__devops_role_seed.sql` | Add `devops` to lookup + seed default prompt id | #11 | P0 |
| `db/flyway/sql/V28__work_item_types.sql` | All 7 work-item types as a first-class type system | #19 | P1 |
| `db/flyway/sql/V29__smart_spine_learning.sql` | 3-tier learning corpus, aggregation views, cross-tenant anonymized memory | #27 | P1 |
| `db/flyway/sql/V30__provider_catalog.sql` | LLM-agnostic provider/model registry replacing R__2 | #2 | P1 |
| `db/flyway/sql/V31__cloud_targets.sql` | Multi-cloud deployment target registry (AWS/Azure/GCP/Railway/Fly/DO) | #20 | P1 |
| `db/flyway/sql/V32__dr_backup_log.sql` | DR backup events + restore-test history | #31 | P1 |
| `db/keycloak-compose.yml` | Optional Keycloak service (sibling compose file) | #25 | P0 |
| `db/vault-compose.yml` (or `db/openbao-compose.yml`) | Local Vault/OpenBao service for dev/laptop deployments | #9 | P0 |
| `db/backup-cron.yml` (or `db/backup.sh`) | Automated pg_dump + WAL archive + retention | #31 | P0 |
| `db/helm/spine-postgres/` (chart skeleton) | K8s deployment of Postgres + Flyway job + watcher for BYOC/on-prem | #17, #15 | P0 |
| `hub/` (new top-level subsystem) | The Hub container: REST + web UI + license + federation broker | #3, #5, #14, #16 | P0 |
| `hub/Dockerfile` | Buildable Hub image | #3, #17 | P0 |
| `hub/helm/spine-hub/` | Hub Helm chart for K8s deploys | #17 | P0 |
| `federation/` (new top-level subsystem) | Federation tree client/server (parent↔child Hub sync) | #4, #10, #16 | P0 |
| `devops/` (new top-level subsystem) | devops role module (role prompt, daemon adapter, runbooks) | #11 | P0 |
| `tools/build-hub-container.sh` | Build + tag + push Hub image to registry | #3, #16 | P0 |
| `tools/install-openbao-wizard.sh` | Interactive OpenBao/Vault bootstrap (init, unseal, seed paths) | #9 | P0 |
| `tools/install-keycloak-wizard.sh` | Interactive Keycloak bootstrap (realm, client, group→role mapping) | #25, #8 | P0 |
| `tools/dispatch-spine-update.sh` | Vendor-side update publishing (build → sign → push to federation root) | #16 | P0 |
| `tools/license-mint.sh` | License token mint/sign/revoke utility for the vendor | #23, #18 | P0 |
| `tools/federation-join.sh` | Child Hub joins a parent Hub | #4, #10 | P0 |
| `tools/federation-snapshot.sh` | Snapshot replication state for a federated tenant | #4, #16 | P1 |
| `tools/evidence-export.sh` | Evidence Store export bundle generator | #24 | P1 |
| `tools/dr-backup.sh` + `tools/dr-restore.sh` | DR runbook scripts (one-command backup and restore) | #31 | P0 |
| `tools/onboarding-wizard.sh` | Onboarding scaffold per #33 (migration scaffold + portability) | #33 | P0 |
| `tools/portability-export.sh` | Full tenant export bundle (data + secrets refs + standards) for portability | #33 | P0 |
| `tools/version-migrate.sh` | Spine version migration runner (umbrella over Flyway + manifest moves + role-prompt diffs) | #33 | P0 |
| `tools/cloud-deploy/aws.sh` `azure.sh` `gcp.sh` `railway.sh` `fly.sh` | One-button deploys per cloud (BYOC/customer-cloud shapes) | #17, #20 | P0 |
| `tools/api-smoke.sh` | API+MCP surface smoke (REST OpenAPI + MCP tool list) | #30 | P1 |
| `tools/mobile-stub-build.sh` | Mobile scaffold builder (read-only client) | #28 | P2 |
| `tools/voice-stub-record.sh` | Voice scaffold smoke (whisper → role-prompt → tts) | #29 | P2 |
| `tools/license-check.sh` | Standalone license validator (used by Hub at boot) | #23 | P0 |
| `vault/` (new top-level subsystem) | Vault/OpenBao adapter library (read-only client used by every subsystem) | #9 | P0 |
| `vault/paths.yaml` | Canonical Vault path schema (`/secret/spine/<tenant>/<purpose>`) | #9 | P0 |
| `keycloak/` (new top-level subsystem) | Keycloak adapter + group→role mapping + token verification middleware | #25, #8 | P0 |
| `license/` (new top-level subsystem) | License feature-flag evaluator + tier matrix loader | #23 | P0 |
| `evidence/` (new top-level subsystem) | Evidence collector hooks (audit, build artifacts, verify findings, decisions) | #24 | P0 |
| `learning/` (new top-level subsystem) | 3-tier Smart Spine learning loop (corpus → eval → prompt update) | #27 | P1 |
| `recipes/devops-incident.md` | Recipe for the new devops role | #11 | P1 |
| `recipes/federation-onboard.md` | Recipe for joining a child Hub to a federation | #4, #10 | P1 |
| `recipes/license-tier-bump.md` | Recipe for upgrading license tier in-place | #23 | P2 |
| `tools/migrate-env-to-vault.sh` | One-shot helper to lift `db/.env` and `verify/.env` contents into Vault paths, then delete | #9, #33 | P0 |
| `Makefile` (consolidated) | One canonical Makefile (merge v1 `Makefile` + `Makefile.v2`); v1 targets archived | #22 | P0 |
| `INSTALL_V3.md` | New install doc for the 4 deployment shapes | #17 | P0 |
| `README_V3.md` (or README rewrite) | New README leading with Hub product, ALL THREE segments, 33 decisions reference | #1, #14, #18, #22 | P0 |
| `requirements-multicloud.txt` | Optional multi-cloud SDK pin set (split out so laptop installs stay slim) | #20 | P1 |
| `.github/workflows/hub-build.yml`, `federation-sync.yml`, `smoke.yml` | CI for Hub build, federation sync, smoke gate | #16 | P1 |

#### Summary

- **Files reviewed: ~110** (db: 41, tools: 14, docs: 13, root + recipes + lite: 42).
- **Markings tally:**
  - **KEEP:** ~46 (mostly Flyway V1–V21 SQL, recipes, foundational tools, research)
  - **REFACTOR:** ~32 (db compose, Makefiles, watcher, smoke harness, boundary rules, PRACTICES, comparison, landing, REQUIREMENTS, PROTOCOL, lite/)
  - **REBUILD:** ~14 (ARCHITECTURE, PRD, BACKLOG, README, INSTALL, positioning, db/README, db/.env.example, db/dashboard/, install.sh, V7–V9 engagement schemas)
  - **DELETE:** ~5 (db/.env, db/.env.bak, IMPROVEMENT_CHECKLIST, pg-snapshot.json, eventually _tron_alembic_upgrade.py)
  - **BUILD-NEW:** ~60+ files spanning 8 new top-level subsystems (`hub/`, `federation/`, `devops/`, `vault/`, `keycloak/`, `license/`, `evidence/`, `learning/`) + 11 new Flyway migrations + ~20 new tools + ~10 new docs.

- **Biggest themes:**
  1. **The four pillars of v3 that aren't here yet:** Hub container (#3), Federation (#4/#10/#16), Vault (#9), Keycloak (#25). These are net-new subsystems, not refactors.
  2. **"AI software company in a box" reframing** (#1, #14) breaks the implicit "developer template" framing in README/INSTALL/install.sh/lite/positioning.
  3. **Deployment-shape multiplication** (#15/#17/#20): the current `db/docker-compose.yml` + bash bootstrap is single-shape (laptop). Helm charts + cloud-specific bootstraps are missing.
  4. **Secrets discipline reversal** (#9): `db/.env` is now an anti-pattern; tooling assumes it.
  5. **License + Evidence + Learning as first-class** (#23/#24/#27): three brand-new cross-cutting subsystems with their own schemas, tools, and docs.
  6. **The 6th role** (#11 devops) needs a slot in `roles.sh`, a charter, a prompt, a daemon path, and a recipe — and to propagate through every smoke test that enumerates roles.

- **Biggest debts:**
  - **`docs/ARCHITECTURE.md`, `docs/PRD.md`, `docs/BACKLOG.md`** — all three are authoritative v2 docs that need full REBUILD against the 33 decisions. They cannot be patched incrementally; the 8 "locked decisions" inside ARCHITECTURE.md need to be replaced by 33, and most INIT/EPIC structure shifts.
  - **`README.md` + `INSTALL.md` + `install.sh`** — three landing artifacts that all lead with the v1 template story; v3 is not a template, it's a Hub product. These mislead every new visitor.
  - **`Makefile` vs `Makefile.v2`** — two-Makefile state must be resolved before v3 ships. Currently the older one is canonical; Makefile.v2 is the v3-correct base.
  - **`db/.env` plaintext + `db/.env.example`** — direct conflict with decision #9. Every script that sources `.env` (smoke-test.sh, bootstrap.sh, spine-flyway-sync.sh, dashboard/build-snapshot.py, dashboard/serve.py, share-pg.sh, install.sh) needs a Vault-aware replacement.

- **Biggest wins (already in shape for v3):**
  - **Flyway V1–V21 SQL migrations** are mostly foundational and survive intact. ~85% KEEP.
  - **`tools/smoke-test.sh`** is a 12-phase harness with a sound architecture — extending with new phases is cheaper than rebuilding.
  - **`tools/bootstrap.sh`** is idempotent and well-staged; adding Vault/Keycloak/Hub steps is additive.
  - **`tools/check-module-boundaries.sh` + `_boundary_parser.py`** are language-aware and rule-driven — adding new subsystems to `boundary-rules.yaml` is trivial.
  - **The watcher** (`db/watcher/spine_watcher.py`) has a clean cursor + deterministic-UUID model that scales to federated event ingest with minor extensions.
  - **`recipes/` and `lite/role-prompts/`** are mostly portable role discipline that the 33 decisions don't disturb.
  - **`docs/research/COMPETITIVE_LANDSCAPE.md`** — its Tier-1/2/3 gap list anticipated 6 of the 33 decisions (audit log, vector memory, MCP, lite path, org bundles, spend caps). Keep as-is, append v3 update.

- **Risks:**
  - **Spine-on-Spine dogfood (`.planning/orchestration/`)** is locally rich but gitignored — useful for v3 testing but won't help users; don't accidentally ship it.
  - **TRON entanglement** — verify/ subtree + dual-Postgres + Alembic dependency adds operational surface area against #15 (not SaaS, fully self-hosted) and #17 (multiple deployment shapes). The migration-survey.md plan to deprecate verify/alembic is healthy but not executed.
  - **`engagement` (V7–V9) vs `spine_lifecycle.project` (V14)** are two parallel project hierarchies. v3 should pick one (lifecycle wins); migration cost is non-trivial because Pass-I-built dashboard views key off engagement.
  - **README + lite/ semantic drift:** the v1 template story is still the default front door. Users discover Spine via README, install via `install.sh`, get a v1 template — and never reach the v2/v3 product. This is the highest-leverage UX bug in the whole scope.
  - **`requirements.txt` is comfortable, not LLM-agnostic.** It pins TRON's Anthropic-flavored stack. Decision #2 requires a real multi-provider pin set or a per-provider optional-extra split.
  - **Closed-source v1.0 (#18) + feature-flag licensing (#23) impose new tooling** (license-mint, license-check) that doesn't exist in tools/ at all.

- **Recommendation on docs overhaul timing:** **Big-bang the *landing* docs (README, INSTALL, ARCHITECTURE, PRD, positioning) as part of v3 ship; do BACKLOG + STATUS + PRACTICES + comparison incrementally.**
  - Landing docs (README, INSTALL, ARCHITECTURE, PRD, positioning, V3_DESIGN_DECISIONS, HUB_OPERATIONS_GUIDE, DEPLOYMENT_SHAPES, FEDERATION_GUIDE, SECURITY_GUIDE, LICENSING_GUIDE, DR_RUNBOOK) **must ship coherent on day 1** — anything else creates a credibility wedge ("they call it v3 but their README still pitches a v1 template installer").
  - BACKLOG.md can fork: archive v2 BACKLOG, start V3_BACKLOG with the 33 decisions; close stories as work lands.
  - STATUS.md updates with each wave (it's already a living doc).
  - PRACTICES.md, comparison.md, naming-decision.md, COMPETITIVE_LANDSCAPE.md, landing/ can update over the first 30 days post-ship without damaging credibility — they're reference docs, not entry points.
  - **Sequencing:** lock the 33 decisions doc first (V3_DESIGN_DECISIONS.md) so all other docs can cite it; then rebuild ARCHITECTURE→PRD→positioning→README→INSTALL in that order; then the operational guides; then incremental cleanup.

---

---

## References

- **Design decisions:** `docs/V3_DESIGN_DECISIONS.md` (commit `645a1bc` — 34 decisions locked)
- **Conversation transcript:** `chatsession.md` (~21k lines; design session 2026-05-17)
- **Triage source files:** `/private/tmp/claude-501/-Users-khashsarrafi-Projects-Apps-SpineDevelopment/890bb5a5-f2ca-4ec3-a354-f467e44ddfc7/tasks/`
  - T1 shared/ → `ad28f13982a5430c1.output`
  - T2 plan/ → `af61edb272c657348.output`
  - T3 build/ → `ad49fa4fd315bf7df.output`
  - T4 verify/ → `a00d9b36cce25fb31.output`
  - T5 orchestrator+lib/ → `a72fb53dcf9f859dc.output`
  - T6 db+tools+docs+root → `a986d7a1bd34316d2.output`
- **Memory artifacts:** `~/.claude/projects/-Users-khashsarrafi-Projects-Apps-SpineDevelopment/memory/`

---

**Document control:**
- Created: 2026-05-17
- Author: AI orchestration (Claude Opus 4.7), reviewed by Khash Sarrafi
- Status: **CANONICAL** — execution plan for v3 rebuild
- Next deliverable: `docs/V3_BUILD_SEQUENCE.md` (dependency-ordered Wave 0–6 execution plan)
