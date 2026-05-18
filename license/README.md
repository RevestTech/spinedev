# `license/` — feature-flag licensing subsystem

> **Status:** Wave 4 Squad B — BUILD-NEW. Per design decision **#23** in
> [`docs/V3_DESIGN_DECISIONS.md`](../docs/V3_DESIGN_DECISIONS.md):
> feature-flag licensing is a Day-1 architectural primitive. Every
> feature in Spine has a flag; the flags ship in a signed bundle issued
> by the vendor; the Hub validates the Ed25519 signature on startup,
> periodically, and on every feature gate.
>
> **Source posture:** closed-source v1.0 (#18) — this subsystem is the
> anti-piracy seam. Verification is local (no phone-home) so air-gapped
> + on-prem deployments work, but the vendor public-key fingerprint is
> hard-coded into the Hub at build time as the trust anchor.

## Files

| File | Purpose |
|---|---|
| `__init__.py` | Public surface re-export. |
| `bundle_verifier.py` | Ed25519 signature verification + vault fetch + periodic re-verify task. |
| `feature_flags.py` | `is_enabled(flag)` + `quota_remaining(flag)` — the per-gate hot path. |
| `quota_ledger.py` | Hash-chained `spine_license.quota_usage` writer. |
| `tests/` | Mock-vault + mock-DB unit tests. |

Sibling artifacts (NOT in this dir but part of this squad):

* `shared/schemas/license/bundle_v1.py` — Pydantic v2 models for the
  signed bundle wire format.
* `shared/mcp/tools/license.py` — three MCP tools
  (`license_get_status`, `license_get_usage`, `license_verify_bundle`).
* `tools/license-sign.sh` — vendor-side signing CLI (NOT for customer
  use; loads the Ed25519 private key on-demand from the vendor vault).

## Dependencies

* `cryptography` (Ed25519 + base64 + SHA-256). NOT added to
  `pyproject.toml` by this squad — see vendoring decision below.
* `asyncpg` for DB access. Imports are guarded so `py_compile` works in
  environments without it (the package is documented as a runtime dep).
* `shared.secrets` for vault access (the vendor public key is fetched
  from `license/vendor_pubkey` per `VENDOR_PUBKEY_VAULT_PATH`).

> **Why no `pyproject.toml` edit?** Per Wave 4 task scope this squad
> touches `license/*`, `shared/schemas/license/*`,
> `shared/mcp/tools/license.py`, `tools/license-sign.sh`, and the
> single import in `shared/api/middleware/feature_flag.py`. Adding
> `cryptography` is a dependency-set decision that belongs to the Wave
> 0 dep audit (Part 1.4 / Wave 5 #4.5). The package is already a
> transitive dep via `keycloak` + `httpx[brotli]`; vendoring it
> formally is a follow-up.

## Trust model

Two distinct cryptographic anchors:

1. **Vendor private signing key.** Lives ONLY in the vendor vault
   (HashiCorp Vault or OpenBao). Recovered via Shamir 3-of-5 (per #9 +
   Part 4.3) if the operating shard is lost. Never written to disk;
   never enters this Python package. Loaded by `tools/license-sign.sh`
   on-demand during a signing run.
2. **Vendor public key fingerprint.** Hex SHA-256 of the 32-byte raw
   public key. Hard-coded into every Hub binary at build time as
   `TRUSTED_VENDOR_FINGERPRINT`. Even if an attacker writes a forged
   public key into the customer's vault, the Hub refuses to load it
   unless its fingerprint matches the baked constant.

The customer's vault still stores the vendor *public* key bytes (so
the verifier has something to verify against), but the fingerprint
check is the substitution-attack guard.

## Verification cadence (per #23)

| When | Function | Effect |
|---|---|---|
| Hub startup | `load_active_bundle(pool=...)` | Reads the active row from `spine_license.bundle`, verifies the signature, installs `ActiveBundle` into process memory. Failure → Hub refuses to start. |
| Every feature gate | `is_enabled(flag)` | Reads `_ACTIVE` (no DB; no signature math). Returns False if signature was invalidated by the periodic check. |
| Every hour (default) | `start_periodic_verifier(pool=...)` | Background asyncio task; re-runs full signature verification. Failure flips `_ACTIVE.signature_ok=False` so subsequent gates fail closed. |
| On admin "reload" | `load_active_bundle(pool=...)` + `invalidate_cache()` | Hot-swap after the customer installs an upgraded bundle. |

The per-gate path is sub-microsecond — no Postgres round-trip — because
the bundle is small (low-double-digit flags) and lives entirely in
memory.

Tune the periodic cadence via `SPINE_LICENSE_VERIFY_INTERVAL_SECONDS`.
The 1-hour default balances "catch a tampered DB row promptly" against
"don't hammer the audit chain". Air-gapped deployments may want longer.

## Quota ledger hash chain

Every increment to `spine_license.quota_usage` recomputes the row's
`ledger_anchor`:

    anchor_i = sha256(
        prev_anchor_hex || "\n" ||
        flag_name        || "\n" ||
        period_start_iso || "\n" ||
        period_end_iso   || "\n" ||
        used_value_after_increment
    )

Bootstrap row's `prev_anchor_hex` is 64 zero hex digits
(`GENESIS_ANCHOR_HEX`). Chain is per-`(flag_name, period_start)` so
concurrent writers to different flags don't have to coordinate; the
within-flag chain uses `FOR UPDATE` row locks so two simultaneous
increments serialise.

`license_verify_bundle` (MCP tool) replays the chain and surfaces the
first row whose stored `ledger_anchor` doesn't match recomputation.
This is `requires_citation=True` (per #12) since it returns a
verdict over historical usage data.

## How this replaces the Wave 3 Squad C stub

The single import surface in
`shared/api/middleware/feature_flag.py` is updated so
`is_feature_enabled(flag)` delegates to `license.feature_flags.is_enabled`.
The middleware's `KNOWN_FEATURE_FLAGS` registry and the
`require_feature_flag` decorator are unchanged — the contract is
preserved exactly. Existing tests
(`shared/api/tests/test_middleware_feature_flag.py`) continue to pass
because:

* `is_feature_enabled` still raises `KeyError` for unknown flags.
* Tests that exercise the "enabled" path inject a mock by monkeypatching
  `is_feature_enabled` directly — that path is untouched.
* The "disabled" path is also exercised via monkeypatch.

When no bundle is loaded (the test default), `is_enabled` returns False
for every flag except `license_inspector`. The existing tests don't
hit `is_feature_enabled` unmocked on the enabled-path, so they still
pass.

## MCP tools

Three tools, all auto-registered by walking the `shared/mcp/tools/`
package on server startup:

| Tool | `requires_citation` | Purpose |
|---|---|---|
| `license_get_status` | False | Return tier + flags + expiry from `_ACTIVE`. |
| `license_get_usage` | False | Return per-flag usage counters from `spine_license.quota_usage`. |
| `license_verify_bundle` | **True (per #12)** | Re-run signature verification AND replay the quota ledger chain. Returns the cryptographic verdict + a `Citation` rooted in `audit_hash`. |

## Vendor-side signing — `tools/license-sign.sh`

NOT for customer use. Vendor runs this script to produce a signed
bundle from a JSON payload:

    tools/license-sign.sh sign \
        --payload payload.json \
        --output  signed-bundle.json \
        --vault-path license/vendor_signing_key

The script:

1. Validates the JSON payload against `license-bundle-v1`.
2. Canonicalises the payload (same code path as the Hub verifier).
3. Loads the Ed25519 private key from the vendor vault.
4. Signs the canonical bytes in memory.
5. Emits the wrapped `SignedLicenseBundle` to `--output`.
6. Zeroes the in-memory key bytes on exit.

Run `tools/license-sign.sh --help` for full usage including the
Shamir-recovery flow.
