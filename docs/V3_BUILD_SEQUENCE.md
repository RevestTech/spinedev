# Spine v3 — Build Sequence

> **Status:** Dependency-ordered execution plan for the v3 rebuild. Built on top of
> `docs/V3_DESIGN_DECISIONS.md` (34 locked decisions) and `docs/V3_TRIAGE.md`
> (~383 files triaged → ~264 BUILD-NEW + ~120 REFACTOR + ~23 REBUILD + ~20 DELETE).
>
> **Source of truth.** This doc is the canonical execution plan. The TODO list, wave-by-wave
> acceptance criteria, and dependency graph here drive every BUILD-NEW / REFACTOR / REBUILD /
> DELETE action. If `docs/STATUS.md` or `docs/BACKLOG.md` conflicts, this doc wins until
> explicitly revised.
>
> **Pre-read order:** `docs/V3_DESIGN_DECISIONS.md` → `docs/V3_TRIAGE.md` → this doc.

---

## Quick navigation

- [Part 1 — Resolved structural decisions](#part-1--resolved-structural-decisions) — locks 4 deferred architectural questions
- [Part 2 — Dependency graph](#part-2--dependency-graph) — what blocks what, critical path
- [Part 3 — Wave-by-wave execution plan](#part-3--wave-by-wave-execution-plan) — Wave 0 through Wave 6
- [Part 4 — Open decisions remaining](#part-4--open-decisions-remaining) — items still needing user input

---

# Part 1 — Resolved structural decisions

These were deferred in `docs/V3_TRIAGE.md` as "to be resolved before build-sequence planning."
Locked here.

## 1.1 Package placement: `shared/*` vs top-level

**Tension:** T1 places all new substrate as `shared/*` sub-packages. T5+T6 place many of the
same things at top level alongside `plan/ build/ verify/ orchestrator/`.

**Resolution — hybrid by nature of the artifact:**

| Artifact nature | Placement | Rationale | Examples |
|---|---|---|---|
| **Cross-cutting library** — callable API surface only, no daemon, no own schema, called from many subsystems | `shared/*` | Lowest coupling cost; every subsystem already imports from `shared/` | `shared/llm/`, `shared/secrets/`, `shared/identity/` |
| **Subsystem** — has own daemons / schemas / containers / runbooks / config; user-visible in Hub UI as a distinct concern | top-level | Symmetric with existing top-level subsystems; clear ownership; each gets its own CHANGELOG, README, tests | `hub/`, `federation/`, `devops/`, `vault/`, `keycloak/`, `license/`, `evidence/`, `learning/`, `recovery/`, `migration/` |

**Note on apparent overlap:** `shared/secrets/` (cross-cutting library that ANY code calls to get a
secret) is distinct from `vault/` (the OpenBao container, init wizard, runbooks). `shared/identity/`
(OIDC client library) is distinct from `keycloak/` (the Keycloak container + realm config + init
wizard). `shared/llm/` is the only one without a top-level companion — there's no "LLM container"
Spine ships; providers are external services.

**Final v3 top-level layout (LOCKED):**

```
hub/                 NEW   — containerized Hub product (#3)
federation/          NEW   — Hub-to-Hub sync (#4, #10, #16)
devops/              NEW   — devops role + 8 control planes (#11)
vault/               NEW   — OpenBao container + init wizard + runbooks (#9)
keycloak/            NEW   — Keycloak container + realm config + init wizard (#25)
license/             NEW   — signed bundle authority + verifier + quota meters (#23)
evidence/            NEW   — Evidence Store + Vanta/Drata/Secureframe push (#24)
learning/            NEW   — Smart Spine 3-tier loop + telemetry pipeline (#27)
recovery/            NEW   — DR backup/restore/auto-recovery (12 layers) (#31, #32)
migration/           NEW   — onboarding + portability + version migration (#33)

orchestrator/        KEEP+REFACTOR — lifecycle + routing + gate core
plan/                KEEP+REFACTOR — intake + decomposer + pipeline + swarm + templates
build/               KEEP+REFACTOR+BUILD-NEW — KG + runtime + bridge + new dispatcher
verify/              KEEP+REFACTOR — TRON subtree (boundary refactors only)

shared/llm/          NEW   — single LLM call surface, multi-provider (#2)
shared/secrets/      NEW   — vault adapter library (#9)
shared/identity/     NEW   — OIDC client library (#25)
shared/runtime/      NEW   — substrate moved from lib/ (vitals/heartbeat/watchdog/notify/executor/usage-parsers/file-lock/updater/db-outbox)
shared/charters/     NEW   — industry-anchored role charters (replaces lib/role-prompts/) (#7)
shared/integrations/ NEW   — external connectors (GitHub/Linear/Jira/Slack/PagerDuty/Twilio/Teams/AWS/Azure/GCP/Railway/Fly/DO/Vanta/Drata/Secureframe)
                            Per Wave 3.5 FIX2 extraction note: this package holds per-vendor
                            *connection + auth* plumbing only. The per-domain *use* of an
                            integration (voice routing in voice/, SMS dispatch in
                            shared/notify/, GitHub repo import in migration/, Vanta evidence
                            push in evidence/) stays in the owning subsystem and imports the
                            plumbing from here. See shared/integrations/README.md for the
                            per-vendor vault-path conventions + extension recipe.
shared/{mcp,audit,standards,calibration,cost,eval,memory,notify,reproducibility,validation,schemas,skills,api,ui}
                     KEEP+REFACTOR — existing substrate

db/                  KEEP+REFACTOR+BUILD-NEW — V22-V32 Flyway migrations
docs/                MOSTLY REBUILD — landing docs per Hub-as-product framing + new operational guides
tools/               KEEP+REFACTOR+BUILD-NEW — Hub container build, license signing, migration export/import, DR test runner

lib/                 RETIRE entirely after migration to shared/runtime/ and shared/charters/
```

## 1.2 KG indexer trigger model

**Resolution — LOCKED:** **per-commit hook is primary; audit-event-driven is secondary; periodic
sweep is safety net.**

| Trigger | Role | When it fires | Failure mode |
|---|---|---|---|
| **per-commit hook** | Primary — captures every code-state change | Git post-commit hook on every project Spine commit | Indexer crash → next sweep catches it |
| **audit-event-driven** | Secondary — captures non-code state changes (bundle updates, role-charter changes, decisions, approvals) | Audit-chain writer publishes event → KG subscriber consumes | Sweep catches missed events |
| **periodic sweep** | Safety net — catches missed events from crashed runs | Hourly (configurable per bundle) | Surfaces stale KG via Hub UI dashboard |

**Implication:** `build/kg/indexer.py` needs 3 entry points (commit-hook CLI / audit-event subscriber
/ sweep CLI). All three write to the same `spine_kg` schema. Conflict resolution is
last-write-wins + observed-state validation.

## 1.3 Federation pipeline customization

**Resolution — LOCKED:** **bundle inheritance with explicit override hooks. Parent Hub bundle
declares pipeline; child Hub can EXTEND (add phases) but not CONTRACT (remove phases) unless parent
declared the phase as `removable: true`.**

Matches the **consent-leaning** federation model (#10) — peer-consent by default; bounded
mandatory upward flows declared in bundle for compliance.

**Implementation:** `shared/standards/bundle-schema.yaml` adds `federation.pipeline` block:

```yaml
federation:
  pipeline:
    phases:
      - id: intake
        removable: false
      - id: prd
        removable: false
      - id: trd
        removable: true       # child Hub may drop this phase
      - id: verify
        removable: false
    extensions_allowed: true  # child Hub may insert new phases between locked ones
```

## 1.4 Spine ↔ TRON boundary (T4's 10 questions resolved)

| # | Question | Resolution |
|---|---|---|
| 1 | Bundle vs optional in each deployment shape | **Bundled** with Hub in BYOC / customer-cloud / on-prem. Bundled with laptop install via Docker (TRON's existing docker-compose). v1.0 = TRON always present. v1.1+ may add "verify-via-remote-Spine-Hub" as a flag for resource-constrained laptops. |
| 2 | Vault migration timing | **Wave 0.** TRON's `verify/.env` secrets migrate to vault references before any other Wave 0 work ships. |
| 3 | Audit-chain federation | **Hash-link.** Spine's chain entries anchor TRON's chain entries via SHA-256 anchor records. Parallel-reconcile is too brittle. Anchor records replayable independently for verification. |
| 4 | Autonomous-engineer self-verify policy | **Always defer to separate verify role.** Per #12 Cite-or-Refuse, the implementer never grades their own work. Autonomous engineer produces build-artifact; verify role (cite-or-refuse contract enforced) audits. No exceptions. |
| 5 | License inventory for 40+ TRON deps under closed-source | **Wave 5 dedicated gate.** Audit + license review before v1.0 ships. Track any GPL/AGPL/copyleft deps; replace before ship. |
| 6 | TRON's own LLM provider | **Routes through `shared/llm/`.** Per #2, no provider hardcoding anywhere. Wave 0 builds `shared/llm/`; Wave 1 wires TRON through it. |
| 7 | TRON sandbox compute attribution | **Verify cost ledger.** Per existing `iso.py` split (pre_verify → Build ledger; verify_phase → Verify ledger). Sandbox CPU/memory seconds added as new line item. |
| 8 | TRON upgrade cadence | **Follows Spine's federation update flow (#16).** TRON ships as a sub-bundle inside Spine release. No independent TRON upgrade channel. |
| 9 | Cite-or-Refuse enforcement at boundary | **Wrapper middleware in `shared/mcp/tools/verify.py` + `iso.py`.** Wave 1 wiring. Refuse if `citation` field absent or fails schema. |
| 10 | Calibration outcomes capture | **`shared/calibration/calibration_sink.py` helper** called from every TRON invoke. Wave 1 wiring. |

---

# Part 2 — Dependency graph

## 2.1 Hard dependencies (what BLOCKS what)

```
Wave 0 (Foundations)
├── shared/secrets/ ────────► blocks every Wave 1+ feature that touches secrets
├── shared/llm/ ────────────► blocks every Wave 1+ feature that calls an LLM
├── shared/identity/ ───────► blocks every Wave 1+ feature that needs current_user
└── DB migrations V22-V32 ──► blocks license/federation/Hub registry/Evidence Store/devops role/work-item types/Smart Spine learning/provider catalog/cloud targets/DR backup log

Wave 1 (Substrate wiring)
├── memory writer hooks ──► blocks Smart Spine Tier 1a/1b (Wave 4)
├── KG indexer ──────────► blocks role-action retrieval (Wave 2+), Cite-or-Refuse evidence (Wave 1 cont.)
├── calibration sink ───► blocks Smart Spine refit loop (Wave 4)
└── Cite-or-Refuse middleware ──► blocks any verify-class role (Wave 2+)

Wave 2 (Work-item types)
├── 6 new role charters ─────► blocks work-item routing (Wave 2 cont.)
├── work-item type schemas ──► blocks intake templates (Wave 2 cont.)
├── intake templates × 6 ────► blocks build dispatcher routing (Wave 2 cont.)
└── build dispatcher routing ► blocks v1.0 multi-type demo

Wave 3 (Hub product)
├── hub/ container ─────────► blocks Hub UI panels (Wave 3 cont.)
├── shared/runtime/ migration ► blocks lib/ retirement (Wave 6)
└── Hub web SPA panels ──────► blocks #3 Hub-as-product framing claim

Wave 4 (Federation + License + Evidence + Learning)
├── federation/ registry + cascade ──► blocks #10 fractal Hub deployment
├── license/ verifier + flags ───────► blocks #23 pricing experimentation
├── evidence/ collectors + push ────► blocks #24 SOC2-grade evidence pipeline
└── learning/ scope + telemetry ────► blocks #27 Smart Spine product value

Wave 5 (DR + Migration + Landing docs)
├── recovery/ (12 layers) ──► blocks #31 + #32 + enterprise sales
├── migration/ A+B+D ──────► blocks #33 + "no lock-in" claim
└── landing-docs big-bang ──► blocks v1.0 launch credibility

Wave 6 (Mobile/Voice/API scaffolds + lib/ retirement)
├── mobile + voice + API scaffolds ──► closes #28/#29/#30
└── lib/ retirement ──────────────────► final subtraction
```

## 2.2 Critical path

Foundation → wiring → Hub container → landing docs.

```
shared/secrets/ → shared/identity/ → hub/ container → Hub web SPA → landing-docs rewrite → v1.0 ship
```

Anything on the critical path can't be parallelized away. Anything OFF the critical path
(license/federation/Evidence/Learning/Recovery/Migration/mobile/voice) can run in parallel within
its wave but blocks ship if not done.

## 2.3 Parallelizable within waves

| Wave | Items that can run in parallel |
|---|---|
| 0 | `shared/secrets/` + `shared/llm/` + `shared/identity/` + DB migrations (no cross-deps) |
| 1 | memory hooks + KG indexer + calibration sink + Cite-or-Refuse middleware (separate codepaths) |
| 2 | 6 role charters (one agent per charter); intake templates × 6 (one agent per type) |
| 3 | Hub container + each Hub SPA panel (10 panels — one agent each) |
| 4 | federation/ + license/ + evidence/ + learning/ (4 subsystems — one squad per subsystem) |
| 5 | recovery/ + migration/ + landing-docs (3 squads in parallel) |
| 6 | mobile + voice + API + lib/ retirement (4 streams) |

---

# Part 3 — Wave-by-wave execution plan

Each wave: **Goal / Prerequisites / Deliverables / Acceptance criteria / Risks / Estimated agent-effort.**

## Wave 0 — Foundations

**Goal:** unblock everything downstream by landing the cross-cutting libraries + DB schema.

**Prerequisites:** none.

**Deliverables (BUILD-NEW):**

| Package | Files | Decision drivers |
|---|---|---|
| `shared/secrets/` | `__init__.py`, `vault.py` (OpenBao adapter), `aws_secrets_manager.py`, `azure_keyvault.py`, `gcp_secret_manager.py`, `cache.py`, `rotation.py`, `README.md` | #9 |
| `shared/llm/` | `__init__.py`, `client.py`, `request.py`, `streaming.py`, `retry.py`, `providers/{anthropic,openai,bedrock,vertex,ollama,qwen,vllm}.py`, `README.md` | #2, #20 |
| `shared/identity/` | `__init__.py`, `keycloak_client.py`, `middleware.py` (FastAPI dep), `rbac.py`, `feature_flag_lightening.py`, `README.md` | #25, #14 |
| `vault/` | container Dockerfile + init wizard + Shamir-OR-KMS unseal config + DR runbook | #9, #32 layer 8 |
| `keycloak/` | container Dockerfile + realm config + Day-0 admin bootstrap + IdP brokering presets | #25 |
| `db/flyway/sql/` | V22 license registry, V23 federation registry, V24 Hub project registry, V25 Evidence Store, V26 Keycloak link, V27 devops role, V28 work-item types, V29 Smart Spine learning, V30 provider catalog, V31 cloud targets, V32 DR backup log | #19, #23, #24, #25, #27, #31, #32 |

**Deliverables (REBUILD):** `verify/.env` → vault-reference manifest (T4 finding).

**Deliverables (REFACTOR):**
- 5 vault violations cleaned: `orchestrator/lib/approval.py`, `lib/_env_loader.sh`, `lib/share-pg.sh`,
  `lib/run-standalone-watcher.sh`, `lib/spine-connect.sh` — all switched to `shared/secrets/` calls.

**Acceptance criteria:**
- `python3 -c "from shared.secrets import get_secret; print(get_secret('test'))"` works against
  OpenBao container
- `python3 -c "from shared.llm import call; r = call(LLMRequest(model='claude-sonnet-4-6', messages=[...])); print(r)"` works against Anthropic AND OpenAI AND Bedrock
- `python3 -c "from shared.identity.middleware import current_user; ..."` resolves real Keycloak token
- All 11 Flyway migrations apply cleanly + rollback cleanly
- Zero grep hits for `os.environ.get("SPINE_` outside `shared/secrets/`
- Smoke test passes 12/12 phases including new vault + keycloak phases

**Risks:**
- OpenBao container init wizard UX is critical Day-0 friction point — budget extra time for
  wizard polish
- Keycloak Java/JVM container memory footprint may surprise laptop users — document min RAM

**Estimated agent-effort:** 1 squad of 4 agents × ~6 days wall-clock (large because foundations).

---

## Wave 1 — Substrate wiring

**Goal:** turn on the substrate that already exists. Stop the data losses (calibration outcomes,
memory writer hooks, KG indexer firing). Enforce Cite-or-Refuse.

**Prerequisites:** Wave 0 complete.

**Deliverables (BUILD-NEW):**

| Item | Files | Decision drivers |
|---|---|---|
| Memory writer hooks at 7 trigger points (per R4) | `shared/memory/writer_hooks.py` + 7 hook integrations into audit_record writer | #27 |
| KG indexer execution (3 trigger entry points) | `build/kg/indexer_commit_hook.py`, `build/kg/indexer_audit_subscriber.py`, `build/kg/indexer_sweep.py` | #27, decision 1.2 |
| `shared/calibration/calibration_sink.py` helper | called from every `shared/mcp/tools/*` audit-class invoke | #27 |
| Cite-or-Refuse middleware in MCP server | tool tag `verify-class` → middleware enforces `citation` field; reject 422 if absent/malformed | #12 |
| `verify/.env` → vault references migration | one-time script + new manifest format | #9 (carried over from Wave 0) |
| `verify/docker-compose.override.yml` move outside subtree | symlink at runtime; prevents merge conflicts on TRON subtree pulls | T4 finding |

**Deliverables (REFACTOR):**
- `shared/mcp/tools/verify.py` + `iso.py` enforce Cite-or-Refuse, capture calibration outcomes
- `shared/cost/prompt_cache.py` → `shared/llm/providers/anthropic.py` (cache becomes provider trait)
- `shared/validation/cross_llm.py` provider Literal extends to all 7 providers
- `shared/notify/channels.py` creds via `shared/secrets/`; rate-limit persisted to V22+ schema
- `shared/memory/playbook_store.py` splits into 3-tier scope (per #27)
- 4 quiet bugs from triage: `plan/pipeline/phase_evolution.py` rename detection, `project_lock.py`
  SQL injection, `build/kg/extractors/markdown.yaml` vs `doc_parser/` duplication, `audit_record.py`
  subsystem enum extension (`hub`, `federation`, `integration`)

**Acceptance criteria:**
- `spine_kg` rows > 0 after a single commit-hook fire
- `spine_calibration.outcome` rows accumulate from every verify/iso invoke
- Any verify-class MCP call without `citation` returns 422 with explicit Cite-or-Refuse message
- Cross-LLM consensus runs successfully across Anthropic + OpenAI + Bedrock + Vertex + Ollama
- Smoke test still passes; new tests for each wiring point pass

**Risks:**
- Memory writer hooks fire on every audit event → cost meter must validate hook fires don't blow
  budget (add per-hook usage line item)
- KG indexer per-commit fires inside Hub container — must not block commits if indexer is slow
  (background dispatch + observable lag)

**Estimated agent-effort:** 1 squad of 4 agents × ~5 days wall-clock.

---

## Wave 2 — Work-item types (closes #19 gap)

**Goal:** v1.0 must handle all 7 work-item types end-to-end (feature/bug/incident/support/refactor/infra/compliance).

**Prerequisites:** Wave 0 + Wave 1 complete.

**Deliverables (BUILD-NEW):**

| Item | Files | Decision drivers |
|---|---|---|
| 6 new role charters | `shared/charters/{devops,customer_support,compliance_officer,security_engineer,tech_writer,release_manager}.md` (PMBOK/ITIL/NIST/SRE anchors) | #7, #11, #19 |
| Existing 13 charters: REBUILD against industry anchors | `shared/charters/{architect,conductor,datawright,engineer,operator,planner,product,qa,ux,...}.md` | #7 |
| Work-item type schemas | `shared/schemas/build/work_item.py` (base + 7 subclasses) | #19 |
| Intake templates × 6 (feature exists) | `plan/templates/{bug,incident,support,refactor,infra,compliance}.yaml` | #19 |
| Build dispatcher routing | `build/runtime/build_dispatcher.py` — adds `work_item_type` switch + per-type pipeline lookup | #19 |
| `devops/` subsystem skeleton | role daemon + 8 control planes scaffolds | #11 |

**Deliverables (REFACTOR):**
- `shared/mcp/tools/orchestrator.py` ProjectType Literal: 4 values → 7 values
- `shared/api/routes/projects.py` `project_type` Literal: 4 values → 7 values
- `plan/decomposer/` recognizes per-type artifact shapes
- `lib/role-prompts/` retired; symlinks/redirects to `shared/charters/`

**Deliverables (DELETE):**
- `lib/role-prompts/_archived/engineering-{backend,frontend}.md` (already in `_archived/`; remove)
- 3 obsolete files from `build/` per T3 triage

**Acceptance criteria:**
- `spine project new "test" --type {feature,bug,incident,support,refactor,infra,compliance}` works
  for all 7
- Each type runs end-to-end intake → PRD → brief → build (dry-run mode for types without external
  integration)
- All 19 role charters (13 rewrites + 6 new) cite industry-standard anchor in their preamble
- Smoke test extended with one phase per work-item type

**Risks:**
- Industry-standard charter authoring is high-judgment work — needs careful agent prompts + human
  spot-check per charter
- DevOps role + 8 control planes is conceptually large; budget extra time for the planes' interfaces

**Estimated agent-effort:** 1 squad of 6 agents × ~7 days wall-clock (one agent per charter; intake
templates parallelizable).

---

## Wave 3 — Hub product (closes #3 gap)

**Goal:** Hub is a real containerized product with a web SPA. CLI becomes power-user tool.

**Prerequisites:** Waves 0 + 1 + 2 complete.

**Deliverables (BUILD-NEW):**

| Item | Files | Decision drivers |
|---|---|---|
| `hub/` container | Dockerfile + entrypoint + healthcheck + multi-arch build | #3 |
| `shared/runtime/` migration from `lib/` | move + adapt: `vitals.sh`, `heartbeat.sh`, `watchdog.sh`, `notify.sh`, `executor.sh`, `usage-parsers.sh`, `file-lock.sh`, `updater.sh`, `db-outbox.sh` | T5 finding |
| Hub web SPA: 10 panels | `shared/ui/dashboard/panels/{decision-queue,master-roles,registry,audit,vault-config,integrations,role-chat,federation,license,kg-search}.js` | #3, #5, #25 |
| Mobile-responsive CSS | `shared/ui/dashboard/responsive.css` | #28 |
| OIDC login page | `shared/ui/login/index.html` + Keycloak redirect flow | #25 |
| Hub-extended API routes | `shared/api/routes/{decisions,role_chat,registry,vault_config,integrations,federation,license}.py` + middleware `oidc.py`, `feature_flag.py` | #3, #6, #23, #25 |
| New MCP transport (remote) | `shared/mcp/server_remote.py` (mTLS over HTTP, bearer-token auth) | #4, #10, #30 |

**Deliverables (REFACTOR):**
- `shared/ui/dashboard/index.html`: 4 tabs → 10 tabs (per #3 enumerated surfaces)
- `shared/api/app.py`: Keycloak OIDC middleware + RBAC scopes + federation context propagation
  header + vault-backed config
- `shared/api/dependencies.py`: REBUILD — replace header-stub auth with OIDC; replace subprocess
  psql with asyncpg pool; replace in-process-only MCP with remote-capable transport
- `shared/api/routes/approvals.py`: emit decision-card events to `shared/notify/` on POST

**Deliverables (DELETE):**
- `shared/ui/approvals/proxy.py` (dev-only, superseded by `shared/api/routes/approvals.py`)
- `shared/ui/approvals/serve.sh` (paired with proxy.py)
- Major lib/ files: `team-agent-daemon.sh`, `team.sh`, `dashboard.html`, `engagement-hook.sh`,
  `team-clean.sh`, `seer-tick.sh`, `serve-dashboard.sh`, `share-pg.sh`, `run-standalone-watcher.sh`,
  `spine-connect.sh`, `spine-disconnect.sh`, `costs-csv.sh` (all per T5 markings)

**Acceptance criteria:**
- `docker run spine/hub:v3` exposes web UI on `:8080`, healthcheck green
- Hub SPA loads in browser at `http://localhost:8080`, all 10 tabs render
- Mobile-responsive: works on iPhone Safari + Android Chrome (test in browser device emulators)
- OIDC login flow: Keycloak → Hub → user session persisted
- `spine` CLI still works (power-user tool) — both `--mode=cli` and `--mode=web` resolve
- Approval queue: REST POST emits decision-card to Slack (default channel)
- Smoke test extended with Hub container phase + login phase + each panel render phase

**Risks:**
- Vanilla-JS SPA may strain at 10 panels — frame check whether to upgrade to a framework
  (Svelte/Solid/Preact most likely). Locking framework choice deferred to start of Wave 3.
- asyncpg migration touches ~15 files via DbHandle — risk of subtle perf regression in hot paths

**Estimated agent-effort:** 1 squad of 8 agents × ~10 days wall-clock (large — Hub is the
biggest single subsystem).

---

## Wave 4 — Federation + License + Evidence + Learning

**Goal:** close #4, #10, #16 (federation), #23 (licensing), #24 (compliance evidence), #27 (Smart Spine).

**Prerequisites:** Waves 0 + 1 + 2 + 3 complete.

**Deliverables (BUILD-NEW) — 4 subsystems run as parallel squads:**

### Squad A: federation/
| Files | Drivers |
|---|---|
| `federation/hub_registry.py`, `federation/upstream_client.py` (mTLS + bearer), `federation/downstream_router.py`, `federation/update_cascade.py`, `federation/consent.py`, `federation/README.md`, `shared/schemas/federation/consent_v1.py`, `shared/mcp/tools/federation.py` | #4, #10, #16 |

### Squad B: license/
| Files | Drivers |
|---|---|
| `license/__init__.py`, `license/bundle_verifier.py` (Ed25519), `license/feature_flags.py`, `license/quota_ledger.py`, `license/README.md`, `shared/schemas/license/bundle_v1.py`, `shared/mcp/tools/license.py`, `tools/license-sign.sh` (vendor-side signing) | #23 |

### Squad C: evidence/
| Files | Drivers |
|---|---|
| `evidence/collectors/{audit_chain,role_decision,vault_access,deploy,approval}.py`, `evidence/exporters/{vanta,drata,secureframe}.py`, `evidence/two_party_attestation.py`, `evidence/README.md` | #24 |

### Squad D: learning/
| Files | Drivers |
|---|---|
| `learning/scope.py` (project/within-hub/cross-org resolver), `learning/contribute.py` (3-tier gates), `learning/consent.py` (cross-org opt-in registry), `learning/anonymizer.py` (Tier 2 telemetry pipeline), `learning/vendor_self_improvement.py`, `learning/README.md` | #27 |

**Deliverables (REFACTOR):**
- `shared/standards/bundle-schema.yaml` adds `federation.pipeline`, `feature_flags`, `licensing`,
  `learning_scope`, `comm_prefs`, `update_policy`, `devops_planes` sections
- `shared/standards/validator.py` mirrors schema extensions; adds cross-section invariants
- `shared/standards/drift_detector.py` plugs into update-distribution flow (#16); surfaces drift
  in Hub decision queue
- `shared/standards/install_bundle.sh` adds install-from-parent-hub mode + license signature
  verification

**Acceptance criteria:**
- Two Hubs federate: parent registers child; child fetches parent bundle; update from vendor flows
  vendor → parent → child with approval gate at each tier
- License bundle signed by vendor private key verifies on Hub start; per-feature gates work
  (`license.is_enabled("federation")` returns False if flag off)
- Audit-chain event fires → Evidence collector picks up → pushed to Vanta test sandbox; auditor
  sees evidence; corroborates against Spine hash; matches
- Smart Spine: lesson written at project tier; aggregated to within-Hub at default-ON setting;
  cross-org consent flow works (denies by default, opt-in via Hub UI surfaces in `learning/consent.py` registry)
- Smoke test extended with 1 phase per squad

**Risks:**
- Federation mTLS + bearer-token auth is security-sensitive — needs dedicated security agent review
- License bundle signing keys are vendor-managed; must be in vendor's vault Day 1 (not customer's)
- Tier 2 anonymizer requires careful privacy review before any Tier 2 telemetry ships

**Estimated agent-effort:** 4 squads × ~7 days wall-clock parallel = 4 squad-weeks.

---

## Wave 5 — DR + Migration + Landing docs

**Goal:** close #31, #32 (DR), #33 (migration), and the v1-template-framing UX bug across landing docs.

**Prerequisites:** Waves 0–4 complete.

**Deliverables (BUILD-NEW) — 3 parallel squads:**

### Squad E: recovery/ (12 layers)
| Files | Drivers |
|---|---|
| `recovery/backup.py` (Postgres logical + KG + manifests + bundles + vault refs), `recovery/restore.py` (tested restore), `recovery/cross_region.py` (active-passive opt-in), `recovery/auto_recovery.py`, `recovery/health.py`, `recovery/runbook_generator.py` (auto-generated DR runbook per deployment), `recovery/README.md`, `shared/mcp/tools/recovery.py`, `tools/dr-test.sh` (weekly restore-to-throwaway validation) | #31, #32 (all 12 layers) |

### Squad F: migration/ (4 concerns)
| Files | Drivers |
|---|---|
| `migration/__init__.py`, `migration/export.py` (full Spine state), `migration/import_.py`, `migration/onboarding.py` (GitHub + Linear OR Jira), `migration/spine_version.py` (DB/bundle/charter/vault/KG schema migrator), `migration/version_registry.py`, `migration/README.md`, `shared/mcp/tools/migration.py` | #33 A+B+D |
| **Note:** #33 C (software-migration-as-work-type intake template) is v1.1 — out of scope |

### Squad G: landing-docs big-bang rewrite (REBUILD)
Per T6's "must ship coherent on Day 1 — anything else creates a credibility wedge."

| File | Drivers |
|---|---|
| `README.md` (Hub-as-product framing) | #3 |
| `INSTALL.md` (4 deployment shapes + BYOC mechanics) | #17 |
| `install.sh` (vault wizard + Hub container) | #3, #9 |
| `docs/ARCHITECTURE.md` (v3 layout per Part 1.1 of this doc) | All |
| `docs/PRD.md` (rewrite to "AI software company in a box") | #1 |
| `docs/positioning.md` (rewrite per #1 sub-tagline) | #1 |
| `db/README.md` (V22-V32 documented) | All Wave 0 DB |
| **NEW** `docs/HUB_OPERATIONS_GUIDE.md` | #3 |
| **NEW** `docs/DEPLOYMENT_SHAPES.md` | #17, #20 |
| **NEW** `docs/FEDERATION_GUIDE.md` | #4, #10, #16 |
| **NEW** `docs/SECURITY_GUIDE.md` | #9, #18, #25 |
| **NEW** `docs/LICENSING_GUIDE.md` | #23 |
| **NEW** `docs/DR_RUNBOOK.md` | #31, #32 |

**Deliverables (incremental, NOT big-bang):**
- `docs/BACKLOG.md` forks to `docs/V3_BACKLOG.md` (v2 archived as `docs/_archived/v2-BACKLOG.md`)
- `docs/STATUS.md` updates each wave (already in this cadence)
- `docs/PRACTICES.md` + `docs/comparison.md` + `docs/research/` update incrementally

**Acceptance criteria:**
- DR weekly test: kill container, restore from backup, verify Hub functional in < 30 min
- DR weekly test runs on schedule; failure pages oncall
- Migration B portability: export full Spine state from Hub A; import to fresh Hub B on different
  cloud; audit-chain verifies; KG reproduces; identical decision history
- Migration A onboarding: GitHub repos + Linear issues import; map to Spine projects + work items
- Migration D Spine version: v1.0 → v1.1 simulated upgrade migrates DB/bundle/charter/vault/KG
  without data loss; downgrade blocked with clear error
- Landing docs read coherent end-to-end; no remaining "drop Spine into your project" v1 framing;
  T6's highest-leverage UX bug closed

**Risks:**
- DR restore is the highest-leverage test — must actually fire weekly, not be a stub
- Migration portability is the "no lock-in" promise — needs marketing-grade polish (round-trippable
  export format becomes a marketing artifact per #33 B)
- Landing docs rewrite is high-judgment writing work — budget multiple agent passes + human review

**Estimated agent-effort:** 3 squads × ~7 days wall-clock parallel = 3 squad-weeks.

---

## Wave 6 — Mobile/Voice/API scaffolds + lib/ retirement

**Goal:** close #28, #29, #30 scaffolds + complete the lib/ retirement.

**Prerequisites:** Waves 0–5 complete.

**Deliverables (BUILD-NEW) — 4 parallel streams:**

### Stream H: mobile scaffold (#28)
| Files |
|---|
| `shared/api/routes/mobile.py` (mobile-API surface: approvals + briefings + status) |
| `mobile/ios/` (placeholder Xcode project + signing cert config) |
| `mobile/android/` (placeholder Android Studio project + signing cert config) |
| `mobile/README.md` (v1.1 native build plan documented) |

### Stream I: voice scaffold (#29)
| Files |
|---|
| `shared/integrations/twilio.py` (already in Wave 4; this is the voice-call adapter extension) |
| `shared/api/routes/voice.py` (voice-integration interface: which decisions voice-approvable, which roles voice-reachable) |
| `voice/README.md` (v1.1 actual voice-flow plan) |

### Stream J: API + MCP heavier (#30)
| Files |
|---|
| `shared/api/openapi_spec.py` (heavier OpenAPI 3.x generation) |
| `shared/api/versioning.py` (`v1` namespace; reserve `v2/v3`) |
| `shared/api/rate_limit.py` (per-org rate-limiting middleware) |
| `shared/mcp/tools/integrations.py` (per-integration test-connection + list-configured) |
| `shared/mcp/schemas/envelopes.py` REFACTOR: add `feature_flag_required` + `actor_token_claims` |

### Stream K: lib/ retirement
- All `lib/` content already migrated to `shared/runtime/` (Wave 3) and `shared/charters/` (Wave 2)
- Remaining `lib/tests/test-*.sh` migrate to `tools/tests/` OR delete if superseded by Wave 1-5 tests
- `git rm -rf lib/` once all callers migrated
- Update root `Makefile` references; remove `lib/` from `.gitignore` exemptions

**Acceptance criteria:**
- `curl https://hub-url/openapi.json` returns valid OpenAPI 3.x spec
- Mobile API smoke tested via HTTP (no native client yet, per scaffold scope)
- Twilio webhook scaffold registers; receives test ping; routes to voice-integration interface
- `lib/` directory does not exist; smoke test still passes 100%; no broken references
- `tools/audit-broken-refs.sh` confirms zero references to retired `lib/` paths

**Risks:**
- Mobile signing cert + dev account setup is administrative — pre-stage Apple/Google accounts
  before Wave 6 starts
- lib/ retirement may surface late-discovered consumers; budget for stragglers

**Estimated agent-effort:** 4 streams × ~5 days wall-clock parallel = 4 stream-weeks.

---

## Wave-summary tally

| Wave | Goal | Wall-clock (parallel) | Agent-effort |
|---|---|---|---|
| 0 | Foundations | ~6 days | 1 squad × 4 agents |
| 1 | Substrate wiring | ~5 days | 1 squad × 4 agents |
| 2 | Work-item types + 6 new charters | ~7 days | 1 squad × 6 agents |
| 3 | Hub product (container + SPA) | ~10 days | 1 squad × 8 agents |
| 4 | Federation + License + Evidence + Learning | ~7 days | 4 squads parallel |
| 5 | DR + Migration + Landing docs | ~7 days | 3 squads parallel |
| 6 | Mobile/Voice/API scaffolds + lib/ retire | ~5 days | 4 streams parallel |
| **Total** | **v3 ready for v1.0 ship** | **~47 days wall-clock** | |

Wall-clock is **agent wall-clock at high concurrency**, not human calendar time. Real timeline
depends on:
- How many agents Khash spawns in parallel per wave
- Approval-gate latency (human-in-loop on every decision card)
- Customer-conversation interruptions
- Unforeseen rework

**Realistic estimate:** 8–14 calendar weeks at sustained pace, per #21's "as fast as AI velocity
can ship it" framing.

---

# Part 4 — Open decisions remaining

These need user input before the affected wave starts. Not blocking THIS doc — blocking the wave
that needs them.

| # | Question | Latest-by wave | Notes |
|---|---|---|---|
| 4.1 | **Which v3 frontend framework** for Hub SPA (vanilla ES modules / Svelte / Solid / Preact / React)? | Start of Wave 3 | T1 + T6 both flagged vanilla won't scale to 10+ panels. Recommended: Svelte (smallest bundle, closest to vanilla ergonomics). |
| 4.2 | **Fly.io OR DigitalOcean** as the 5th cloud Day 1 (#20)? | Start of Wave 0 (DB schema needs cloud catalog) | Khash to pick based on 30-day signal — per #20 spec |
| 4.3 | **License bundle key custody** — vendor uses own vault for signing key; what's the backup/escrow for that? | Wave 4 Squad B | Operational decision; consult licensing pattern from HashiCorp/Confluent |
| 4.4 | **DR cross-region active-passive** opt-in default — bundle policy? Enterprise-tier-only? | Wave 5 Squad E | Per #32 it's "Optional per bundle policy (enterprise tier feature flag)" — does that mean default-OFF and only available if license has `dr.cross_region` flag? |
| 4.5 | **TRON license inventory** — any GPL/AGPL/copyleft deps that need replacing before #18 closed-source v1.0? | Wave 5 dedicated gate | Per Part 1.4 question #5 — audit before ship |
| 4.6 | **Workspace hygiene (#34)** location — does it live in `shared/runtime/hygiene.py` or top-level `hygiene/`? | Wave 1 (substrate wiring) | Per Part 1.1, cross-cutting library → `shared/runtime/`. Confirming. |
| 4.7 | **Hosted demo sandbox `try.spine.dev`** infra — Spine company runs it where? | Pre-v1.0 launch (not blocking any wave) | Per #15 — marketing artifact only; not a product tier |
| 4.8 | **Air-gapped deployment shape** — confirm v1.1 deferral holds, OR pull into v1.0 for defense pilot? | Wave 5 (deployment shapes finalized) | Per #17 — currently deferred to v1.1 |

---

## References

- **Design decisions:** `docs/V3_DESIGN_DECISIONS.md` (commit `645a1bc` — 34 decisions locked)
- **Codebase triage:** `docs/V3_TRIAGE.md` (commit `70e9e89` — ~383 files triaged)
- **Conversation transcript:** `chatsession.md` (~21k lines; design session 2026-05-17)
- **Memory artifacts:** `~/.claude/projects/-Users-khashsarrafi-Projects-Apps-SpineDevelopment/memory/`

---

**Document control:**
- Created: 2026-05-17
- Author: AI orchestration (Claude Opus 4.7), reviewed by Khash Sarrafi
- Status: **CANONICAL** — drives v3 rebuild execution
- Resolves: 4 structural decisions deferred from `docs/V3_TRIAGE.md` (placement, KG trigger,
  federation pipeline, Spine-TRON boundary × 10 questions)
- Next update trigger: any wave acceptance failure that requires sequence revision, OR any open
  decision (Part 4) resolved that changes the wave plan
