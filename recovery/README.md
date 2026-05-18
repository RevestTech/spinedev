# recovery/ — Spine v3 Disaster Recovery subsystem

> Wave 5 Squad E. Implements design decisions #31 (DR = BUILD properly
> for v1.0) and #32 (12-layer DR architecture) per
> `docs/V3_DESIGN_DECISIONS.md`.

The cost of getting DR wrong = the customer loses their AI team's
institutional memory. This subsystem is non-negotiable for v1.0.

## What this subsystem owns

| #  | Layer                                | Status v1.0      | File                       |
|----|--------------------------------------|------------------|----------------------------|
| 1  | Container auto-recovery              | BUILD            | `auto_recovery.py`         |
| 2  | Process supervision                  | BUILD            | `auto_recovery.py`         |
| 3  | Continuous data backup               | BUILD            | `backup.py`                |
| 4  | Tested data restore                  | BUILD            | `restore.py` + `dr-test.sh`|
| 5  | Heartbeat protocol                   | BUILD            | `health.py`                |
| 6  | Federation autonomy                  | observed only    | health probes (HEALTH_COMPONENTS) |
| 7  | Cross-region replication             | STUB v1.0        | `cross_region.py`          |
| 8  | Vault unseal recovery                | runbook coverage | `runbook_generator.py`     |
| 9  | Soft-delete recovery                 | runbook coverage | `runbook_generator.py`     |
| 10 | Vendor update infra DR               | health probe + runbook | `health.py` + `runbook_generator.py` |
| 11 | Auto-generated DR runbook            | BUILD            | `runbook_generator.py`     |
| 12 | Backup verification on every release | BUILD            | `tools/dr-test.sh`         |

## Why STUB on layer 7 (cross-region)

Per `docs/V3_BUILD_SEQUENCE.md` Part 4.4, cross-region active-passive is
*"optional per bundle policy (enterprise tier feature flag)"* with
default-OFF. v1.0 ships the seam (license flag gate + structured error)
so the Hub UI can light up the upgrade path; the actual replication
plumbing arrives in v1.1+ enterprise. Until then,
`CrossRegionReplicator.start_replication()` raises
`CrossRegionDisabled("dr.cross_region not enabled in active license")` if
the flag is off and `NotImplementedError("v1.1+ enterprise tier")` if
the flag is on.

The license flag name is `dr.cross_region`. See
`license/feature_flags.py` for the gate API.

## Storage backends (S3 / GCS / Azure Blob)

Backups are uploaded via the customer's already-installed cloud CLI:

* AWS S3 / S3-compatible → `aws s3 cp ...` (works with MinIO + Wasabi
  via `--endpoint-url`).
* GCP Cloud Storage → `gcloud storage cp ...`.
* Azure Blob → `az storage blob upload ...`.

We deliberately do NOT pull in `boto3`, `azure-storage-blob`, or
`google-cloud-storage` as hard dependencies. Rationale:

1. Customers already install the relevant CLI for operator workflows
   (debug, ad-hoc inspection). One toolchain, not two.
2. Keeps the closed-source wheel footprint small (per #18).
3. CLI invocations are auditable in shell history — useful during
   regulated incident reviews.

If you need to support a backend without an official CLI, write a
custom `BackupTarget` adapter and hand it to `BackupManager`.

## KMS encryption

Every backup is KMS-encrypted at rest. The KMS key reference is
fetched via `shared.secrets.get_secret(...)` per design decision #9 —
the path is `recovery/kms/<env>/key_id` (see `BackupTarget.from_bundle`
for the default path convention). The KMS material itself never leaves
the cloud provider's KMS; we only ever hold a key reference / ARN.

## How `dr-test.sh` runs

`tools/dr-test.sh` is the layer-4 + layer-12 enforcer. It:

1. Picks the most recent `spine_dr.backup_run` row with
   `status='completed'`.
2. Spins up a throwaway Postgres + KG container (named
   `spine-dr-test-<run_id>`).
3. Drives `RestoreManager.restore_to_environment(env="dr-sandbox")`.
4. Records the outcome (succeeded / RTO seconds / anomalies) into
   `spine_dr.restore_test`.
5. Tears down the throwaway environment.
6. Pages on-call via `shared.notify` if restore failed.

Wire it into cron / a Kubernetes CronJob / GitHub Actions / whatever
scheduler the deployment uses; default cadence is weekly.

## MCP tools surfaced to the Hub

| Tool                       | requires_citation | Purpose                                       |
|----------------------------|-------------------|-----------------------------------------------|
| `recovery_snapshot`        | True (#12)        | Trigger a snapshot backup; high-impact write  |
| `recovery_restore`         | True (#12)        | Restore a backup; mutates substrate           |
| `recovery_test`            | False             | Run a restore-to-throwaway and record outcome |
| `recovery_health`          | False             | Read-only health probe across DR components   |
| `recovery_runbook_export`  | False             | Generate + return the runbook markdown        |

See `shared/mcp/tools/recovery.py`.

## Tests

`recovery/tests/` exercises every module against mock S3 / GCS / Azure
CLIs and a mock asyncpg pool. There are no live cloud calls in CI.

Run with:

```bash
.venv/bin/python -m pytest recovery/tests/ -q
```

## Wave 6 follow-ups (out of scope for Wave 5)

* `cross_region.py` real plumbing (active-passive failover).
* `health.py` integration into the Hub dashboard "DR posture" panel.
* `runbook_generator.py` cross-link into evidence/ for Vanta/Drata
  audit-evidence export.
* MCP tool `recovery_failover` for one-click standby promotion.
