"""
recovery
========

Spine v3 Disaster Recovery subsystem (Wave 5 Squad E).

Implements design decisions **#31** (DR = BUILD properly for v1.0, not a
scaffold) and **#32** (12-layer DR architecture) from
``docs/V3_DESIGN_DECISIONS.md``. Cost of getting DR wrong = the customer
loses their AI team's institutional memory. Non-negotiable.

12 layers (see ``docs/V3_DESIGN_DECISIONS.md`` §32). What this subsystem
provides today vs. defers:

    1.  Container auto-recovery       — BUILD (auto_recovery.py wraps
                                        shared/runtime/watchdog.sh)
    2.  Process supervision           — BUILD (auto_recovery.py)
    3.  Continuous data backup        — BUILD (backup.py — WAL +
                                        snapshot, S3/GCS/Azure, KMS)
    4.  Tested data restore           — BUILD (restore.py + dr-test.sh
                                        weekly restore-to-throwaway)
    5.  Heartbeat protocol            — BUILD (health.py, hits
                                        spine_dr.heartbeat + notify)
    6.  Federation autonomy           — N/A here — guaranteed by
                                        federation/ subsystem (Squad A);
                                        recovery only OBSERVES it via
                                        health probes
    7.  Cross-region replication      — STUB v1.0 (cross_region.py raises
                                        NotImplementedError; gated by
                                        license flag ``dr.cross_region``;
                                        default-OFF per Part 4.4)
    8.  Vault unseal recovery         — runbook coverage only (vault/
                                        owns the unseal mechanism; we
                                        document it in the auto-generated
                                        runbook per layer 11)
    9.  Soft-delete recovery          — runbook coverage only (Hub UI
                                        owns the 7d soft-delete; runbook
                                        documents the restore command)
    10. Vendor update infra DR        — vendor-side concern; we document
                                        it in the runbook + health-probe
                                        the upstream artifact registry
    11. DR runbook                    — BUILD (runbook_generator.py —
                                        auto-generated per deployment)
    12. Backup verification on every release — BUILD (dr-test.sh hooks
                                                into upgrade flow)

Public surface (locked for Wave 5):

    BackupManager       — continuous WAL + snapshot backup orchestration
    RestoreManager      — tested restore with spine_dr.restore_test logging
    AutoRecoveryManager — container + process auto-restart on liveness fail
    HealthProber        — hub/vault/keycloak/postgres/MCP server probes
    RunbookGenerator    — auto-generated DR runbook per deployment

Hard rules (per V3 design decisions):

* **#9 — Vault-only secrets.** KMS keys + storage credentials route
  through ``shared.secrets``. Never read from env vars directly.
* **#12 — Cite-or-Refuse.** ``recovery_snapshot`` and ``recovery_restore``
  MCP tools are tagged ``requires_citation=True`` because they're
  high-impact (mutate customer data substrate or rehydrate it).
* **#32 / Part 4.4 — cross-region default-OFF.** ``cross_region.py``
  always checks ``license.is_enabled("dr.cross_region")`` first and
  raises if disabled OR if the license is not loaded.

Scope boundary: this package touches ONLY ``recovery/*``,
``tools/dr-test.sh``, and ``shared/mcp/tools/recovery.py``. No edits to
``migration/`` (Squad F), landing docs (Squad G), or any other
subsystem.

Storage backends are invoked via ``subprocess`` against the
already-installed cloud CLIs (``aws s3 cp`` / ``gcloud storage cp`` /
``az storage blob upload``). We deliberately do NOT pull in
``boto3`` / ``azure-storage-blob`` / ``google-cloud-storage`` hard
deps — the customer's deployment already has the relevant CLI for
operator-driven troubleshooting, and this keeps the wheel footprint
small. See ``recovery/README.md`` for the install matrix.
"""
from __future__ import annotations

from recovery.auto_recovery import (
    AutoRecoveryManager,
    LivenessProbe,
    RecoveryAction,
    RecoveryResult,
    SupervisedTarget,
)
from recovery.backup import (
    BackupManager,
    BackupOutcome,
    BackupTarget,
    SnapshotPlan,
    WalPlan,
)
from recovery.cross_region import (
    CrossRegionDisabled,
    CrossRegionReplicator,
    promote_standby,
)
from recovery.health import (
    HEALTH_COMPONENTS,
    HealthProber,
    HealthReport,
    HealthStatus,
    ProbeOutcome,
)
from recovery.restore import (
    RestoreManager,
    RestoreOutcome,
    RestorePlan,
    TestRestoreReport,
)
from recovery.runbook_generator import (
    RunbookGenerator,
    RunbookSection,
)

__all__ = [
    # backup.py
    "BackupManager",
    "BackupOutcome",
    "BackupTarget",
    "SnapshotPlan",
    "WalPlan",
    # restore.py
    "RestoreManager",
    "RestoreOutcome",
    "RestorePlan",
    "TestRestoreReport",
    # cross_region.py
    "CrossRegionReplicator",
    "CrossRegionDisabled",
    "promote_standby",
    # auto_recovery.py
    "AutoRecoveryManager",
    "LivenessProbe",
    "RecoveryAction",
    "RecoveryResult",
    "SupervisedTarget",
    # health.py
    "HealthProber",
    "HealthReport",
    "HealthStatus",
    "ProbeOutcome",
    "HEALTH_COMPONENTS",
    # runbook_generator.py
    "RunbookGenerator",
    "RunbookSection",
]
