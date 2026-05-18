# `migration/` — Spine v3 migration subsystem

> **Status:** Wave 5 Squad F — BUILD-NEW. Per design decision **#33** in
> [`docs/V3_DESIGN_DECISIONS.md`](../docs/V3_DESIGN_DECISIONS.md): four
> distinct migration concerns, **three of which are v1.0 deliverables**.
> Per [`docs/V3_BUILD_SEQUENCE.md`](../docs/V3_BUILD_SEQUENCE.md) Wave 5
> "DR + Migration + Landing docs".
>
> **Concern C** (software-migration-as-work-type) is captured by the
> work-item-type design (#19) and the intake template is **v1.1** —
> out of scope for this squad.

## Files

| File | Purpose |
|---|---|
| `__init__.py` | Public surface re-export. |
| `export.py` | Concern B — signed, deterministic, round-trippable Spine state export tarball. |
| `import_.py` | Concern B inverse — verify (signature + per-slice hash + audit chain) then UPSERT into a fresh deployment. |
| `onboarding.py` | Concern A — GitHub + Linear connectors + `OnboardingDispatcher`. |
| `spine_version.py` | Concern D — version-upgrade planner + executor; downgrade-blocked; N-2 commitment. |
| `version_registry.py` | Frozen registry of every versioned subsystem. |
| `connectors/` | Reserved for v1.1+ connector implementations (Jira / Confluence / Notion / Asana / GitLab). |
| `_v1_v2_migrator_legacy.py` | Historical v1 → v2 migrator preserved per #33 as canonical example. Imports may break. |
| `tests/` | Mock-vault + mock-HTTP + mock-DB unit tests. |

Sibling artifacts (NOT in this dir but part of this squad):

* `shared/mcp/tools/migration.py` — four MCP tools.

## Hard constraints (per task brief)

| # | Constraint | Realisation |
|---|---|---|
| #9 | Signing key via `shared.secrets` | `VaultSigner` + `VaultVerifier` load Ed25519 keys from `shared.secrets.get_secret`. No env-var fallback. See `ADR-F-002`. |
| #12 | Cite-or-Refuse on destructive ops | `migration_import` + `migration_version_upgrade` MCP tools tagged `requires_citation=True`. |
| #33 B | Round-trippable export | `export.py` freezes tar mtime + emits sorted JSONL + uses canonical JSON for the manifest. Round-trip test asserts byte-identical re-export. |
| #33 D | N-2 cross-version commitment + downgrade blocked | `spine_version.upgrade` consults `version_registry.N_MINUS_K_DIRECT_UPGRADE_DISTANCE` (=2). Anything older = multi-hop plan; downgrade raises `DowngradeBlocked`. |
| #16 | No auto-push | `spine_version.upgrade` refuses to proceed without an explicit `approve` callable returning True. |

## Architecture decision records (squad-local)

### ADR-F-001 — Linear vs Jira for Day-1 onboarding

**Decision:** Ship Linear in v1.0; defer Jira to v1.1.

**Rationale:**

* Modern GraphQL surface (Jira has 4 distinct APIs).
* Linear's `state.type` enum maps 1-to-1 onto Spine work-item lifecycle.
* Linear targets the same segment as Spine's bottom-up adoption play
  (per #14).
* Jira will return as the **first v1.1 connector** because the
  mid-market / enterprise expansion path needs it.

### ADR-F-002 — Re-use the license signing key for migration exports

**Decision:** `VaultSigner` defaults to vault path
`license/vendor_signing_key` (same path as `tools/license-sign.sh`)
rather than minting a distinct migration key.

**Rationale:**

* Spine has exactly one anti-piracy trust anchor (the vendor Ed25519
  key fingerprint baked into the Hub at build time). A migration export
  is *trust evidence from the same vendor*; verifying against the same
  fingerprint is the simplest mental model for customer admins.
* Adding a distinct migration key would require a separate Shamir
  3-of-5 ceremony, a separate fingerprint baked into the Hub binary,
  and another rotation runbook. Marginal security benefit is unclear.
* **Operators who want strict separation** can construct
  `VaultSigner(vault_path="migration/signing_key")` instead — the
  parameter is exposed precisely for this.

### ADR-F-003 — Mock-only tests

**Decision:** No real DB / vault / GitHub / Linear in
`migration/tests/`. Every external surface is a `Protocol` so tests
inject in-memory fakes.

**Rationale:**

* Per task brief: "Tests use mocks."
* Decoupling from a live Postgres keeps the test suite runnable in CI
  without docker-compose.
* The round-trip byte-equality test is the single most important
  property for #33 B and it's deterministic only because the file
  system is bypassed (we exercise tarball bytes directly).

## v1.1 follow-ups

| Item | Concern | Source |
|---|---|---|
| Confluence connector | A | docs/V3_DESIGN_DECISIONS.md deferred-items |
| Notion connector | A | docs/V3_DESIGN_DECISIONS.md deferred-items |
| Asana connector | A | docs/V3_DESIGN_DECISIONS.md deferred-items |
| Jira connector | A | ADR-F-001 |
| GitLab connector | A | implied by GitHub-first posture |
| Software-migration-as-work-type intake template | C | #33 C deferral |
| Real Flyway / charter / KG handler registry | D | StubExecutor placeholder |

## How to run the tests

```
.venv/bin/python -m pytest migration/tests/ -q
```

Each test class uses fixtures from `migration/tests/conftest.py`:

* `mock_signer` / `mock_verifier` — in-memory Ed25519 keypair.
* `mock_reader` / `mock_writer` — state-source/sink mocks.
* `mock_http` — `HttpClient` recorder + scripted responses for the
  GitHub + Linear connectors.

## Smoke

```
python3 -m py_compile migration/*.py migration/tests/*.py \
                       shared/mcp/tools/migration.py
bash tools/smoke-test.sh 2>&1 | tail -3
```
