# Spine v3 — Keycloak DR runbook

> **Driver:** Decision #31 (DR build-properly), #32 layer 8 (Vault unseal recovery — Keycloak's
> equivalent applies here for realm-admin recovery), #25 (Keycloak embedded).
>
> **Cross-cutting:** `recovery/` (Wave 5 squad E) integrates this runbook as one of the 12 DR
> layers. This file is the canonical recovery procedure for the Keycloak component specifically;
> the Hub-wide DR runbook is auto-generated per deployment by `recovery/runbook_generator.py`.

---

## Scope

Recovers from three classes of incident:

1. **Container loss** — Keycloak container destroyed; DB intact.
2. **DB loss / corruption** — Keycloak Postgres destroyed; must restore from backup.
3. **Lost realm-admin credentials** — admin password forgotten / compromised; need to regain access
   without wiping the realm.

Plus key rotation: **realm signing keys** (rolling JWKS rotation without breaking active sessions).

---

## RPO / RTO targets

| Scenario | RPO | RTO |
|---|---|---|
| Container loss (DB intact) | 0 (no data loss) | < 5 min (pull image, recreate container, point at existing DB) |
| DB loss (restore from last backup) | ≤ 5 min (Postgres WAL streaming default) | < 30 min (matches Hub-wide DR target per #32 layer 4) |
| Lost realm-admin (full recovery, no realm wipe) | 0 (users / clients preserved) | < 15 min |
| Signing-key rotation (planned) | 0 | < 5 min, zero-downtime |

---

## Prerequisites

You'll need:

- Access to the Postgres backing store (`spine-keycloak-db` container or its production equivalent).
- The `kcadm.sh` binary (inside the Keycloak container at `/opt/keycloak/bin/kcadm.sh`).
- Shell access on the Keycloak host (laptop) OR `kubectl exec` (cloud).
- For DB restore: the most recent Keycloak Postgres backup tarball from
  `recovery/backup.py`'s output directory (default `s3://spine-backups/<hub-id>/keycloak/`).

---

## Scenario A — Container loss, DB intact

```bash
# 1. Confirm the DB is healthy.
docker exec spine-keycloak-db pg_isready -U keycloak -d keycloak

# 2. Stop / remove the broken container if it's still around.
docker rm -f spine-keycloak || true

# 3. Recreate (compose pulls latest image, healthcheck waits for DB).
cd keycloak/
docker compose --env-file .env.local up -d keycloak

# 4. Verify ready.
curl -fsS http://localhost:9000/health/ready

# 5. Verify realm + clients survived.
docker exec spine-keycloak /opt/keycloak/bin/kcadm.sh config credentials \
  --server http://localhost:8080 --realm master \
  --user "$KC_ADMIN_USER" --password "$KC_ADMIN_PASS"
docker exec spine-keycloak /opt/keycloak/bin/kcadm.sh get realms/spine -F realm,enabled
docker exec spine-keycloak /opt/keycloak/bin/kcadm.sh get clients -r spine -q clientId=spine-hub
```

**Success criteria:** `/health/ready` returns 200, realm `spine` is enabled, client `spine-hub`
present. No further action.

---

## Scenario B — DB loss / corruption, restore from backup

> **DO NOT skip the pre-restore snapshot step.** If the restore goes wrong you need a path back.

```bash
# 1. Stop Keycloak (DB writes during restore would corrupt the restore).
docker compose stop keycloak

# 2. Take a defensive snapshot of the (broken) DB before overwriting.
docker exec spine-keycloak-db pg_dump -U keycloak keycloak \
  | gzip > "keycloak-pre-restore-$(date -u +%Y%m%dT%H%M%SZ).sql.gz"

# 3. Drop & recreate the keycloak DB (cleanly start from the backup baseline).
docker exec -i spine-keycloak-db psql -U keycloak -d postgres -c "DROP DATABASE keycloak;"
docker exec -i spine-keycloak-db psql -U keycloak -d postgres -c "CREATE DATABASE keycloak;"

# 4. Restore from the most recent backup.
gunzip -c /path/to/keycloak-backup-YYYYMMDD.sql.gz \
  | docker exec -i spine-keycloak-db psql -U keycloak -d keycloak

# 5. Start Keycloak (it will run any pending Liquibase migrations on startup).
docker compose start keycloak

# 6. Wait for ready, then re-import the realm (idempotent merge; preserves restored users).
./init-bootstrap.sh \
  --keycloak-url http://localhost:8080 \
  --admin-user "$KC_ADMIN_USER" \
  --admin-pass "$KC_ADMIN_PASS"

# 7. Smoke-test: log in as a real user; confirm groups/roles present.
```

**Success criteria:** Keycloak healthy, realm + clients + users + groups present, a known user can
authenticate.

**Failure mode to watch:** Liquibase migration failure on startup means backup version mismatch with
container image version. Match the container image to the version that wrote the backup. Keycloak
N-1 backward compat is reliable; N-2+ may need an intermediate-version replay.

---

## Scenario C — Lost realm-admin credentials (without wiping the realm)

This is the equivalent of #32 layer 8's "vault unseal recovery" applied to Keycloak. You will
inject a **new** admin user directly into the master realm via SQL, log in with it, rotate the
real admin, then delete the SQL-injected one.

```bash
# 1. Generate a one-shot recovery password (treat as if you only get one shot).
RECOVERY_PASS="$(python3 -c 'import secrets,string; a=string.ascii_letters+string.digits; print("".join(secrets.choice(a) for _ in range(32)))')"
echo "RECOVERY (save now, single use): ${RECOVERY_PASS}"

# 2. Compute a bcrypt-like Keycloak-credential JSON inside the container (Keycloak does this for us
#    if we use the `add-user.sh` mechanism on the next container boot — it writes a new master-realm
#    admin into add-user-keycloak.json that gets ingested on startup).
docker exec -it spine-keycloak /opt/keycloak/bin/kc.sh bootstrap-admin user \
  --username "recovery-admin" --password "${RECOVERY_PASS}"

# 3. Restart Keycloak so the recovery admin is picked up.
docker compose restart keycloak

# 4. Wait for ready, log in with recovery-admin.
./init-bootstrap.sh \
  --keycloak-url http://localhost:8080 \
  --admin-user recovery-admin \
  --admin-pass "${RECOVERY_PASS}" \
  --generate-admin --output bootstrap-credentials.txt

# 5. The bootstrap script generated a fresh admin password into bootstrap-credentials.txt (chmod 600).
#    Save it to your password manager. Then delete the recovery admin.
docker exec spine-keycloak /opt/keycloak/bin/kcadm.sh config credentials \
  --server http://localhost:8080 --realm master \
  --user admin --password "$(grep spine_keycloak_admin_password bootstrap-credentials.txt | cut -d= -f2)"
docker exec spine-keycloak /opt/keycloak/bin/kcadm.sh delete users -r master \
  "$(docker exec spine-keycloak /opt/keycloak/bin/kcadm.sh get users -r master -q username=recovery-admin --fields id --format csv --noquotes | tail -1)"

# 6. Shred the credentials file once written to your vault.
shred -u bootstrap-credentials.txt 2>/dev/null || rm -P bootstrap-credentials.txt 2>/dev/null || rm -f bootstrap-credentials.txt
```

**Success criteria:** new admin password works on `/admin/`, recovery-admin user no longer exists,
all realm `spine` users and clients intact.

**Audit:** every step above is recorded in Keycloak's admin events log (which we keep on per
`realm-config/spine-realm.json`). The recovery should appear in the next Vanta/Drata evidence push
as an admin-recovery event.

---

## Scenario D — Signing-key rotation (planned, zero-downtime)

Keycloak rotates JWKS keys without breaking active sessions if you add the new key as `ACTIVE`
while keeping the old key as `PASSIVE` until all existing tokens expire.

```bash
# 1. Add a new RSA key in PASSIVE state (clients don't use it yet).
docker exec spine-keycloak /opt/keycloak/bin/kcadm.sh create components -r spine \
  -s name=rsa-rotate-$(date -u +%Y%m%d) \
  -s providerId=rsa-generated \
  -s providerType=org.keycloak.keys.KeyProvider \
  -s 'config.priority=["110"]' \
  -s 'config.enabled=["true"]' \
  -s 'config.active=["false"]' \
  -s 'config.algorithm=["RS256"]' \
  -s 'config.keySize=["2048"]'

# 2. After verifying the new key shows in JWKS (clients can validate either):
curl -s http://localhost:8080/realms/spine/protocol/openid-connect/certs | jq '.keys[].kid'

# 3. Promote new key to ACTIVE, demote old key to PASSIVE.
#    (Look up component IDs first.)
docker exec spine-keycloak /opt/keycloak/bin/kcadm.sh get components -r spine \
  -q parent=$(docker exec spine-keycloak /opt/keycloak/bin/kcadm.sh get realms/spine --fields id --format csv --noquotes | tail -1) \
  -q type=org.keycloak.keys.KeyProvider

# Then update each via PUT components/<id> with config.active flipped.

# 4. After max access-token TTL has passed (15m default), delete the old key.
```

**Success criteria:** `curl /.well-known/openid-configuration` returns the new `jwks_uri`; new
tokens validate against new key; old tokens still validate against old key until expiry.

---

## Backup cadence (configured in `recovery/backup.py` Wave 5)

| Item | Cadence | Retention | Location |
|---|---|---|---|
| Keycloak Postgres logical dump | Hourly | 7d | Customer S3-compatible storage |
| Keycloak Postgres WAL streaming | Continuous | 24h | Customer S3-compatible storage |
| Realm config export (`kcadm.sh export realms/spine`) | Daily | 30d | Customer S3-compatible storage |
| `kcadm.sh export` of all clients | Daily | 30d | Customer S3-compatible storage |

Restore-to-throwaway validation runs **weekly** per #32 layer 4 — `tools/dr-test.sh` (Wave 5)
restores the latest backup into a disposable container, runs the smoke test
(`tests/test-keycloak-up.sh`), and pages oncall on failure.

---

## Escalation

If recovery fails after exhausting this runbook:

1. Surface in Hub decision queue with `incident` work-item type (per #19).
2. Page Master DevOps (per bundle's pager rotation).
3. If Spine company support enabled and customer is on a supported tier, vendor support gets
   notified via the federation heartbeat (#32 layer 5) opt-in.

**Do not** wipe the realm to "start fresh" unless explicitly authorized — it destroys all user
credentials, group mappings, and audit history.
