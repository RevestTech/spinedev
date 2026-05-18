# learning/ — Smart Spine 3-tier learning loop

Wave 4 Squad D deliverable. Implements Design Decision **#27** from
`docs/V3_DESIGN_DECISIONS.md`.

## What this subsystem does

A lesson originates in `spine_memory.lesson` (Wave 1 `writer_hooks`).
This subsystem decides *which copies* of that lesson are released into
`spine_learning.lesson` (V29) at which scope:

| Tier | Scope | Default | Customer override |
|---|---|---|---|
| **1a** | `project` | ALWAYS on | n/a |
| **1b** | `within_hub` | DEFAULT ON | `spine_learning.scope_policy.within_hub_enabled=false` |
| **2** | `cross_org` | DEFAULT OFF | explicit opt-in via `learning_grant_cross_org_consent` |
| **3** | vendor self-improvement | always on for vendor's own deployment | n/a |

## Module map

| File | Role |
|---|---|
| `scope.py` | Pure scope resolver — given a directive + policy snapshot, decide highest permitted tier. No DB. |
| `contribute.py` | 3-tier contribution gates + DB writer for `spine_learning.lesson`. |
| `consent.py` | Cross-org opt-in registry: writes `spine_learning.scope_policy` (granular per-category supported). |
| `anonymizer.py` | Tier 2 anonymization pipeline (k-anonymity default, DP available). Suppresses leakers. |
| `vendor_self_improvement.py` | Tier 3 — hooks vendor's own audit chain into `spine_learning.lesson` unconditionally. |
| `tests/` | Unit tests (mock writers / readers; no DB needed). |

MCP tools live in `shared/mcp/tools/learning.py`:

| Tool | Citation required (V3 #12)? |
|---|---|
| `learning_contribute` | no |
| `learning_query` | no |
| `learning_grant_cross_org_consent` | **YES** — high-stakes data-sharing decision |
| `learning_revoke_cross_org_consent` | no (revocation always safe) |

## Anonymization choice

**Default: k-anonymity, k=5.**

Rationale:
- Tier 2 exports only aggregate pattern counts; k-anonymity is sufficient + auditable.
- Customer admins can verify suppression decisions by inspection (no calibrated noise to explain).
- Enterprise bundles can tighten k (10/15); vendor's Tier 3 needs no anonymization.
- Differential privacy is available as opt-in (`differential_privacy_method(epsilon=...)`).
- A field denylist + PII regex always scrubs raw identifiers before the method runs.

## Hard constraints honored

- Per #27 — Tier 2 cross-org default OFF (`ScopePolicy.cross_org_consent=False` by default).
- Per #27 — Granular per-category consent via `granular_consent_jsonb`.
- Per #27 — Anonymized + aggregated only; raw `lesson_text` never enters
  Tier 2 export; `anonymizer._ALWAYS_REDACT` strips identifiers + PII regex
  catches stragglers.
- Per #9 — No secret access here. Vendor self-improvement future federation
  publishing will route through `shared.secrets`.
- Per #12 — `learning_grant_cross_org_consent` tagged
  `requires_citation=True`; MCP server middleware refuses calls
  without a non-empty `citation` list.
- Per #21/#27 Tier 3 — vendor's own deployment auto-permits cross_org
  bypassing customer consent (only the vendor's own data is involved).

## Wave 5 wiring TODOs

These hooks intentionally use stubs / no-ops so the package is
self-contained and the unit tests run without infra:

- `contribute._default_writer` — real psql round-trip via `shared.runtime/db-outbox`.
- `consent._default_reader` / `_default_writer` — already psql-shaped;
  needs a connection pool wrapper.
- `learning_query` MCP tool — `_query_reader` stub returns empty list;
  Wave 5 wires the psql read with scope filter + project_id lookup.
- `vendor_self_improvement.UpstreamPublisher` — wire into
  `federation/update_cascade.py` (Squad A) for the published-bundle
  flow per #16.
- Bundle schema `learning_scope` block (per `V3_BUILD_SEQUENCE` Wave 4
  REFACTOR list) — `shared/standards/bundle-schema.yaml` extension.
