# evidence/ — Spine Evidence Store + GRC vendor push

> **Status:** Wave 4 Squad C (V3 #24). Vanta + Drata + Secureframe Day 1;
> Tugboat Logic / Strike Graph / Thoropass v1.1+ stubs (config + auth
> wired, `send()` raises `NotImplementedError("v1.1+")`).

## Why this exists

Per V3 design decision #24, Spine becomes the **highest-velocity SOC 2
evidence producer in the customer's stack**:

* **Read:** the `compliance_officer` role queries Vanta/Drata for current
  control status, gaps, deadlines.
* **Write:** Spine pushes every audit-chain event that is relevant
  evidence — PRs, deploys, approvals, config changes, role
  authorisations, vault access events, capability grants, drift
  remediations — into the customer's Vanta/Drata/Secureframe vault
  automatically.

The **two-party attestation** (V25 schema `two_party_attestation_hash`)
is the corroboration loop: customer's auditor sees evidence in
Vanta/Drata, hash-verifies against Spine's append-only audit chain, and
matches. Regulatory-grade trust.

**Startup wedge** (per #24): at the startup tier the audit chain
produces SOC 2-grade evidence automatically as a byproduct of using
Spine — NOT gated. When the startup adds Vanta/Drata later, this
subsystem pushes their existing audit trail backwards. "We started SOC
2 today" actually means "we have 18 months of evidence already
collected."

## Layout

```
evidence/
├── __init__.py            – package facade + re-exports of core types
├── _types.py              – EvidencePayload / ExportBatch / ExportResult
├── _db.py                 – tiny psql shim used by collectors
├── collectors/
│   ├── __init__.py
│   ├── audit_chain.py     – generic pull from spine_audit.audit_event
│   ├── role_decision.py   – role decision events (gate / approval / phase)
│   ├── vault_access.py    – vault read/write/delete events
│   ├── deploy.py          – spine_devops.action_log deploys (V27)
│   └── approval.py        – approval_granted / revoked / override
├── exporters/
│   ├── __init__.py
│   ├── _base.py           – BaseExporter (vault fetch + HTTP + log)
│   ├── vanta.py           – Day 1 (real)
│   ├── drata.py           – Day 1 (real)
│   ├── secureframe.py     – Day 1 (real)
│   ├── tugboat.py         – v1.1+ stub
│   ├── strikegraph.py     – v1.1+ stub
│   └── thoropass.py       – v1.1+ stub
├── two_party_attestation.py – SHA-256(payload || sigA || sigB) per V25
└── tests/                 – unit tests (mocks, no real API calls)
```

MCP surface lives in `shared/mcp/tools/evidence.py`:

| Tool                          | Citation? | Notes                                 |
|-------------------------------|-----------|----------------------------------------|
| `evidence_collect`            | yes (#12) | one audit_hash citation per payload   |
| `evidence_export`             | yes (#12) | collect → push → log to V25 export_log |
| `evidence_status`             | no        | read-only count by status              |
| `evidence_attestation_verify` | no        | regenerate hash; compare bytes         |

## Vault paths (per #9 — vault-only secrets)

Every exporter reads credentials fresh from `shared.secrets.get_secret`
on each `send()` call; nothing is cached on the instance.

| Vendor       | Required path                        | Optional URL override            |
|--------------|--------------------------------------|----------------------------------|
| Vanta        | `evidence/vanta/api_key`             | `evidence/vanta/api_url`         |
| Drata        | `evidence/drata/api_key`             | `evidence/drata/api_url`         |
| Secureframe  | `evidence/secureframe/api_key`       | `evidence/secureframe/api_url`   |
| Tugboat¹     | `evidence/tugboat/api_key`           | `evidence/tugboat/api_url`       |
| Strike Graph¹| `evidence/strikegraph/api_key`       | `evidence/strikegraph/api_url`   |
| Thoropass¹   | `evidence/thoropass/api_key`         | `evidence/thoropass/api_url`     |

¹ v1.1+ stub: config + auth path verified Day 1 but `send()` refuses.

## Two-party attestation

Input order is **fixed**:

```
SHA-256( payload_canonical_json
         || attestor_A_signature
         || attestor_B_signature )
```

* `attestor_A` = Spine itself (deployment-side signature; typically the
  audit chain `content_hash`).
* `attestor_B` = the customer's GRC tool / auditor countersignature.

Verification regenerates the hash with the same canonicalisation
(sorted-keys JSON, UTC ISO 8601 timestamps) and the same concatenation
order, then byte-compares (`hmac.compare_digest`) to the stored bytes
in `spine_evidence.evidence_record.two_party_attestation_hash`.

## Wave 5 follow-ups

* Promote `tugboat.py` / `strikegraph.py` / `thoropass.py` from stub →
  real Day-1-equivalent — per V3 #24 they're v1.1 work.
* Wire `evidence_collect` outputs into `compliance_officer` master-role
  prompts so the role auto-runs the right collector per control.
* Async fan-out exporter wrapper for large daily batches (current path
  is one POST per `send()` call).
* GRC-vendor-side countersignature ingest endpoint to populate
  `attestor_b_signature` automatically per evidence_record.
