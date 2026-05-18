# Spine — Positioning

> Strategic source-of-truth for how Spine describes itself to outsiders. Drivers: [`V3_DESIGN_DECISIONS.md`](V3_DESIGN_DECISIONS.md) — **#1** (positioning + sub-tagline), **#3** (Hub-as-product), **#14** (3 segments), **#15** (NOT SaaS), **#17** (4 deployment shapes), **#18** (closed-source v1.0), **#21** (ALL AI ALL THE TIME), **#23** (feature-flag licensing), **#24** (Vanta/Drata SOC 2 evidence), **#27** (Smart Spine), **#31/32** (DR built properly).

---

## Tagline

**"AI software company in a box."**

## Sub-tagline

**AI does the work. AI scrum masters bring decisions to you. The audit log proves you understood what you signed.**

## What Spine is (two paragraphs)

Spine is a **containerized product — the Hub** — that runs an entire AI engineering organization on your laptop, your cloud account, or your datacenter. Plan, Build, Verify, Operate. Product Managers, Architects, Scrum Masters, Engineers, QA, DevOps, Security, Release, Compliance — every role you'd hire if you were standing up an engineering org, running 24/7, paying their own LLM bills, talking to YOU when they need a decision and shipping when they don't. The Hub is the primary surface — not a template you drop into a project (the v1 framing was wrong, #3).

Spine is **enterprise-grade software for orgs OR individuals who want production software**. It is **not** for vibecoder one-offs. It is **not** a SaaS coding agent. It is **not** an IDE plugin. It is **not** a framework. It is **not** multi-tenant — Spine vendor never holds your code, secrets, or audit trail (#15). It is closed-source v1.0 (#18). It is the only product aiming at: **fully-AI engineering organization + self-hosted + audit-grade + LLM-agnostic + active-push communication + 6-corner SDLC (Plan/Build/Verify/Operate/Federate/Comply)** — and the only one whose vendor is willing to dogfood it as their entire engineering team (#21).

---

## The differentiation, in one sentence per category

| Category | Spine claim |
|---|---|
| **Coverage** | A full org — not a coder. Product → Plan → Build → Verify → Release → Operate → Comply. |
| **Communication** | Active push (#5). Scrum Masters bring decisions to you on Slack / email / SMS / WhatsApp / Teams / PagerDuty. You approve; they ship. You don't babysit a dashboard. |
| **Deployment** | NOT SaaS (#15). Laptop / BYOC / customer-cloud / on-prem (#17). 5+ clouds Day 1 (#20). Air-gapped v1.1. |
| **Source posture** | Closed-source v1.0 (#18). Trust comes from SOC 2 + pen tests + source escrow + audit chain + design-partner case studies — not from GitHub stars. |
| **Identity** | Keycloak embedded (#25). Federate to your Okta / Azure AD / Google Workspace / Ping / OneLogin. |
| **Secrets** | Vault-only (#9). OpenBao bundled by default. Spine never holds your secrets. |
| **LLM** | 7 providers Day 1 (#2): Anthropic / OpenAI / Bedrock / Vertex / Ollama / Qwen / vLLM. Customer chooses. We never marry one. |
| **Compliance** | Vanta + Drata + Secureframe Day 1 (#24). Audit chain → evidence pipeline as a byproduct. *"We started SOC 2 today"* really means *"we have 18 months of evidence already collected."* |
| **Federation** | Fractal Hub (#10): same container at team / division / enterprise / corporate tier. Updates cascade through the tree (#16); each tier admin approves. |
| **Licensing** | Feature-flag licensing as a Day-1 architectural primitive (#23). Every feature has a flag. Bundles are signed Ed25519. License grants ride the federation tree. |
| **Smart Spine** | 3-tier learning (#27). Project Spine learns from itself. Within-Hub aggregates across projects. Cross-org (opt-in, anonymized) learns across customers — vendor publishes refined charters back through the federation tree. |
| **Disaster recovery** | Built properly (#31), 12 layers (#32). Tested restore on a schedule. Backup verification on every release. |
| **Workspace hygiene** | Architectural concern (#34) — Conductor refuses to mark a project done if uncleaned workspace state exists. The same trust mechanism as the audit chain. |
| **Self-dogfooded** | Spine is built by Spine (#21). The proof of the product is the product. *"Yours will be too."* |

---

## Target market — ALL three segments (#14)

One product. One Hub container. Different SKUs and onboarding paths. Same underlying engine.

### Solo founder (laptop / BYOC)
*One person trying to be a full team.* Free tier on laptop for evaluation. Founder tier on BYOC ($50–200/mo management fee, deferred pricing per #23) when ready to ship. PM, architect, engineer, QA, devops, security, release manager — all AI, all the time. The same person stays in the loop as the approver at every gate. Audit chain produces SOC 2-grade evidence automatically — so the day your first enterprise customer asks for SOC 2, you have 18 months of evidence already collected (#24).

### Mid-market tech (BYOC → self-hosted)
*A staff engineer at a 50-person company who can't hire 5 more engineers but can ship a parallel AI org alongside their human team.* Customer-cloud shape on EKS / AKS / GKE. MFA required, multi-IdP federation, basic SCIM (Keycloak Team tier per `keycloak/tier-config.md`). Standards bundles enforce house rules — banned libraries, required QA scope, mandatory architect-sign on schema migrations. Smart Spine within-Hub means the Master Scrum Master learns from Finance's PRDs what Marketing's PRDs typically miss.

### Regulated enterprise (on-prem / air-gapped v1.1)
*A bank, defense supplier, healthcare provider, government.* On-prem K8s, OpenShift, or Rancher. Shamir 3-of-5 vault unseal (#32 layer 8). Cross-region active-passive DR (#32 layer 7). In-house vLLM or Ollama serving local weights (no outbound LLM calls). Full SCIM 2.0 + multi-realm Keycloak + WebAuthn / passkey + step-up auth + admin event export. Bounded mandatory upward flows to corporate Hub for security incident reporting (#10 — fractal Hub, consent-leaning + bounded mandatory). Hash-chained audit log + two-party attestation via Vanta/Drata = regulatory-grade trust (#24).

Bottom-up adoption (solo) → mid-market expansion → enterprise. Notion / Linear / Figma growth pattern, but with a **unified product** rather than separate-tier-as-separate-product.

---

## NOT SaaS (#15) — explicit and repeated

**No vendor-hosted multi-tenant cloud. Period.** Spine is enterprise-self-hosted at every tier. The vendor never holds customer data or runs customer workloads.

> Spine doesn't hold your code, doesn't hold your secrets, doesn't hold your audit trail. Ever. It can't be subpoenaed for your data. It can't be breached for your data. It doesn't exist in our cloud.

`try.spine.dev` is a public demo sandbox — demo data, 24h expiry, marketing/evaluation only. **Not a product tier.**

This is the architectural answer to the procurement department's *"what about data residency / sovereignty / breach exposure?"* question. Spine cannot become the breached vendor in your security review because Spine never had your data to begin with.

---

## Closed-source v1.0 (#18) — and what replaces GitHub stars

No public source code in v1.0. Open-sourcing the project Spine engine is on the table after enterprise traction is real — not Day 1. The OSS license question (Apache 2.0 vs MIT vs other) is deferred until/unless anything open-sources.

**What replaces "GitHub stars as trust signal":**

- **Founder presence.** Khash is reachable. Office hours. Discord. Public roadmap (`docs/V3_BUILD_SEQUENCE.md`). Direct line for design-partner customers.
- **Design-partner case studies** with named customers as they ship.
- **Discord community** — for support, recipes, integration patterns, escalation.
- **Public roadmap + Wave-by-Wave status** (`docs/STATUS.md`).
- **Public uptime + security posture page** — vendor's own SOC 2 status, advisory feed.
- **SOC 2 Type II** (in progress, no longer optional under closed-source).
- **Independent pen test reports** — annually, published summary.
- **Source-escrow option** (Iron Mountain / NCC Group) for top-tier enterprise contracts.
- **Demo-environment access** for security reviews — full Hub in a sandbox you can hit with whatever scanner you want.

Cloud-provider competition risk: **zero.** Nothing to fork.

---

## ALL AI ALL THE TIME (#21) — the ultimate proof of the product

Cursor isn't built by Cursor. Devin isn't built by Devin. Factory isn't built by Factory. **Spine IS built by Spine.**

Every line of code in this repo was shipped by AI roles operating through the same Hub you'd run yourself. Every architectural decision went through the same decision queue. Every PR has an audit-chain entry. The vendor's own Spine deployment is the proving ground for every feature before it ships to customers (Smart Spine Tier 3, #27).

This is not marketing copy. It is operationally true and verifiable in the public commit log. The human role at Spine is irreducibly: strategic direction, approval gates, customer relationships, brand / voice. **Everything else is AI.**

Pitch line: *"Spine built itself this way — yours will too."*

---

## Three worked examples (3-segment)

### A — Solo founder ships a time-tracking SaaS (laptop → BYOC)
Khash equivalent: a non-technical founder runs `bash install.sh ~/spine`. Hub UI lands on a Decision Queue. Master Product role intros itself, runs the 5-move intake protocol (naive cast → provoke → reframe → tier → PRD artifact). Founder approves the PRD. Master Architect convenes a swarm; TRD comes back; founder approves. Conductor decomposes; Engineer team fans out across worker slots; auditor cross-checks every file; Verify subsystem runs sandboxed tests + cross-LLM consensus. Compliance role pushes audit-chain events into Vanta automatically (#24). Five days, one person, full SDLC, audit-grade. When the founder needs to focus on customers and not ops, they flip to BYOC — Spine vendor provisions identical Hub into the founder's AWS account; same product, vendor handles ops. To exit BYOC: revoke the IAM role. Hub keeps running. No data migration. No lock-in.

### B — Mid-market team ships a multi-quarter migration (customer-cloud)
Acme Corp, 80 engineers, EKS. CTO runs `helm install spine/hub`. Day-0 wizard federates Keycloak to their existing Okta. License bundle declares: per-feature flags, banned-libraries list, mandatory QA + security swarm for revenue paths, weekly DR test on. Smart Spine within-Hub aggregates: Master Scrum Master notices that revenue-critical PRDs from the Billing team always need a Compliance sign-off the Marketing team's don't — proactively surfaces this on Decision cards. A 6-month migration from session-cookie auth → OAuth2: Master Architect queries the Knowledge Graph for impact radius, decomposer uses KG-driven story sequencing, Engineer team fans out across the touched modules, Auditor re-runs impact_radius against each report to flag missed callers, Cross-region DR active-passive standby in second AWS region (#32 layer 7). Migration ships behind a feature flag with full test coverage and zero scope creep.

### C — Regulated enterprise rolls Spine to 5,000 devs (on-prem federation)
Acme Bank, 5,000 devs, OpenShift, OpenBao, Active Directory, in-house vLLM. Corporate Hub at the root. Division Hubs for Retail / Investment / Asset Mgmt — each registers under Corporate. Team Hubs under each Division — each registers under their parent. Updates cascade vendor → corporate → division → team (#16); each admin approves. Bundle policy at Corporate declares: *"all subsidiary Hubs report security incidents upward"* (#10 — bounded mandatory upward flow). Shamir 3-of-5 vault unseal across 5 named compliance officers; cloud-KMS auto-unseal forbidden by policy. Cross-LLM consensus on every security-critical decision (#12 Cite-or-Refuse contract — verify-class roles must cite KG-node ID or refuse). Audit-chain entries push to Vanta + the bank's existing GRC; two-party attestation matches independently. *"Spine started today; here's 18 months of evidence-grade decision history for our regulator."*

---

## The six corners of the moat (v3 frame)

```
                       SELF-HOSTED EVERYWHERE
                       (laptop → on-prem, NOT SaaS)
                                  │
                                  │
   ACTIVE-PUSH        ────────────●────────────    FRACTAL FEDERATION
   SCRUM MASTERS                 / \                (Hub IS a Hub IS a Hub)
                                /   \
                               /     \
                              /  SPINE \
                             /          \
                            /            \
   CITE-OR-REFUSE     ─────●──────────────●─────  ALL-AI BUILD + 6-CORNER
   VERIFY CONTRACT          \            /         COVERAGE (Plan/Build/
                             \          /          Verify/Operate/Comply/
                              \        /           Release)
                               \      /
                                \    /
                                 \  /
                            FEATURE-FLAG LICENSING
                            + AUDIT-CHAIN EVIDENCE
                            (SOC 2 as byproduct)
```

| Corner | Spine | Devin | Factory | Cursor | ruflo | MetaGPT |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| Self-hosted everywhere (#15 #17) | ✅ | ❌ | ❌ | ⚠️ | ⚠️ | ✅ |
| Active-push Scrum Masters (#5) | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Fractal federation (#4 #10) | ✅ | ❌ | ❌ | ❌ | ⚠️ | ❌ |
| 6-corner coverage (#11 #19) | ✅ | ❌ | ❌ | ❌ | ❌ | ⚠️ |
| Cite-or-Refuse verify (#12) | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Feature-flag licensing + audit evidence (#23 #24) | ✅ | ⚠️ | ⚠️ | ❌ | ⚠️ | ❌ |

Each corner is necessary; the moat is *all six together* — and the seventh, unspoken corner is that **Spine is built by Spine** (#21).

---

## Status

v3 rebuild in flight. Waves 0–4 complete (foundations, substrate wiring, work-item types, Hub product part 1, federation + license + evidence + learning). Wave 5 (DR + Migration + Landing docs) in progress. Wave 6 (Mobile/Voice/API scaffolds + lib/ retirement) to follow.

See [`docs/STATUS.md`](STATUS.md) for the wave-by-wave state and [`docs/V3_BUILD_SEQUENCE.md`](V3_BUILD_SEQUENCE.md) for the full execution plan.

---

## Try it

```bash
git clone <repo>
cd SpineDevelopment
bash install.sh ~/spine
cd ~/spine && make hub-up
open $(cat _state/hub_url)
```

Or run the marketing-only hosted demo at `try.spine.dev` (#15 — demo data, 24h expiry, not a product tier).

Full install + deployment guide: [`INSTALL.md`](../INSTALL.md). Architecture: [`docs/ARCHITECTURE.md`](ARCHITECTURE.md). Why each design choice: [`docs/V3_DESIGN_DECISIONS.md`](V3_DESIGN_DECISIONS.md).
