# Federation Guide

> Set up and run parent / child Hubs. Manage the update cascade. Understand consent + bounded mandatory upward flows. Drivers: [`V3_DESIGN_DECISIONS.md`](V3_DESIGN_DECISIONS.md) — **#4** (control plane / data plane split), **#10** (fractal Hub — "a Hub is a Hub is a Hub"), **#16** (update distribution via federation tree with per-tier approval), **#9** (vault-only secrets for federation creds), **#23** (license grants ride the federation tree).
>
> **Audience:** Hub admin federating their Hub under a parent, OR an enterprise admin setting up corporate → division → team Hub hierarchy.

---

## 1. What federation IS and ISN'T

### IS

- **Fractal Hub topology** — the same Hub container runs at every tier (team / division / enterprise / corporate). One product. Zero structural difference between a single-team Hub and a corporate-root Hub. (#10)
- **Control plane / data plane split** — federation moves *control* (bundle updates, license grants, audit aggregates, security advisories) up and down the tree. Data (your code, your secrets, your raw audit chain) **never crosses tier boundary** unless bundle policy explicitly opens that channel. (#4)
- **Update distribution channel** — vendor publishes signed Hub releases → corporate approves → distributes to divisions → divisions approve → distribute to teams. Per-tier admin approval; **auto-push never** (unless bundle declares `auto_approve_security_patches: true` for that admin's trust posture). (#16)
- **Consent-leaning** — peer-consent by default; bounded mandatory upward flows declared in bundle for compliance (e.g., "all subsidiary Hubs report security incidents upward"). (#10)

### ISN'T

- **Not SaaS multi-tenancy.** Each Hub is fully self-contained; the parent is not a SaaS for the child. (#15)
- **Not a CI/CD pipeline.** Federation distributes policy + bundles, not code artifacts. Code lives in customer's git provider; build artifacts live in customer's container registry.
- **Not a chat aggregator.** Master roles at the parent don't read raw conversations at the child unless explicit consent grant exists.

---

## 2. Topology examples

### Solo founder (laptop) — no federation
```
[Spine Hub (laptop)]   ← subscribes direct to vendor for updates (#16)
        │
        └── all projects, all decisions, all audits — local
```

### Mid-market team (customer-cloud)
```
                [Vendor (root)]
                       │
                       ▼  signed bundle updates
            [Team Hub] ← admin approves each release
                       │
                       └── 12 projects, 8 engineers, 1 PM
```

### Regulated enterprise (corporate)
```
            [Vendor (root)]
                   │
                   ▼  signed updates (security advisories, charter improvements)
        [Corporate Hub] ← Compliance Officer approves
                   │
        ┌──────────┼──────────┐
        ▼          ▼          ▼   bounded mandatory upward: security incidents
   [Division A] [Division B] [Division C]    ← Division CTOs approve
        │          │          │
   ┌────┼────┐    │     ┌─────┼──────┐
   ▼    ▼    ▼   ▼     ▼     ▼      ▼
 [T1] [T2] [T3]…    [T1] [T2] [T3] [T4]    ← Team Hub admins approve
```

Each box is the **same Hub container** in a different role per the federation hub registry (V23). `spine_federation.hub.role` ∈ `{vendor, corporate, division, team, project, leaf}`.

---

## 3. Day-2: register a child under a parent

### Step 1 — On the parent Hub

```bash
# Issue an invite for the child
spine federation invite \
    --child-name "marketing-team" \
    --output /tmp/marketing-invite.json
```

This produces a one-time invite token containing: parent Hub URL, parent's public CA, expected child hub_id placeholder, signed claims about what consent the parent is granting the child (typically: receive bundles, send aggregated audits, do NOT send raw audit chain).

The invite is **vault-signed** (#9) — the underlying mTLS materials live under `federation/mtls/<role>/` in the parent's vault.

### Step 2 — On the child Hub (during install OR after)

During install:
```bash
bash hub/wizard/init.sh \
    --parent-hub https://corporate.acme.com \
    --invite /tmp/marketing-invite.json
```

Post-install (existing Hub joining):
```bash
spine federation register \
    --parent https://corporate.acme.com \
    --invite /tmp/marketing-invite.json
# Confirms consent grant; mints child mTLS materials into local vault;
# writes spine_federation.hub row with parent_hub_id set
```

### Step 3 — Confirm on the parent

```bash
spine federation list
# corporate.acme.com (root) — me
#   ├── division-retail.acme.com
#   │     ├── team-checkout.acme.com   ← just joined
#   │     └── team-inventory.acme.com
#   └── division-investment.acme.com
```

Parent's Hub UI Registry → Federation panel shows the new child with status `consent_pending` until the parent admin approves.

### Step 4 — Approve / configure consent

Hub UI Decision Queue at parent gets a card: *"New child Hub: team-checkout requesting consent to receive bundle updates"*. Admin approves (per `federation/consent.py`).

Bundle policy at parent declares default consent posture for new children. To customize:

```bash
spine federation consent grant \
    --child team-checkout.acme.com \
    --tools 'license_get_status,bundle_apply,federation_pull_updates' \
    --reason "Standard child onboarding"
```

---

## 4. The update cascade (#16)

When vendor publishes a new Hub release:

1. Vendor signs the bundle (`tools/license-sign.sh sign ...`). Bundle includes: new container image fingerprint, changelog, risk notes, rollout cadence, impact preview, OPTIONAL `auto_approve_security_patches` hint for low-severity sec patches.

2. Vendor's federation endpoint publishes the bundle to all directly-subscribed Hubs (typically just corporate Hubs of customers; standalone Hubs subscribe direct).

3. **Corporate Hub's** decision queue fires a card. Compliance Officer + CTO (per bundle approval policy) review → approve / defer / reject.

4. On approve: `update_cascade.py` forwards the signed bundle to all **division** children that have consented to bundle updates.

5. **Division Hub's** decision queue fires a card. Division CTO approves → cascade continues to **team** children.

6. **Team Hub's** admin approves → Hub takes a backup (DR layer 12 verification), pulls signed image, validates fingerprint, restarts under new version.

7. Audit chain records, at every tier: who approved + when + reason + bundle hash. Each tier's audit chain anchors into its parent's chain via SHA-256 anchor records (so parent can prove compliance without seeing child's raw audit data).

### Auto-approve security patches

```yaml
# In a Hub's bundle policy
federation:
  update_policy:
    auto_approve_security_patches: true   # only takes effect for vendor-signed sec patches
    auto_approve_max_severity: "low"      # "low" | "medium" | "high" — bundle declares ceiling
    require_human_for: ["high", "critical", "breaking_change"]
```

Even when auto-approve fires, the admin gets a post-fact audit entry — you always know what happened.

### Rollback

```bash
spine hub update --rollback --to <prior-release-id>
# Restores Postgres to pre-update snapshot per DR layer 9; pulls prior image; restarts
```

---

## 5. Consent model (#10)

Federation uses **consent-leaning hybrid** trust:

| Default | Override mechanism |
|---|---|
| **Peer consent** for most flows (child must opt in to receive each new tool grant from parent) | Bundle policy at parent can declare `default_consent: granted` for child tools listed |
| **Bounded mandatory upward flows** for compliance (declared in bundle at parent level) | Examples: "all subsidiary Hubs report security incidents upward"; "all GRC-class audit events flow to corporate Evidence Store" |

### Bundle-declared mandatory flows

```yaml
# In the corporate Hub's bundle (parent of all subsidiaries)
federation:
  mandatory_upward:
    - event_class: "security.incident.created"
      target_tier: "corporate"
      include_payload: false        # only metadata; payload stays at originating Hub
      audit_required: true
    - event_class: "compliance.control_failure"
      target_tier: "division"
      include_payload: true         # division compliance needs the detail
      audit_required: true
```

Children CANNOT opt out of mandatory_upward flows — that's the "bounded mandatory" part of #10. The bundle change itself is an audit event children can see; if they object, they object via bundle-policy dispute mechanism (admin escalation up the tree), not by ignoring the flow.

### Peer-consent flows

```yaml
# In a child Hub's bundle (team-checkout consenting upward)
federation:
  upward_consent:
    aggregated_audits:
      enabled: true
      frequency: "weekly"
      include: ["count_by_role", "decision_latency_p50", "cost_summary"]
      exclude: ["raw_events", "user_emails", "secret_paths"]
    license_pull:
      enabled: true                 # child fetches license updates from parent
    bundle_pull:
      enabled: true                 # child fetches bundle updates from parent
```

The Hub UI surface for this is at `/hubs` → child → "Consent settings".

---

## 6. License grants via federation (#23)

License bundles flow through the same federation tree as Hub releases.

Vendor publishes a signed license bundle to corporate. Corporate approves. Corporate forwards (cascade) to divisions that have consented to license-pull. Divisions forward to teams.

This means: when corporate buys a new feature, divisions and teams **see the new flag enabled in their next update card**. They don't need to wait for a separate license-distribution channel.

Quota-style flags (`max_projects: 50`) are evaluated locally at each Hub — the team Hub knows its own count. Quota usage rolls up to corporate (aggregated, anonymized) via consent grants.

---

## 7. The MCP tool surface

Federation exposes 4 MCP tools (`shared/mcp/tools/federation.py`):

| Tool | Used by | Purpose |
|---|---|---|
| `federation_register_child` | Parent Hub admin | Issue invite + register child once it joins |
| `federation_grant_consent` | Parent Hub admin | Grant a new tool / data class to a child |
| `federation_push_update` | Parent (typically called by `update_cascade.py`) | Send a bundle down the tree |
| `federation_pull_updates` | Child Hub | Pull pending updates from parent |

AI agents drive these end-to-end per #21 — federating a new team Hub under corporate can be fully automated from `spine federation invite` through to update cascade.

---

## 8. Federation autonomy (DR layer 6 — #32)

**If a parent Hub goes down, children keep working autonomously.** No cascading failures.

- Children continue normal operation (project work, decisions, audits all flow locally)
- Children buffer pending upward flows (security incident reports, aggregated audits) in their own queue
- When parent comes back: children flush the buffer; parent's audit chain re-anchors the buffered child events
- License flags continue to work (bundle is verified locally each gate)
- Updates: children can't pull from a down parent, but they can still subscribe direct to vendor as fallback (configurable per bundle)

This is the architectural reason "fractal Hub" works at scale — no single point of failure for the federation tree.

---

## 9. Updating bundles + role charters via federation

Bundles + role charters distributed Hub→projects per #7 are themselves federation-distributable. Same cascade pattern as Hub releases:

```bash
# Vendor or corporate updates a charter (e.g., security_engineer charter NIST 800-53 refresh)
spine bundle edit --file shared/charters/security_engineer.md
spine bundle sign --bundle <bundle-id>

# Push down the tree (consent + per-tier approval per child Hub policy)
spine federation push-bundle --bundle-id <id> --to-children all
```

Children see a Decision Queue card: *"New security_engineer charter from corporate — review changes"*. Approve → charter takes effect on next project intake → audit chain records who approved.

---

## 10. Troubleshooting

### Child registration fails: "mTLS handshake failed"

```bash
# Verify both Hubs trust each other's CA
spine federation diagnose --parent https://corporate.acme.com

# Common: child's vault doesn't have parent's CA in trust store. Fix:
vault kv put spine/federation/trust_anchors/corporate.acme.com cert=@parent-ca.pem
spine restart federation
```

### Update cascade stuck at one tier

```bash
# Where in the cascade did it stall?
spine federation update-status --bundle-id <id>
# corporate.acme.com    APPROVED 2026-05-18T10:00:00Z
# division-retail.acme.com    PENDING (Decision Queue card #abc123, owner cto@retail.acme.com)
# division-investment.acme.com   APPROVED 2026-05-18T11:15:00Z
#   └── team-fixed-income.acme.com    PENDING (Decision Queue card #def456)
```

Page the named owners; resolve via Hub UI Decision Queue.

### Mandatory upward flow blocked by child

Mandatory flows cannot be blocked by child consent — if a child Hub is refusing the flow, it's a bug in `consent.py` enforcement, not a feature. File a vendor support ticket with the audit-chain snippet showing the refusal.

### Aggregate reads from parent showing stale child data

```bash
# Force re-pull aggregated data from a child
spine federation pull-aggregates --from team-checkout.acme.com --since 2026-05-17T00:00:00Z
```

Children push aggregates on consented cadence (default weekly); manual pull works for spot checks.

---

## 11. Multi-cloud federation example

Common pattern: corporate runs on-prem; subsidiaries run customer-cloud on different clouds.

```text
[Corporate Hub (on-prem, OpenBao+Shamir)]
        │
        ├── [Division-Americas (AWS EKS)] — vault adapter: aws
        │     ├── [Team-Boston (BYOC-Railway)]
        │     └── [Team-SF (BYOC-AWS)]
        ├── [Division-EMEA (Azure AKS)] — vault adapter: azure
        │     └── [Team-London (laptop)]    ← single dev evaluating
        └── [Division-APAC (GCP GKE)] — vault adapter: gcp
              └── [Team-Tokyo (BYOC-Fly)]
```

Federation works identically regardless of cloud — mTLS + bearer auth handles the transport; consent policy handles what flows.

---

## 12. Related artifacts

- [`docs/HUB_OPERATIONS_GUIDE.md`](HUB_OPERATIONS_GUIDE.md) — day-2 Hub ops
- [`docs/DEPLOYMENT_SHAPES.md`](DEPLOYMENT_SHAPES.md) — per-shape × per-cloud matrix
- [`docs/LICENSING_GUIDE.md`](LICENSING_GUIDE.md) — license grants ride federation tree
- [`docs/SECURITY_GUIDE.md`](SECURITY_GUIDE.md) — mTLS + bearer auth detail
- [`docs/DR_RUNBOOK.md`](DR_RUNBOOK.md) — federation autonomy (DR layer 6)
- `federation/README.md` — subsystem internals
- `federation/consent.py` — ConsentEngine reference
- `federation/update_cascade.py` — cascade implementation
- `shared/mcp/tools/federation.py` — 4 MCP tools
