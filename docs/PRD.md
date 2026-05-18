# Spine — Product Requirements (PRD)

> Canonical product requirements document for **"AI software company in a box"** (per [`V3_DESIGN_DECISIONS.md`](V3_DESIGN_DECISIONS.md) **#1**).
>
> Each REQ has a stable section anchor (`#req-init-N`). Cross-references from `BACKLOG.md`, `ARCHITECTURE.md`, and elsewhere link directly to those anchors.
>
> **Status legend:** *Draft v1* (awaiting first sign-off) · *Approved* (locked, work can proceed) · *Superseded* (new REQ replaces this one; keep for history)
>
> **Source posture (#18):** every REQ here describes capability of the v1.0 closed-source product. OSS license question deferred.

## Index

| Anchor | REQ | Initiative | Status |
|---|---|---|---|
| [#req-init-1](#req-init-1) | Plan Subsystem — intake → PRD → TRD → Roadmap | INIT-1 | **Approved** |
| [#req-init-2](#req-init-2) | Hub — containerized product (Hub-as-product) | INIT-2 | **Draft v1** |
| [#req-init-3](#req-init-3) | Federation — fractal Hub topology | INIT-3 | **Draft v1** |
| [#req-init-4](#req-init-4) | Operate Subsystem — 6th corner + 8 control planes | INIT-4 | **Draft v1** |
| [#req-init-5](#req-init-5) | Vault-only secrets | INIT-5 | **Approved** |
| [#req-init-6](#req-init-6) | Identity — Keycloak embedded | INIT-6 | **Approved** |
| [#req-init-7](#req-init-7) | LLM-agnostic by architecture | INIT-7 | **Approved** |
| [#req-init-8](#req-init-8) | Feature-flag licensing + signed bundles | INIT-8 | **Draft v1** |
| [#req-init-9](#req-init-9) | Compliance evidence pipeline (Vanta/Drata/Secureframe) | INIT-9 | **Draft v1** |
| [#req-init-10](#req-init-10) | Smart Spine — 3-tier learning | INIT-10 | **Draft v1** |
| [#req-init-11](#req-init-11) | Disaster recovery — 12 layers, built properly | INIT-11 | **Draft v1** |
| [#req-init-12](#req-init-12) | Migration tooling — 4 concerns | INIT-12 | **Draft v1** |
| [#req-init-13](#req-init-13) | Verify Subsystem — TRON + Cite-or-Refuse contract | INIT-13 | **Draft v1** |

---

## Cross-cutting context

Spine v3 is **enterprise-grade software for orgs OR individuals who want production software** (#1). NOT a vibecoder one-off generator. NOT SaaS (#15). NOT closed in a single LLM vendor (#2). NOT a template you drop into a project — the **Hub IS the product** (#3).

Spine ships a **single containerized Hub** that customers run on laptop / BYOC / customer-cloud / on-prem (#17). The Hub is the **primary management surface**; CLI is a power-user tool. The Hub bundles vault (OpenBao default per #9), identity (Keycloak per #25), Postgres, and the FastAPI app, plus a Day-0 wizard that bootstraps everything.

Spine **actively pushes** to the human (#5): AI Scrum Master / PM / Release Manager / Compliance Officer push briefings + decision cards on the human's chosen channels (web / Slack / email / SMS / WhatsApp / Teams / PagerDuty for incidents) (#6).

Spine **federates** fractally (#10): the same Hub container at team / division / enterprise / corporate tier. Updates cascade vendor → corporate → division → team (#16), each tier admin approves; auto-push never.

Spine is **closed-source v1.0** (#18). Trust comes from SOC 2 + pen tests + source escrow + audit chain + design-partner case studies — not from GitHub stars.

Spine is **built by Spine** (#21). The vendor's own deployment is the proving ground for every feature before it ships.

---

## REQ-INIT-1

**Plan Subsystem — Intake → PRD → TRD → Roadmap (SDLC front door)**

| | |
|---|---|
| **Status** | **Approved** (locked 2026-05-16; v3 framing applied 2026-05-18) |
| **Owner** | Khash Sarrafi |
| **Drivers** | #5 (active push), #7 (industry-anchored roles), #19 (7 work-item types), #21 (ALL AI) |

### 1.1 Summary

Build the **upfront SDLC pipeline** that takes someone from "I have an idea" to "fully baked, signed-off PRD + TRD + Roadmap, ready to execute." Three phases: **Product Discovery → Technical Review (swarm) → Decomposition**, each producing a signed artifact, each gated on user approval, all cost-aware-tier-routed, all declaratively customizable.

### 1.2 Problem

A human with a vague idea ("I want to build an app for managing my team's time off") either gets a hallucinated build with wrong assumptions, or has to write a detailed directive cold — which they can't, because they don't yet know what they want. Spine refuses to build until the spec is real. The `product` role runs a **5-move dialogue protocol** (naive cast → provoke correction → reframe → tier MUST/SHOULD/COULD → produce the PRD artifact). A PRD with any `TBD` field cannot be marked complete.

### 1.3 Goals

#### MUST (P0)
- Pipeline produces three signed artifacts in order: **PRD**, **TRD**, **Roadmap** — each a real file with defined schema (Pydantic), not a chat transcript.
- Each phase gated on **explicit user sign-off** via Hub Decision Queue card.
- Pipeline definition is **declarative** YAML (`sdlc-pipeline.yaml`) editable by roles with `can_modify_sdlc_pipeline` capability.
- Technical-review runs as a **swarm of supporting roles** synthesized by the architect.
- **Cost-aware tier routing** built in (per-phase defaults; per-user/org budget enforcement via `shared/cost/`).
- **Per-work-item-type intake templates** for all 7 types (#19): feature / bug / incident / support / refactor / infra / compliance.

#### SHOULD (P1)
- **Hub web SPA** is the primary front door — drop-a-project form, approval queue, cost meter, live phase status (#3).
- Pipeline manifest **versioned in git** with author / timestamp / rationale.
- Projects **lock to a pipeline version** at start.
- Approval gates support **request-changes** (routing back with notes).
- **Active push** notifications on decision cards (#5) via per-user channel prefs (#6).

#### COULD (P2)
- Multi-approver gates (TRD requires CTO + Compliance to both sign).
- Cost projection at start of each phase.
- Pipeline templates for org archetypes (startup-lite, regulated-enterprise, design-led).

#### WON'T (out of scope)
- SaaS multi-tenant hosting — Spine is self-hosted at every tier (#15).
- Replacing Jira / Linear — Spine produces a Roadmap that *exports* to those tools.

### 1.4 Functional requirements

**FR-1 — Pipeline-as-data manifest.** YAML declares phases, role leads, swarm composition, artifact templates, tier defaults, gates. Override hierarchy: org bundle → team → project (most-specific wins). Bundle inheritance supports federation per #10 (parent Hub bundle → child Hub overrides → project overrides).

**FR-2 — 5-move intake.** `product` role enforces naive-cast → provoke → reframe → tier → artifact. Each move logged to audit chain (#24).

**FR-3 — Swarm-driven TRD.** Architect role synthesizes a per-project swarm (researcher / engineer / security_engineer / qa / operator / devops as needed); LangGraph subgraph runs inside architect daemon.

**FR-4 — Cost-aware tier router.** Every phase declares a `tier_default ∈ {low, medium, high}`. Per-user budget enforcement is **hard caps, not warnings**. Router lives in `shared/cost/` and routes to one of 7 LLM providers per `shared/llm/` (#2).

**FR-5 — Approval gates emit decision cards.** On phase boundary, gate emits a `decision_card` event to `shared/notify/`; user gets pinged on their chosen channel (#6).

### 1.5 Acceptance

- All 7 work-item types route through correct intake template + phase pipeline.
- Pipeline edits gated on `can_modify_sdlc_pipeline` capability per bundle policy.
- Smoke test exercises Plan → Build → Verify thread for at least one type end-to-end.

---

## REQ-INIT-2

**Hub — containerized product (Hub-as-product)**

| | |
|---|---|
| **Status** | **Draft v1** |
| **Drivers** | #3 (Hub-as-product), #17 (4 deployment shapes), #21 (AI-drivable wizard), #25 (Keycloak embedded) |

### 2.1 Summary

The Hub is the **primary management surface** of Spine. Single container shipping vault (OpenBao), Keycloak, Postgres, Flyway migrations, the FastAPI app, and the Day-0 bootstrap wizard. Runs in all four deployment shapes (laptop / BYOC / customer-cloud / on-prem).

### 2.2 Goals

#### MUST (P0)
- **Hub container** with multi-arch (amd64+arm64) Docker image, non-root user, healthcheck, signed by vendor (cosign), pulled from `ghcr.io/spine/hub`.
- **Day-0 wizard** with 7 steps (`hub/wizard/init.sh`): shape / vault / keycloak / llm / admin / license / parent-hub. **Every prompt has a `--flag` equivalent** so an AI agent can drive the wizard non-interactively (#21).
- **9 Hub surfaces:** dashboard, master roles, registry, audit, vault config, integrations, decision queue, "talk to a role" chat, federation hub-switcher.
- **Mobile-responsive Hub UI** (#28) — works on iPhone Safari + Android Chrome.
- **OIDC login** via Keycloak (#25); session persistence; logout.

#### SHOULD (P1)
- Hub-extended REST API (`shared/api/routes/{decisions,role_chat,registry,vault_config,integrations,federation,license}.py`) with OpenAPI 3.x spec (#30).
- Remote MCP transport (mTLS + bearer) for cross-Hub federation (#4, #10).

#### COULD (P2)
- Embedded terminal in Hub UI for power users.

### 2.3 The 9 enumerated surfaces

| Surface | What it does |
|---|---|
| Dashboard | KPIs across projects, active workers, recent decisions, cost meter |
| Master roles | One Master per discipline; clickable to chat / brief / re-task |
| Registry | All projects, all Hubs, all federated subsidiaries |
| Audit | Hash-chained ledger view + search + Vanta/Drata push status |
| Vault config | Adapter status, rotation schedule, secret-access audit |
| Integrations | GitHub / Linear / Jira / Slack / PagerDuty / Twilio / Teams / clouds / GRC |
| Decision queue | All open decision cards across all projects, owner + due-by + risk |
| Talk to a role | Chat UI to any Master role (#5 — active push from role's side) |
| Federation hub-switcher | Drop-down: switch context between team / division / enterprise Hub (#10) |

### 2.4 Acceptance

- `docker run spine/hub:v3` exposes web UI on `:8090`; healthcheck green
- All 9 surfaces render after OIDC login
- `bash hub/wizard/init.sh --no-interactive --shape laptop --vault openbao --keycloak bundled --llm anthropic --admin-email a@b.c` succeeds end-to-end

---

## REQ-INIT-3

**Federation — fractal Hub topology**

| | |
|---|---|
| **Status** | **Draft v1** |
| **Drivers** | #4 (control plane / data plane split), #10 (a Hub is a Hub), #16 (update cascade with per-tier approval) |

### 3.1 Summary

Spine federates fractally: **the same Hub container at every tier** (team / division / enterprise / corporate). Hubs register child Hubs alongside projects. Updates cascade vendor → parent → child with **approval gate at each tier**. Trust model: peer-consent by default; bounded mandatory upward flows declared in bundle for compliance (e.g., *"all subsidiary Hubs report security incidents upward"*).

### 3.2 Goals

#### MUST (P0)
- Parent Hub registers child Hub via `federation/hub_registry.py` (consumes `hub/_state/hub_id.txt`).
- `federation/upstream_client.py` mTLS + bearer auth via vault (#9); paths `federation/mtls/<role>/cert`, `…/key`, `federation/bearer/<role>`.
- `federation/update_cascade.py` distributes signed bundles vendor → parent → child; per-tier admin approval (#16) via Hub decision queue.
- `federation/consent.py` — peer-consent default + bounded mandatory upward flows from bundle policy.
- Aggregated reads pull up the tree; raw data never crosses tier boundary unless bundle policy explicitly permits.

#### SHOULD (P1)
- Hub UI federation switcher for context-aware viewing across owned Hubs.
- Federation update history visible in audit log.

#### COULD (P2)
- Cross-tier role chat (Master CTO at corporate can ping Master CTO at subsidiary).

### 3.3 Acceptance

- Two Hubs federate (parent registers child; child fetches parent bundle).
- Update from vendor cascades vendor → parent → child with approval gate at each tier.
- Bundle-mandated upward security-incident flow tested end-to-end.

---

## REQ-INIT-4

**Operate Subsystem — the 6th corner + 8 control planes**

| | |
|---|---|
| **Status** | **Draft v1** |
| **Drivers** | #11 (Operate subsystem), #19 (work-item types include `infra` + `incident`), #34 (workspace hygiene) |

### 4.1 Summary

Spine builds AND operates production. Every competitor stops at "ship the code." Spine ships the **Operate subsystem** with a dedicated `devops` role (customer-facing, **distinct from `operator` which is Spine-internal**) and **8 control planes**, each with its own state, vendors, blast radius, and human-in-loop seam.

### 4.2 The 8 control planes (#11)

| # | Plane | Owner role | Examples |
|---|---|---|---|
| 1 | Compute | devops | container restarts, autoscaling, scheduled jobs |
| 2 | Network | devops | DNS, load balancer rules, ingress, mTLS rotation |
| 3 | Data | devops + datawright | DB backups, restore tests, schema migrations |
| 4 | Identity | devops + security_engineer | Keycloak realm changes, IdP federation, SCIM sync |
| 5 | Secrets | devops + security_engineer | Vault rotation, AppRole renewal, audit |
| 6 | Observability | devops + operator | Metrics, logs, traces, alert routing |
| 7 | Incident | devops + security_engineer + release_manager | Pager routes, runbooks, postmortems |
| 8 | Workspace hygiene | devops + conductor | `.spine/work/` lifecycle, `.spine/archive/` sweep, stale-run cleanup (#34) |

### 4.3 Acceptance

- `devops` role distinct from `operator` (no conflation, per #11 explicit).
- Each control plane has its own MCP tool surface in `shared/mcp/tools/devops.py`.
- Conductor refuses to mark a project done if uncleaned workspace exists for it (#34 §5).

---

## REQ-INIT-5

**Vault-only secrets**

| | |
|---|---|
| **Status** | **Approved** |
| **Drivers** | #9 (vault-only, OpenBao Day-0 default) |

### 5.1 Summary

**No exceptions.** No `env://`. No built-in secret store. Spine never holds customer secrets. Day-0 default: wizard-installed OpenBao container.

### 5.2 Acceptance

- Adapters: HashiCorp Vault / AWS Secrets Manager / Azure Key Vault / GCP Secret Manager / Infisical / 1Password — all in `shared/secrets/`.
- Zero grep hits for `os.environ.get("SPINE_*` outside `shared/secrets/`.
- Day-0 wizard (`vault/init-wizard.sh`) initializes OpenBao with Shamir 3-of-5 or KMS auto-unseal (operator chooses).

---

## REQ-INIT-6

**Identity — Keycloak embedded**

| | |
|---|---|
| **Status** | **Approved** |
| **Drivers** | #25 (Keycloak embedded + feature-flag lightening per tier) |

### 6.1 Summary

Keycloak ships as a **sibling container alongside Hub**. JVM dep accepted as cost of mature feature set + enterprise-recognized name + 10+ years production hardening. Hub uses Keycloak as OIDC provider; never directly handles SAML/SCIM/social-login/MFA. Customer's existing IdP federates into Keycloak as brokered upstream.

### 6.2 Tier matrix (per `keycloak/tier-config.md`)

| Tier | Capabilities |
|---|---|
| Free / laptop | Single realm, basic username+password, no MFA, no IdP federation |
| Founder (BYOC) | + MFA optional, social login, single IdP federation |
| Team | + MFA required, multi-IdP, basic SCIM |
| Enterprise | + Full SCIM 2.0, multi-realm, advanced password policy, custom themes, audit export |
| Air-gapped (v1.1) | Works fully; social login disabled |

### 6.3 Acceptance

- Day-0 wizard installs Keycloak + generates admin credentials (into vault) + creates default realm + configures Hub as OIDC client (`keycloak/init-bootstrap.sh`).
- `feature_flag_lightening.py` in `shared/identity/` enforces tier matrix.

---

## REQ-INIT-7

**LLM-agnostic by architecture**

| | |
|---|---|
| **Status** | **Approved** |
| **Drivers** | #2 (7 providers Day 1) |

### 7.1 Summary

All LLM calls go through `shared/llm/`. Routes across **Anthropic / OpenAI / Bedrock / Vertex / Ollama / Qwen / in-house vLLM**. Customer chooses primary; multiple providers can be configured. Provider-specific traits (prompt caching, structured-output schemas) are provider methods, not hardcoded.

### 7.2 Acceptance

- `shared/llm/providers/{anthropic,openai,bedrock,vertex,ollama,qwen,vllm}.py` — all implemented.
- `shared/cost/prompt_cache.py` replaced by `shared/llm/providers/anthropic.py` cache trait.
- Cross-LLM consensus (#27 — disagreement as learning signal) runs across all 7 providers in `shared/validation/cross_llm.py`.

---

## REQ-INIT-8

**Feature-flag licensing + signed bundles**

| | |
|---|---|
| **Status** | **Draft v1** |
| **Drivers** | #23 (Day-1 architectural primitive), #16 (federation distribution), #18 (closed-source — license is the anti-piracy seam) |

### 8.1 Summary

**Pricing deferred** until product is built. **Feature-level access control is a Day-1 architectural primitive.** Any pricing model — per-feature solo, bundled tiers mid-market, custom contracts enterprise — is mechanically supported when ready to set numbers.

### 8.2 Architecture

- **Every feature has a flag.** From `federation.enabled` to `integrations.pagerduty` to `customer_support.role` to `max_projects` to `aws.provisioning`.
- **License bundle = signed Ed25519 bundle from vendor.** Reuses `shared/standards/` bundle infrastructure.
- **Hub validates signature** on startup + periodically (default 1h) + on every feature gate.
- **`license.is_enabled("flag_name")` at every entry point.** If disabled: graceful UI message + "upgrade to unlock" path. **Licensing as discovery, not a wall.**
- **Per-feature usage metering Day 1** even when not billed (hash-chained `quota_ledger`).
- **License grants ride the federation tree** (#16) — parent Hub distributes child Hub licenses through same approval cascade.

### 8.3 Vendor key custody

Per Part 4.3 decision: vendor uses own vault for signing key + Shamir 3-of-5 recovery (HashiCorp Enterprise pattern). `tools/license-sign.sh` is the vendor-side signing CLI. Trust anchor: `TRUSTED_VENDOR_FINGERPRINT` baked into Hub binary at build time.

### 8.4 Acceptance

- `license_get_status` / `license_get_usage` / `license_verify_bundle` MCP tools shipped.
- Hub refuses to expose a feature whose flag is OFF; surfaces "upgrade" CTA.
- Pricing experimentation = changing bundle content, not refactoring code.

---

## REQ-INIT-9

**Compliance evidence pipeline (Vanta / Drata / Secureframe)**

| | |
|---|---|
| **Status** | **Draft v1** |
| **Drivers** | #24 (3 GRC integrations Day 1; two-party attestation) |

### 9.1 Summary

Spine's **hash-chained audit chain IS the SOC 2 evidence pipeline.** Every audit event — PRs, deploys, approvals, config changes, role authorizations, vault access, capability grants, drift remediations — pushed into customer's Vanta / Drata / Secureframe vault automatically.

### 9.2 Two flows

- **Read:** `compliance_officer` role queries GRC APIs for control status, evidence gaps, audit-prep checklists, deadline tracking.
- **Write:** Spine pushes every relevant audit event into GRC. **Spine becomes the highest-velocity SOC 2 evidence producer in the customer's stack.**

### 9.3 Two-party attestation

Customer's auditor sees evidence in Vanta + corroborates against Spine's hash-chained log + matches → trust. Regulatory-grade.

### 9.4 Startup-tier value

At startup tier, audit chain produces SOC 2-grade evidence **automatically as byproduct of using Spine**, NOT gated. When startup adds Vanta/Drata, Spine immediately pushes existing trail backwards. **"We started SOC 2 today"** means **"we have months of evidence already collected."**

### 9.5 Acceptance

- 5 collectors: `audit_chain` / `role_decision` / `vault_access` / `deploy` / `approval`.
- 3 real exporters (Vanta / Drata / Secureframe) + 3 v1.1 stubs (Tugboat / StrikeGraph / Thoropass).
- Two-party SHA-256 attestation per V25 schema.

---

## REQ-INIT-10

**Smart Spine — 3-tier learning**

| | |
|---|---|
| **Status** | **Draft v1** |
| **Drivers** | #27 (3-tier learning architecture), #12 (Cite-or-Refuse contract — evidence must be cited) |

### 10.1 Summary

Spine learns at 3 tiers. **Default on at per-project + within-Hub; opt-in at cross-org.** Vendor self-improvement is Tier 3 (vendor's own Spine eats its own dogfood).

### 10.2 Tiers

| Tier | What learns | Default |
|---|---|---|
| 1a — Per-project | Each project Spine learns from its own work (codebase patterns, prior decisions, role outcomes, calibration) | Always on |
| 1b — Within-Hub | Lessons flow between project Spines under same Hub federation tree; Master roles aggregate | **Default ON.** Admin can disable for joint ventures / legally-isolated subsidiaries |
| 2 — Cross-org | Vendor learns statistical patterns across all customers; publishes improved role charters / bundles / scanner rules via federation (#16) | **Default OFF.** Customer must explicitly opt in via Hub UI consent flow. Granular per data class. Anonymized + aggregated only; no raw data. |
| 3 — Vendor self-improvement | Vendor's own Spine deployment improves the product. Drift audits, calibration, eval-on-every-release | Always on (vendor choice) |

### 10.3 Required build (per #27)

12 explicit items including: memory writer hooks (7 trigger points), KG retrieval at every role action, calibration outcome capture, KG indexer firing, Master role aggregation, lesson promotion ladder, anonymized telemetry pipeline, eval harness on every release, retro role wired up, cross-LLM consensus as learning signal, *"Spine knows you"* UX.

### 10.4 Acceptance

- Lesson written at project tier → aggregated to within-Hub under default-ON → cross-org consent flow denies by default, opt-in via Hub UI.
- `learning_scope` / `learning_contribute` / `learning_consent` / `learning_telemetry` MCP tools shipped.

---

## REQ-INIT-11

**Disaster recovery — 12 layers, built properly**

| | |
|---|---|
| **Status** | **Draft v1** |
| **Drivers** | #31 (DR built properly, not scaffold), #32 (12 layers) |

### 11.1 Summary

Cost of getting DR wrong = *"customer loses their AI team's institutional memory."* Non-negotiable. Auto-recovery + immediate notification + tested restore.

### 11.2 The 12 layers (#32)

| # | Layer | RPO / RTO |
|---|---|---|
| 1 | Container auto-recovery (K8s replicas + probes; watchdog for non-K8s) | 30s from container death |
| 2 | Process supervision (per-role daemons + circuit breaker on flapping) | 30s from role-daemon crash |
| 3 | Continuous data backup (PG WAL + Vault snapshots + KG state → S3/GCS/Azure Blob/MinIO/Wasabi, KMS-encrypted) | RPO ≤ 5 min |
| 4 | Tested data restore (weekly default — restore-to-throwaway-environment) | RTO ≤ 30 min full Hub |
| 5 | Heartbeat protocol (self + federation parent + vendor status registry, opt-in) | Detection ≤ 1 min |
| 6 | Federation autonomy (per #10, child Hubs keep working if parent down) | Always-on |
| 7 | Cross-region replication (active-passive opt-in per bundle, enterprise tier flag `dr.cross_region`) | RPO ≤ 5 min / RTO ≤ 10 min |
| 8 | Vault unseal recovery (Shamir 3-of-5 OR cloud-KMS auto-unseal) | Manual or auto |
| 9 | Soft-delete with 7d retention; full deletion requires HMAC double-confirmation | Recoverable 7d |
| 10 | Vendor update infrastructure DR | Customers unaffected by vendor outage |
| 11 | DR runbook (auto-generated per deployment; updated on bundle/topology change) | Always current |
| 12 | Backup verification on every release | Continuous |

### 11.3 Acceptance

- Weekly DR test runs on schedule; failure pages oncall.
- Kill Hub container; restore from backup; Hub functional in < 30 min.
- DR runbook auto-generates per deployment per `recovery/runbook_generator.py` (Wave 5 Squad E).

---

## REQ-INIT-12

**Migration tooling — 4 concerns**

| | |
|---|---|
| **Status** | **Draft v1** |
| **Drivers** | #33 (4 distinct concerns), #15 (NOT SaaS → portability proves no lock-in) |

### 12.1 The 4 concerns

| Concern | v1.0 treatment |
|---|---|
| A — Onboarding migration (import customer's GitHub / Linear / Jira / Confluence / Notion data) | **Scaffold** connector interface + ship GitHub + (Linear OR Jira) Day 1 |
| B — Spine portability (move Spine deployment between shapes or clouds without losing audit / KG / charters / bundle / vault refs / memory / history) | **Build properly Day 1.** Non-negotiable for "no lock-in" claim |
| C — Software-migration-as-work-type (Spine helps customer migrate THEIR product: Python 3.8→3.12, etc.) | **v1.1** (specialized intake template + pipeline variant) |
| D — Spine version migrations (when vendor publishes v2.0 with breaking changes) | **Build properly Day 1.** N-2 cross-version compat commitment |

### 12.2 Strategic value of B

The structural answer to enterprise procurement's *"what's our exit strategy?"* question. Closed-source + self-hosted raises *"what if your company goes away?"* The answer: *"export your full state at any time; audit chain proves it's complete; recreate on whatever you want. **We've explicitly designed Spine so you can leave.**"* Export format becomes a **marketing artifact** — published spec, sample download, demonstrably round-trippable. *"Try Spine; we already proved you can leave."*

### 12.3 Acceptance

- Migration B: export full Spine state from Hub A; import to fresh Hub B on different cloud; audit-chain verifies; KG reproduces; identical decision history.
- Migration A: GitHub repos + Linear issues import; map to Spine projects + work items.
- Migration D: v1.0 → v1.1 simulated upgrade migrates DB/bundle/charter/vault/KG without data loss; downgrade blocked with clear error.

---

## REQ-INIT-13

**Verify Subsystem — TRON + Cite-or-Refuse contract**

| | |
|---|---|
| **Status** | **Draft v1** |
| **Drivers** | TRON inheritance, #12 (Cite-or-Refuse contract), Part 1.4 (10 Spine ↔ TRON boundary resolutions) |

### 13.1 Summary

Verify subsystem inherits TRON (`git subtree` into `verify/`). Per #12, **verify-class roles** (auditor / qa / verify) must cite supporting evidence (KG node ID, file:line, prior audit row hash) **or refuse to act**. Refusal is itself an audit event.

### 13.2 Boundary resolutions (Part 1.4)

| # | Question | Resolution |
|---|---|---|
| 1 | Bundle vs optional per shape | **Bundled** with Hub in all 4 shapes Day 1; v1.1+ may add remote-verify flag |
| 2 | Vault migration timing | **Wave 0** — `verify/.env` migrated to vault refs before any other Wave 0 work shipped |
| 3 | Audit-chain federation | **Hash-link** — Spine chain anchors TRON chain via SHA-256 anchor records |
| 4 | Autonomous-engineer self-verify | **Always defer to separate verify role** — implementer never grades own work (#12) |
| 5 | License inventory of 40+ TRON deps | **Wave 5 dedicated gate** — audit + replace GPL/AGPL before ship |
| 6 | TRON's LLM provider | Routes through `shared/llm/` (#2) |
| 7 | TRON sandbox compute attribution | Verify cost ledger — sandbox CPU/mem as new line item |
| 8 | TRON upgrade cadence | Follows Spine federation update flow (#16) as sub-bundle |
| 9 | Cite-or-Refuse boundary enforcement | Wrapper middleware in `shared/mcp/tools/verify.py` + `iso.py`; reject 422 if `citation` absent/malformed |
| 10 | Calibration outcomes capture | `shared/calibration/calibration_sink.py` helper called from every TRON invoke |

### 13.3 Acceptance

- Any verify-class MCP call without `citation` returns 422 with explicit Cite-or-Refuse message.
- `verify/.env` zero plaintext secrets; all references vault-fetched.
- Cross-LLM consensus runs against all 7 providers (#2 + #27).

---

## Related artifacts

- [`docs/V3_DESIGN_DECISIONS.md`](V3_DESIGN_DECISIONS.md) — 34 locked decisions (this PRD's drivers)
- [`docs/V3_TRIAGE.md`](V3_TRIAGE.md) — per-artifact KEEP/REFACTOR/REBUILD/BUILD-NEW/DELETE
- [`docs/V3_BUILD_SEQUENCE.md`](V3_BUILD_SEQUENCE.md) — 7-wave dependency-ordered execution plan
- [`docs/ARCHITECTURE.md`](ARCHITECTURE.md) — v3 top-level layout + subsystem map
- [`docs/positioning.md`](positioning.md) — strategic story
- [`docs/HUB_OPERATIONS_GUIDE.md`](HUB_OPERATIONS_GUIDE.md) — day-2 ops
- [`docs/DEPLOYMENT_SHAPES.md`](DEPLOYMENT_SHAPES.md) — 4 shapes × 7 clouds
- [`docs/FEDERATION_GUIDE.md`](FEDERATION_GUIDE.md) — parent / child setup
- [`docs/SECURITY_GUIDE.md`](SECURITY_GUIDE.md) — vault + closed-source compensations
- [`docs/LICENSING_GUIDE.md`](LICENSING_GUIDE.md) — flags + bundles + quotas
- [`docs/DR_RUNBOOK.md`](DR_RUNBOOK.md) — 12-layer DR operational
- [`db/README.md`](../db/README.md) — Postgres schemas V1–V35

---

**Document control:**
- v3 rewrite: 2026-05-18 (Wave 5 Squad G, per `V3_BUILD_SEQUENCE.md` §Part 3 Wave 5)
- Supersedes pre-v3 PRD that pitched single-project "drop Spine into your project" template framing (archived at `docs/_archived/v2-PRD.md`)
- Source of truth: every REQ here cross-references the decision(s) in `V3_DESIGN_DECISIONS.md` that drove it. If a decision changes, the corresponding REQ is the first thing to revisit.
