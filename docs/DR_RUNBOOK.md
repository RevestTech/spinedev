# Disaster Recovery Runbook

> 12-layer DR architecture, operationally. Drivers: [`V3_DESIGN_DECISIONS.md`](V3_DESIGN_DECISIONS.md) — **#31** (DR built properly for v1.0 — not scaffold), **#32** (12 layers detail), **#9** (vault unseal recovery is part of DR), **#32 layer 11** (auto-generated DR runbook per deployment).
>
> **Audience:** Hub admin running DR tests, devops on-call doing actual restore, security reviewer auditing posture.
>
> **Status:** this is the **architectural** DR runbook. Per #32 layer 11, the **per-deployment runbook is auto-generated** by `recovery/runbook_generator.py` (Wave 5 Squad E — landing) and written to `_state/dr_runbook.md` after `hub/wizard/init.sh`. It reflects YOUR exact configuration: backup destinations, RPO/RTO commits, pager rotation, last test date, escalation path. **Read both** — this doc tells you the architecture; the auto-generated one tells you the buttons.

---

## 1. Why DR is built properly (not scaffold) — #31

Cost of getting DR wrong = **"customer loses their AI team's institutional memory."** Per #27 Smart Spine, this institutional memory compounds — by month 12 your Spine knows your codebase, your patterns, your team's decision style. Losing that is losing the product itself.

So DR for v1.0 is:

- **Auto-recovery** (containers + processes self-heal)
- **Immediate notification** (multi-medium per #6)
- **Tested restore** (weekly schedule, not "we'll figure it out when it breaks")

Non-negotiable.

---

## 2. The 12 layers (#32)

| # | Layer | What we build | RPO / RTO target |
|---|---|---|---|
| **1** | Container auto-recovery | K8s with replicas + liveness/readiness probes + auto-restart. `shared/runtime/watchdog.sh` for non-K8s (laptop, single-host) | 30s from container death |
| **2** | Process supervision | Each role daemon supervised; auto-restart on crash; circuit breaker on flapping | 30s from role-daemon crash |
| **3** | Continuous data backup | Postgres WAL + Vault snapshots + KG state → customer-chosen S3-compatible storage (S3 / GCS / Azure Blob / MinIO / Wasabi). KMS-encrypted at rest. Per-bundle retention (default 30d) | RPO ≤ 5 min |
| **4** | Tested data restore | Documented + automated restore. **Periodic restore-to-throwaway-environment** verification (weekly default) — catches "backups exist but restore broken" failure mode | RTO ≤ 30 min full Hub restoration |
| **5** | Heartbeat protocol | Each Hub heartbeats to itself + federation parent (if any) + vendor status registry (opt-in for proactive support). Failure → multi-medium notification per #6 | Detection ≤ 1 min |
| **6** | Federation autonomy | Per #10 — if parent Hub is down, child Hubs keep working autonomously. No cascading failures | Always-on at child Hub level |
| **7** | Cross-region replication | **Optional per bundle policy** (enterprise tier feature flag `dr.cross_region`). Active-passive: standby replica in second region; promotes on primary failure. Active-active deferred to v1.1+ (CAP-theorem complications) | RPO ≤ 5 min, RTO ≤ 10 min active-passive |
| **8** | Vault unseal recovery | **Shamir secret-sharing (3-of-5 humans)** for high-security OR **cloud-KMS auto-unseal** (AWS KMS / Azure KV / GCP KMS) — customer chooses at setup wizard. Runbook auto-generated | Manual if Shamir; auto if KMS |
| **9** | Customer-accidentally-deleted-Hub recovery | Soft-delete with 7d retention. Restore via Hub UI or vendor support. Full deletion requires HMAC-signed double-confirmation | Recoverable for 7d |
| **10** | Vendor update infrastructure DR | Vendor's own update publishing has DR (CDN-fronted artifact registry, multi-region, signed bundles). If vendor infra down, customers keep running current version (no auto-degradation) | Customers unaffected by vendor outage |
| **11** | DR runbook | **Auto-generated per deployment** based on actual configuration. Updated when bundle or topology changes. Includes: pager rotation, recovery commands, escalation paths, RPO/RTO, last-tested date | Always current |
| **12** | Backup verification on every release | When vendor publishes new Spine version, customer's automated DR test re-validates restore against new version. **Catches "upgrade broke backup compat" before it matters** | Continuous |

---

## 3. Day-2: routine ops

### Weekly DR test (layers 4 + 12)

```bash
# Manual trigger
bash tools/dr-test.sh

# Or via cron / scheduler — recommended setup wires it into the Hub's own scheduler
```

What `dr-test.sh` does:

1. Picks the most recent backup
2. Restores to a throwaway environment (separate K8s namespace OR separate Postgres DB on same host)
3. Brings up a parallel Hub against the restored data
4. Runs smoke test (`/healthz` + login + list projects + decision queue render)
5. Compares restored audit chain hash to current — verifies no corruption
6. Logs result to `spine_recovery.restore_test` (V32)
7. Tears down throwaway environment
8. If fail: pages on-call via PagerDuty + emits Decision Queue card

Default cadence: **weekly** (Sunday 02:00 UTC). Bundle policy can override.

### Daily backup verification

`shared/runtime/heartbeat.sh` checks every 5 minutes:

- Last successful PG WAL ship < 5 min ago (layer 3, RPO target)
- Last vault snapshot < 1 hour ago
- Last KG snapshot < 1 hour ago
- Backup storage destination reachable

If any check fails: Decision Queue card + multi-channel notify (#6).

### Heartbeat (layer 5)

Each Hub heartbeats every minute:

- To **itself** (in-Postgres `spine_instance` row gets `last_seen_at` updated)
- To **federation parent** (if any; child Hub publishes `InstanceHeartbeat` event upward via consented channel)
- To **vendor status registry** (opt-in via bundle: `dr.heartbeat_to_vendor: true` for proactive support)

Missed 3 consecutive: alert fires.

---

## 4. Actual restore — full Hub down

### Scenario A: container crashed, layer 1 didn't recover

```bash
# 1. Diagnose
make hub-status
make hub-logs --tail 200

# 2. Force restart with verbose
make hub-down
make hub-up

# 3. If vault unseal needed (typically: yes, after a hard restart with Shamir):
# Follow vault/dr-runbook.md — quorum-of-3 ceremony
```

If restart fixes it: log incident, file postmortem, move on. If it doesn't restart cleanly: proceed to Scenario B.

### Scenario B: data corruption, need restore from backup

```bash
# 1. Identify the most recent verified backup
spine recovery list-backups --verified
# backup_id              | timestamp                | size_gb | hash_chain_ok
# rec_2026-05-18T0200    | 2026-05-18T02:00:00Z     | 4.2     | YES (verified weekly)
# rec_2026-05-17T0200    | 2026-05-17T02:00:00Z     | 4.1     | YES
# rec_2026-05-16T0200    | 2026-05-16T02:00:00Z     | 4.1     | YES

# 2. Stop the broken Hub
make hub-down

# 3. Restore — automatic vault restore + PG restore + KG state restore + bundle restore
spine recovery restore --backup-id rec_2026-05-18T0200

# 4. Bring up
make hub-up

# 5. Verify audit chain integrity
spine audit verify-chain
# OK — chain intact, last_anchor matches restored backup

# 6. Federation re-sync (if federated)
spine federation pull-aggregates --since <last-known-good-timestamp>
```

RTO target: < 30 min full Hub restoration.

### Scenario C: cross-region failover (layer 7)

Only available if enterprise tier with `dr.cross_region` flag enabled.

```bash
# Primary region (us-east-1) is down
# Standby in us-west-2 has been replicating WAL continuously

# Manual failover trigger (typically automated for enterprise tier)
spine recovery failover --to us-west-2 --confirm
# 1. Promote us-west-2 replica to primary
# 2. Update DNS via cloud provider API
# 3. Re-issue mTLS certs for federation
# 4. Notify all federated children of new primary URL
# 5. Smoke test against new primary

# When us-east-1 comes back: spine recovery failback --to us-east-1
```

RPO target: ≤ 5 min (WAL replication lag). RTO target: ≤ 10 min.

### Scenario D: vault unsealed but corrupted (layer 8)

```bash
# Symptoms: vault is "unsealed" but reads fail / writes fail
# Likely cause: storage backend (Raft) corrupted

# 1. Stop vault
docker compose -f hub/docker-compose.yml stop vault

# 2. Restore vault snapshot from backup
bao operator raft snapshot restore /backups/vault-snapshot-2026-05-18.snap

# 3. Restart vault
docker compose -f hub/docker-compose.yml start vault

# 4. Re-unseal (Shamir 3-of-5 ceremony OR KMS auto-unseal kicks in)
bash vault/unseal/shamir-restore.sh   # Shamir mode
# OR auto on container start for KMS mode
```

Detailed runbook: `vault/dr-runbook.md`.

### Scenario E: customer accidentally deleted Hub (layer 9)

```bash
# Soft-deleted; recoverable for 7d
spine recovery undelete --hub <hub-id> --confirm
# HMAC double-confirmation required:
#   "I am <admin email> and I want to undelete <hub-id> at <timestamp>"
# Restores Hub to last-known-good state pre-deletion
```

After 7d: hard-deleted. Recovery is from offsite backup (layer 3 — customer's chosen S3-compatible storage).

---

## 5. Backup destinations (layer 3)

`recovery/backup.py` writes to customer-chosen S3-compatible storage:

| Destination | Adapter | Setup |
|---|---|---|
| AWS S3 | native | IAM role grant; KMS key for encryption-at-rest |
| GCP Cloud Storage | native | Service account + key |
| Azure Blob Storage | native | Storage account + access key (in vault) |
| MinIO | S3-compatible | Self-hosted; endpoint URL + access key (in vault) |
| Wasabi | S3-compatible | API key (in vault) |
| Backblaze B2 | S3-compatible | App key (in vault) |

Encryption: KMS at rest (customer-managed key); TLS in transit. Per-bundle retention (default 30d; enterprise tier typically 1y+).

What gets backed up:

- **PostgreSQL** — WAL streaming + daily logical dump
- **Vault** — Raft snapshots (hourly) + audit device log (continuous)
- **KG state** — incremental snapshots of `spine_kg` schema
- **Bundles** — every signed bundle version (`shared/standards/`)
- **License bundles** — current + history
- **`_state/` manifests** — `hub_id`, `wizard_manifest.json`, DR-runbook auto-gen output

What does NOT get backed up:

- Ephemeral container state
- `/tmp/` files
- `__pycache__/`
- Workspace dirs (`.spine/work/<run_id>/`) — these get archived to `.spine/archive/` instead per #34

---

## 6. The auto-generated runbook (layer 11)

`recovery/runbook_generator.py` produces `_state/dr_runbook.md` for YOUR deployment. It includes:

- **Pager rotation** — who's on-call this week, per the `devops` role schedule
- **Recovery commands** — exact CLI invocations for YOUR vault adapter, YOUR Postgres flavor, YOUR backup destination
- **Escalation paths** — vendor escalation contacts at your tier (CSM email, on-call number for enterprise tier)
- **RPO/RTO targets** — per your bundle policy (free tier RPO 1h vs enterprise RPO 5min)
- **Last-tested date** — from `spine_recovery.restore_test` table; warns if > 14 days since last successful test
- **Topology** — your federation tree (drawn) so on-call knows what cascades depend on this Hub
- **Cross-references** — which `vault/dr-runbook.md`, `keycloak/dr-runbook.md`, federation cascade docs apply

The runbook regenerates:

- After every `hub/wizard/init.sh` run
- After every bundle change
- After every federation topology change (child join/leave)
- After every successful DR test (updates "last tested" timestamp)

Read your own `_state/dr_runbook.md` for the operational truth specific to your deployment.

---

## 7. RPO / RTO ladder by tier

Per bundle policy + the 12-layer architecture:

| Layer | Free | Founder | Team | Enterprise |
|---|---|---|---|---|
| 1 — Container auto-recovery | 30s | 30s | 30s | 30s |
| 2 — Process supervision | 30s | 30s | 30s | 30s |
| 3 — Backup RPO | 1h | 30 min | 15 min | 5 min |
| 4 — Restore RTO | 2h | 1h | 1h | 30 min |
| 5 — Heartbeat detection | 5 min | 2 min | 1 min | 30s |
| 6 — Federation autonomy | n/a | n/a | always | always |
| 7 — Cross-region active-passive | n/a | n/a | opt-in (+$) | available |
| 8 — Vault unseal | local file | KMS auto | KMS auto | Shamir 3-of-5 |
| 9 — Soft-delete window | 7d | 7d | 7d | 7d |
| 10 — Vendor infra DR | covered | covered | covered | covered + dedicated escalation |
| 11 — DR runbook | auto-gen | auto-gen | auto-gen | auto-gen + quarterly tabletop |
| 12 — Backup verification on release | recommended | required | required | required + report to compliance |

---

## 8. Failure mode catalog

| Failure | First responder | Layer(s) | Likely cause | Time-to-mitigation |
|---|---|---|---|---|
| Hub container crash loop | devops on-call | 1, 2 | Migration bug after update | < 5 min auto-restart loop; if persists 3 attempts, pager fires |
| Postgres unreachable | devops on-call | 3, 4 | Disk full / network split | Heartbeat detects ≤ 1 min; restore RTO target by tier |
| Vault sealed after restart | security_engineer | 8 | Restart cleared in-memory unseal | Shamir ceremony: 5–15 min; KMS auto: < 30s |
| Federation parent down | none (autonomous) | 6 | Parent infra outage | No action needed; child keeps working; buffer flushed on reconnect |
| Cross-region primary down | devops on-call | 7 | AZ outage | Failover RTO 10 min |
| Backup destination unreachable | devops on-call | 3 | S3 access key rotated; cloud provider issue | Heartbeat detects in 5 min; pager fires |
| Last DR test > 14d ago | conductor (gate trigger) | 4, 11 | Test scheduler broken | Conductor refuses release until tested |
| Audit chain integrity broken | security_engineer (priority 0) | 3, 12 | Backup corruption OR tampering | Investigate immediately; isolate Hub; restore from last verified backup |
| License bundle expired | admin | n/a (not DR but related) | Forgot renewal | Hub enters degraded mode; admin pastes new bundle |

---

## 9. Testing DR — quarterly tabletop

For Team+ tier, run a quarterly tabletop:

1. Pick one of the failure modes from §8
2. Trigger via `tools/dr-chaos.sh --scenario <name>` (chaos-engineering hook)
3. On-call responds as if real incident — using only the auto-generated runbook
4. Time the mitigation
5. Postmortem: did the runbook contain everything needed? Were RPO/RTO targets met?
6. Update bundle if runbook had gaps; regenerate runbook; re-test in next tabletop

Per #11, this is a `devops` role responsibility under control-plane 7 (Incident).

---

## 10. AI-drivable DR (#21)

Common AI-driven DR workflows:

```bash
# AI agent triggers DR test as part of release readiness check
bash tools/dr-test.sh --as-release-gate <release-id>
# Returns: 0 (pass) | non-zero (block release)

# AI agent diagnoses last-failed DR test
spine recovery diagnose --test-id <id>
# Identifies which step failed, suggests likely cause + fix

# AI agent proposes RTO improvement
spine recovery analyze --past-90d
# "Restore RTO p95 is 47 min; target 30 min. Recommend: enable parallel restore for KG + audit chain."
```

---

## 11. Related artifacts

- `recovery/README.md` — recovery subsystem internals (Wave 5 Squad E)
- `recovery/runbook_generator.py` — auto-runbook (layer 11)
- `recovery/backup.py` + `restore.py` + `cross_region.py` + `auto_recovery.py` + `health.py`
- `tools/dr-test.sh` — weekly test (layer 4)
- `tools/dr-chaos.sh` — chaos-engineering hook (quarterly tabletop)
- `vault/dr-runbook.md` — vault-specific DR (layer 8)
- `keycloak/dr-runbook.md` — Keycloak-specific DR
- `db/flyway/sql/V32__dr_backup_log.sql` — backup/restore/verification schemas
- `_state/dr_runbook.md` — **your auto-generated runbook** (read this, not just this doc)
- [`docs/SECURITY_GUIDE.md`](SECURITY_GUIDE.md) §3 — vault unseal recovery security posture
- [`docs/FEDERATION_GUIDE.md`](FEDERATION_GUIDE.md) §8 — federation autonomy (layer 6)
- [`docs/HUB_OPERATIONS_GUIDE.md`](HUB_OPERATIONS_GUIDE.md) §10 — healthy-Hub checklist (includes DR cadence)
- [`docs/V3_DESIGN_DECISIONS.md`](V3_DESIGN_DECISIONS.md) #31, #32 — driver decisions
