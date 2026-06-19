# Vault paths — production population checklist (SPINE-018)

> **Status:** Canonical operator checklist for V1 launch gate §4.
> **Source gate:** [`docs/V1_SHIP_CHECKLIST.md`](V1_SHIP_CHECKLIST.md) §4 — *All vault paths populated with REAL values (not `InMemoryAdapter`)*.
> **Related audit:** [`tools/audit-secrets.sh`](../tools/audit-secrets.sh) — confirms no secret **values** in committed code; does **not** prove vault population.

---

## What this doc covers

| Check | Tool / action | Proves |
|-------|---------------|--------|
| No secret values in git | `bash tools/audit-secrets.sh` | Classifier-aware grep: env-var **names**, vault **path references**, and obviously-fake test placeholders are allowed; confirmed value leaks fail the script. Wired in CI (`.github/workflows/ci.yml`) and smoke (`boot.audit_secrets` INFO in `tools/smoke-test.sh`). |
| Real secrets in production vault | Operator walk-through below | Every path resolves via the configured vault adapter (OpenBao / HashiCorp / cloud SM) — **not** `InMemoryAdapter`. |

Per design decision **#9** (vault-only secrets): code and bundles may reference paths; only the vault holds values.

---

## Dev vs production posture

| Concern | Local dev / smoke / CI | Production (customer Hub or vendor ops) |
|---------|------------------------|---------------------------------------|
| Secret adapter | `InMemoryAdapter` injected in smoke (`tools/smoke-test.sh` phase 8) and laptop `hub-up` dev mode | OpenBao (Day-0 default) or customer-chosen adapter from org bundle (`hub/config/default_bundle.yaml`) |
| Postgres / TRON passwords | Code sentinel `tron_LOCAL_DEV_ONLY_2026` + ephemeral docker volumes; smoke uses `SPINE_APPROVAL_VAULT_PATH` per-run HMAC path | Real passwords at canonical `tron/*` and `spine/postgres/*` paths |
| License signing | Optional `SPINE_LICENSE_LOCAL_PRIV_HEX` for offline dev; Shamir rehearsal on tmpfs | `license/vendor_signing_key` from Shamir 3-of-5 reconstruction only |
| Federation mTLS | Skipped when `federation.enabled: false` (Day-0 default) | Required for child Hubs: populate per-role cert/key/bearer triplets |
| Notify / evidence / GRC | Channels degrade gracefully when vault read returns empty; stubs raise `NotImplementedError('v1.1+')` for SMS/WhatsApp transport | Populate paths for every enabled integration flag before go-live |
| `audit-secrets.sh` | Must exit **0** on every PR (no value leaks in repo) | Same — plus operator must verify vault KV entries exist (this checklist) |

**Rule of thumb:** if the Hub process starts with `InMemoryAdapter` or empty vault reads, you are in **dev posture**. Production launch requires a real adapter and every **Required** row below marked populated.

---

## Required paths — V1_SHIP_CHECKLIST §4

Paths listed verbatim in the ship checklist. Populate before customer ship sign-off.

### Spine core (Hub database + approvals)

| Vault path | Purpose | Code reference |
|------------|---------|----------------|
| `spine/postgres/password` | Postgres role password for Spine app | `orchestrator/lib/_env_loader.sh` (`SPINE_PG_PASSWORD_VAULT_PATH`) |
| `spine/postgres/dsn` | Full DSN (or composed from password) | `shared/api/dependencies.py` (`SPINE_DB_DSN_VAULT_PATH`) |
| `spine/approval/hmac_key` | HMAC key for phase-gate approval tokens | `orchestrator/lib/approval.py` (`HMAC_KEY_VAULT_PATH`) |

> **Hub compose note:** `hub/docker-compose.yml` defaults `SPINE_DB_PASSWORD_VAULT_PATH` to `spine/data/db/spine-app-password`. Day-0 wizard may write either layout; operator must align bundle, compose env, and actual KV entries.

### License (vendor-side)

| Vault path | Purpose | Code reference |
|------------|---------|----------------|
| `license/vendor_signing_key` | Ed25519 private key (hex) for bundle signing | `tools/license-sign.sh` (`SPINE_LICENSE_SIGNING_VAULT_PATH`) |
| `license/vendor_pubkey` | Ed25519 public key (hex) for verify / fingerprint checks | `tools/license-sign.sh` (`SPINE_LICENSE_VENDOR_PUBKEY_PATH`) |

Populate signing key via `tools/license-sign.sh shamir-split` → custodian distribution → `recover-shamir` (see `license/README.md`). `TRUSTED_VENDOR_FINGERPRINT` in the Hub binary must match the reconstructed key.

### Keycloak (OIDC)

| Vault path (§4) | Canonical bundle path | Purpose |
|-----------------|----------------------|---------|
| `keycloak/spine-hub/client-secret` | `spine/data/keycloak/spine-hub/client-secret` | `spine-hub` OIDC client secret |

See `hub/config/default_bundle.yaml` → `identity.keycloak.client_secret_vault_path`. Keycloak init scripts may use `secret/spine/keycloak/spine-hub/client-secret` — **normalize to one path** per deployment and update bundle + wizard accordingly.

### Federation (child / upstream Hubs)

For each federation **role** in use (default upstream role: `child`; also `downstream`, `security_reporter`, …):

| Vault path template | Purpose |
|---------------------|---------|
| `federation/mtls/<role>/cert` | PEM client certificate |
| `federation/mtls/<role>/key` | PEM client private key |
| `federation/bearer/<role>` | Keycloak service-account bearer token |

Templates overridable via `SPINE_FED_MTLS_CERT_PATH_TPL`, `SPINE_FED_MTLS_KEY_PATH_TPL`, `SPINE_FED_BEARER_PATH_TPL`. See `federation/upstream_client.py`, `shared/mcp/server_remote.py`.

### Notifications (`notify/*`)

Per V1 §4 wildcard `notify/{slack,email,sms,whatsapp,teams,pagerduty}/...`. Canonical paths from `shared/notify/channels.py` and `shared/integrations/*`:

| Channel | Vault path(s) | Required when |
|---------|---------------|---------------|
| Slack | `notify/slack/webhook_url` | `integrations.slack` or decision-class routes Slack |
| Email (SMTP) | `notify/smtp/password` | Email channel enabled (Day-0 default) |
| SMS | `notify/twilio/account_sid`, `notify/twilio/auth_token`, `notify/twilio/from_number` | `voice.twilio` / SMS channel (transport v1.1+) |
| WhatsApp | above + `notify/twilio/whatsapp_from` | WhatsApp channel (transport v1.1+) |
| Teams | `notify/teams/webhook_url` | `integrations.teams` |
| PagerDuty | `notify/pagerduty/routing_key` | `integrations.pagerduty` / incident pageout |

Non-secret SMTP config (host, port, sender) lives in org bundle / constructor kwargs — only **password** is vault-bound.

### Evidence / GRC exporters

| Vault path | Purpose | Required when |
|------------|---------|---------------|
| `evidence/vanta/api_key` | Vanta API bearer token | `integrations.vanta` |
| `evidence/drata/api_key` | Drata API bearer token | `integrations.drata` |
| `evidence/secureframe/api_key` | Secureframe API token | `integrations.secureframe` |

Optional overrides: `evidence/<vendor>/api_url`. v1.1 stubs (`tugboat`, `strikegraph`, `thoropass`) — do not block v1.0 ship.

### TRON (`tron/*`)

V1 §4 TRON prod rotation (replaces dev sentinel `tron_LOCAL_DEV_ONLY_2026`):

| Vault path (§4) | `verify/.env.vault-refs` | Purpose |
|-----------------|--------------------------|---------|
| `tron/postgres/password` | `tron/db/password` | TRON Postgres |
| `tron/redis/password` | `tron/redis/password` | TRON Redis |
| `tron/minio/user` | `tron/minio/user` | MinIO admin user |
| `tron/minio/password` | `tron/minio/password` | MinIO admin password |
| `tron/grafana/password` | `tron/grafana/password` | Grafana admin |

**Operator action:** pick one Postgres path convention and populate it; align `verify/.env.vault-refs` if you standardize on `tron/postgres/password`.

Additional TRON paths in `verify/.env.vault-refs` (populate for full verify stack, not repeated in §4 bullet list):

| Vault path | Legacy env var |
|------------|----------------|
| `tron/minio/kms-key` | `MINIO_KMS_KEY` |
| `tron/auth/secret-key` | `SECRET_KEY` |
| `tron/auth/jwt-secret` | `JWT_SECRET` |
| `tron/auth/master-key` | `TRON_MASTER_KEY` |
| `tron/auth/admin-password` | `TRON_ADMIN_PASSWORD` |
| `tron/llm/openai-key` | `OPENAI_API_KEY` |
| `tron/llm/anthropic-key` | `ANTHROPIC_API_KEY` |

---

## Extended paths — production Hub bundle (not §4 bullets, but Day-0 real values)

From `hub/config/default_bundle.yaml` and wizard — populate when the corresponding feature is enabled:

| Vault path | Purpose |
|------------|---------|
| `spine/data/keycloak/spine-hub/client-secret` | OIDC client secret (bundle canonical) |
| `spine/data/keycloak/bootstrap-admin` | Keycloak bootstrap admin password (`hub/wizard/init.sh`) |
| `spine/data/llm/anthropic/api-key` | Anthropic API key (default LLM provider) |
| `spine/data/llm/openai/api-key` | OpenAI API key (when provider enabled) |
| `spine/data/db/spine-app-password` | Hub compose default DB password path |

Integration registry paths (`shared/api/routes/registry.py`) use `spine/integrations/...` prefix for feature-gated connectors — populate per enabled flag.

---

## Verification commands

### 1. Code audit (no value leaks)

```bash
bash tools/audit-secrets.sh
# exit 0 → ✓ secret-value grep audit: 0 confirmed value leaks
# exit 1 → fix leaks or extend OBVIOUS_FAKE_PATTERNS in the script (test placeholders only)
```

Classifier behavior (see script header):

- **Allowed:** env-var name references, vault path strings containing `/`, obviously-fake prefixes (`smoke-test-`, `tron_LOCAL_DEV_ONLY_2026`, …).
- **Fails:** literal secret values assigned in `.py` / `.sh` / `.yaml` / `.yml`.

### 2. Vault population spot-check (production)

```bash
# Example — adjust for your adapter CLI (OpenBao/Vault):
vault kv get -mount=spine spine/postgres/password
vault kv get -mount=spine spine/approval/hmac_key
python3 -m shared.secrets.cli get spine/postgres/dsn   # from Hub container

# TRON manifest resolution dry-run:
grep '^[A-Z].*=vault:' verify/.env.vault-refs | while read -r line; do
  path="${line#*=vault:}"
  python3 -m shared.secrets.cli get "$path" || echo "MISSING: $path"
done
```

### 3. Smoke harness (includes audit)

```bash
bash tools/smoke-test.sh
# Expect boot.audit_secrets INFO when audit-secrets.sh is clean
```

---

## Launch gate cross-reference

| V1_SHIP_CHECKLIST §4 item | This doc |
|---------------------------|----------|
| No env-var secret VALUES in committed code | § Verification → `audit-secrets.sh` |
| TRON prod password population | § TRON table |
| All vault paths real values (not InMemoryAdapter) | § Required paths + § Extended paths |
| TRUSTED_VENDOR_FINGERPRINT matches Shamir key | § License |

**Sign-off:** mark each **Required** path populated in your operator runbook; re-run `bash tools/audit-secrets.sh` before tag `v1.0.0`.

---

**Document control**

- Created: 2026-06-19 (SPINE-018)
- Task: `todo/BACKLOG.md` SPINE-018
- Next update: new vault path added to code or V1 §4 gate
