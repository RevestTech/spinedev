# ADR-002: Compliance control packs vs third-party attestation

## Status

**Done (reference packs)** — Tron ships **built-in, read-only JSON reference packs** and APIs.  
**Deferred (attestation)** — Vendor **certified** control libraries and formal attestations remain out of scope.

## Context

The proposal distinguished (a) heuristic / LLM-assisted compliance scanning and (b) vendor-certified SOC2 / ISO / HIPAA **attestation** products. (b) cannot be implemented as in-repo code alone.

## Decision

1. **Shipped:** `tron/standards/packs/*.json` (e.g. `soc2_reference`, `hipaa_reference`, `iso27001_reference`), loader **`tron/standards/control_packs.py`**, REST **`GET /api/standards/control-packs`** and **`GET /api/standards/control-packs/{id}`**, optional project column **`compliance_control_pack_ids`**, env **`TRON_COMPLIANCE_PACKS`**, and prompt merge into **`ComplianceISO`** via **`ISOConfig.compliance_reference_context`**.
2. **Still excluded:** Purchasing or integrating third-party **certified** pack subscriptions, CPA reports, or implying certification from Tron output alone.

## Consequences

- Marketing and UI must not claim third-party certification derived only from Tron.
- **`MASTER_PROPOSAL_TODO.md`** marks reference packs **Done** and attestation **Deferred** (this ADR).
