"""Recovery (DR) MCP tools — Wave 5 Squad E / design decisions #31 + #32.

Five tools, auto-registered when the unified MCP server walks this
package on startup:

* ``recovery_snapshot``      — trigger a snapshot backup. Tagged
                               ``requires_citation=True`` per #12 (mutates
                               substrate; high-impact).
* ``recovery_restore``       — restore from a backup_run. Tagged
                               ``requires_citation=True`` per #12 (mutates
                               substrate; highest-impact).
* ``recovery_test``          — run the weekly restore-to-throwaway test
                               (layer 4 + layer 12). Not citation-required —
                               this is the verification harness, not a
                               substrate mutation.
* ``recovery_health``        — read-only health-probe aggregator across
                               hub/vault/keycloak/postgres/mcp_server.
* ``recovery_runbook_export``— generate + return the Markdown runbook
                               (layer 11).

All tools route audit writes through ``shared/audit/audit_record.py`` so
the Hub admin UI's "recent recovery activity" panel can render history
and pricing analytics can trace which deployments are exercising DR.

Citation strategy (#12):

* For ``recovery_snapshot`` / ``recovery_restore`` we always have:
    - An ``audit_hash`` citation rooted in the audit row UUID generated
      by this tool call.
    - A ``file_line`` citation pointing at the V32 migration that
      defines the spine_dr schema (so the reviewer can walk to the
      durable evidence of what was changed).
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Literal, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from shared.mcp.schemas import Citation, ToolError, ToolResponse
from shared.mcp.tools import register_tool

logger = logging.getLogger(__name__)

_FORBID = ConfigDict(extra="forbid")

# Stable file:line ref for evidence pointers; if the V32 migration moves
# to a new file/line this constant is the one place to update.
V32_MIGRATION_REF: str = "db/flyway/sql/V32__dr_backup_log.sql:28"


# ---------------------------------------------------------------------------
# Shared helpers (mirror shared/mcp/tools/license.py)
# ---------------------------------------------------------------------------


def _log(tool: str, project_id: str, actor: str) -> None:
    logger.info("mcp_tool_call",
                extra={"tool": tool, "project_id": project_id, "actor": actor})


def _error(code: str, message: str, *, retryable: bool = False) -> ToolResponse:
    return ToolResponse(
        status="error", audit_id=uuid4(),
        error=ToolError(code=code, message=message, retryable=retryable),
    )


def _audit_write(
    *, action: str, project_id: str, actor: str,
    subject_type: str, subject_id: str,
    metadata: dict[str, Any],
) -> UUID:
    """Best-effort audit write; never blocks the tool result."""
    audit_uuid = uuid4()
    try:
        from shared.audit.audit_record import (
            AuditRecord, chain_to_previous, write_via_psql,
        )
        try:
            project_id_int: Optional[int] = int(project_id)
        except (TypeError, ValueError):
            project_id_int = None
        rec = AuditRecord(
            role=actor, subsystem="shared", action=action, actor=actor,
            project_id=project_id_int,
            subject_type=subject_type, subject_id=subject_id,
            metadata=metadata, event_uuid=audit_uuid,
        )
        rec = chain_to_previous(rec, None)
        write_via_psql(rec)
    except Exception as exc:  # noqa: BLE001 — audit best-effort
        logger.warning("recovery_tool_audit_failed",
                       extra={"action": action, "err": str(exc)})
    return audit_uuid


def _get_pool() -> Any:
    """Return the process-wide asyncpg pool, or None if not bootstrapped.

    Tests inject a mock via :func:`license.feature_flags.set_pool` (the
    feature_flags module owns the canonical handle in Wave 4/5).
    """
    try:
        from license.feature_flags import _POOL
        return _POOL
    except Exception:
        return None


def _make_backup_target_from_request(payload_target: dict[str, Any]):
    """Construct a BackupTarget from the inbound payload dict.

    Kept tiny so tests can stub ``recovery.backup.BackupTarget`` without
    importing here.
    """
    from recovery.backup import BackupTarget
    return BackupTarget.from_bundle(payload_target)


# ---------------------------------------------------------------------------
# recovery_snapshot  —  requires_citation per #12
# ---------------------------------------------------------------------------


class RecoverySnapshotInput(BaseModel):
    model_config = _FORBID
    project_id: str = Field(..., min_length=1)
    actor: str = Field(default="devops", min_length=1)
    components: tuple[str, ...] = Field(
        default=("postgres", "kg", "vault", "bundles"),
        description="Subset of components to snapshot.",
    )
    retention_days: int = Field(default=30, ge=1, le=3650)
    target: dict[str, Any] = Field(
        ...,
        description=(
            "BackupTarget payload: {scheme, bucket, prefix, endpoint_url, "
            "region, kms_key_ref, storage_creds_path}. KMS + creds paths "
            "are vault refs (#9), not values."
        ),
    )


@register_tool(
    name="recovery_snapshot",
    input_model=RecoverySnapshotInput,
    story="STORY-31.1.1",
    description="Trigger a snapshot backup across requested DR components.",
    tags=("recovery", "backup"),
    requires_citation=True,  # V3 #12 — high-impact substrate write
)
def recovery_snapshot(payload: RecoverySnapshotInput) -> ToolResponse:
    """Run one point-in-time snapshot backup synchronously.

    Returns a ToolResponse whose ``data`` carries the BackupOutcome dict.
    Cite-or-Refuse: every response carries audit_hash + file_line
    citations rooted in the generated audit row + V32 migration.
    """
    _log("recovery_snapshot", payload.project_id, payload.actor)
    try:
        from recovery.backup import BackupManager, SnapshotPlan
        target = _make_backup_target_from_request(payload.target)
        mgr = BackupManager(target=target, pool_factory=_get_pool)
        plan = SnapshotPlan(
            components=tuple(payload.components),
            retention_days=payload.retention_days,
            actor=payload.actor,
            project_id=payload.project_id,
        )
        try:
            outcome = asyncio.run(mgr.run_snapshot(plan))
        except RuntimeError as exc:
            # Already inside a loop (async server case) — degrade clean.
            return _error("loop_already_running", str(exc))
    except Exception as exc:  # noqa: BLE001 — terminal path
        logger.exception("recovery_snapshot_failed")
        return _error("snapshot_failed", str(exc))

    audit_id = _audit_write(
        action="recovery_snapshot",
        project_id=payload.project_id, actor=payload.actor,
        subject_type="backup_run", subject_id=str(outcome.run_id),
        metadata=outcome.as_audit_metadata(),
    )
    citations: list[Citation] = [
        Citation(type="audit_hash", ref=str(audit_id),
                 excerpt=f"backup_run={outcome.run_id} status={outcome.status}"),
        Citation(type="file_line", ref=V32_MIGRATION_REF,
                 excerpt="spine_dr.backup_run definition"),
    ]
    data = {
        "run_id": str(outcome.run_id),
        "status": outcome.status,
        "size_bytes": outcome.size_bytes,
        "target_uri": outcome.target_uri,
        "encryption_kms_key_ref": outcome.encryption_kms_key_ref,
        "components_uploaded": list(outcome.components_uploaded),
        "started_at": outcome.started_at.isoformat(),
        "completed_at": outcome.completed_at.isoformat() if outcome.completed_at else None,
        "error": outcome.error,
    }
    return ToolResponse(status="ok", data=data, audit_id=audit_id,
                        citation=citations)


# ---------------------------------------------------------------------------
# recovery_restore  —  requires_citation per #12
# ---------------------------------------------------------------------------


class RecoveryRestoreInput(BaseModel):
    model_config = _FORBID
    project_id: str = Field(..., min_length=1)
    actor: str = Field(default="devops", min_length=1)
    backup_run_id: str = Field(..., description="UUID of spine_dr.backup_run.id")
    tested_in_env: Literal["staging", "dr-sandbox", "qa"] = Field(
        default="dr-sandbox",
        description="Restore env. Production restore uses a different tool path.",
    )
    target_postgres_dsn: Optional[str] = Field(
        default=None, description="Override target DSN (defaults to dr-sandbox).",
    )
    components: tuple[str, ...] = Field(
        default=("postgres", "kg", "vault", "bundles"),
    )
    target: dict[str, Any] = Field(...)


@register_tool(
    name="recovery_restore",
    input_model=RecoveryRestoreInput,
    story="STORY-31.1.2",
    description="Restore from a backup_run row; logs outcome to spine_dr.restore_test.",
    tags=("recovery", "restore"),
    requires_citation=True,  # V3 #12 — highest-impact substrate write
)
def recovery_restore(payload: RecoveryRestoreInput) -> ToolResponse:
    """Restore the named backup into the named environment."""
    _log("recovery_restore", payload.project_id, payload.actor)
    try:
        from recovery.restore import RestoreManager, RestorePlan
        target = _make_backup_target_from_request(payload.target)
        try:
            run_uuid = UUID(payload.backup_run_id)
        except ValueError:
            return _error("invalid_backup_run_id",
                          f"not a UUID: {payload.backup_run_id!r}")
        mgr = RestoreManager(target=target, pool_factory=_get_pool)
        plan = RestorePlan(
            backup_run_id=run_uuid,
            tested_in_env=payload.tested_in_env,
            target_postgres_dsn=payload.target_postgres_dsn,
            components=tuple(payload.components),
            actor=payload.actor, project_id=payload.project_id,
        )
        try:
            outcome = asyncio.run(mgr.restore_to_environment(plan))
        except RuntimeError as exc:
            return _error("loop_already_running", str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("recovery_restore_failed")
        return _error("restore_failed", str(exc))

    audit_id = _audit_write(
        action="recovery_restore",
        project_id=payload.project_id, actor=payload.actor,
        subject_type="restore_test", subject_id=str(outcome.restore_test_id),
        metadata=outcome.as_audit_metadata(),
    )
    citations: list[Citation] = [
        Citation(type="audit_hash", ref=str(audit_id),
                 excerpt=f"restore_test={outcome.restore_test_id} ok={outcome.restore_succeeded}"),
        Citation(type="file_line", ref=V32_MIGRATION_REF,
                 excerpt="spine_dr.restore_test definition"),
    ]
    data = {
        "restore_test_id": str(outcome.restore_test_id),
        "backup_run_id": str(outcome.backup_run_id),
        "restore_succeeded": outcome.restore_succeeded,
        "rto_seconds": outcome.rto_seconds,
        "components_restored": list(outcome.components_restored),
        "anomalies": outcome.anomalies,
        "tested_in_env": outcome.tested_in_env,
        "tested_at": outcome.tested_at.isoformat(),
        "error": outcome.error,
    }
    return ToolResponse(status="ok", data=data, audit_id=audit_id,
                        citation=citations)


# ---------------------------------------------------------------------------
# recovery_test  —  weekly DR test cycle
# ---------------------------------------------------------------------------


class RecoveryTestInput(BaseModel):
    model_config = _FORBID
    project_id: str = Field(..., min_length=1)
    actor: str = Field(default="dr-test-cron", min_length=1)
    target: dict[str, Any] = Field(...)


@register_tool(
    name="recovery_test",
    input_model=RecoveryTestInput,
    story="STORY-31.1.3",
    description="Run the weekly DR restore-to-throwaway test (layers 4 + 12).",
    tags=("recovery", "test"),
)
def recovery_test(payload: RecoveryTestInput) -> ToolResponse:
    """Pick the most recent successful backup_run, restore into dr-sandbox.

    Records a row into ``spine_dr.restore_test`` either way. Not tagged
    ``requires_citation`` — this is the verification harness layer 4/12
    plumbing; the verdict IS the report. (Calls to ``recovery_restore``
    are still citation-required for substrate mutations.)
    """
    _log("recovery_test", payload.project_id, payload.actor)
    try:
        from recovery.restore import RestoreManager
        target = _make_backup_target_from_request(payload.target)
        mgr = RestoreManager(target=target, pool_factory=_get_pool)
        try:
            report = asyncio.run(mgr.run_weekly_test(
                project_id=payload.project_id, actor=payload.actor,
            ))
        except RuntimeError as exc:
            return _error("loop_already_running", str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("recovery_test_failed")
        return _error("test_failed", str(exc))

    audit_id = _audit_write(
        action="recovery_test",
        project_id=payload.project_id, actor=payload.actor,
        subject_type="restore_cycle", subject_id=str(report.cycle_id),
        metadata={
            "cycle_id": str(report.cycle_id),
            "all_passed": report.all_passed,
            "worst_rto_seconds": report.worst_rto_seconds,
            "outcome_count": len(report.outcomes),
        },
    )
    data = {
        "cycle_id": str(report.cycle_id),
        "all_passed": report.all_passed,
        "worst_rto_seconds": report.worst_rto_seconds,
        "outcomes": [
            {
                "restore_test_id": str(o.restore_test_id),
                "backup_run_id": str(o.backup_run_id),
                "tested_in_env": o.tested_in_env,
                "succeeded": o.restore_succeeded,
                "rto_seconds": o.rto_seconds,
                "anomalies": o.anomalies,
                "error": o.error,
            }
            for o in report.outcomes
        ],
        "started_at": report.started_at.isoformat(),
        "completed_at": report.completed_at.isoformat(),
    }
    return ToolResponse(status="ok", data=data, audit_id=audit_id)


# ---------------------------------------------------------------------------
# recovery_health  —  read-only health-probe aggregator
# ---------------------------------------------------------------------------


class RecoveryHealthInput(BaseModel):
    model_config = _FORBID
    project_id: str = Field(..., min_length=1)
    actor: str = Field(default="system", min_length=1)


@register_tool(
    name="recovery_health",
    input_model=RecoveryHealthInput,
    story="STORY-31.1.4",
    description="Run probes across hub/vault/keycloak/postgres/mcp_server.",
    tags=("recovery", "health"),
)
def recovery_health(payload: RecoveryHealthInput) -> ToolResponse:
    """Return a HealthReport covering all DR-critical components."""
    _log("recovery_health", payload.project_id, payload.actor)
    try:
        from recovery.health import HealthProber
        prober = HealthProber(pool_factory=_get_pool)
        try:
            report = asyncio.run(prober.generate_report())
        except RuntimeError as exc:
            return _error("loop_already_running", str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("recovery_health_failed")
        return _error("health_failed", str(exc))

    report_dict = report.as_dict()
    audit_id = _audit_write(
        action="recovery_health",
        project_id=payload.project_id, actor=payload.actor,
        subject_type="health_report", subject_id=str(report.report_id),
        metadata={
            "overall_status": report.overall_status,
            "components_probed": len(report.outcomes),
        },
    )
    return ToolResponse(status="ok", data=report_dict, audit_id=audit_id)


# ---------------------------------------------------------------------------
# recovery_runbook_export  —  layer 11 export
# ---------------------------------------------------------------------------


class RecoveryRunbookExportInput(BaseModel):
    model_config = _FORBID
    project_id: str = Field(..., min_length=1)
    actor: str = Field(default="devops", min_length=1)
    deployment_shape: Literal["laptop", "byoc", "customer-cloud", "on-prem"] = Field(
        default="customer-cloud",
    )
    customer_name: str = Field(default="customer")
    primary_region: str = Field(default="us-east-1")
    pager_rotation: tuple[str, ...] = Field(default=())
    storage_target_uri: str = Field(default="s3://example-spine-dr/")
    kms_key_ref: Optional[str] = Field(default=None)
    cross_region_licensed: bool = Field(default=False)
    federation_parent_url: Optional[str] = Field(default=None)


@register_tool(
    name="recovery_runbook_export",
    input_model=RecoveryRunbookExportInput,
    story="STORY-31.1.5",
    description="Generate the Markdown DR runbook (layer 11) for this deployment.",
    tags=("recovery", "runbook"),
)
def recovery_runbook_export(payload: RecoveryRunbookExportInput) -> ToolResponse:
    """Render the runbook + return Markdown + content hash."""
    _log("recovery_runbook_export", payload.project_id, payload.actor)
    try:
        from recovery.runbook_generator import RunbookGenerator, RunbookInputs
        inputs = RunbookInputs(
            deployment_shape=payload.deployment_shape,
            customer_name=payload.customer_name,
            primary_region=payload.primary_region,
            pager_rotation=tuple(payload.pager_rotation),
            storage_target_uri=payload.storage_target_uri,
            kms_key_ref=payload.kms_key_ref,
            cross_region_licensed=payload.cross_region_licensed,
            federation_parent_url=payload.federation_parent_url,
        )
        gen = RunbookGenerator()
        body_md = gen.render(inputs)
        body_hash = gen.content_hash(inputs)
    except Exception as exc:  # noqa: BLE001
        logger.exception("recovery_runbook_export_failed")
        return _error("runbook_failed", str(exc))

    audit_id = _audit_write(
        action="recovery_runbook_export",
        project_id=payload.project_id, actor=payload.actor,
        subject_type="dr_runbook", subject_id=body_hash[:12],
        metadata={
            "content_hash": body_hash,
            "deployment_shape": payload.deployment_shape,
            "primary_region": payload.primary_region,
            "cross_region_licensed": payload.cross_region_licensed,
            "byte_count": len(body_md),
        },
    )
    return ToolResponse(status="ok", data={
        "body_markdown": body_md,
        "content_hash": body_hash,
        "byte_count": len(body_md),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }, audit_id=audit_id)


__all__ = [
    "RecoveryHealthInput",
    "RecoveryRestoreInput",
    "RecoveryRunbookExportInput",
    "RecoverySnapshotInput",
    "RecoveryTestInput",
    "V32_MIGRATION_REF",
    "recovery_health",
    "recovery_restore",
    "recovery_runbook_export",
    "recovery_snapshot",
    "recovery_test",
]
