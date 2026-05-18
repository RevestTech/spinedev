# `federation/` — Spine v3 Hub-to-Hub subsystem

> Wave 4 Squad A. Owns the fractal-Hub federation per
> `docs/V3_DESIGN_DECISIONS.md` #4 (topology), #10 (consent-leaning
> fractal trust), and #16 (update distribution via federation tree with
> per-tier approval gate).

## Modules

| Module | Role |
| --- | --- |
| `hub_registry.py` | Async CRUD over `spine_federation.hub` (V23). Bootstrap reads `hub/_state/hub_id.txt`. |
| `upstream_client.py` | mTLS + bearer client for talking up the tree to a parent Hub. Vault paths: `federation/mtls/<role>/cert`, `…/key`, `federation/bearer/<role>`. |
| `downstream_router.py` | Route delegated tools to child Hubs; consent-gated fan-out with concurrency cap. |
| `consent.py` | `ConsentEngine` — peer-consent default + bounded mandatory upward flows from bundle policy. |
| `update_cascade.py` | Vendor → parent → child cascade with per-tier approval gate (#16). |

## Cross-subsystem contracts

* **hub_id flow:** `hub/wizard/init.sh` writes `hub/_state/hub_id.txt`
  (UUIDv4) at Day-0. On first Hub start the lifespan calls
  `federation.bootstrap_hub_id(...)` which reads the file and
  INSERT-or-FETCHes one row into `spine_federation.hub`.
* **Vault paths (#9):** `federation/mtls/<role>/cert`,
  `federation/mtls/<role>/key`, `federation/bearer/<role>`. The
  `<role>` is the local Hub's role from the parent's perspective
  (typically `"child"`; bundles may declare additional roles).
* **Audit subsystem tag:** every audit event emitted by federation
  code uses `subsystem='federation'` (already in
  `shared/audit/audit_record.ALLOWED_SUBSYSTEMS`).
* **MCP tools (#12 Cite-or-Refuse):**
  `federation_register_child` and `federation_push_update` are
  registered with `requires_citation=True`. The server middleware
  rejects responses without a `Citation` with HTTP 422.

## MCP tools

| Tool | requires_citation | Story |
| --- | --- | --- |
| `federation_register_child` | yes | WAVE-4.A.1 |
| `federation_grant_consent` | no | WAVE-4.A.2 |
| `federation_push_update` | yes | WAVE-4.A.3 |
| `federation_pull_updates` | no | WAVE-4.A.4 |

Wiring: the Hub lifespan calls
`shared.mcp.tools.federation.set_federation_deps(hub_registry=...,
consent_engine=..., update_cascade=..., local_hub_id=...)` once at
startup. Tools return `status='stub_implementation'` until wired so
smoke tests can detect un-wired deployments.

## Bundle policy contract

Per #10, bundles may declare mandatory upward consent flows:

```yaml
federation:
  consent:
    mandatory_upward:
      - class: security_incident
        rationale: "Org-wide regulatory reporting (SOC2 CC7.4)"
      - class: critical_compliance_evidence
        rationale: "Evidence chain integrity (SOC2 CC4.2)"
```

Every entry MUST declare a rationale. `ConsentEngine.from_bundle_policy`
raises `ValueError` on entries missing a rationale.

## Hard constraints honored

* All async Python (`asyncpg` + `httpx`).
* No real network / DB / vault in tests — pure mock pool + injected
  secret fetcher.
* No touches outside `federation/*`, `shared/schemas/federation/*`,
  `shared/mcp/tools/federation.py`, `federation/tests/*`.

## Wave 5 follow-ups (not in scope here)

* Wire `federation.bootstrap_hub_id` into the Hub container lifespan
  (`hub/entrypoint.sh` + a `shared/api/app.py` startup hook).
* Replace the in-process `_GRAPH` dict in
  `shared/api/routes/federation.py` with calls to `HubRegistry`.
* Migration B (`migration/`) must include `spine_federation.*` in the
  full-state export bundle.
* Squad E (`recovery/`) layer-6 federation-autonomy verification
  test should kill the parent Hub and confirm child cascades degrade
  cleanly to local-only mode.
