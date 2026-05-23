# Spine — AI software company in a box

> **AI does the work. AI scrum masters bring decisions to you. The audit log proves you understood what you signed.**

**Master reference (read this first):** [`docs/SPINE_MASTER.md`](docs/SPINE_MASTER.md) — what the system must do, component list, gaps, doc map.

> Drivers: [`docs/V3_DESIGN_DECISIONS.md`](docs/V3_DESIGN_DECISIONS.md) — especially **#1** (positioning), **#3** (Hub-as-product), **#15** (NOT SaaS), **#17** (4 deployment shapes), **#18** (closed-source v1.0).

Spine is enterprise-grade software for **organizations** or **individuals** who want production software. It is the only product in the market that ships a full AI engineering organization — product, architecture, build, verify, release, operate, compliance — under your control, with an audit trail that holds up in front of a regulator.

This is **not** a vibecoder one-off generator. It is not a SaaS coding agent. It is not a developer framework you drop into a project. The Hub IS the product (#3).

---

## What you get on Day 1

A single containerized **Hub** that runs on your laptop, your cloud account, or your datacenter — your choice (#17). Inside the Hub:

| Surface | What it does |
|---|---|
| **Decision queue** | AI scrum masters push briefings + decision cards at you (#5). You approve, defer, redirect — never babysit. |
| **Master roles** | One Master per discipline (Product, Architect, Conductor, Engineer, QA, DevOps, Security, Release, Compliance) — Director-level, talkable, persistent. |
| **Project Spines** | Per-project teams that run the SDLC end-to-end (intake → PRD → TRD → build → verify → release → operate). |
| **Registry** | All your projects, all your Hubs, all your federated subsidiaries — one pane of glass. |
| **Audit** | Hash-chained ledger of every action. SOC 2-grade evidence as a byproduct of normal use (#24). |
| **Vault config** | Your secrets stay in your vault. Spine never holds them (#9). |
| **Integrations** | GitHub, Linear/Jira, Slack, PagerDuty, Twilio, Teams, AWS/Azure/GCP/Railway/Fly, Vanta/Drata/Secureframe. |
| **Talk to a role** | Chat surface to any Master role — for advice, briefings, or to override a decision (#8). |
| **Federation** | Switch between your team Hub, division Hub, enterprise Hub, vendor Hub (#10). |
| **License + flags** | Every feature behind a flag (#23). Signed, enforced locally. No phone-home. |

The Hub talks to **7 LLM providers** (Anthropic, OpenAI, Bedrock, Vertex, Ollama, Qwen, in-house vLLM) — you pick (#2). It bundles **OpenBao** as the default vault (#9) and **Keycloak** as the default IdP (#25). It runs on **5 clouds Day 1** (AWS / Azure / GCP / Railway / Fly.io) plus laptop and on-prem (#17, #20).

---

## What's different from every other "AI dev tool"

Cursor isn't built by Cursor. Devin isn't built by Devin. Factory isn't built by Factory. **Spine IS built by Spine.** Every line of code in this repo was shipped by AI roles operating through the same Hub you'd run yourself, gated by the same approval cards you'd see, recorded in the same audit chain you'd inherit (#21).

That's not marketing. It is the only honest demo of an AI engineering organization that actually ships. Your Spine, on day 365, will be smarter than your Spine on day 1 — because Spine learns at three tiers (per-project, within-Hub, optional cross-org) and Master roles aggregate lessons across your portfolio (#27).

---

## NOT SaaS (#15)

**No vendor-hosted multi-tenant cloud. Period.** Spine is enterprise-self-hosted at every tier — solo founder on a laptop through regulated bank on bare metal. The vendor never holds your code, never holds your secrets, never holds your audit trail.

> Spine doesn't hold your code, doesn't hold your secrets, doesn't hold your audit trail. Ever. It can't be subpoenaed for your data. It can't be breached for your data. It doesn't exist in our cloud.

A hosted demo at `try.spine.dev` exists for evaluation only — public, demo-data, 24h expiry. It is not a product tier.

---

## Four deployment shapes Day 1 (#17)

| Shape | Who operates it | Where it runs | Who it's for |
|---|---|---|---|
| **Laptop** | You | Your machine | Solo founder eval, individual dev |
| **Vendor-Managed (BYOC)** | Spine vendor via delegated role | Your AWS/Azure/GCP/Railway/Fly/DO account | Solo + early mid-market — you focus on product, we run ops |
| **Self-hosted customer-cloud** | You | Your EKS/AKS/GKE | Mid-market and enterprise teams |
| **Self-hosted on-prem** | You | Your datacenter / OpenShift / Rancher | Regulated enterprise |

BYOC mechanics: you grant Spine a **scoped IAM role** (provision-and-manage-Spine, nothing more), Spine automation provisions Hub + OpenBao + Postgres into your account, you get a Hub URL. To exit: revoke the role; the Hub keeps running; you take over ops. **No lock-in. Zero data migration. The deployment doesn't move.**

Air-gapped lands in v1.1.

Full details: [`docs/DEPLOYMENT_SHAPES.md`](docs/DEPLOYMENT_SHAPES.md).

---

## Install

The Day-0 experience is a single wizard. From a fresh checkout:

```bash
bash install.sh ~/spine        # creates ~/spine, runs vault wizard + Hub container bootstrap
cd ~/spine
make hub-up                    # docker compose up -d — Vault + Keycloak + Postgres + Hub
open $(cat _state/hub_url)     # opens the Hub in your browser
```

The wizard asks you:

1. **Deployment shape** — laptop / BYOC / customer-cloud / on-prem
2. **Vault adapter** — bundled OpenBao / external HashiCorp Vault / AWS Secrets Manager / Azure Key Vault / GCP Secret Manager
3. **Keycloak** — bundled / external (federate from Okta / Azure AD / Google Workspace / Ping / OneLogin)
4. **LLM provider(s)** — primary required; add as many as you want
5. **Initial admin** — email + Keycloak credentials (written into vault, never to disk)
6. **License bundle** — paste signed bundle from vendor (free tier auto-generated for laptop)
7. **Parent Hub** — leave blank for standalone; paste parent Hub URL to federate (#10)

Every prompt has a `--flag` equivalent so an AI agent can drive the wizard non-interactively (#21).

Full install guide including all four shapes: [`INSTALL.md`](INSTALL.md).

---

## Documentation map

| Read this | When |
|---|---|
| [`docs/V3_DESIGN_DECISIONS.md`](docs/V3_DESIGN_DECISIONS.md) | Source of truth — every architectural choice with rationale |
| [`docs/positioning.md`](docs/positioning.md) | Strategic story for an outside reader |
| [`docs/PRD.md`](docs/PRD.md) | Product requirements (REQ-INIT-N anchors) |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | v3 top-level layout + subsystem map |
| [`INSTALL.md`](INSTALL.md) | All four deployment shapes + BYOC mechanics |
| [`docs/HUB_OPERATIONS_GUIDE.md`](docs/HUB_OPERATIONS_GUIDE.md) | Day-to-day running of a Hub |
| [`docs/DEPLOYMENT_SHAPES.md`](docs/DEPLOYMENT_SHAPES.md) | 4 shapes × 7 cloud providers |
| [`docs/FEDERATION_GUIDE.md`](docs/FEDERATION_GUIDE.md) | Parent / child Hub setup + update cascade |
| [`docs/SECURITY_GUIDE.md`](docs/SECURITY_GUIDE.md) | Vault posture + closed-source compensations + Keycloak |
| [`docs/LICENSING_GUIDE.md`](docs/LICENSING_GUIDE.md) | Signed bundles + feature flags + quotas |
| [`docs/DR_RUNBOOK.md`](docs/DR_RUNBOOK.md) | 12-layer DR operationally |
| [`db/README.md`](db/README.md) | Postgres schema (V1–V35) |

---

## Why closed-source v1.0 (#18)

Spine is closed-source for v1.0. Open-sourcing the project Spine engine is on the table once enterprise traction is real — not Day 1. There is **no GitHub-stars-as-trust narrative** here. Instead, trust is earned via:

- **Founder presence** — Khash is reachable. Office hours, Discord, public roadmap.
- **Design-partner case studies** — published with named customers as they ship.
- **Discord community** — for support, recipes, and discussion.
- **Public roadmap** — every Wave and decision in `docs/V3_BUILD_SEQUENCE.md` and `docs/STATUS.md`.
- **Public uptime + security posture page** — vendor's own SOC 2 status, pen-test summaries, advisories.
- **SOC 2 Type II** (in progress) + independent pen test reports + source-escrow option (Iron Mountain / NCC) for top-tier enterprise.
- **Demo-environment access** for security reviews — full Hub in a sandbox you can hit with whatever scanner you want.

Cloud-provider competition risk: zero. There is nothing to fork.

---

## Status

v3 rebuild is in flight. See [`docs/STATUS.md`](docs/STATUS.md) for the wave-by-wave state. Waves 0–4 complete; Wave 5 (DR + Migration + Landing docs — this rewrite) and Wave 6 (Mobile/Voice/API scaffolds + lib retirement) in progress. Critical path is shared/secrets → shared/identity → hub/ container → Hub web SPA → landing docs → v1.0 ship (`docs/V3_BUILD_SEQUENCE.md` §2.2).

---

## Pricing

Pricing is **deferred** until product is built and tested with real users (#23, #26). Feature-flag licensing is in from Day 1 so any pricing model — per-feature, per-tier, custom contract — is mechanically supported when the vendor sets numbers. See [`docs/LICENSING_GUIDE.md`](docs/LICENSING_GUIDE.md).

---

## License + brand

License terms not yet finalized (closed-source v1.0; OSS license question deferred to whenever / if anything open-sources, per #18 + the deferred-items table in `docs/V3_DESIGN_DECISIONS.md`). Naming and branding are working titles ("Spine") until validated with first paying customers.

For everything else — contact, contributing (closed-source = no public PRs Day 1; bug reports + feature requests via Discord), and roadmap — see the docs map above.
