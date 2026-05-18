# Security Guide

> Spine's security posture: what we ship, what we DON'T hold, how we compensate for closed-source. Drivers: [`V3_DESIGN_DECISIONS.md`](V3_DESIGN_DECISIONS.md) — **#9** (vault-only secrets, OpenBao Day-0 default), **#15** (NOT SaaS — vendor never holds customer data), **#18** (closed-source v1.0 — explicit compensation list), **#24** (SOC 2 evidence pipeline), **#25** (Keycloak embedded; OIDC + federation), **#12** (Cite-or-Refuse for verify-class roles), **#32 layer 8** (vault unseal recovery), **#34** (workspace hygiene as architectural concern).
>
> **Audience:** Security reviewer, CISO, compliance team, anyone doing a procurement-grade security review on Spine.

---

## 1. The shortest possible posture statement

> **Spine doesn't hold your code. Spine doesn't hold your secrets. Spine doesn't hold your audit trail. Ever. It can't be subpoenaed for your data. It can't be breached for your data. It doesn't exist in our cloud.** (#15)

Every other claim in this guide flows from that.

---

## 2. NOT SaaS (#15) — what this means in practice

- No vendor-hosted multi-tenant cloud. Period.
- Spine vendor's own infrastructure does NOT process customer workloads.
- The only thing the vendor hosts: an artifact registry for signed Hub releases + license bundles (#16, #23), a status page, the marketing demo at `try.spine.dev` (24h expiry, demo data only, not a product tier).
- BYOC shape (#17) runs the Hub in the **customer's** cloud account via delegated IAM role; vendor sees infra-level metrics (CPU / mem / disk) needed to keep lights on; **vendor never sees Hub contents**.
- All customer data — source code, decisions, audit chain, KG, role memory — never crosses the customer's network boundary unless customer explicitly federates upward to another customer-owned Hub (#10).
- The vendor cannot be compelled to produce customer data (subpoena, breach, government request) because the vendor doesn't have it. The customer's own cloud account / on-prem infra is the only attack surface for customer data.

---

## 3. Vault-only secrets (#9)

### Hard rule

**No `env://`. No built-in secret store. Spine never holds customer secrets in process memory beyond the lifetime of a single LLM call.** All secrets resolve through `shared/secrets/`:

```python
from shared.secrets import get_secret
api_key = get_secret("anthropic/api_key")   # fetched from vault per request
```

### Adapters Day 1

- **OpenBao** (bundled, Day-0 default) — `vault/init-wizard.sh` initializes
- **HashiCorp Vault** (enterprise customer's existing cluster)
- **AWS Secrets Manager** (BYOC + customer-cloud-AWS)
- **Azure Key Vault** (BYOC + customer-cloud-Azure)
- **GCP Secret Manager** (BYOC + customer-cloud-GCP)
- **Infisical** (alternative for cost-sensitive deployments)
- **1Password** (for very small teams using 1Password as their SSO + secret backend)

Adapter selection happens at Day-0 wizard step 2; the choice is recorded in `_state/wizard_manifest.json` for audit.

### What "vault-only" rules out

- No `.env` files with secrets in Wave 0+ code
- No `os.environ.get("SPINE_*` outside `shared/secrets/` (grep enforces; 5 v2 violations closed during Wave 0 Pass 2)
- No secret values written to `_state/`, logs, or docker volumes
- No secrets in container env vars (vault AppRole tokens are the only thing that approximates this — short-lived, scoped, auto-rotated)

### Vault unseal recovery (#32 layer 8)

Operator picks at Day-0:

| Mode | Audience | Mechanism |
|---|---|---|
| **Shamir 3-of-5** | High-security on-prem | 5 named humans receive shards offline; quorum-of-3 needed to unseal after restart. Recovery keys printed ONCE at init; do NOT write to disk unless `--recovery-output=<path>` (chmod 600 + loud warning to move offline). |
| **Cloud-KMS auto-unseal** | BYOC / customer-cloud | AWS KMS / Azure Key Vault / GCP KMS holds the unseal key; vault auto-unseals on restart. Runbook auto-generated per cloud. |

Runbooks: `vault/unseal/shamir-config.md`, `vault/unseal/kms-config-{aws,azure,gcp}.md`. DR runbook: `vault/dr-runbook.md`.

### Vault audit

Every `get_secret(path)` call logs to vault's own audit device + Spine's hash-chained audit ledger (`spine_audit` with `subsystem=secrets`). To review who accessed which secret when:

```bash
spine audit query --subsystem secrets --since 2026-05-17 --user khash@example.com
```

---

## 4. Identity — Keycloak embedded (#25)

### Architecture

Keycloak ships as a **sibling container alongside Hub**. Spine Hub uses Keycloak as its OIDC provider. **Hub never directly handles SAML / SCIM / social-login / MFA logic** — delegates everything to Keycloak. Customer's existing IdP (Okta / Azure AD / Google Workspace / Ping / OneLogin) federates into Keycloak as brokered upstream IdP. **Spine Hub trusts only Keycloak.**

This isolation matters because:

- Identity bugs in Keycloak (10+ years production hardening) are well-studied and have a known patch cadence
- Spine Hub's auth surface is tiny — just OIDC client + bearer token verification
- Customer's IdP migration (Okta → Azure AD) requires NO Spine Hub change — reconfigure Keycloak's brokered IdP, done

### Per-tier feature matrix

Per `keycloak/tier-config.md` — feature-flag lightening per tier (#25):

| Tier | Identity capabilities |
|---|---|
| **Free / laptop** | Single realm; basic username+password; no MFA enforced; no IdP federation |
| **Founder (BYOC)** | + Optional MFA; social login (Google + GitHub); single IdP federation allowed |
| **Team** | + MFA required; multi-IdP federation; basic SCIM; email/SMS notification channels |
| **Enterprise** | + Full SCIM 2.0; multi-realm; advanced password/lockout policy; custom themes; admin event export + retention; WebAuthn / passkey; step-up auth for high-risk operations |
| **Air-gapped (v1.1)** | Works fully (Keycloak has no external deps); social login disabled by default; IdP federation requires local IdP |

### Day-0 bootstrap

`keycloak/init-bootstrap.sh` does (idempotent):

1. Waits for Keycloak `/health/ready`
2. Generates random 32-char admin password (printed ONCE OR written to `--output=<path>` chmod 600)
3. Imports `realm-config/spine-realm.json` (realm = `spine`)
4. Imports `realm-config/spine-hub-client.json` (OIDC client = `spine-hub`)
5. Generates fresh client_secret for `spine-hub`; emits vault-reference manifest (vault/init-wizard.sh writes the actual secret)
6. Seeds default groups: `hub-admins`, `project-admins`, `developers`, `viewers`, `service-accounts` with realmRole mappings

### Brokered IdP presets

`keycloak/idp-presets/` ships ready-to-use brokering configs for Okta / Azure AD / Google Workspace / Ping / OneLogin. Customer admin pastes their IdP-side OIDC client credentials into vault (`spine/keycloak/idp/<name>/client_secret`), then runs:

```bash
keycloak/init-bootstrap.sh --add-idp okta --client-id <id>
```

---

## 5. Closed-source v1.0 (#18) — compensation list

Closed-source for v1.0. Open-sourcing the project Spine engine is on the table after enterprise traction is real — not Day 1.

**What replaces "GitHub stars as trust signal":**

| Compensation | Status / cadence |
|---|---|
| **Founder presence** | Khash directly reachable. Office hours Tue/Thu 11 AM ET. Discord. Public roadmap (`docs/V3_BUILD_SEQUENCE.md`). Direct line for design-partner customers. |
| **Design-partner case studies** | Published with named customers as they ship. First 3 design partners onboarded by v1.0 GA. |
| **Discord community** | Public. Channels: #help, #recipes, #incidents, #compliance, #federation. Vendor staff present in #help during business hours. |
| **Public roadmap + Wave-by-Wave status** | `docs/V3_BUILD_SEQUENCE.md` + `docs/STATUS.md` updated weekly. |
| **Public uptime + security posture page** | `status.spine.dev` — vendor's own SOC 2 status, advisory feed, RPO/RTO commitments. |
| **SOC 2 Type II** | In progress (no longer optional under closed-source per #18). Target completion: q3 2026. |
| **Independent pen test reports** | Annually. Published summary (full report to NDA'd enterprise prospects). |
| **Source-escrow option** | Iron Mountain OR NCC Group. Available for top-tier enterprise contracts. Triggered on vendor insolvency / acquisition / discontinuation. |
| **Demo-environment access** | Full Hub in a sandbox you can hit with whatever scanner you want. Available on request for security reviews. |

**Cloud-provider competition risk:** zero. There is nothing to fork.

**Repo migration:** existing public-trajectory v2 work is moving to private repos immediately (operational follow-through per #18 implications).

---

## 6. Audit chain — the SOC 2 evidence foundation (#24)

### Hash-chained ledger

`spine_audit.record` is append-only with cryptographic chaining:

```
row_hash = sha256(prev_row_hash || canonical(row))
```

Tamper detection: any insert / update / delete out of band breaks the chain. Verifier (`tools/audit-verify-chain.py`) runs on every Hub start + hourly + on every Vanta/Drata push.

### What goes in the ledger

Every action across every subsystem:

- PR opened / merged
- Deploy
- Approval (decision card outcome)
- Config change
- Role authorization granted / revoked
- Vault access (every `get_secret`)
- Capability grant
- Drift remediation
- License flag evaluation result
- Federation update cascade event
- Bundle change

`subsystem` enum extended for v3: `audit` / `cost` / `verify` / `plan` / `build` / `kg` / `lifecycle` / `notify` / `memory` / `eval` / `standards` / `mcp` / `hub` / `federation` / `integration` / `devops` (V33 + V35 extensions).

### Two-party attestation (#24)

The trust play that closes the closed-source gap for regulated buyers:

```
Customer's auditor → opens Vanta/Drata
   sees audit evidence: { PR-123 merged at 14:33, approved by alice@bank,
                          hash 0xABCD... }
   ↓
   reads Spine's hash-chained audit log
   sees row with hash 0xABCD... at same timestamp
   ↓
   matches → trust
```

Two parties (customer's GRC vendor + Spine's hash chain) both attest to the same event. Tampering with either side breaks the match. Regulator-grade.

### Push pipeline

`evidence/` subsystem (#24) does the pushing:

- 5 collectors: `audit_chain` / `role_decision` / `vault_access` / `deploy` / `approval` — extract the right shape per evidence target
- 3 real exporters: Vanta, Drata, Secureframe (Day 1)
- 3 v1.1 stubs: Tugboat Logic, StrikeGraph, Thoropass

Spine becomes the **highest-velocity SOC 2 evidence producer in the customer's stack** — not because it does more work, but because every action is already a real, ordered, signed event.

---

## 7. Verify-class roles — Cite-or-Refuse (#12)

Verify-class roles (`auditor`, `qa`, `verify`) operate under a **strict tier** contract: every action must cite supporting evidence OR refuse to act. Cited evidence is one of:

- KG node ID (e.g., `kg:node:python:src/auth.py:42`)
- File:line reference
- Prior audit row hash

**Refusal is itself an audit event** — `subsystem=verify`, `action=refuse`, `reason=missing_citation`.

Enforcement is wrapper middleware in `shared/mcp/tools/verify.py` + `iso.py`: any verify-class MCP call without `citation` field returns HTTP 422 with explicit Cite-or-Refuse message.

This matters for security review because: when Spine's auditor role greenlights a PR, you can trace exactly which KG node ID and which prior audit hashes justified the greenlight. No black-box approvals.

---

## 8. Federation security (#10)

### Transport

- mTLS between parent + child Hubs. CAs in vault under `federation/mtls/<role>/`.
- Bearer-token auth on top of mTLS (defense in depth). Tokens in vault under `federation/bearer/<role>`.
- All federation traffic over TLS 1.3.

### Authorization

`federation/consent.py` enforces:

- Peer consent by default (child opts in to each tool grant)
- Bounded mandatory upward flows (bundle-declared, e.g., "security incidents flow to corporate")
- Children cannot block mandatory_upward flows; objection is via bundle-policy dispute (admin escalation), not silent refusal

### Audit anchoring

Each Hub's audit chain anchors into its parent's chain via SHA-256 anchor records (#33 Q3 resolution: hash-link, not parallel-reconcile). Independent verification across the federation tree without raw data crossing tier boundaries.

---

## 9. Workspace hygiene as a security concern (#34)

Workspace hygiene isn't just tidiness — it's a security primitive. AI agents leave cruft: temp files, scratch scripts, half-finished outputs. Over days, this becomes:

- **Signal-to-noise drop** in the repo (harder to spot anomalous additions)
- **Forgotten secrets** in `/tmp/` files (one of the most common breach vectors)
- **Unattributed state** that surveys don't expect

Spine ships **#34 — workspace hygiene as architectural concern**:

- Per-run workspace dir: `.spine/work/<run_id>/`
- Explicit promotion of final artifacts; no implicit "workspace becomes artifact"
- Archive on completion to `.spine/archive/<date>/<run_id>.tar.zst`; delete from live tree
- Periodic sweep: `make hygiene` OR `spine hygiene sweep`
- **Conductor refuses to mark a project done if uncleaned workspace state exists for it.** Release-blocking acceptance criterion.

Bundle policy declares retention windows + sweep cadence + acceptable workspace patterns. Customer can tune for their environment (longer retention for debug, shorter for throughput).

This is the same trust mechanism as the audit chain — proves work was actually completed cleanly, not just declared done with debris.

---

## 10. LLM provider isolation (#2)

7 providers Day 1: Anthropic, OpenAI, Bedrock, Vertex, Ollama, Qwen, vLLM. Customer chooses; Spine never marries one.

**Air-gapped deployments use in-house vLLM or Ollama** — no outbound LLM calls. Cross-LLM consensus still works because both can be self-hosted.

LLM API keys flow through vault (#9). Per-provider rate limits + cost ceilings enforced by `shared/cost/`. If a key is compromised: rotate via vault; Hub re-reads on next call; no restart needed.

---

## 11. Per-shape security posture

| Posture concern | Laptop | BYOC | Customer-cloud | On-prem |
|---|---|---|---|---|
| Network egress | Outbound to LLM provider | Outbound to LLM provider | Outbound to LLM provider | In-house LLM (no egress) |
| Vault unseal | Local file | Cloud KMS auto-unseal | Cloud KMS or HashiCorp Vault | **Shamir 3-of-5** recommended; KMS allowed by policy |
| MFA | Optional | Optional | Required | Required + WebAuthn |
| IdP federation | None (single realm) | 1 IdP | Multi-IdP | Multi-IdP + multi-realm |
| Audit retention | 90 days default | 90 days default | 1 year default | **Per regulator** (3–7+ years typical) |
| Cross-region DR | None | Opt-in | Opt-in | Required + tested weekly |
| Vendor reachability | Discord + email | Discord + email + dedicated CSM | Discord + email + dedicated CSM | Dedicated CSM + 24/7 escalation path |

---

## 12. Threat model — quick

| Threat | Mitigation |
|---|---|
| Vendor breached, customer data exposed | Vendor doesn't hold customer data (#15). Nothing to breach. |
| Vendor subpoenaed for customer data | Vendor doesn't hold customer data. Subpoena returns nothing. |
| Vendor disappears (insolvency / acquisition) | Source escrow (#18) at top tier; portability export (#33 B); customer's Hub keeps running. |
| Customer cloud account compromised | Vault adapter rotates; audit chain reveals attack timeline; portability export to fresh cloud is a recovery path. |
| Malicious agent action inside Spine | Cite-or-Refuse contract on verify (#12); Conductor hygiene gate (#34); audit chain reveals; auditor role re-runs against KG. |
| License piracy | Ed25519 signature verification on bundle (`license/bundle_verifier.py`); periodic re-verify (default 1h); per-gate evaluation. TRUSTED_VENDOR_FINGERPRINT baked into Hub binary. |
| Tampering with audit chain | Hash chain breaks; `tools/audit-verify-chain.py` flags; Vanta/Drata two-party attestation no longer matches; regulator notified. |
| Tampering with KG (insert false evidence) | KG is also append-only with row hashes; KG indexer 3 trigger points all sign; sweep catches missed events. |
| Federation MITM | mTLS + bearer; both must validate; cert pinning at trust anchors. |

---

## 13. For your security review — what to ask for

When evaluating Spine, request:

1. **SOC 2 Type II report** (current; in-progress through q3 2026)
2. **Latest annual pen test report summary** (full report NDA available)
3. **Source escrow option terms** (if enterprise tier; Iron Mountain or NCC Group)
4. **Demo-environment access** for hands-on scanner runs
5. **Audit-chain verification walkthrough** — show your auditor how two-party attestation works against your Vanta/Drata sandbox
6. **DR test artifacts** — last 4 weeks of `tools/dr-test.sh` runs from a reference deployment
7. **License-bundle verification** — show the Ed25519 trust anchor + signing key custody (vendor vault + Shamir 3-of-5)
8. **Boundary documentation** — `docs/ARCHITECTURE.md` §5 (cross-cutting tech stack) for what calls what

---

## 14. Related artifacts

- [`docs/HUB_OPERATIONS_GUIDE.md`](HUB_OPERATIONS_GUIDE.md) — day-2 ops
- [`docs/DEPLOYMENT_SHAPES.md`](DEPLOYMENT_SHAPES.md) — per-shape security posture
- [`docs/FEDERATION_GUIDE.md`](FEDERATION_GUIDE.md) — mTLS + consent detail
- [`docs/LICENSING_GUIDE.md`](LICENSING_GUIDE.md) — license verification + key custody
- [`docs/DR_RUNBOOK.md`](DR_RUNBOOK.md) — operational DR
- `vault/README.md` — vault subsystem internals
- `vault/dr-runbook.md` — vault-specific DR
- `keycloak/README.md` — Keycloak subsystem internals
- `keycloak/tier-config.md` — per-tier feature matrix (source of truth)
- `keycloak/dr-runbook.md` — Keycloak-specific DR
- `evidence/README.md` — SOC 2 evidence pipeline internals
- `tools/audit-verify-chain.py` — chain integrity verifier
