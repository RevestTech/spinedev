# Spine — Architecture (v3)

> **Status:** v3 refresh per `docs/V3_BUILD_SEQUENCE.md` Part 1.1 (Wave 5 Squad G). The full v3 architecture is large enough that incremental rebuild continues across subsequent waves; this doc is the **authoritative v3 layout** anchor, with per-subsystem detail delegated to each subsystem's own README. The pre-v3 (v2) version of this file is archived at `docs/_archived/v2-ARCHITECTURE.md`.
>
> **Source of truth.** Where this doc says one thing and a subsystem README says another, the subsystem README wins for that subsystem's internals. Cross-cutting structure (placement, dependency graph, deployment shapes) — this doc wins.
>
> **Drivers:** [`docs/V3_DESIGN_DECISIONS.md`](V3_DESIGN_DECISIONS.md) — all 34 decisions inform the layout. The most architecturally consequential are #1, #2, #3, #4, #9, #10, #11, #15, #17, #19, #23, #25, #27, #31, #32, #34.

---

## 1. Executive summary

Spine v3 is a **containerized product** (the Hub) plus **10 subsystems** at top level (5 cross-cutting `shared/*` libraries + 10 top-level subsystems with their own daemons/containers/runbooks). The Hub is the **primary management surface** (#3); the CLI is a power-user tool. The Hub runs in **4 deployment shapes** (#17) on **5+ clouds Day 1** (#20). Pricing is deferred (#23, #26); feature-flag licensing is a Day-1 architectural primitive that makes any pricing model mechanically supported. Closed-source v1.0 (#18) — trust via SOC 2 + pen tests + source escrow + audit chain.

The v3 layout was independently converged on by three triage agents (T1 + T5 + T6 in `docs/V3_TRIAGE.md`) and resolved structurally in `docs/V3_BUILD_SEQUENCE.md` Part 1.1.

---

## 2. Top-level layout (LOCKED)

Per Build Sequence §Part 1.1:

```
hub/                 NEW    — containerized Hub product (#3)
federation/          NEW    — Hub-to-Hub sync (#4, #10, #16)
devops/              NEW    — devops role + 8 control planes (#11)
vault/               NEW    — OpenBao container + init wizard + runbooks (#9)
keycloak/            NEW    — Keycloak container + realm config + init wizard (#25)
license/             NEW    — signed bundle authority + verifier + quota meters (#23)
evidence/            NEW    — Evidence Store + Vanta/Drata/Secureframe push (#24)
learning/            NEW    — Smart Spine 3-tier loop + telemetry pipeline (#27)
recovery/            NEW    — DR backup/restore/auto-recovery (12 layers) (#31, #32)
migration/           NEW    — onboarding + portability + version migration (#33)

orchestrator/        KEEP+REFACTOR — lifecycle + routing + gate core
plan/                KEEP+REFACTOR — intake + decomposer + pipeline + swarm + templates
build/               KEEP+REFACTOR+BUILD-NEW — KG + runtime + bridge + new dispatcher
verify/              KEEP+REFACTOR — TRON subtree (boundary refactors only)

shared/llm/          NEW    — single LLM call surface, multi-provider (#2)
shared/secrets/      NEW    — vault adapter library (#9)
shared/identity/     NEW    — OIDC client library (#25)
shared/runtime/      NEW    — substrate moved from lib/ (vitals/heartbeat/watchdog/notify/executor/usage-parsers/file-lock/updater/db-outbox)
shared/charters/     NEW    — industry-anchored role charters (replaces lib/role-prompts/) (#7)
shared/integrations/ NEW    — external connectors (GitHub/Linear/Jira/Slack/PagerDuty/Twilio/Teams/AWS/Azure/GCP/Railway/Fly/DO/Vanta/Drata/Secureframe)
shared/{mcp,audit,standards,calibration,cost,eval,memory,notify,reproducibility,validation,schemas,skills,api,ui}
                     KEEP+REFACTOR — existing substrate

db/                  KEEP+REFACTOR+BUILD-NEW — Flyway migrations V1–V35
docs/                MOSTLY REBUILD — landing docs per Hub-as-product framing + new operational guides
tools/               KEEP+REFACTOR+BUILD-NEW — Hub container build, license signing, migration export/import, DR test runner

lib/                 RETIRE entirely after migration to shared/runtime/ and shared/charters/
```

### Placement rule (hybrid by nature of artifact)

| Artifact nature | Placement | Examples |
|---|---|---|
| Cross-cutting library — callable API surface only, no daemon, no own schema, called from many subsystems | `shared/*` | `shared/llm/`, `shared/secrets/`, `shared/identity/` |
| Subsystem — has own daemons/schemas/containers/runbooks/config; user-visible in Hub UI as distinct concern | top-level | `hub/`, `federation/`, `devops/`, `vault/`, `keycloak/`, `license/`, `evidence/`, `learning/`, `recovery/`, `migration/` |

Note: `shared/secrets/` (cross-cutting lib) is distinct from `vault/` (OpenBao container). `shared/identity/` (OIDC client lib) is distinct from `keycloak/` (Keycloak container). `shared/llm/` has no top-level companion because providers are external services.

### Layer model

> Adapted from the ECC `agentic-os` skill (`affaan-m/ecc`, MIT). See
> `docs/ECC_BORROWS.md` B9. Makes the implicit Spine 4-layer model
> explicit for newcomers and tooling.

Spine's runtime is layered. Each layer has a single responsibility and a
named persistence posture so a fresh contributor can place new work
without re-reading the whole codebase:

| Layer | Purpose | Lives in | Persistence |
|---|---|---|---|
| **Kernel** | Identity, routing, locked decisions | `CLAUDE.md`, `docs/V3_DESIGN_DECISIONS.md`, `docs/SPINE_MASTER.md` | Git-tracked |
| **Charters** | Role identities + industry-anchored contracts (#7) | `shared/charters/` | Git-tracked |
| **Commands** | User + MCP-facing surface | `shared/mcp/tools/`, `shared/api/routes/`, `orchestrator/bin/spine` | Git-tracked |
| **Daemons** | Orchestration + scheduled tasks | `orchestrator/`, `tools/`, `recovery/`, `shared/runtime/*.sh` | Git-tracked |
| **Workspace** | Per-run scratch + promoted artifacts (#34) | `.spine/work/`, `.spine/archive/` | Hygiene-swept |
| **Audit** | Hash-chained ledger + decision ledger (#12, #12a) | `shared/audit/`, `shared/audit/decision_ledger/` | Append-only |
| **Instincts** | Atomic learned behaviours pending lesson promotion (#27, B3) | `learning/instinct.py` JSONL under `~/.spine/instincts/` | Append-only, per-project |

When in doubt about *where* something belongs, ask which row of this
table it serves. Routing belongs in Kernel; "what a role may not do"
belongs in Charters; the user-facing CLI shape belongs in Commands;
a heartbeat goroutine belongs in Daemons.

---

## 3. Architectural picture

```
                   ┌─────────────────────────────────────────┐
                   │            HUB (containerized)          │ ← #3
                   │  9 enumerated surfaces in Hub web SPA   │
                   │  Day-0 wizard (7 steps, all flaggable)  │
                   │  OIDC via Keycloak; vault for secrets   │
                   └───┬───────┬───────┬──────┬──────┬───────┘
                       │       │       │      │      │
                       ▼       ▼       ▼      ▼      ▼
                   ┌──────┐ ┌──────┐ ┌──────┐ ┌─────┐ ┌─────────┐
                   │ PLAN │ │BUILD │ │VERIFY│ │OPER-│ │FEDERATE │ ← top-level
                   │      │ │      │ │      │ │ ATE │ │         │   subsystems
                   │intake│ │KG+run│ │TRON  │ │8 ctl│ │parent/  │
                   │PRD   │ │+disp │ │+Cite-│ │planes│ │child Hub│
                   │TRD   │ │atcher│ │or-   │ │+dev-│ │cascade  │
                   │swarm │ │      │ │Refuse│ │ops  │ │updates  │
                   │roadmp│ │      │ │      │ │role │ │         │
                   └──────┘ └──────┘ └──────┘ └─────┘ └─────────┘
                       │      │       │       │        │
                       └──────┴───┬───┴───────┴────────┘
                                  ▼
                  ┌──────────────────────────────────────────┐
                  │      CROSS-CUTTING (shared/*)            │
                  │                                          │
                  │  shared/llm/         7 providers (#2)    │
                  │  shared/secrets/     vault adapters (#9) │
                  │  shared/identity/    OIDC client (#25)   │
                  │  shared/runtime/     ex-lib/ substrate   │
                  │  shared/charters/    industry-anchored   │
                  │  shared/integrations/  GH/Linear/Slack…  │
                  │  shared/{mcp,audit,standards,calibration,│
                  │   cost,eval,memory,notify,validation,    │
                  │   schemas,skills,api,ui}                 │
                  └────────────┬─────────────────────────────┘
                               ▼
                  ┌──────────────────────────────────────────┐
                  │   POSTGRES (db/flyway/sql V1–V35)        │
                  │   spine_pg + spine_kg + spine_audit +    │
                  │   spine_lifecycle + spine_cost +         │
                  │   spine_memory + spine_eval +            │
                  │   spine_verify_* + spine_license +       │
                  │   spine_federation + spine_evidence +    │
                  │   spine_devops + spine_learning + ...    │
                  └──────────────────────────────────────────┘

  Sibling containers in laptop shape (hub/docker-compose.yml):
   - vault (OpenBao bundled, #9)
   - keycloak (+ its own postgres, #25)
   - spine_pg (Postgres for Hub data)
   - flyway (one-shot migration runner)
   - hub (FastAPI app)

  External services Day 1 (out-of-process):
   - LLM provider(s) per #2 (one of 7; customer chooses)
   - GRC platform per #24 (Vanta / Drata / Secureframe)
   - Integration endpoints per #19 (GitHub / Linear / Jira / Slack / PagerDuty / Twilio / Teams / clouds)

  Federated:
   - Parent / child Hubs via federation/ subsystem (#4 #10)
   - Vendor (root of update tree per #16)
```

---

## 4. Subsystem responsibilities (one-paragraph each)

### `hub/` (#3)
The containerized product. Multi-arch Dockerfile, docker-compose for laptop, entrypoint (under tini), healthcheck, Day-0 wizard (`hub/wizard/init.sh` — 7 steps, all flaggable per #21). Hosts the FastAPI app (`shared/api/`) which serves the 9 Hub surfaces. `hub/main.py` is a thin wrapper over `shared.api.app.create_app`; routes + middleware live in `shared/api/`. Sibling containers (vault, keycloak, postgres, flyway) wire through the `spine` Docker bridge network. See `hub/README.md`.

### `federation/` (#4 #10 #16)
Hub-to-Hub control plane. `hub_registry.py` owns the `spine_federation.hub` table (V23). `upstream_client.py` mTLS + bearer-token client (creds via vault per #9). `downstream_router.py` routes delegated tools to child Hubs with consent gating. `consent.py` ConsentEngine — peer-consent default + bounded mandatory upward flows. `update_cascade.py` distributes signed bundles vendor → parent → child with per-tier approval gate. 4 MCP tools (`federation_register_child`, `federation_grant_consent`, `federation_push_update`, `federation_pull_updates`). See `federation/README.md`.

### `devops/` (#11)
Customer-facing devops subsystem + 8 control planes (compute / network / data / identity / secrets / observability / incident / workspace-hygiene). `devops` role is **distinct from `operator`** (Spine-internal) — conflation is what every "AI DevOps" startup got wrong. Dispatcher + per-plane scaffolds in `devops/planes/`. 3 MCP tools. See `devops/README.md`.

### `vault/` (#9 #32 layer 8)
OpenBao container + Dockerfile + docker-compose (laptop shape) + Day-0 init wizard (`vault/init-wizard.sh` — Shamir 3-of-5 OR cloud-KMS auto-unseal, operator chooses). Least-privilege policies (`policies/spine-hub.hcl`, `spine-readonly.hcl`). Unseal-mode runbooks (`unseal/shamir-config.md` + `kms-config-{aws,azure,gcp}.md`). DR runbook. See `vault/README.md`.

### `keycloak/` (#25)
Keycloak container + Dockerfile + docker-compose + Day-0 bootstrap (`keycloak/init-bootstrap.sh` — realm + spine-hub OIDC client + groups). IdP brokering presets for Okta / Azure AD / Google Workspace / Ping / OneLogin. Per-tier feature matrix in `keycloak/tier-config.md` (5 tiers: free / founder / team / enterprise / airgapped). DR runbook. See `keycloak/README.md`.

### `license/` (#23 #18)
Feature-flag licensing — Day-1 architectural primitive. `bundle_verifier.py` Ed25519 signature verification + vault fetch + periodic re-verify (TRUSTED_VENDOR_FINGERPRINT trust anchor baked into Hub binary). `feature_flags.py` per-gate hot path. `quota_ledger.py` hash-chained usage. Vendor-side signing CLI: `tools/license-sign.sh` (vendor vault + Shamir 3-of-5 recovery per Part 4.3). 3 MCP tools. See `license/README.md`.

### `evidence/` (#24)
SOC 2 evidence pipeline. 5 collectors (`audit_chain` / `role_decision` / `vault_access` / `deploy` / `approval`) + 3 real exporters (Vanta / Drata / Secureframe) + 3 v1.1 stubs (Tugboat / StrikeGraph / Thoropass). Two-party SHA-256 attestation per V25 schema. 4 MCP tools. See `evidence/README.md`.

### `learning/` (#27)
Smart Spine 3-tier loop. `scope.py` resolver (project / within-Hub / cross-org). `contribute.py` 3-tier gates. `consent.py` cross-org opt-in registry. `anonymizer.py` k=5 telemetry pipeline. `vendor_self_improvement.py` Tier 3 hook for vendor's own Spine. 4 MCP tools. See `learning/README.md`.

### `recovery/` (#31 #32)
12-layer DR. `backup.py` (PG logical + KG + manifests + bundles + vault refs to S3-compat storage). `restore.py` (tested restore). `cross_region.py` (active-passive opt-in). `auto_recovery.py`. `health.py`. `runbook_generator.py` (auto-generated DR runbook per deployment). `tools/dr-test.sh` (weekly restore-to-throwaway validation). MCP tool surface. **Status:** Wave 5 Squad E — may be still landing when this doc is read. See `recovery/README.md` (forthcoming with Squad E delivery).

### `migration/` (#33)
4 concerns. `export.py` full Spine state export (signed tarball, integrity-verified, audit-chain hash-anchored). `import_.py` re-import. `onboarding.py` (GitHub + (Linear OR Jira) Day 1; others v1.1+ on demand). `spine_version.py` DB/bundle/charter/vault/KG schema migrator (N-2 cross-version compat). `version_registry.py`. MCP tool surface. C — software-migration-as-work-type — v1.1. See `migration/README.md` (forthcoming with Wave 5 Squad F delivery).

### `orchestrator/` (KEEP+REFACTOR)
Project lifecycle state machine, phase transitions, routing, gates. Bash core + Postgres state. The thin coordinator — owns state, not intelligence. Existing code largely KEEPs; REFACTORs are around vault wiring (#9) + audit-subsystem-enum extension for v3 subsystems.

### `plan/` (KEEP+REFACTOR)
Intake (5-move protocol), decomposer, pipeline-as-data, swarm (LangGraph subgraph inside architect daemon), per-work-item-type templates. REFACTORs: 7 intake templates (one per type per #19), decomposer recognizes per-type artifact shapes.

### `build/` (KEEP+REFACTOR+BUILD-NEW)
KG (tree-sitter parsers + indexer + 8 MCP tools), runtime (worker pool, daemon infra), bridge (interface to Verify subsystem), build dispatcher (per-type routing per #19). BUILD-NEW: KG indexer 3 entry points (commit hook / audit subscriber / sweep). REFACTORs: `implementer_kind ∈ {claude_code, cursor, aider, openhands, human}` + `autonomy_tier` fields (#13).

### `verify/` (KEEP+REFACTOR)
TRON via `git subtree`. Boundary refactors: route LLM through `shared/llm/`, capture calibration outcomes through `shared/calibration/`, enforce Cite-or-Refuse (#12) at wrapper middleware in `shared/mcp/tools/verify.py` + `iso.py`. Vault migration done in Wave 0 — `verify/.env` plaintext refs replaced with vault references. `docker-compose.override.yml` relocated to `tools/verify-overrides/` to avoid TRON subtree-pull conflicts.

### `shared/llm/` (#2)
Single LLM call surface. 7 provider adapters (Anthropic / OpenAI / Bedrock / Vertex / Ollama / Qwen / vLLM). Streaming + retry + structured-output schemas. Provider-specific traits (Anthropic prompt caching) live in `providers/anthropic.py`, not as core LLM code.

### `shared/secrets/` (#9)
Vault adapter library. 5 adapters: OpenBao / HashiCorp Vault / AWS Secrets Manager / Azure Key Vault / GCP Secret Manager (+ Infisical / 1Password). InMemoryAdapter for tests. `get_secret(path)` is the only public entry; rotation + caching + audit-log fingerprint logged on every fetch.

### `shared/identity/` (#25)
OIDC client library. Keycloak client + FastAPI middleware (`current_user` dep) + RBAC scopes + `feature_flag_lightening.py` (per-tier enforcement of the matrix in `keycloak/tier-config.md`). The Hub trusts only Keycloak; customer's IdPs broker into Keycloak.

### `shared/runtime/`
Substrate migrated from `lib/` in Wave 3: `vitals.sh`, `heartbeat.sh`, `watchdog.sh`, `notify.sh`, `executor.sh`, `usage-parsers.sh`, `file-lock.sh`, `updater.sh`, `db-outbox.sh`. Plus `hygiene.py` (#34 — workspace hygiene with Conductor gate).

### `shared/charters/` (#7)
Industry-anchored role charters replacing `lib/role-prompts/`. 19 charters: 13 REBUILDs (architect→TOGAF+arc42, auditor→NIST 800-53+Cite-or-Refuse, conductor→Scrum+SAFe, datawright→DAMA-DMBOK+Kimball, engineer→#13 tier-bifurcation+Clean Code, operator→SRE-internal+12-factor, planner→PMBOK 7+Scrum, product→Inspired+JTBD, qa→ISTQB, researcher→Cite-or-Refuse+IDEO+NN/g, ux→Nielsen+WCAG 2.2) + 6 NEW (devops, customer_support, compliance_officer, security_engineer, tech_writer, release_manager).

### `shared/integrations/`
External connectors. GitHub, Linear, Jira, Slack, PagerDuty, Twilio, Teams, AWS, Azure, GCP, Railway, Fly.io (Part 4.2 choice), DO, Vanta, Drata, Secureframe.

### Other `shared/*`
`mcp/` unified MCP server (42 tools across all subsystems as of Wave 4), `audit/` hash-chained ledger (writer + ALLOWED_SUBSYSTEMS extended for v3 subsystems), `standards/` org bundles + drift detector + validator + install_bundle.sh, `calibration/` Platt scaling, `cost/` cost router (per-user/org hard caps), `eval/` golden-suite eval harness, `memory/` 3-tier scope + playbook store + writer hooks (per #27), `notify/` 8+ event types incl. `decision_card`, `validation/` cross-LLM consensus, `schemas/` Pydantic v2 models, `skills/` skill auto-trigger, `api/` FastAPI routes + middleware (OIDC + feature-flag + RBAC), `ui/` dashboard SPA (Svelte chosen per Part 4.1 decision).

---

## 5. Cross-cutting tech stack (LOCKED)

| Concern | Choice | Lives in | Driver |
|---|---|---|---|
| Orchestration core | Bash + Postgres | `orchestrator/lib/` + `db/` | KEEP — debuggability moat |
| Verify pipeline | Python + FastAPI + Temporal (TRON inheritance) | `verify/` | KEEP — TRON existing |
| Knowledge Graph | Postgres `spine_kg` schema + pgvector + tree-sitter parsers | `db/` + `build/kg/` | KEEP — Spine v2 inheritance |
| LLM call surface | 7-provider library | `shared/llm/` | #2 |
| Vault | OpenBao bundled + 5 adapters | `vault/` + `shared/secrets/` | #9 |
| Identity | Keycloak embedded + OIDC client | `keycloak/` + `shared/identity/` | #25 |
| Frontend framework | Svelte | `shared/ui/dashboard/` | Part 4.1 decision |
| MCP server | Unified, 42+ tools | `shared/mcp/` | KEEP |
| Audit log | Append-only hash-chained Postgres | `db/V15` + `shared/audit/` | #24 |
| Standards / policy | Org bundles, signed, federation-distributed | `shared/standards/` | #7 #16 |
| Memory & lessons | 3-tier scope + per-role MD + Postgres index | `shared/memory/` | #27 |
| Sandbox execution | Docker ephemeral + seccomp (TRON existing) | `verify/sandbox/` | KEEP |
| Confidence calibration | Platt scaling | `shared/calibration/` | KEEP |
| Cross-LLM consensus | 7-provider validator | `shared/validation/cross_llm.py` | #2 + #27 |
| Federation | mTLS + bearer via vault; signed bundle cascade | `federation/` | #4 #10 #16 |
| Licensing | Ed25519 signed bundles; hash-chained quota; per-gate flag | `license/` | #23 |
| Evidence | 5 collectors → Vanta/Drata/Secureframe push | `evidence/` | #24 |
| Learning | 3-tier scope + cross-org consent + k=5 anonymizer | `learning/` | #27 |
| Recovery | 12-layer DR + auto-generated runbook | `recovery/` | #31 #32 |
| Migration | Export/import + version migrator + onboarding connectors | `migration/` | #33 |

---

## 6. Deployment shapes (#17 + #20)

| Shape | Operator | Where it runs | Tier |
|---|---|---|---|
| Laptop | Customer | Docker Desktop on macOS/Linux/Windows-WSL2 | Free |
| Vendor-Managed (BYOC) | Spine vendor via delegated IAM role | Customer's AWS / Azure / GCP / Railway / Fly.io / DigitalOcean / Hostinger account | Founder |
| Self-hosted customer-cloud | Customer | EKS / AKS / GKE | Team / Enterprise |
| Self-hosted on-prem | Customer | Vanilla K8s / OpenShift / Rancher | Enterprise |
| Air-gapped (v1.1) | Customer | Air-gapped infrastructure | Defense / classified |

Operational detail: `docs/DEPLOYMENT_SHAPES.md`.

---

## 7. Critical path

Per Build Sequence §2.2:

```
shared/secrets/ → shared/identity/ → hub/ container → Hub web SPA → landing-docs rewrite → v1.0 ship
```

Off-critical-path (parallelizable but ship-blocking): license, federation, evidence, learning, recovery, migration, mobile, voice.

---

## 8. Bundle inheritance model

Per Build Sequence §1.3 (federation pipeline customization decision) + cross-cutting pattern §9:

```
parent Hub bundle  →  child Hub overrides  →  project bundle overrides
```

Same mechanism for: federation, licensing, learning policy, comm prefs, DR policy, devops planes. Child can EXTEND but not CONTRACT phases unless parent declared `removable: true`. Consent-leaning federation (#10) — peer-consent default; bounded mandatory upward flows declared in bundle for compliance.

---

## 9. What's archived

- v2 architecture (single-project assumption, INIT-1/6/7/8/9 framing): `docs/_archived/v2-ARCHITECTURE.md`
- v2 PRD: `docs/_archived/v2-PRD.md`
- v2 README / INSTALL / install.sh / positioning / db README: `docs/_archived/v2-*`

---

## 10. What's still incrementally landing (rebuild-in-progress)

This v3 architecture is the **layout authority**. The following sections are deliberately deferred to per-subsystem READMEs OR forthcoming dedicated docs:

- Per-subsystem internals → each subsystem's `README.md` is canonical for its module structure, file inventory, tests, contract with siblings.
- Migration phases (v2 → v3 cutover) → `docs/V3_BUILD_SEQUENCE.md` §Part 3 Waves 0–6.
- v1 → v1.1 + v1.1 → v2 migration plans → `migration/README.md` (Wave 5 Squad F).
- DR architecture detail → `docs/DR_RUNBOOK.md`.
- Security architecture → `docs/SECURITY_GUIDE.md`.
- Federation operational detail → `docs/FEDERATION_GUIDE.md`.
- License architecture detail → `docs/LICENSING_GUIDE.md`.
- Hub operational detail → `docs/HUB_OPERATIONS_GUIDE.md`.

**A full incremental rebuild of this doc is sequenced for Wave 6** — once all subsystem READMEs stabilize the file inventory + contract surface. Until then, this doc + per-subsystem READMEs are jointly authoritative.

---

## 11. Related artifacts

- [`docs/V3_DESIGN_DECISIONS.md`](V3_DESIGN_DECISIONS.md) — 34 locked decisions
- [`docs/V3_TRIAGE.md`](V3_TRIAGE.md) — ~383 files triaged
- [`docs/V3_BUILD_SEQUENCE.md`](V3_BUILD_SEQUENCE.md) — 7-wave plan with critical path, dependency graph, per-wave acceptance
- [`docs/STATUS.md`](STATUS.md) — wave-by-wave state of v3 rebuild
- [`docs/PRD.md`](PRD.md) — 13 REQ-INIT-N sections
- [`docs/positioning.md`](positioning.md) — strategic story
- `hub/README.md`, `vault/README.md`, `keycloak/README.md`, `federation/README.md`, `license/README.md`, `evidence/README.md`, `learning/README.md`, `devops/README.md` — per-subsystem authoritative docs
- [`db/README.md`](../db/README.md) — Postgres schema V1–V35

---

**Document control:**
- v3 refresh: 2026-05-18 (Wave 5 Squad G, focused REFRESH per scope brief — full rebuild incremental in Wave 6)
- Authority: v3 top-level layout per Build Sequence Part 1.1; v3 cross-cutting tech stack per §5 above
- Supersedes: v2 framing (single-project umbrella, TRON-only verify boundary); archived at `docs/_archived/v2-ARCHITECTURE.md`
- Next update trigger: any new top-level subsystem locked, OR Wave 6 incremental rebuild
