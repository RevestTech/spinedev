# Spine v3 — Design Decisions (34 locked)

> **Read first:** [`SPINE_MASTER.md`](SPINE_MASTER.md) for vision, gaps, and doc map.
> This file is the **decision ledger** (#1–#34). Origin:
> [`_archived/chatsession-2026-05-17.md`](_archived/chatsession-2026-05-17.md).
> Reconstructed from `chatsession.md` (~21k-line transcript). Triage agents (T1–T6) used these
> as drivers for the per-artifact KEEP/REFACTOR/REBUILD/BUILD-NEW/DELETE marks in `docs/V3_TRIAGE.md`
> (forthcoming).
>
> **Source of truth.** If a doc, role-charter, ARCHITECTURE, PRD, or BACKLOG conflicts with anything
> here, this doc wins until explicitly updated. T6 flagged this as the *first* v3 doc to lock,
> because everything else (ARCHITECTURE, PRD, READMEs, install scripts, operational guides) depends
> on it.
>
> **Numbering note.** Conversation transcript showed a numbering gap: first locked tracker enumerated
> #1–#10, then jumped to #13 without explicitly locking #11 and #12. `#11 = Operate subsystem (devops
> + 8 control planes)` (from R7 research + W2 reframe) and `#12 = Cite-or-Refuse contract` (from R3/R4
> research) were treated as locked by triage agents and have now been **formally ratified** in this
> doc (2026-05-17). **#34 = Workspace hygiene as architectural concern** was previously a flagged-but-unnumbered
> Spine design concern (per `feedback_workspace_hygiene` memory) and has been formally locked as #34
> in this doc (2026-05-17).
>
> **Annotations added 2026-05-29.** Four extension annotations (#7a, #7b, #12a, #30a) were ratified
> following [`docs/ECC_BORROWS.md`](ECC_BORROWS.md) review. Annotations refine an existing locked
> decision rather than introducing a new one; they bind contracts that the parent decision left
> unspecified. Source: ECC ([`affaan-m/ecc`](https://github.com/affaan-m/ecc), MIT) skill catalog,
> reviewed and adapted to Spine's architecture.

---

## Quick index

| # | Theme | Decision |
|---|---|---|
| 1 | Positioning | "AI software company in a box" |
| 2 | LLM stack | LLM-agnostic by architecture |
| 3 | Hub | Containerized product, primary management surface |
| 4 | Topology | Federation (control plane / data plane split) |
| 5 | Comms — outbound | Master roles actively push (briefings + decision cards) |
| 6 | Comms — channels | Per-user / per-decision-class / per-medium flexible |
| 7 | Roles | Charters anchored in industry standards |
| 7a | Charter regression | Pass@k eval gate when a charter is touched |
| 7b | Charter pre-implement | Engineer + Architect bind to a `search-first` contract |
| 8 | Authority | Two-tier (Master + project) hybrid authority + bounded override |
| 9 | Secrets | Vault-only, no exceptions, OpenBao Day-0 default |
| 10 | Federation | Fractal Hub — "a Hub is a Hub is a Hub" |
| 11 | Operate | 6th corner — devops role + 8 control planes |
| 12 | Verify contract | Cite-or-Refuse for verify-class roles |
| 12a | Promotion gate | Recursive confidence does not promote work to live; freshness + replay gates required |
| 13 | Engineer | Hybrid by tier, wrapper over Claude Code / Cursor / Aider / OpenHands |
| 14 | Target market | ALL three segments (solo founder → mid-market → enterprise) |
| 15 | Hosting | NOT SaaS. Self-hosted every tier |
| 16 | Updates | Distribution via federation tree with approval cascade |
| 17 | Deployment shapes | 4 modes Day 1 (laptop / BYOC / customer-cloud / on-prem); air-gapped v1.1 |
| 18 | Source posture | Closed-source v1.0 |
| 19 | Work-item types | All 7 Day 1 (feature/bug/incident/support/refactor/infra/compliance) |
| 20 | Cloud breadth | 5+ clouds Day 1 (AWS+Azure+GCP+Railway+Fly/DO) |
| 21 | Build team | ALL AI ALL THE TIME — solo human + AI orchestration |
| 22 | v2→v3 work | Intelligent per-artifact triage (this very exercise) |
| 23 | Pricing / licensing | Pricing deferred. Feature-flag licensing as Day-1 primitive |
| 24 | Compliance integrations | Vanta + Drata + Secureframe first-class Day 1 |
| 25 | Identity | Keycloak embedded by default, feature-flag lightening per tier |
| 26 | Business ops | Corp structure / IP / EULA / funding — deferred |
| 27 | Smart Spine | 3-tier learning (per-project / within-Hub default-ON / cross-org opt-in) |
| 28 | Mobile | SCAFFOLD for v1.0 + mobile-responsive web Day 1 |
| 29 | Voice | SCAFFOLD for v1.0 (Twilio stub) |
| 30 | API + MCP | SCAFFOLD for v1.0 — heavier (OpenAPI 3.x + Keycloak auth + RBAC + rate limits) |
| 30a | MCP envelope | Typed response envelope (`status`/`summary`/`next_actions`/`artifacts`); verify-class extends with `citations` |
| 31 | DR | BUILD properly for v1.0 (not scaffold) |
| 32 | DR architecture | 12 layers (see #32 detail) |
| 33 | Migration tools | 4 concerns (onboarding / portability / work-type / Spine version) |
| 34 | Workspace hygiene | Architectural concern — per-agent workspace dirs + auto-cleanup + Conductor gate |

---

## 1. Positioning

**"AI software company in a box"** — enterprise-grade software for orgs OR individuals who want
production software. NOT vibecoder one-offs.

**Sub-tagline:** *"AI does the work. AI scrum masters bring decisions to you. The audit log proves
you understood what you signed."*

---

## 2. LLM-agnostic by architecture

Routes across **Anthropic / OpenAI / Bedrock / Vertex / Ollama / Qwen / in-house (vLLM)**. Customer
chooses. Spine never marries one provider.

Implication: every LLM call must go through `shared/llm/` (T1 BUILD-NEW). Anthropic-specific code
(`shared/cost/prompt_cache.py`) becomes a provider trait. `shared/validation/cross_llm.py` provider
Literal extends to cover all 7 providers.

---

## 3. Hub = containerized product

Hub is the **primary management surface** — not a template you drop into projects (v1 framing
was wrong).

**Enumerated Hub surfaces (9):** dashboard / master roles / registry / audit / vault config /
integrations / decision queue / "talk to a role" chat / federation hub-switcher.

T6's #1 doc-cycle priority: rewrite README, INSTALL, ARCHITECTURE, PRD, positioning to reflect
Hub-as-product framing. T5 + T6 propose new top-level `hub/` directory for the containerized product.

---

## 4. Hub-to-project topology = federation

**Control plane / data plane split.** Project Spines run independently; register with Hub; bundle
distribution pushes policy; aggregated reads pull up. Same container supports single-cluster OR
distributed topology.

---

## 5. Active push communication

AI Scrum Master / PM / Release Manager / etc. **ACTIVELY communicate** with the business user.
Push briefings + decision cards. NOT just passive gates / pull-based dashboards.

This is the "managed shop" differentiator — competitors stop at the dashboard.

---

## 6. Communication preferences

Fully flexible **per-user, per-decision-class, per-medium** (web / Slack / email / SMS / WhatsApp /
Teams / PagerDuty for incident class).

Implication for `shared/notify/` (T1 REFACTOR): event vocabulary expands beyond 8 types to include
`decision_card`, `daily_briefing`, `weekly_briefing`, `incident_pageout`, `release_announcement`.
Rate limit must persist (federation needs it). Per-user prefs become first-class.

---

## 7. Role charters anchored in industry standards

Scrum Guide, PMBOK, SRE handbook, ITIL, NIST. Bundled artifacts distributed Hub→projects.
**Customer-editable via Hub UI** within bundle policy.

Implication: every charter in `shared/charters/` is industry-anchored (T5 marking complete).
Plus 6 NEW charters per #19 (devops / customer_support / compliance_officer / security_engineer /
tech_writer / release_manager).

---

## 7a. Charter regression — pass@k eval gate

> Annotation added 2026-05-29. Adapted from ECC `eval-harness` / `agent-eval` skills.

Charters are industry-anchored (#7) but currently lack a regression guarantee — a charter edit
can silently degrade role behavior. Any PR touching `shared/charters/*.md` must run the affected
role's capability eval suite and report **pass@k ≥ target** (default `pass@5 ≥ 0.8`). Eval
definitions live in `verify/charter_evals/<role>/`. Results are written to the audit ledger
(per #12a). Target thresholds are per-role and bundle-policy-overridable.

Implication: Engineer/Architect/Auditor/QA charters need a starter eval suite before this gate
becomes enforcing. Gate runs in `advise` mode until each charter has ≥ 3 capability evals.

---

## 7b. Charter pre-implementation — `search-first` contract

> Annotation added 2026-05-29. Adapted from ECC `search-first` skill.

Engineer + Architect charters bind to a pre-implementation contract:

1. **Tool-availability preflight.** Confirm registry channels (`pip-index`, `npm view`, MCP
   registry, `gh search`) are reachable; honestly report any skipped channel.
2. **Parallel search.** Registry + MCP catalog + GitHub for adoptable solutions.
3. **Adopt / extend-wrap / build-custom matrix.** Score on functionality, maintenance,
   community, docs, license, dependency surface.
4. **Cite or refuse.** Record the chosen path (or "no fit found, building custom because …")
   in the decision ledger (per #12a) before any Write/Edit.

Implication: prevents one-off reimplementation when a battle-tested library or MCP tool
already covers the case. Refusal to cite a search result is itself an audit event.

---

## 8. Two-tier role hierarchy + hybrid authority

**Per Hub:** Master roles (Director-level) + project-level roles.

**Authority model:** policy-default (bundle-declared) + **bounded emergency override** per declared
incident class. E.g. Master DevOps can override during a P0 incident, audited, time-bounded.

---

## 9. Vault-only secrets

**No exceptions.** No `env://`. No built-in secret store. Spine never holds customer secrets.

**Day-0 default:** wizard-installed OpenBao container.

**Adapters:** HashiCorp Vault / AWS Secrets Manager / Azure Key Vault / GCP Secret Manager / Infisical / 1Password.

Implication: T1 identifies 5 vault violations in current code (`approval.py`, `_env_loader.sh`,
`share-pg.sh`, `run-standalone-watcher.sh`, `spine-connect.sh`) — all must be remediated before v1.0.
New `shared/secrets/` package required.

---

## 10. Fractal Hub federation

**"A Hub is a Hub is a Hub."** Same container at every tier (team / division / enterprise / corporate).
Hubs register child Hubs alongside projects.

**Trust model:** hybrid consent-leaning — **peer-consent by default**; bounded mandatory upward flows
declared in bundle for compliance. E.g. corporate Hub can mandate "all subsidiary Hubs report
security incidents upward."

---

## 11. Operate subsystem — the 6th corner

> Source: R7 research recommendation + W2 expansion. Formally ratified 2026-05-17.

Spine builds AND **operates** production. Every competitor stops at "ship the code." Spine ships INIT-10
Operate Subsystem.

**New role:** `devops` — customer-facing, **distinct from `operator`** (Spine-internal). Conflating
them = the mistake every "AI DevOps" startup made.

**8 control planes** (per W2 reframe of R7): each with its own state, vendors, blast radius, and
human-in-loop seam. Captured in `shared/charters/devops.md`.

---

## 12. Cite-or-Refuse contract

> Source: R3 + R4 research recommendation. Formally ratified 2026-05-17.

**Strict tier for verify-class roles** (auditor / qa / verify): must cite supporting evidence (KG node
ID, file:line, prior audit row hash) or **refuse to act**. Refusal is itself an audit event.

Implication: T4 found verify wrappers and `shared/mcp/tools/verify.py`, `iso.py` don't enforce this.
REFACTOR required. T1 found `shared/calibration/` already supports the confidence band needed.

---

## 12a. Promotion gate — recursive confidence ≠ live promotion

> Annotation added 2026-05-29. Adapted from ECC `recursive-decision-ledger` skill.

Cite-or-Refuse (#12) governs whether a role may act. **#12a governs whether the result of
those acts may be promoted to live.** Repeated rollouts, ensemble votes, and recursive
self-checks are useful for ranking candidates but do not, by themselves, authorize
production deploys, capital-class migrations, or destructive operations.

**Append-only decision ledger** (`shared/audit/decision_ledger/`, JSONL, hash-chained into
the existing audit ledger) records every Conductor / Auditor / QA rollout with:

- rollout id, timestamp, run_id
- prior accepted winner + prior watchlist
- fresh evidence ingested (KG node ids / file:line / prior audit hash)
- search space size, trial count, effective trial count
- top candidates with explicit marks (`accept` / `watch` / `reject` / `decay` / `replay`)
- **coherence mark** against the prior ledger
- **promotion gate result** — explicit `live_promotion: true | false` plus reason

**Default promotion mode is paper / dry-run / preview / read-only.** `live_promotion: true`
requires explicit freshness gate (data not stale beyond bundle policy) AND replay gate
(prior winner reproducible on current state). Bundle policy declares the gates per work-item
class (#19) and per tier (laptop / BYOC / enterprise / on-prem).

Implication: ledger is a new directory under `shared/audit/`; existing audit ledger chains
in unchanged. Conductor and Auditor charter contracts grow a `promotion_gate_required` flag
sourced from the work-item type.

---

## 13. Engineer = hybrid by tier

**Autonomous engineer** for tier-low work (refactors, dep updates, bug fixes, dataclass plumbing).

**Human-with-AI** for tier-high (architecture, novel features).

**Per-bundle opt-in.** Banks set `autonomous=never; always human-with-AI`.

**Implementation:** when autonomous mode runs, it's a **thin wrapper over an external coding agent** —
Claude Code / Cursor / Aider / OpenHands. **Spine never competes on raw coding quality**; Spine
composes whichever coding agent the customer prefers.

Implication: `build_dispatch` adds `implementer_kind ∈ {claude_code, cursor, aider, openhands, human}`
+ `autonomy_tier` fields (T1 REFACTOR for `shared/mcp/tools/build.py`).

---

## 14. Target market = ALL three segments

**Solo founder → mid-market tech → regulated enterprise.** One product. One Hub container. Different
SKUs, different onboarding paths — same underlying engine.

Bottom-up adoption (solo) feeds mid-market expansion which feeds enterprise. Notion / Linear / Figma
growth pattern, but with a **unified product** instead of separate tiers being separate products.

---

## 15. NOT SaaS

**No vendor-hosted multi-tenant cloud. Period.** Spine is enterprise-self-hosted at every tier.
Vendor never holds customer data or runs customer workloads.

Sharpens the pitch to: *"Spine doesn't hold your code, doesn't hold your secrets, doesn't hold
your audit trail. Ever. It can't be subpoenaed for your data. It can't be breached for your data.
It doesn't exist in our cloud."*

**Hosted demo sandbox at `try.spine.dev`** is acceptable — public, demo-data-only, 24h expiry, for
marketing/evaluation only. NOT a product tier.

---

## 16. Update distribution via federation tree

Vendor publishes **signed Hub releases** via artifact registry. Vendor IS the root of the update tree.

Each Hub subscribes to an upstream — either its parent Hub (federated org) OR directly to vendor
source (leaf / standalone Hub).

**Approval gate at each tier:** admin sees changelog + recommended-rollout-cadence + risk notes +
impact preview → approves, defers, or rejects. **Auto-push is never an option.** Audit chain captures
every update decision.

Vendor security advisories flow through same channel with severity tagging; bundle policy can declare
"auto-approve security patches" if customer trusts vendor.

Pattern: HashiCorp Vault Enterprise replication / Red Hat OpenShift lifecycle / regulated-industry
software updates.

---

## 17. v1.0 deployment shapes — 4 modes (+1 deferred)

| Mode | Who operates | Where it runs | Tier |
|---|---|---|---|
| **Laptop** | Customer | Customer's laptop | Free; solo founder eval, devs |
| **Vendor-Managed (BYOC)** | Spine company (via delegated role) | Customer's cloud (AWS/Azure/GCP/Railway/Hostinger/DO/Fly.io) | Founder tier — solo + early mid-market |
| **Self-hosted customer-cloud** | Customer | Customer's K8s (EKS/AKS/GKE) | Team / Enterprise |
| **Self-hosted on-prem** | Customer | Customer's datacenter (vanilla K8s / OpenShift / Rancher) | Enterprise — regulated |
| *(v1.1)* Air-gapped | Customer | Customer's air-gapped infra | Defense / classified |

**BYOC mechanics:** founder signs up → picks cloud → grants Spine company a delegated role (AWS IAM
role / Azure delegated admin / GCP service account — **scoped to provision-and-manage-Spine, nothing
more**) → Spine automation provisions Hub + OpenBao + Postgres into founder's account → founder
gets Hub URL. Founder pays: their cloud bill directly + Spine management fee (~$50–200/mo).

**Exit ramp:** founder revokes the role; Hub keeps running; they take over ops self-hosted. No
lock-in. Zero data migration. The deployment doesn't move.

Plus marketing-only sandbox at `try.spine.dev` (see #15).

---

## 18. Closed-source v1.0

No public source code. May reconsider open-sourcing the project Spine engine after enterprise
traction is established, **not Day 1**. License-for-OSS-pieces question (Apache 2.0 vs MIT vs other)
**deferred**.

**Downstream implications (consequences, not new decisions):**

- **Community strategy changes.** No GitHub stars / OSS contributions as trust signal. Need: founder
  presence + content + design partner case studies + Discord community + transparent product roadmap +
  public uptime/security posture pages.
- **Enterprise trust gap.** Regulated buyers can't audit source. Compensations: **SOC2 Type II (no
  longer optional)**, independent **pen test reports**, **source-escrow option** (Iron Mountain or
  NCC) for top-tier enterprise contracts, **demo-environment access** for security reviews.
- **Repo migration:** existing public-trajectory v2 work moves to private repos immediately
  (operational follow-through).

**Cloud-provider competition risk → zero.** Nothing to fork.

---

## 19. Work-item types — all 7 Day 1

**`feature` / `bug` / `incident` / `support` / `refactor` / `infra` / `compliance`**

Each gets its own intake template + phase pipeline + role-charter responsibilities + UX surface +
integration set.

**6 NEW role charters needed** (per W3 audit; existing 13 charters cover the rest):
- `customer_support` (for support type)
- `compliance_officer` (for compliance type)
- `security_engineer` (for incidents + ongoing)
- `tech_writer` (cross-cutting)
- `release_manager` (for release decisions)
- `devops` (per #11, distinct from `operator`)

All 6 authored formally against industry standards (Scrum Guide / PMBOK / ITIL / NIST).

**Integration set per work-item type (minimum Day 1):**

| Type | Source | Sink |
|---|---|---|
| feature / bug / refactor | GitHub | GitHub PR |
| incident | PagerDuty + Sentry | Slack + audit |
| support | Linear Service Desk OR Zendesk | Slack + ticket reply |
| compliance | Vanta | Evidence Store + audit |
| infra | (devops-initiated) | Terraform PR + audit |
| (cross-cutting) | Slack + email |  |

---

## 20. Cloud breadth Day 1 = 5+ providers (Option D)

**AWS + Azure + GCP + Railway + (Fly.io OR DigitalOcean — pick on signal in next 30 days).**

Covers nearly the full segment spectrum: regulated enterprise (AWS/Azure/GCP) to solo founder
(Railway/Fly.io/DO).

**Long-tail providers** (Hostinger, Linode, Vercel) added in v1.1+ based on customer demand.

Applies in two places:
1. Vendor-Managed (BYOC) tier — Spine provisions Hub + OpenBao + Postgres
2. Infra work-item type — devops role provisions customer infrastructure

---

## 21. Build team = ALL AI ALL THE TIME

**Solo human (Khash) + AI orchestration** (Claude Code orchestrating subagents now; Spine
orchestrating Spine eventually). **No human engineering hires.**

The human role is irreducibly: strategic direction, approval gates, customer relationships, brand /
voice. **Everything else is AI.**

This is also the **ultimate proof of the product** — Cursor isn't built by Cursor; Devin isn't built
by Devin; **Spine IS built by Spine**. Every line of code, every architectural decision, every PR
has an audit trail. The audit chain is the trust mechanism. *"Spine built itself this way — yours
will too."*

**Architectural blind spots:** answer is NOT "hire humans for peer review" — it's the AI techniques
Spine itself ships (drift audits, ground-truth audits, hygiene audits, auditor role pattern, cross-LLM
consensus, calibration math). All exist as substrate; need wiring.

**Timeline:** v1.0 ships "as fast as AI velocity can ship it." Bottleneck = YOU (decision approvals,
strategic direction, customer feedback) — exactly the "human at well-defined decision points" pattern.

---

## 22. v2→v3 work = intelligent per-artifact triage

**KEEP / REFACTOR / REBUILD / BUILD-NEW / DELETE** per artifact — NOT a blanket A/B/C choice.

Each marking justified by what the new commitments require of that artifact specifically.
Deliverable: triaged-codebase doc + the actual marks in git, **before any rebuild work starts.**

*(This decision is the very exercise that just ran. Output → `docs/V3_TRIAGE.md` aggregating T1–T6.)*

---

## 23. Pricing deferred + feature-flag licensing as Day-1 primitive

**Pricing deferred** until product is built + tested with real users. No tier-and-dollar commitments
now.

**Feature-level access control = Day-1 architectural primitive.** Any pricing model is mechanically
supported when ready to set numbers.

**Architectural implications:**

- **Every feature has a flag.** From "federation enabled" to "PagerDuty integration enabled" to
  "SSO enabled" to "customer_support role enabled" to "Master roles enabled" to "max projects ≤ N"
  to "AWS provisioning enabled" — each is a flag in the license bundle.
- **License bundle = special signed bundle from vendor.** Reuses bundle infrastructure
  (`shared/standards/`). Hub validates **Ed25519 signature** on startup + periodically + on every
  feature gate (given closed-source).
- **Feature gate at every entry point.** Before any feature runs, code calls
  `license.is_enabled("feature_name")`. If disabled: graceful UI message with "upgrade to unlock"
  path. **Licensing becomes product discovery, not a wall.**
- **Per-feature usage metering Day 1**, even if not billed yet. Tells us which features are
  most-used, most-valued, by which segment — exact data needed to set rational pricing later.
- **Pricing experimentation later = changing bundle content, not refactoring code.** Per-feature
  pricing for solo; bundled tiers for mid-market; custom contracts for enterprise — all without
  engineering changes.
- **License grants are bundle-distributable** through the same federation update mechanism (#16).

Pattern: HashiCorp Vault Enterprise / Confluent Platform / MongoDB Atlas Enterprise.

---

## 24. Vanta + Drata + Secureframe — first-class integrations Day 1

**Vanta + Drata + Secureframe Day 1.** Tugboat Logic + Strike Graph + Thoropass v1.1+ (covers ~95% of
GRC SaaS market).

**Two flows:**

- **Read:** `compliance_officer` role queries Vanta/Drata APIs for current control status, evidence
  gaps, audit-prep checklists, deadline tracking.
- **Write:** Spine pushes every audit-chain event that's relevant evidence — PRs, deploys, approvals,
  config changes, role authorizations, vault access events, capability grants, drift remediations —
  into customer's Vanta/Drata vault automatically. **Spine becomes the highest-velocity SOC2 evidence
  producer in the customer's stack.**

**Two-party attestation:** customer's auditor sees evidence in Vanta + corroborates against Spine's
hash-chained audit log + matches → trust. Regulatory-grade.

**Startup-specific value (resolves the SOC 2 / startups question):** at the startup tier, Spine's audit
chain produces SOC 2-grade evidence **automatically as a byproduct of using Spine**, NOT gated.
When the startup adds Vanta/Drata, Spine immediately pushes existing trail backwards. **Their "we
started SOC 2 today" actually means "we have months of evidence already collected."**

Startup pitch: *"Build your product with Spine. When your first enterprise customer asks for SOC 2,
you have 18 months of audit evidence already collected. You answer 'yes' on the same call, not 6
months later."*

---

## 25. Identity = Keycloak embedded by default, feature-flag lightening per tier

**Keycloak ships as a sibling container alongside Hub.** Java/JVM dep accepted as the cost of mature
feature set + enterprise-recognized name + 10+ years production hardening.

Spine Hub uses Keycloak as its **OIDC provider**. Hub never directly handles SAML/SCIM/social-login/MFA
logic; **delegates everything to Keycloak**. Customer's existing IdP (Okta / Azure AD / Google
Workspace / Ping / OneLogin) federates into Keycloak as a brokered upstream IdP. **Spine Hub trusts
only Keycloak.**

**Feature flags control which Keycloak capabilities are exposed per tier:**

| Tier | Capabilities |
|---|---|
| Free / laptop | single realm, basic username+password, no MFA enforcement, no IdP federation |
| Founder (BYOC) | MFA optional, social login enabled, single IdP federation allowed |
| Team | MFA required, multi-IdP federation, basic SCIM |
| Enterprise | full SCIM 2.0, multi-realm, advanced password policy, custom themes, audit export |
| Air-gapped | works fully (Keycloak has no external deps); social login disabled by default |

**Day-0 wizard:** installs Keycloak + generates initial admin credentials + creates default realm +
configures Hub as a Keycloak OIDC client.

**Identity is foundational** because many earlier decisions REQUIRE it: AI scrum master ping (#5)
needs identity / comm prefs per-user (#6) need identity / two-tier authority (#8) needs identity /
vault two-party audit (#9) needs identity / federation consent (#10) needs identity / feature-flag
licensing (#23) needs user-group mapping / SOC 2 evidence (#24) requires per-user attribution.

---

## 26. Business ops — deferred

Corp structure (C-corp vs LLC) / IP / patents / EULA / customer contracts (MSA / DPA / AUP) / funding
posture — **deferred until product exists.** Focus = building the product.

Vendor's own operational state (vendor's vault, license signing keys, SOC 2 evidence pipeline) is
operational from Day 1 — not really "decisions" but tracked separately.

---

## 27. Smart Spine — 3-tier learning architecture

| Tier | What learns | Default | Override |
|---|---|---|---|
| **1a — Per-project** | Each project Spine learns from its own work (codebase patterns, prior decisions, role outcomes, calibration) | Always on | N/A |
| **1b — Within-Hub** | Lessons + patterns flow between project Spines under same Hub federation tree. Master roles aggregate. Marketing's Scrum Master learns from Finance's | **DEFAULT ON.** Customer admin can disable via bundle (joint ventures / legally-isolated subsidiaries) | `learning.within_hub: enabled` |
| **2 — Cross-org** | Vendor learns statistical patterns across all customers; publishes improved role charters / bundles / scanner rules via federation update (#16) | **DEFAULT OFF.** Customer must explicitly opt in via Hub UI consent flow. Granular opt-in per data class (calibration-outcomes vs role-success-rates vs pattern-frequencies). **Anonymized + aggregated only; no raw data.** | `learning.cross_org.consent: false` |
| **3 — Vendor self-improvement** | Vendor's own Spine deployment improves the product. Eats own dogfood. Drift audits, calibration, eval-on-every-release | Always on (vendor choice) | N/A |

**What this requires in the build (all explicit must-build for v1.0):**

1. **Memory writer hooks** — wire R4's 7 trigger points (audit_event → lesson)
2. **Memory retrieval at every role action** — query memory + KG before acting; cite sources per #12
3. **Calibration outcome capture** — every verify pass/fail, every auditor approve/reject, every user
   approve/reject feeds `spine_calibration.outcome` → weekly Platt refit
4. **KG indexer firing** — on every commit / directive / artifact (currently 0 nodes)
5. **Master role aggregation** — Master Scrum Master / Master Architect periodically aggregate child
   Hub lessons; publish refined playbooks; distribute via bundle inheritance
6. **Lesson promotion ladder** — per-role → per-project → per-Hub → (with consent) → vendor cross-org
7. **Anonymized telemetry pipeline** for Tier 2 — pattern extraction + sanitization + aggregation +
   transmission + audit trail of what was shared
8. **Update bundle authoring at vendor** — Master roles in vendor's Spine produce improvements;
   signed bundles flow through federation tree
9. **Eval harness on every release** — golden suite runs; results in audit; regressions block
10. **Retro role wired up** — currently stub in `phases.yaml`; auto-fires per work-item completion
11. **Cross-LLM consensus as learning signal** — disagreement is data; feeds calibration corpus
12. **"Spine knows you" UX** — Master roles proactively surface: *"Your team has rejected the last 3
    proposals like this; want me to adjust my approach?"*

This is "AI org that's been with you for 3 years" made architecturally real. **Cursor / Devin /
Factory / Copilot — none have this loop.** Smart Spine is the wedge that compounds: month 12 Spine
at your customer >> month 1, AND month 12 Spine (the product) >> month 1 product.

---

## 28. Mobile / native apps = SCAFFOLD for v1.0

- Define **mobile-API surface** (REST endpoints for approvals + briefings + status)
- Build **placeholder iOS/Android project structure** with signing certs and Apple/Google developer
  accounts
- Ship **web-mobile-responsive Hub UI** that works on phones via browser

Native mobile apps deferred to v1.1+. Responsive web covers most "approve on the go" use cases
initially.

---

## 29. Voice / phone = SCAFFOLD for v1.0

- Define **voice-integration interface** (which decisions can be voice-approved, which roles can be
  voice-reachable)
- Wire **one provider stub — Twilio** (most established voice API)

Defer actual voice flows to v1.1+ until customer demand surfaces (likely *"Master CTO callable for
critical incidents"* first).

---

## 30. API + MCP surface = SCAFFOLD for v1.0 — but heavier

**Public Hub REST API** with:
- **OpenAPI 3.x spec**
- **Auth via Keycloak** (#25)
- **Rate limiting**
- **Versioning** (`v1` from Day 1; reserve `v2`/`v3` namespaces)

**MCP server surface** for AI-tool integration.

**Why heavier than the other scaffolds:** API and MCP surfaces are foundational — they're what makes
Spine **programmable + integration-friendly + ecosystem-extensible**. Scaffold the framework, ship
the contract, build adapters/endpoints as needed.

---

## 30a. MCP response envelope

> Annotation added 2026-05-29. Adapted from ECC `agent-harness-construction` skill (Observation Design).

Every tool registered in `TOOL_REGISTRY` returns a typed envelope:

```
status:       Literal["success", "warning", "error", "refusal"]
summary:      str                  # one-line, role-readable result
next_actions: list[str]            # actionable follow-ups for the calling role
artifacts:    list[Artifact]       # file paths, KG node ids, run ids
metadata:     dict                 # tool-specific extension
```

Verify-class tools (`requires_citation=True` per #12) extend with `citations: list[Citation]`
and emit `status="refusal"` with a populated `summary` if citations are missing or unverifiable.

Enforcement: a Pydantic schema in `shared/mcp/envelope.py`; middleware in `shared/mcp/server.py`
rejects non-conforming responses in dev and warns in prod for graceful migration. Smoke test
in `shared/mcp/tests/test_server_smoke.py` walks every entry in `TOOL_REGISTRY` and asserts
envelope conformance.

Implication: existing tool responses across the 18 tool modules need normalization; landing
this is the first task that materially improves cross-role observability and recovery quality
(the two largest agent-completion constraints per the ECC model).

---

## 31. Disaster recovery = BUILD properly for v1.0

Not a scaffold. **Auto-recovery + immediate notification + tested restore.**

Cost of getting DR wrong = *"customer loses their AI team's institutional memory."* Non-negotiable.

(Architecture detail in #32.)

---

## 32. DR architecture — 12 layers

| # | Layer | What we build | RPO / RTO target |
|---|---|---|---|
| 1 | Container auto-recovery | K8s with replicas + liveness/readiness probes + auto-restart. `lib/watchdog.sh` for non-K8s (laptop, single-host) | 30s from container death |
| 2 | Process supervision | Each role daemon supervised; auto-restart on crash; circuit breaker on flapping | 30s from role-daemon crash |
| 3 | Continuous data backup | Postgres WAL + Vault snapshots + KG state → customer-chosen S3-compatible storage (S3 / GCS / Azure Blob / MinIO / Wasabi). KMS-encrypted at rest. Per-bundle retention (default 30d) | RPO ≤ 5 min |
| 4 | Tested data restore | Documented + automated restore. **Periodic restore-to-throwaway-environment** verification (weekly default) — catches "backups exist but restore broken" failure mode | RTO ≤ 30 min full Hub restoration |
| 5 | Heartbeat protocol | Each Hub heartbeats to itself + federation parent (if any) + vendor status registry (opt-in for proactive support). Failure → multi-medium notification per #6 | Detection ≤ 1 min |
| 6 | Federation autonomy | Per #10 — if parent Hub is down, child Hubs keep working autonomously. No cascading failures | Always-on at child Hub level |
| 7 | Cross-region replication | **Optional per bundle policy** (enterprise tier feature flag). Active-passive: standby replica in second region; promotes on primary failure. Active-active deferred to v1.1+ (CAP-theorem complications) | RPO ≤ 5 min, RTO ≤ 10 min active-passive |
| 8 | Vault unseal recovery | **Shamir secret-sharing (3-of-5 humans)** for high-security OR **cloud-KMS auto-unseal** (AWS KMS / Azure KV / GCP KMS) — customer chooses at setup wizard. Runbook auto-generated | Manual if Shamir; auto if KMS |
| 9 | Customer-accidentally-deleted-Hub recovery | Soft-delete with 7d retention. Restore via Hub UI or vendor support. Full deletion requires HMAC-signed double-confirmation | Recoverable for 7d |
| 10 | Vendor update infrastructure DR | Vendor's own update publishing has DR (CDN-fronted artifact registry, multi-region, signed bundles). If vendor infra down, customers keep running current version (no auto-degradation) | Customers unaffected by vendor outage |
| 11 | DR runbook | **Auto-generated per deployment** based on actual configuration. Updated when bundle or topology changes. Includes: pager rotation, recovery commands, escalation paths, RPO/RTO, last-tested date | Always current |
| 12 | Backup verification on every release | When vendor publishes new Spine version, customer's automated DR test re-validates restore against new version. **Catches "upgrade broke backup compat" before it matters** | Continuous |

**Deferred to v1.1+:**
- Multi-cloud failover (active in AWS, standby in GCP) — hard problem; rare requirement
- Real-time hot-standby with sub-second failover — most customers accept warm standby

**Architectural truth:** DR isn't a feature; it's a **property of every component**. Hub container,
Vault, Postgres, KG, project Spines — each has its DR story built in. The "always notify immediately"
requirement satisfied by routing through #6 — customer's chosen mediums get the alert within 60 sec.

---

## 33. Migration tooling — 4 distinct concerns

| Concern | Treatment |
|---|---|
| **A. Onboarding migration** — importing customer's existing data (code from GitHub/GitLab, issues from Linear/Jira, docs from Confluence/Notion, existing standards/runbooks/wikis) | **Scaffold** the connector interface + **ship GitHub + (Linear OR Jira) Day 1**. Wizard step in first-time-setup. Others (Confluence/Notion/Asana/etc.) built on customer demand |
| **B. Spine portability** — moving Spine deployment between shapes (laptop → BYOC → on-prem) or between clouds (AWS → GCP) without losing audit chain / KG / role charters / bundle config / vault refs / memory / lessons / project history | **Build properly Day 1.** **Non-negotiable** for the "no lock-in" claim to be real. Signed tarball format; integrity-verified; auditable |
| **C. Software-migration-as-work-type** — Spine helps customer migrate THEIR product (Python 3.8 → 3.12, React 17 → 18, MySQL → Postgres, monolith → microservices, on-prem → cloud) | Captured by **work-item-type design (#19)**. Add specialized **"migration" intake template + pipeline variant in v1.1** |
| **D. Spine version migrations** — when vendor publishes v2.0 with breaking changes, customer's v1.0 needs to migrate cleanly (DB schemas, bundle formats, role-charter versions, vault namespace structures, KG schema) | **Build properly Day 1.** Required engineering hygiene. Wired into update-distribution flow (#16) with **customer-admin approval gate per migration**. **N-2 cross-version compatibility** commitment |

**Strategic value of B (portability):** the structural answer to enterprise procurement's *"what's
our exit strategy?"* question. Closed-source + self-hosted often raises *"what if your company goes
away?"* anxiety. The answer: *"export your full state at any time; the audit chain proves it's
complete; recreate on whatever you want. **We've explicitly designed Spine so you can leave.**"*

Same trust play as OSS-with-portable-data (Linear / Notion) but applied to closed-source. The export
format becomes a **marketing artifact** — published spec, sample download, demonstrably
round-trippable. *"Try Spine; we already proved you can leave."*

---

## 34. Workspace hygiene as architectural concern

> Source: `feedback_workspace_hygiene` memory + recurring user concern across multi-agent sessions.
> Formally ratified 2026-05-17.

**Problem:** AI-generated work leaves cruft. Each agent locally optimizes — drops temp files, returns,
moves on. Nobody's the janitor. Over days this becomes measurable signal-to-noise drop in the repo
and makes onboarding new contributors (or the user returning) harder.

**Spine must own this as a first-class architectural concern**, not a manual cleanup chore.

**Design requirements:**

1. **Per-run workspace dir.** Every agent / subagent invocation gets `.spine/work/<run_id>/`.
   Agents write all intermediate state there. No more scattering `/tmp/*` or repo-root scratch.
2. **Explicit promotion.** Final artifacts (DB writes, commits, copies-to-canonical) are explicitly
   **promoted** out of the workspace before it closes. No implicit "and the workspace becomes the
   artifact."
3. **Archive on completion.** On agent completion (success OR failure), the workspace is
   **archived to `.spine/archive/<date>/<run_id>.tar.zst`** (compressed) and then **deleted from
   the live tree**.
4. **Periodic sweep command.** `spine hygiene` (or `make hygiene`) sweeps:
   - `/tmp/spine-*` orphans
   - `.spine/archive/` past N days (configurable per bundle; default 30d)
   - Stale workspaces from crashed agents (older than max-run-duration)
   - `__pycache__/` not in `.gitignore`
   - Repo-root files matching one-off scratch patterns
5. **Conductor gate.** **Conductor role refuses to mark a project done if uncleaned workspace state
   exists for it.** Hygiene is a release-blocking acceptance criterion, not a nice-to-have.
6. **Per-bundle policy.** Bundle declares retention window + sweep cadence + acceptable workspace
   patterns. Customer can tune for their environment (longer retention for debug, shorter for
   throughput).

**Implication for #11 (Operate):** workspace hygiene is one of the 8 control planes for the devops
role. Hub UI surfaces hygiene status per project (currently uncleaned workspaces / next sweep ETA /
last sweep result).

**Why this matters strategically:** every other AI dev tool leaves cruft. Spine refusing to mark
work done until the workspace is clean is the same trust mechanism as the audit chain — proves the
work was actually completed, not just declared done with debris left behind.

---

# Deferred items (NOT numbered decisions)

These came up during the session, were explicitly deferred, and should be revisited later:

| Item | Why deferred | Revisit when |
|---|---|---|
| Pricing tiers + specific $ | Per #23 — won't price what hasn't been built/tested | After first paying customers |
| Naming / branding | Defer until positioning validated with first users | Pre-launch |
| Demo / launch sequence | Depends on product readiness | Approaching v1.0 ship |
| OSS license question (Apache 2.0 vs MIT vs other) | Per #18 — closed-source Day 1; license irrelevant until something open-sources | If/when project Spine engine open-sources |
| SOC 2 Type II calendar start | Per #24 — startup-tier audit chain produces evidence automatically as byproduct; Spine company's own SOC 2 timing TBD | Vendor entity formalization |
| Internationalization / multi-language | Raised, never explicitly locked | When first non-English customer surfaces |
| Marketplace for community-contributed role charters / bundles / integrations | Raised, never locked | Long-term play; post-v1.0 community traction |
| Spine company corp structure / IP / EULA / contracts / funding | Per #26 — deferred until product exists | After first customer |
| Active-active multi-cloud failover | Per #32 — CAP-theorem complications | v1.1+ |
| Native mobile apps (iOS/Android) | Per #28 — responsive web covers initial use cases | v1.1+ on demand |
| Actual voice/phone flows | Per #29 — scaffold only Day 1 | v1.1+ on demand |
| Confluence/Notion/Asana migration connectors | Per #33 A — GitHub + (Linear OR Jira) Day 1; others on demand | v1.1+ on customer demand |
| Long-tail cloud providers (Hostinger / Linode / Vercel / etc.) | Per #20 — top 5 Day 1; rest on demand | v1.1+ on customer demand |
| Software-migration-as-work-type intake template | Per #33 C | v1.1 |
| Air-gapped deployment shape | Per #17 — deferred from Day 1 | v1.1 |

---

# Naturally-resolved items (NOT numbered)

| Item | Resolved by |
|---|---|
| Team building Spine (solo+AI / +1-2 engineers / full team) | #21 (ALL AI ALL THE TIME) |
| Spine-for-Spine recursive use case | Implicit consequence of #16 (vendor as update tree root) + #21 (all AI) + #27 (vendor self-improvement is Tier 3 of Smart Spine). **All principles we locked apply equally to vendor's own deployment** — which makes vendor's Spine the proving ground for every feature before it ships to customers. |
| MVP v1.0 scope | Composite of #17 (4 shapes) + #19 (all 7 work-types) + #20 (5+ clouds) + #28-31 (scaffolds + DR build) |

---

# Architectural primitives that emerged (cross-decision)

These weren't single decisions — they're patterns that emerged across multiple decisions and need
explicit attention in the build (10 patterns):

1. **BYOC delegated-role pattern** (#15, #17): vendor automation provisions into customer's cloud
   via scoped IAM role; customer can revoke at any time
2. **License bundle = signed vendor bundle** (#23): reuses existing bundle infrastructure
   (`shared/standards/`); Ed25519 signature; per-Hub validation on startup + periodically
3. **Vendor as root of update tree** (#16, #21, #27): vendor publishes signed releases / bundles /
   role-charter improvements / scanner rules — all flow through same federation distribution channel
4. **Hub enumerated surfaces (9)** (#3): dashboard / master roles / registry / audit / vault config /
   integrations / decision queue / talk-to-a-role chat / federation hub-switcher
5. **8 control planes for Operate** (#11): each with own state, vendors, blast radius,
   human-in-loop seam
6. **7 trigger points for memory writer hooks** (#27): audit_event → lesson at 7 specific lifecycle
   points
7. **Hash-chained audit as SOC2 evidence pipeline** (#24): every audit chain entry IS evidence;
   pushed to Vanta/Drata as byproduct of normal operation
8. **Two-party attestation pattern** (#24): customer auditor sees evidence in Vanta + corroborates
   against Spine's hash-chained log + matches → trust
9. **Bundle inheritance for fractal Hub** (#10): parent Hub bundle → child Hub overrides → project
   bundle overrides — same mechanism for federation, licensing, learning policy, comm prefs, DR
   policy
10. **Cross-LLM consensus as learning signal, not just error** (#27): disagreement is data feeding
    calibration corpus

---

# v1.0 → v1.1+ split (consolidated)

**Day 1 (v1.0):**
- All 34 decisions above, with their scaffolds/builds as specified
- 4 deployment shapes (laptop / BYOC / customer-cloud / on-prem)
- 5+ cloud providers
- 7 work-item types
- 19 role charters (13 existing rewrites + 6 new)
- 3 compliance integrations (Vanta + Drata + Secureframe)
- Keycloak + OpenBao + Postgres + KG + audit chain + hash-chained ledger
- Smart Spine 3-tier loop (full build)
- DR 12 layers (full build)
- Migration B + D (full build)
- Migration A scaffolded with GitHub + (Linear OR Jira)
- Mobile + voice + API+MCP scaffolds
- Hosted demo sandbox `try.spine.dev`
- Workspace hygiene primitive (#34): `.spine/work/`, `.spine/archive/`, `spine hygiene` sweep, Conductor gate

**v1.1+ (post-v1.0):**
- Air-gapped deployment shape
- Tugboat Logic / Strike Graph / Thoropass compliance integrations
- Long-tail cloud providers (Hostinger / Linode / Vercel / etc.)
- Native mobile apps (iOS/Android)
- Actual voice/phone flows
- Confluence / Notion / Asana migration connectors
- Software-migration-as-work-type intake template (#33 C)
- Active-active multi-cloud failover
- Real-time hot-standby with sub-second failover

---

# References

- Conversation transcript: `chatsession.md` (~21k lines)
- Triage reports (forthcoming): `docs/V3_TRIAGE.md` aggregating T1–T6
- Research synthesis: R3 (sandbox), R4 (KG/RAG + Cite-or-Refuse), R7 (DevOps/SRE → INIT-10 Operate),
  W2 (Operate 8 control planes), W3 (role lineup audit)
- Memory artifacts:
  `~/.claude/projects/-Users-khashsarrafi-Projects-Apps-SpineDevelopment/memory/`

---

**Document control:**
- Created: 2026-05-17
- Author: AI orchestration (Claude Opus 4.7), reviewed by Khash Sarrafi
- Status: **CANONICAL** — supersedes any conflicting content in ARCHITECTURE.md, PRD.md,
  BACKLOG.md, README.md, INSTALL.md, positioning.md until those are rewritten per #22 triage
  recommendations
- Revision 2 (2026-05-17): formally ratified #11 (Operate / devops + 8 control planes), #12
  (Cite-or-Refuse contract), and added #34 (Workspace hygiene as architectural concern). Total locked
  decisions: **34**.
- Next update trigger: any new design decision locked in subsequent sessions, OR any locked decision
  revisited and changed
