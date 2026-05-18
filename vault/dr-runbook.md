# Vault DR runbook — Spine v3

> Covers `V3_DESIGN_DECISIONS #32 layer 8` (Vault unseal recovery) plus the
> vault-relevant parts of layers 3 (continuous backup) and 4 (tested restore).
> The umbrella DR runbook is `docs/DR_RUNBOOK.md` (Wave 5, Squad E). This
> document is the vault-subsystem-specific drill-down.

## Quick reference

| Scenario | Path | RTO target |
|---|---|---|
| Container crashed | [Container restart](#1-container-crash--auto-restart) | ≤ 30s |
| Vault sealed after restart (Shamir) | [Shamir unseal](#2-restart-with-shamir-manual-unseal) | ≤ 10min (humans assembling) |
| Vault sealed after restart (KMS) | [KMS auto-unseal failure](#3-kms-auto-unseal-failed) | ≤ 5min |
| Data volume corrupted | [Restore from snapshot](#4-data-volume-lostcorrupted) | ≤ 30min |
| Lost some Shamir shares (≤2 of 5) | [Rekey](#5-lost-shamir-shares-recoverable) | minutes |
| Lost ≥ threshold Shamir shares | [Catastrophic Shamir loss](#6-lost-shamir-shares-catastrophic) | hours-to-days |
| KMS key destroyed | [KMS catastrophic loss](#7-kms-key-destroyed) | hours |
| Snapshot encryption key lost | [Snapshot encryption key loss](#8-snapshot-encryption-key-loss) | catastrophic |
| Hub container can't auth (revoked secret-id) | [Re-issue AppRole secret-id](#9-hub-cannot-authenticate) | minutes |

---

## 1. Container crash → auto-restart

**Symptom:** `docker ps` shows vault container exited / restarting.

**Cause:** OOM, host reboot, k8s pod eviction, etc.

**Recovery:**
- `restart: unless-stopped` in compose (or k8s `Deployment` replicas) auto-restarts.
- KMS auto-unseal modes resume serving immediately.
- Shamir mode comes up SEALED — proceed to [section 2](#2-restart-with-shamir-manual-unseal).
- `lib/watchdog.sh` (DR layer 1) detects non-k8s shape failures and pages.

**Verify:**
```bash
curl -s http://127.0.0.1:8200/v1/sys/seal-status | jq .
docker logs spine-vault --tail=200
```

---

## 2. Restart with Shamir → manual unseal

**Symptom:** `sealed: true` after container starts; Hub gets 503 on every read.

**Recovery:** assemble K share holders (default 3 of 5):

```bash
# Each holder runs from their secured workstation
export BAO_ADDR=https://vault.your-spine.example:8200
bao operator unseal
# Pastes their share at the prompt.
```

**During outage:** Hub continues to serve cached secrets from
`shared/secrets/cache.py` (TTL ~5min). After cache expiry, Hub returns 503
for any new secret read. Active LLM calls / DB connections keep working.

**Lessons:** if assembly time > 10min consistently, consider migrating to KMS
auto-unseal — the 10min RTO is too long for production trustworthiness.

---

## 3. KMS auto-unseal failed

**Symptom:** Vault container restarted but `sealed: true` won't clear; logs
show `error fetching seal key` / `403 from KMS`.

**Diagnosis order:**

1. **KMS reachable?**
   - AWS: `aws kms describe-key --key-id alias/spine-vault-unseal`
   - Azure: `az keyvault key show --vault-name <kv> --name <key>`
   - GCP: `gcloud kms keys versions list --keyring=<kr> --key=<key> --location=<loc>`

2. **Permissions intact?**
   - AWS: instance profile / IRSA role still has `kms:Decrypt`?
   - Azure: Managed Identity still in Key Vault access policy?
   - GCP: Workload Identity binding still in IAM?

3. **Key still exists / not scheduled for deletion?**
   - AWS: `aws kms describe-key` → `KeyState` should be `Enabled`. If
     `PendingDeletion`, cancel: `aws kms cancel-key-deletion --key-id ...`.
   - Azure: `az keyvault key list-deleted --vault-name <kv>` — if listed,
     recover: `az keyvault key recover ...`.
   - GCP: check `cryptoKeyVersions` state for `DESTROY_SCHEDULED`; restore.

**If key is irrecoverable:** go to [section 7](#7-kms-key-destroyed).

---

## 4. Data volume lost/corrupted

**Symptom:** Vault container starts but reports
`storage error: file does not exist` or Raft cluster cannot form.

**Recovery (assumes DR layer 3 backups exist):**

```bash
# 1. Stop the vault container
docker compose -f vault/docker-compose.yml stop vault

# 2. Restore the data volume from latest snapshot
#    (snapshot location set by your bundle's recovery.backup_destination)
recovery_cli restore --subsystem=vault --target-snapshot=<id>

# 3. Start the container
docker compose -f vault/docker-compose.yml up -d vault

# 4. KMS auto-unseal: resumes automatically.
#    Shamir: same K shares as BEFORE the loss. (Snapshots do NOT change the
#    master key.) Submit shares per section 2.
```

**Verify post-restore:**
- `bao status` → unsealed, leader if single-node
- `bao kv list spine/` → returns expected keys
- Trigger one Hub secret read end-to-end

---

## 5. Lost Shamir shares (recoverable, ≤ N − K)

**Symptom:** Share holder leaves company; physical share is lost in a move; etc.

**Recovery (no Vault downtime needed):**

```bash
# Initiate rekey
bao operator rekey -init -key-shares=5 -key-threshold=3

# Each EXISTING holder contributes their old share (need K of N existing)
bao operator rekey   # each holder, prompted for their share

# After K old shares submitted, NEW share set issued. Distribute per
# vault/unseal/shamir-config.md best practices. Physically destroy old shares.
```

**Audit:** record the rekey in your separate physical custody log
(date + holders + reason). Do NOT log share material.

---

## 6. Lost Shamir shares (catastrophic, ≥ K of N)

**Symptom:** You can no longer assemble K holders. The master key is
unrecoverable. Vault data is encrypted-at-rest with that key.

**This is the worst scenario in pure-Shamir mode. There is no vendor
recovery and no upstream support contract that can decrypt your data.**

**Recovery path (lossy):**

1. **Confirm you have backups** (DR layer 3) AND that those backups are NOT
   encrypted with the same master key (snapshot encryption layer must be
   independent — see [section 8](#8-snapshot-encryption-key-loss)).

2. **Stand up a NEW Vault instance** with a fresh init:
   ```bash
   docker compose -f vault/docker-compose.yml down -v   # nukes the volume
   docker compose -f vault/docker-compose.yml up -d
   ./vault/init-wizard.sh   # NEW shares; capture them properly this time
   ```

3. **Restore secret material from out-of-band sources:**
   - LLM provider API keys: re-issue from provider consoles.
   - GitHub / Linear / Slack tokens: re-issue.
   - Signing keys: must be re-issued; OLD signed artifacts (license bundles,
     federation bundles) still verify against old public keys — track that as
     a separate trust-rotation event.

4. **Audit-log this as a P0 trust event.** Notify federation parents/children
   per #10 + #16 — your signing keys may have rotated.

5. **Post-mortem mandatory.** Move to KMS auto-unseal OR increase N (e.g. 7
   shares with K=4) OR add custodian redundancy.

---

## 7. KMS key destroyed

**Symptom:** KMS key permanently purged; auto-unseal fails irrecoverably.

**Recovery (use recovery shares — captured at init):**

```bash
# 1. Create a NEW KMS key (any cloud, any region; doesn't have to match)
#    Update the seal stanza in HCL to point at it. DO NOT remove the old
#    seal stanza yet — the migration command needs both.

# 2. Add the NEW seal as "seal" and rename the old to "disabled_seal":
seal "awskms" {                       # the NEW key
  region     = "us-east-1"
  kms_key_id = "alias/spine-vault-unseal-NEW"
}
seal "awskms" {                       # the OLD (destroyed) key, marked
  disabled   = "true"
  region     = "us-east-1"
  kms_key_id = "alias/spine-vault-unseal"
}

# 3. Restart Vault. It comes up SEALED (old key dead, new key not yet bound).

# 4. Submit recovery shares to migrate:
bao operator unseal -migrate <recovery-share-1>
bao operator unseal -migrate <recovery-share-2>
bao operator unseal -migrate <recovery-share-3>   # K shares total

# 5. Once unsealed, remove the disabled_seal stanza and restart cleanly.
```

If recovery shares are ALSO lost: combine this section with [section 6](#6-lost-shamir-shares-catastrophic) — restore from snapshot to a fresh Vault.

---

## 8. Snapshot encryption key loss

**Symptom:** You have Vault snapshots from DR layer 3, but they were encrypted
at rest by a KMS key that is also gone.

**Prevention (this is the section that prevents the worst-case spiral):**

- Snapshot encryption MUST use a key managed independently of the Vault
  unseal key. E.g.:
  - Vault auto-unseal key in AWS KMS in `us-east-1`
  - Snapshot encryption key in AWS KMS in `us-west-2` (different region)
  - OR snapshot encryption key in a DIFFERENT cloud entirely
- Maintain at least one **offline copy** of the snapshot encryption key
  material (paper, HSM offline, escrow).

**If both keys lost:** the snapshots are cryptographically inaccessible.
This is the failure mode that ends companies. The mitigation is preventive:
DR layer 3 implementation MUST enforce key-separation policy. Owned by the
Wave 5 `recovery/` squad.

---

## 9. Hub cannot authenticate

**Symptom:** Hub container logs show `403 forbidden` from Vault; or `permission
denied: secret-id expired`.

**Cause:** AppRole secret-id expired (default TTL 24h), or operator revoked.

**Recovery (run from the operator's workstation with a root or admin token):**

```bash
export BAO_TOKEN=<root-or-admin-token>
export BAO_ADDR=https://vault.your-spine.example:8200

# Issue a fresh wrapped secret-id
NEW_WRAP=$(bao write -wrap-ttl=300 -force -f auth/approle/role/spine-hub/secret-id)

# Extract the wrap token
TOKEN=$(echo "$NEW_WRAP" | grep wrapping_token: | awk '{print $2}')

# Hand off to Hub via your secure channel (Hub env var):
echo "SPINE_VAULT_SECRET_ID_WRAPPED=$TOKEN"
```

Hub restarts; `shared/secrets/` unwraps; auth resumes.

---

## Tested-restore cadence (DR layer 4)

The umbrella DR runbook + the `tools/dr-test.sh` runner exercise this vault
runbook weekly:
1. Snapshot live Vault.
2. Spin up throwaway Vault container.
3. Restore snapshot.
4. Unseal (Shamir auto-test uses ephemeral test shares; KMS test uses a
   dedicated test KMS key).
5. Verify `bao kv get spine/_dr_test/canary` returns the canary value.
6. Tear down.

**Failure = page oncall.** A failing weekly DR test blocks the next release
per `recovery/runbook_generator.py` policy.

---

## References

- DR architecture: `docs/V3_DESIGN_DECISIONS.md` §32 (all 12 layers)
- Shamir best practices: `unseal/shamir-config.md`
- KMS configs: `unseal/kms-config-{aws,azure,gcp}.md`
- Umbrella DR runbook (Wave 5): `docs/DR_RUNBOOK.md` (when written)
- Recovery subsystem: `recovery/` (Wave 5, Squad E)
