# Licensing Guide

> Signed bundles, feature flags, quota metering. The architecture that makes any pricing model mechanically supported without touching code. Drivers: [`V3_DESIGN_DECISIONS.md`](V3_DESIGN_DECISIONS.md) — **#23** (pricing deferred + feature-flag licensing as Day-1 architectural primitive), **#18** (closed-source v1.0 — license is the anti-piracy seam), **#16** (license grants ride the federation update tree), **#26** (business ops including pricing deferred until product exists).
>
> **Audience:** Hub admin managing license + flag state; vendor staff signing bundles; security reviewer auditing the license trust chain.

---

## 1. The shortest possible statement

> **Pricing is deferred. Feature-flag licensing is in from Day 1. Every feature has a flag. Bundles are signed Ed25519. License verification is local (no phone-home). Pricing experimentation is changing bundle content, not refactoring code.** (#23)

---

## 2. Why this architecture (#23)

Per `V3_DESIGN_DECISIONS.md` #23 — **pricing deferred** until product is built and tested with real users. **Feature-level access control is a Day-1 architectural primitive.** Any pricing model — per-feature solo, bundled tiers mid-market, custom contracts enterprise — becomes mechanically supported when ready to set numbers.

Reference pattern: HashiCorp Vault Enterprise, Confluent Platform, MongoDB Atlas Enterprise. All ship one binary; licensing lives in a signed bundle that unlocks features.

Spine differs in two ways:

1. **NOT SaaS** (#15) — license verification is **local**, not phone-home. Air-gapped + on-prem deployments work without any vendor connectivity beyond initial bundle import.
2. **Bundle distribution rides the federation tree** (#16) — license grants flow vendor → corporate → division → team through the same approval-gated cascade as Hub releases.

---

## 3. Anatomy of a license bundle

A license bundle is a JSON document containing:

```json
{
  "bundle_version": "1.0",
  "bundle_id": "bdl_2026Q2_acme_enterprise_001",
  "customer": {
    "name": "Acme Bank",
    "hub_fingerprint": "abc123...",
    "tier": "enterprise"
  },
  "issued_at": "2026-04-01T00:00:00Z",
  "expires_at": "2027-04-01T00:00:00Z",
  "feature_flags": {
    "federation.enabled": true,
    "federation.consent_engine": true,
    "license.full_seats": true,
    "integrations.pagerduty": true,
    "integrations.vanta": true,
    "integrations.drata": false,
    "integrations.secureframe": false,
    "customer_support.role_enabled": true,
    "compliance_officer.role_enabled": true,
    "max_projects": 500,
    "max_users": 1000,
    "aws.provisioning": true,
    "azure.provisioning": true,
    "gcp.provisioning": false,
    "dr.cross_region": true,
    "learning.cross_org_telemetry": false,
    "keycloak.multi_realm": true,
    "keycloak.scim_2_0": true,
    "keycloak.webauthn": true
  },
  "quotas": {
    "llm.tokens_per_day": 100000000,
    "decisions.cards_per_user_per_day": 200,
    "audit.retention_days": 2555,
    "evidence.exports_per_day": 10000
  },
  "issuer": "spine.dev",
  "signature": "ed25519:..."
}
```

The `signature` covers all preceding fields. Trust anchor: `TRUSTED_VENDOR_FINGERPRINT` baked into Hub binary at build time per #23 (closed-source = signature trust chain is the anti-piracy seam per #18).

---

## 4. Verification — local, periodic, per-gate

`license/bundle_verifier.py` runs three times:

1. **On Hub startup** — load active bundle from `spine_license.bundle` (V22), verify Ed25519 signature against `TRUSTED_VENDOR_FINGERPRINT`. Refuse to start if invalid.
2. **Periodically** — default 1h (configurable per bundle policy). If bundle expired / revoked / signature broken: Hub enters degraded mode (free tier only) and surfaces a Decision Queue card.
3. **On every feature gate** — `license.is_enabled("flag.name")` consults the in-memory verified bundle. Fast path (no I/O).

No phone-home. Air-gapped works fully. The vendor publishes signed bundles to a public mirror; customer's secure courier imports for air-gapped (#17 + #18).

---

## 5. The `is_enabled` API

Every Hub feature calls `license.is_enabled("flag.name")` before executing. Examples:

```python
from license import feature_flags

if not feature_flags.is_enabled("federation.enabled"):
    raise HTTPException(403, "Federation requires a tier with `federation.enabled` flag")

if not feature_flags.is_enabled("integrations.pagerduty"):
    return upgrade_cta("Connect PagerDuty", "team_tier")
```

**Gating UX = product discovery, not a wall.** If a flag is OFF: graceful UI message + "Upgrade to unlock" CTA path. The user sees what's possible.

---

## 6. Quota metering — Day 1 even when not billed

Per #23: per-feature usage metering Day 1, even if not billed yet. Tells us which features are most-used, most-valued, by which segment — exact data needed to set rational pricing later.

`license/quota_ledger.py` writes hash-chained usage records to `spine_license.quota_usage` (V22). Same chain pattern as `spine_audit` — tamper-evident.

```bash
spine license usage
# Shows current period usage vs quotas:
#   llm.tokens_per_day:    47,892,134 / 100,000,000 (47.9%)
#   decisions.cards/user/day:  84 avg / 200 cap
#   evidence.exports/day:  1,247 / 10,000 (12.5%)
```

When a quota approaches its cap: Decision Queue card warns the admin; at hard cap, the Hub denies the next call gracefully + offers "Increase quota" link (post-launch this links to vendor upgrade flow; today it's a contact form).

---

## 7. Federation distribution of license grants (#16)

License bundles ride the same federation cascade as Hub releases. When vendor issues a new bundle to a corporate customer:

1. Vendor signs bundle (`tools/license-sign.sh sign ...`)
2. Vendor publishes to federation endpoint for that customer
3. **Corporate Hub's** Decision Queue: *"New license bundle: enterprise tier, +federation.consent_engine, expires 2027-04-01"*
4. Corporate admin approves → bundle stored in `spine_license.bundle` table; old bundle marked superseded
5. If divisions consent to license-pull: bundle cascades down with per-tier approval

This means: when corporate buys a new feature for the org, divisions and teams see the new flag enabled on their next update card. They don't wait for a separate license-distribution channel.

---

## 8. Vendor-side: signing bundles

`tools/license-sign.sh` is the vendor-side signing CLI (NOT shipped to customers). Subcommands:

```bash
# Bootstrap fresh Ed25519 keypair (vendor first-run only; rotation via Shamir recovery)
tools/license-sign.sh bootstrap-keypair --vault-path license/vendor_signing_key

# Sign a bundle (loads private key from vault, signs in memory, exits — key never lands on disk)
tools/license-sign.sh sign \
    --payload customer-acme-bundle.json \
    --output customer-acme-bundle.signed.json \
    --vault-path license/vendor_signing_key

# Verify (smoke-test from signer side; customers use Python `bundle_verifier`)
tools/license-sign.sh verify --bundle customer-acme-bundle.signed.json

# Recover signing key via Shamir 3-of-5 (only when key lost / compromised)
tools/license-sign.sh recover-shamir --shard <hex>   # called 3 times, once per shard holder
```

### Signing key custody (Part 4.3 resolution)

Per `V3_BUILD_SEQUENCE.md` Part 4.3:

- Signing key lives **only** in vendor's vault under `license/vendor_signing_key`
- **Shamir 3-of-5 recovery** for the master signing key (HashiCorp Enterprise pattern)
- 5 named vendor staff hold shards offline (multi-jurisdictional for resilience)
- If key compromised: reconstruct from 3 shards into new vault path; release new Hub binary with updated `TRUSTED_VENDOR_FINGERPRINT`

This is the vendor-internal counterpart to customer-side vault unseal recovery (#32 layer 8).

---

## 9. Per-tier flag inventory (target — pricing deferred)

Pricing tiers per `V3_DESIGN_DECISIONS.md` #14 (3 segments × 4 deployment shapes). Tier names are working labels; pricing TBD.

| Flag class | Free | Founder | Team | Enterprise | Air-gapped |
|---|:---:|:---:|:---:|:---:|:---:|
| **Federation** | ❌ | ❌ | ✅ self only | ✅ full | ✅ full |
| **License bundle multi-Hub** | ❌ | single | up to 5 | unlimited | unlimited |
| **Customer support role** | ❌ | ❌ | ✅ | ✅ | ✅ |
| **Compliance officer role** | ❌ | ❌ | ✅ | ✅ | ✅ |
| **Master roles (#5)** | 5 of 9 | 7 of 9 | full | full | full |
| **Smart Spine within-Hub** | ✅ | ✅ | ✅ | ✅ | ✅ |
| **Smart Spine cross-org telemetry** | ❌ | opt-in | opt-in | opt-in (typically off) | ❌ forbidden |
| **Integrations: GH, Linear/Jira, Slack** | ✅ | ✅ | ✅ | ✅ | ✅ |
| **Integrations: PagerDuty, Twilio, Teams** | ❌ | ❌ | ✅ | ✅ | ✅ |
| **Integrations: Vanta + Drata + Secureframe** | ❌ | 1 of 3 | 2 of 3 | full 3 | full 3 |
| **Cloud provisioning: AWS / Azure / GCP** | ❌ | 1 of 3 | 2 of 3 | full 3 | n/a |
| **Cloud provisioning: Railway / Fly / DO** | ❌ | full 3 | full 3 | full 3 | n/a |
| **DR cross-region active-passive** | ❌ | ❌ | opt-in | recommended | mandatory |
| **DR weekly test enforcement** | recommended | recommended | required | required | required |
| **Keycloak multi-realm** | ❌ | ❌ | ❌ | ✅ | opt |
| **Keycloak SCIM 2.0** | ❌ | ❌ | basic | full 2.0 | full 2.0 |
| **Keycloak WebAuthn / passkey** | ❌ | ❌ | ❌ | ✅ | ✅ |
| **Audit retention** | 30d | 90d | 1y | per regulator | per regulator |
| **Source escrow** | ❌ | ❌ | ❌ | optional add-on | optional add-on |

Reminder: **none of these tiers are priced today** per #23 + #26. The flag plumbing exists; the dollars do not. Names + ladder may change.

---

## 10. Quota dimensions

| Quota | Unit | Why metered |
|---|---|---|
| `llm.tokens_per_day` | tokens | Cost control + capacity planning |
| `decisions.cards_per_user_per_day` | cards | Per-user signal — heavy approvers vs casual |
| `audit.retention_days` | days | Regulatory variant |
| `evidence.exports_per_day` | per-GRC pushes | Vanta/Drata API rate-limit alignment |
| `max_projects` | projects | Tier ladder |
| `max_users` | distinct Keycloak users | Tier ladder |
| `federation.children_max` | child Hubs | Tier ladder |
| `learning.cross_org_telemetry_events_per_day` | events | Cross-org privacy control |

Quota usage hash-chained in `spine_license.quota_usage` (V22).

---

## 11. The MCP tool surface

`shared/mcp/tools/license.py` exposes 3 tools:

| Tool | Used by | Purpose |
|---|---|---|
| `license_get_status` | Hub UI, admins, AI agents | Returns current bundle + flags + expiry + fingerprint |
| `license_get_usage` | Hub UI usage tab, finance teams | Returns quota usage current period |
| `license_verify_bundle` | Hub UI vault-config tab, audit | On-demand re-verify signature (smoke test) |

AI agents drive license operations per #21 — admin can ask Master Compliance Officer *"verify our license bundle"* via chat; it calls `license_verify_bundle` and reports.

---

## 12. Failure modes

### Bundle expired

Hub enters degraded mode: free-tier flags only; Decision Queue card warns admin; Hub remains functional for in-flight work but blocks new tier-gated features. Admin pastes new bundle via Hub UI Vault-config → License OR via CLI:

```bash
spine license apply --bundle new-bundle.signed.json
```

### Signature verification failed (wrong fingerprint)

Hub refuses to start (Day-0) OR enters degraded mode (in-flight). Logs identify which check failed: `bundle.issuer != TRUSTED_VENDOR_FINGERPRINT` OR `bundle.signature invalid`. Common cause: trying to use a bundle signed by an old vendor signing key against a newer Hub binary with the rotated fingerprint. Fix: upgrade Hub binary to a version that trusts both old + new fingerprints during the rotation window, OR re-issue bundle with current signing key.

### Quota exceeded mid-operation

Operation completes (no mid-call kill); next call denied with `429` + UX surface explaining quota + upgrade path. Quota window typically `per_day` (UTC); resets at 00:00 UTC.

### License revoked by vendor

Vendor issues a revocation bundle (same signature pattern; revokes prior bundle by ID). Hub picks up on next periodic verify; degrades to free tier. **Rare in practice** — vendor's posture is graceful: contact, negotiate, replace, never silently revoke.

---

## 13. Compliance + audit perspective

Every license event is in `spine_audit` with `subsystem=mcp` (license MCP tool calls) + custom `action` field:

- `license.bundle.applied`
- `license.bundle.verified` (every periodic verify; visible in audit)
- `license.bundle.expired`
- `license.flag.evaluated` (heavy — typically aggregated; emit only on first-of-period or denial)
- `license.quota.exceeded`
- `license.bundle.revoked`

This trail is itself SOC 2-grade evidence — proves the customer is operating within licensed boundaries.

---

## 14. AI-drivable license ops (#21)

Common AI-driven license workflows:

```bash
# AI agent renews a license proactively before expiry
spine license status --json | jq .expires_at
# Compare to today; if < 30 days: agent files a request via Master Compliance Officer

# AI agent compares two bundle versions for diff impact
spine license diff --from <bundle-A> --to <bundle-B>
# +integrations.secureframe enabled
# +keycloak.scim_2_0 enabled
# +max_projects 100 → 500
# -learning.cross_org_telemetry remained off

# AI agent runs a quota projection
spine license usage --project 30d
# llm.tokens_per_day:  projected to hit cap in 12 days at current rate
```

---

## 15. Related artifacts

- `license/README.md` — license subsystem internals
- `license/bundle_verifier.py` — verification implementation
- `license/feature_flags.py` — `is_enabled` hot path
- `license/quota_ledger.py` — hash-chained quota writer
- `tools/license-sign.sh` — vendor-side signing CLI
- `shared/mcp/tools/license.py` — 3 MCP tools
- `shared/schemas/license/bundle_v1.py` — Pydantic models for bundle wire format
- `db/flyway/sql/V22__license_registry.sql` — Postgres schema
- [`docs/SECURITY_GUIDE.md`](SECURITY_GUIDE.md) §5 — closed-source compensation list (license = anti-piracy seam)
- [`docs/FEDERATION_GUIDE.md`](FEDERATION_GUIDE.md) §6 — license grants ride federation tree
- [`docs/V3_DESIGN_DECISIONS.md`](V3_DESIGN_DECISIONS.md) #23, #18, #16, #26 — driver decisions
