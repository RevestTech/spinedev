# Spine v1.0 — Release Notes

> An AI software company in a box. Containerized. Self-hosted. Audit-trailed.
> One solo founder or one enterprise org runs a full AI engineering organization
> on a laptop, in their own cloud, or on-prem — under their own control.

**Release date:** `[YYYY-MM-DD]`
**Tier matrix:** Solo · Startup · Enterprise (BYOC + on-prem)
**Deployment shapes:** laptop · BYOC · customer-cloud K8s · on-prem
**Source policy:** closed-source v1.0 (per design decision #18)

---

## Who Spine is for

**You're a solo vibecoder.** You ship product faster with AI than you
ever did without it — but the chat history isn't enough. Decisions get
lost, work goes stale, security review is "I'll come back to it later."
You want the speed of a one-person shop with the discipline of a real
engineering org, on your own machine, without giving anyone else
custody of your code or your secrets.

**You're a startup CTO.** Your AI engineering setup is a graveyard of
scripts, prompts, and Slack threads. You want roles, artifacts,
hand-offs, audit trail, and an org chart that survives the next hire.
You want self-hosted because your investors and your design partners
both ask the same questions about data residency.

**You're an enterprise architect.** AI dev tools are a procurement
problem: "Where does our code go? Who else can see it? What's the SOC
2 / GDPR / sector-regulator story?" You need every-tier self-hosted,
your own IdP, your own vault, your own audit ledger, federation across
business units, and a license envelope your finance team can model.

Spine ships all of that as one product.

---

## What's new in v1.0

v1.0 is the first general-availability release. Earlier "v1" and "v2"
internal builds were a file-bus orchestration framework you dropped
into your own repo; v1.0 is a containerized **Hub** you run as its own
product. Some highlights:

### The Hub (containerized product)

- **Day-0 wizard** — 7 steps, fully flag-driven, runs on first boot.
  Get from `docker compose up` to a working Hub in `[~5 minutes]`.
  No checklists, no YAML editing, no "see the docs."
- **Single image, every tier.** The same `spine/hub` container runs
  Solo, Startup, and Enterprise; your license bundle determines which
  feature flags activate (per #14).
- **Four deployment shapes Day 1.** Laptop (`docker compose`), BYOC
  (Terraform-templated AWS / Azure / GCP / Railway / Fly / DigitalOcean),
  customer-cloud Kubernetes (Helm chart), on-prem (airgap installer).
- **SvelteKit admin SPA** — small bundle, fast, dark-mode native;
  serves the 9 enumerated Hub surfaces (per #3).
- **REST + MCP** — every Hub capability surfaces both as `/api/v2/`
  REST (OIDC + feature-flag gated + rate-limited) and as MCP tools
  (54 tools at GA, registered via `shared/mcp/`).

### Roles + artifacts (Plan / Build / Verify)

- **18 industry-anchored role charters.** Architect (TOGAF), Auditor
  (NIST 800-53), Conductor (Scrum + SAFe), Product (Inspired + JTBD),
  QA (ISTQB), UX (Nielsen + WCAG 2.2), and twelve more. Every charter
  cites a recognized methodology per #7 — no "we made it up."
- **Cite-or-Refuse** for verify-class roles per #12. Auditor / QA /
  Verify tools must cite (KG node ID / file:line / prior audit hash)
  or refuse to act. Refusal is itself an audit event.
- **Workspace hygiene as architectural concern** per #34. Per-run
  workspaces under `.spine/work/<run_id>/`, promote artifacts
  explicitly, archive on completion, Conductor gates project
  completion on a clean workspace.

### Security + trust

- **Vault-only secrets** per #9, no exceptions. Every secret comes
  from a vault adapter (`shared/secrets/`); OpenBao ships embedded
  Day-0. No `env://`. No `.env` containing real values.
- **Hash-chained audit ledger** per #24. Every action — every LLM
  call, every PR, every role decision — writes a `spine_audit`
  ledger row chained to the prior row's SHA-256. Two-party
  attestation pattern with Vanta / Drata / Secureframe via the
  Evidence Store exporters.
- **Federation with mTLS + bearer.** Hub-to-Hub federation per
  #10 + #16 for multi-business-unit enterprise deployments.
- **License bundle Ed25519 signing.** Bundles verified at install,
  re-verified periodically, re-verified at feature-gate check.
  Signing key custody via Shamir 3-of-5 split (`license/shamir.py`).
- **12-layer disaster recovery** per #31 + #32. Backup + restore +
  heartbeat + runbook (`docs/DR_RUNBOOK.md`) all shipped with v1.0.

### Compliance

- **Evidence Store** (`evidence/`) — collectors for every security
  control + native exporters to Vanta, Drata, Secureframe.
- **SOC 2 Type II** window starting `[YYYY-MM-DD]` on Spine's
  license-bundle service + telemetry ingest (the only surfaces Spine
  itself operates).
- **Source escrow** available at Enterprise tier `[escrow agent]`.

### Migration tooling

- **Onboarding** (`migration/onboarding.py`) — assist new design
  partners standing up their first Hub.
- **Portability** — export your entire Hub state (audit ledger,
  workspaces, charters, bundles) to take to another vendor at any
  time. We make leaving easy on purpose.
- **Version migrator** — `[upgrade path from v3.x to v1.0]`.

### Smart Spine learning loop (opt-in)

A 3-tier opt-in loop per #27 that lets your Hub get smarter over time
by sharing anonymized signals with Spine. **All three tiers are OFF by
default.** Enable per tier from the Hub admin UI with on-screen consent
that explains exactly what's transmitted. Revocable at any time.

### Developer surfaces (scaffolds)

- **Mobile** (`mobile/`) — iOS + Android scaffold; Hub API routes
  ready for client apps in v1.x.
- **Voice** (`voice/`) — Twilio adapter scaffold; voice-driven role
  invocation in v1.x.

---

## How to get started

1. **Solo / Startup laptop:**
   ```
   git clone <your-licensed-distribution>
   make bootstrap
   docker compose -f hub/docker-compose.yml up
   ```
   Hub at `http://localhost:8090`. Day-0 wizard runs on first boot.

2. **BYOC:**
   ```
   tools/byoc/provision.sh <cloud>
   ```
   where `<cloud>` is one of `aws`, `azure`, `gcp`, `railway`, `fly`,
   `do`. See `docs/DEPLOYMENT_SHAPES.md`.

3. **Customer-cloud Kubernetes:**
   ```
   helm install spine ./hub/chart \
     --set licenseBundle=$(cat your-license-bundle.json | base64) \
     --values your-values.yaml
   ```
   See `docs/HUB_OPERATIONS_GUIDE.md`.

4. **On-prem / airgap:**
   See `docs/DEPLOYMENT_SHAPES.md` §`[airgap]`.

---

## Known limits (v1.0)

- **Mobile + Voice** ship as scaffolds (`mobile/` + `voice/`); first
  client surfaces target v1.1.
- **iOS / Android client apps** not in v1.0; v1.x.
- **Custom IdPs beyond Keycloak's 5-preset matrix** require an
  Enterprise SOW.
- **Federation across cloud providers** supported; latency profiles
  best between cloud regions of the same provider.
- **Smart Spine learning loop** tiers 2 and 3 require explicit
  per-tier consent + the corresponding feature flag in your bundle.

---

## Upgrade path

This is the first general-availability v1.0. Customers running
pre-release v3.x builds: see `docs/V1_SHIP_CHECKLIST.md` §0 + the
version-migrator notes in `migration/version_migrator.py`.

The pre-v3 file-bus orchestration framework (v1.x / v2.x internal
builds that lived in `lib/`) is **fully retired** per Wave 6. Migrate
to v1.0 by deploying a Hub and importing your existing workspace
state via the migration tooling.

---

## Support

- **Solo / Startup:** community Slack at `[invite link]`, GitHub
  Issues for bug reports, `[support hours]`.
- **Enterprise:** designated support contacts per your MSA; response
  times per support tier in your Order Form.
- **Security disclosures:** `security@spine.dev` (PGP key at
  `[link]`).
- **Status:** `status.spine.dev` (per `docs/STATUS_PAGE_SETUP.md`).

---

## Documentation

| Doc | Purpose |
|---|---|
| `docs/PRD.md` | Product requirements + positioning |
| `docs/ARCHITECTURE.md` | Architectural overview |
| `docs/DEPLOYMENT_SHAPES.md` | The 4 ways to run a Hub |
| `docs/HUB_OPERATIONS_GUIDE.md` | Day-2 operations |
| `docs/SECURITY_GUIDE.md` | Security posture + incident response |
| `docs/LICENSING_GUIDE.md` | License bundles + feature flags |
| `docs/FEDERATION_GUIDE.md` | Hub-to-Hub federation |
| `docs/DR_RUNBOOK.md` | Disaster recovery |
| `docs/legal/EULA_TEMPLATE.md` | End-user license |
| `docs/legal/MSA_TEMPLATE.md` | Master Services Agreement |
| `docs/legal/DPA_TEMPLATE.md` | Data Processing Addendum |

For the full v1.0 internal change log + commit-level provenance, see
`CHANGELOG.md` `[Unreleased] — v1.0`.

---

**Built by Spine, with Spine.** Per #21 (all-AI-all-the-time): every
line of v1.0 code is in our own audit ledger. The trust mechanism is
the audit chain — not "trust us."

`[Vendor Legal Entity]` · `[contact@spine.dev]` · `[spine.dev]`
