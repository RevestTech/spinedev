"""Migration MCP tools (Wave 5 Squad F / design decision #33).

Four tools, auto-registered when the unified MCP server walks this
package on startup:

* ``migration_export`` — write a signed Spine state tarball to disk.
  Read-only against state stores; the only side effect is the
  filesystem write. Not Cite-or-Refuse (export is not a verdict).
* ``migration_import`` — verify + load a signed tarball into the
  destination Hub. **Tagged ``requires_citation=True`` per #12** because
  this is a high-impact destructive op (writes into 12 schemas, replays
  the audit chain, registers vault refs).
* ``migration_onboarding_dispatch`` — run a configured matrix of
  onboarding connectors (GitHub + Linear in v1.0).
* ``migration_version_upgrade`` — run the version-upgrade planner +
  executor. **Tagged ``requires_citation=True`` per #12** for the same
  reason as ``migration_import``.

Each tool writes a structured row to ``spine_audit.audit_event``
(subsystem=``shared``, mirroring ``license``/``standards`` tools) so the
migration panel UI can show "last export/import at Y" + the wizard can
track onboarding progress.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from shared.mcp.schemas import Citation, ToolError, ToolResponse
from shared.mcp.tools import register_tool

logger = logging.getLogger(__name__)

_FORBID = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# Audit helpers (mirrors shared/mcp/tools/license.py)
# ---------------------------------------------------------------------------


def _log(tool: str, project_id: str, actor: str) -> None:
    logger.info("mcp_tool_call",
                extra={"tool": tool, "project_id": project_id, "actor": actor})


def _error(code: str, message: str, *, retryable: bool = False,
           audit_id: Optional[UUID] = None) -> ToolResponse:
    aid = audit_id or uuid4()
    return ToolResponse(
        status="error", audit_id=aid,
        error=ToolError(code=code, message=message, retryable=retryable),
    )


def _audit_write(*, action: str, project_id: str, actor: str,
                 subject_id: str, metadata: dict[str, Any]) -> UUID:
    """Best-effort audit write; never blocks the tool result on a write failure."""
    audit_uuid = uuid4()
    try:
        from shared.audit.audit_record import (
            AuditRecord, chain_to_previous, write_via_psql,
        )
        rec = AuditRecord(
            role=actor, subsystem="shared", action=action, actor=actor,
            subject_type="migration_artifact", subject_id=subject_id,
            metadata=metadata, event_uuid=audit_uuid,
        )
        rec = chain_to_previous(rec, None)
        write_via_psql(rec)
    except Exception as exc:  # noqa: BLE001 — audit is best-effort
        logger.warning("migration_tool_audit_failed",
                       extra={"action": action, "err": str(exc)})
    return audit_uuid


# ---------------------------------------------------------------------------
# migration_export
# ---------------------------------------------------------------------------


class MigrationExportInput(BaseModel):
    model_config = _FORBID
    project_id: str = Field(..., min_length=1)
    actor: str = Field(default="operator", min_length=1)
    out_path: str = Field(..., min_length=1,
        description="Destination tarball path (convention: spine-export-<bundle_id>.tar).")
    bundle_id: str = Field(..., min_length=1,
        description="Unique id for this export run (e.g. '<hub_id>-<utc>').")
    source_hub_id: Optional[str] = Field(default=None)
    notes: str = Field(default="")


@register_tool(
    name="migration_export",
    input_model=MigrationExportInput,
    story="STORY-33.B.1",
    description="Write a signed, deterministic Spine state tarball.",
    tags=("migration", "portability"),
)
def migration_export(payload: MigrationExportInput) -> ToolResponse:
    """Run :func:`migration.export.export_state` against the live Hub stores.

    The Hub injects production ``StateReader`` + ``VaultSigner`` at
    startup via :func:`set_runtime`; absent that injection this tool
    returns ``status_code=stub_implementation`` rather than crashing.
    """
    _log("migration_export", payload.project_id, payload.actor)

    reader, signer = _get_runtime_export()
    if reader is None or signer is None:
        audit_id = _audit_write(
            action="migration_export", project_id=payload.project_id,
            actor=payload.actor, subject_id=payload.bundle_id,
            metadata={"stub": True, "reason": "no runtime reader/signer"},
        )
        return ToolResponse(
            status="stub_implementation",
            data={"reason": "runtime not bootstrapped"},
            audit_id=audit_id,
        )

    try:
        from migration.export import export_state
        manifest = export_state(
            payload.out_path, reader=reader, signer=signer,
            bundle_id=payload.bundle_id, source_hub_id=payload.source_hub_id,
            notes=payload.notes,
        )
    except Exception as exc:  # noqa: BLE001
        return _error("export_failed", str(exc))

    audit_id = _audit_write(
        action="migration_export", project_id=payload.project_id,
        actor=payload.actor, subject_id=payload.bundle_id,
        metadata={
            "out_path": payload.out_path,
            "schema_slices": len(manifest.schemas),
            "aux_files": len(manifest.auxiliary_files),
            "signing_fp": manifest.signing_key_fingerprint,
        },
    )
    return ToolResponse(
        status="ok", audit_id=audit_id,
        data={
            "bundle_id": manifest.bundle_id,
            "spine_version": manifest.spine_version,
            "generated_at": manifest.generated_at,
            "schemas": [s.schema for s in manifest.schemas],
            "schema_row_counts": {s.schema: s.row_count for s in manifest.schemas},
            "signing_key_fingerprint": manifest.signing_key_fingerprint,
        },
    )


# ---------------------------------------------------------------------------
# migration_import  —  requires_citation per #12
# ---------------------------------------------------------------------------


class MigrationImportInput(BaseModel):
    model_config = _FORBID
    project_id: str = Field(..., min_length=1)
    actor: str = Field(default="operator", min_length=1)
    in_path: str = Field(..., min_length=1)
    dry_run: bool = Field(default=False)
    notes: str = Field(default="")


@register_tool(
    name="migration_import",
    input_model=MigrationImportInput,
    story="STORY-33.B.2",
    description="Verify + UPSERT a signed Spine state tarball into the live Hub.",
    tags=("migration", "portability", "verify"),
    requires_citation=True,  # per V3 #12 — destructive op
)
def migration_import(payload: MigrationImportInput) -> ToolResponse:
    """Run :func:`migration.import_.import_state` against the live Hub stores.

    Cite-or-Refuse: the response carries an ``audit_hash`` citation for
    the audit row + a ``file_line`` citation for the verified manifest.
    """
    _log("migration_import", payload.project_id, payload.actor)

    verifier, writer = _get_runtime_import()
    if verifier is None or writer is None:
        audit_id = _audit_write(
            action="migration_import", project_id=payload.project_id,
            actor=payload.actor, subject_id=payload.in_path,
            metadata={"stub": True, "reason": "no runtime verifier/writer"},
        )
        # Even when stubbed, satisfy Cite-or-Refuse with a single audit_hash citation.
        return ToolResponse(
            status="stub_implementation",
            data={"reason": "runtime not bootstrapped"},
            audit_id=audit_id,
            citation=[Citation(
                type="audit_hash", ref=str(audit_id),
                excerpt="stub run; no destructive write occurred",
            )],
        )

    try:
        from migration.import_ import ImportError as MIE, import_state
        report = import_state(
            payload.in_path, verifier=verifier, writer=writer,
            dry_run=payload.dry_run, notes=payload.notes,
        )
    except MIE as exc:
        audit_id = _audit_write(
            action="migration_import", project_id=payload.project_id,
            actor=payload.actor, subject_id=payload.in_path,
            metadata={"error_code": exc.code, "dry_run": payload.dry_run},
        )
        # Still cite — refusal is itself audited (per #12).
        return ToolResponse(
            status="error", audit_id=audit_id,
            error=ToolError(code=exc.code, message=str(exc), retryable=False),
            citation=[Citation(
                type="audit_hash", ref=str(audit_id),
                excerpt=f"import refused: {exc.code}",
            )],
        )

    audit_id = _audit_write(
        action="migration_import", project_id=payload.project_id,
        actor=payload.actor, subject_id=report.bundle_id,
        metadata={
            "all_ok": report.all_ok(),
            "dry_run": report.dry_run,
            "source_spine_version": report.source_spine_version,
            "schema_row_counts": report.schema_row_counts,
            "audit_chain_ok": report.audit_chain_ok,
        },
    )
    citations = [
        Citation(
            type="audit_hash", ref=str(audit_id),
            excerpt=f"import {report.bundle_id} all_ok={report.all_ok()}",
        ),
        Citation(
            type="file_line", ref=f"{payload.in_path}:MANIFEST.json",
            excerpt=f"source spine_version={report.source_spine_version}",
        ),
    ]
    return ToolResponse(
        status="ok", audit_id=audit_id,
        data={
            "bundle_id": report.bundle_id,
            "source_spine_version": report.source_spine_version,
            "dest_spine_version": report.dest_spine_version,
            "signature_ok": report.signature_ok,
            "fingerprint_ok": report.fingerprint_ok,
            "schema_row_counts": report.schema_row_counts,
            "schema_hash_ok": report.schema_hash_ok,
            "audit_chain_ok": report.audit_chain_ok,
            "vault_paths_registered": report.vault_paths_registered,
            "role_charters_written": report.role_charters_written,
            "dry_run": report.dry_run,
            "all_ok": report.all_ok(),
        },
        citation=citations,
    )


# ---------------------------------------------------------------------------
# migration_onboarding_dispatch
# ---------------------------------------------------------------------------


class _ConnectorSpec(BaseModel):
    model_config = _FORBID
    kind: str = Field(..., description="'github' or 'linear'.")
    org_or_workspace: str = Field(..., min_length=1)
    repo_filter: Optional[list[str]] = None
    team_keys: Optional[list[str]] = None


class MigrationOnboardingDispatchInput(BaseModel):
    model_config = _FORBID
    project_id: str = Field(..., min_length=1)
    actor: str = Field(default="operator", min_length=1)
    connectors: list[_ConnectorSpec] = Field(..., min_length=1)


@register_tool(
    name="migration_onboarding_dispatch",
    input_model=MigrationOnboardingDispatchInput,
    story="STORY-33.A.1",
    description="Run the configured onboarding connectors (GitHub + Linear in v1.0).",
    tags=("migration", "onboarding"),
)
def migration_onboarding_dispatch(
    payload: MigrationOnboardingDispatchInput,
) -> ToolResponse:
    """Walk every spec, build a connector, and dispatch via the runtime sink."""
    _log("migration_onboarding_dispatch", payload.project_id, payload.actor)

    http, sink = _get_runtime_onboarding()
    if http is None or sink is None:
        audit_id = _audit_write(
            action="migration_onboarding_dispatch", project_id=payload.project_id,
            actor=payload.actor, subject_id="dispatch",
            metadata={"stub": True, "connector_count": len(payload.connectors)},
        )
        return ToolResponse(
            status="stub_implementation",
            data={"reason": "runtime not bootstrapped"},
            audit_id=audit_id,
        )

    from migration.onboarding import (
        GitHubConnector,
        LinearConnector,
        OnboardingDispatcher,
    )
    built: list[Any] = []
    for spec in payload.connectors:
        if spec.kind == "github":
            built.append(GitHubConnector(
                http=http, org=spec.org_or_workspace,
                repo_filter=tuple(spec.repo_filter) if spec.repo_filter else None,
            ))
        elif spec.kind == "linear":
            built.append(LinearConnector(
                http=http, workspace=spec.org_or_workspace,
                team_keys=tuple(spec.team_keys) if spec.team_keys else None,
            ))
        else:
            return _error(
                "unknown_connector_kind",
                f"connector kind {spec.kind!r} not supported in v1.0; v1.1 will add "
                "{jira, confluence, notion, asana, gitlab}.",
            )

    dispatcher = OnboardingDispatcher(connectors=built, sink=sink)
    report = dispatcher.run()
    audit_id = _audit_write(
        action="migration_onboarding_dispatch", project_id=payload.project_id,
        actor=payload.actor, subject_id="dispatch",
        metadata={
            "connector_count": len(payload.connectors),
            "total_work_items": report.total_work_items,
            "total_written": report.total_written,
            "errors": report.errors[:8],
        },
    )
    return ToolResponse(
        status="ok", audit_id=audit_id,
        data={
            "started_at": report.started_at,
            "finished_at": report.finished_at,
            "total_work_items": report.total_work_items,
            "total_written": report.total_written,
            "per_connector": [
                {
                    "connector": p.connector,
                    "repos": p.repos,
                    "issues": p.issues,
                    "comments": p.comments,
                    "work_items_mapped": p.work_items_mapped,
                    "errors": p.errors,
                }
                for p in report.per_connector
            ],
            "errors": report.errors,
        },
    )


# ---------------------------------------------------------------------------
# migration_version_upgrade  —  requires_citation per #12
# ---------------------------------------------------------------------------


class MigrationVersionUpgradeInput(BaseModel):
    model_config = _FORBID
    project_id: str = Field(..., min_length=1)
    actor: str = Field(default="operator", min_length=1)
    from_version: str = Field(..., min_length=1)
    to_version: str = Field(..., min_length=1)
    dry_run: bool = Field(default=False)
    approved_by: str = Field(..., min_length=1,
        description="Identifier of the customer admin who approved this upgrade "
                    "via the Hub decision-card flow. Per #16, no auto-push.")


@register_tool(
    name="migration_version_upgrade",
    input_model=MigrationVersionUpgradeInput,
    story="STORY-33.D.1",
    description="Plan + execute a Spine version upgrade (downgrade blocked; N-2 enforced).",
    tags=("migration", "spine_version", "verify"),
    requires_citation=True,  # per V3 #12 — destructive op
)
def migration_version_upgrade(
    payload: MigrationVersionUpgradeInput,
) -> ToolResponse:
    """Run :func:`migration.spine_version.upgrade` end-to-end.

    Cite-or-Refuse: every response carries an ``audit_hash`` citation +
    a ``file_line`` citation pointing at the upgrade-plan owner module
    so reviewers can trace which subsystems were touched.
    """
    _log("migration_version_upgrade", payload.project_id, payload.actor)

    from migration.spine_version import (
        DowngradeBlocked,
        UnsupportedUpgradePath,
        upgrade,
    )
    executor = _get_runtime_upgrade_executor()  # may be None -> StubExecutor

    # Per #16, the approval is recorded inside the audit envelope so the
    # decision-card trace is preserved. The gate function below is a
    # closure that returns True iff approved_by is non-empty; the real
    # decision-card flow happens upstream in the Hub UI.
    def _approve(_plan):  # type: ignore[no-redef]
        return bool(payload.approved_by)

    try:
        report = upgrade(
            from_version=payload.from_version,
            to_version=payload.to_version,
            executor=executor,
            approve=_approve,
            dry_run=payload.dry_run,
        )
    except DowngradeBlocked as exc:
        audit_id = _audit_write(
            action="migration_version_upgrade", project_id=payload.project_id,
            actor=payload.actor, subject_id=f"{payload.from_version}->{payload.to_version}",
            metadata={"refused": "downgrade_blocked", "approved_by": payload.approved_by},
        )
        return ToolResponse(
            status="error", audit_id=audit_id,
            error=ToolError(code="downgrade_blocked", message=str(exc), retryable=False),
            citation=[Citation(
                type="audit_hash", ref=str(audit_id),
                excerpt="downgrade refused per #33 D policy",
            )],
        )
    except UnsupportedUpgradePath as exc:
        audit_id = _audit_write(
            action="migration_version_upgrade", project_id=payload.project_id,
            actor=payload.actor, subject_id=f"{payload.from_version}->{payload.to_version}",
            metadata={"refused": "unsupported_path", "approved_by": payload.approved_by},
        )
        return ToolResponse(
            status="error", audit_id=audit_id,
            error=ToolError(code="unsupported_path", message=str(exc), retryable=False),
            citation=[Citation(
                type="audit_hash", ref=str(audit_id),
                excerpt="upgrade path unsupported per N-2 policy",
            )],
        )
    except PermissionError as exc:
        audit_id = _audit_write(
            action="migration_version_upgrade", project_id=payload.project_id,
            actor=payload.actor, subject_id=f"{payload.from_version}->{payload.to_version}",
            metadata={"refused": "approval_missing"},
        )
        return ToolResponse(
            status="error", audit_id=audit_id,
            error=ToolError(code="approval_missing", message=str(exc), retryable=True),
            citation=[Citation(
                type="audit_hash", ref=str(audit_id),
                excerpt="no customer-admin approval recorded (#16)",
            )],
        )

    audit_id = _audit_write(
        action="migration_version_upgrade", project_id=payload.project_id,
        actor=payload.actor, subject_id=f"{payload.from_version}->{payload.to_version}",
        metadata={
            "all_ok": report.all_ok,
            "dry_run": payload.dry_run,
            "step_count": len(report.plan.steps),
            "intermediate_stops": report.plan.intermediate_stops,
            "approved_by": payload.approved_by,
        },
    )
    citations = [
        Citation(
            type="audit_hash", ref=str(audit_id),
            excerpt=f"upgrade {payload.from_version}->{payload.to_version} "
                    f"all_ok={report.all_ok}",
        ),
        Citation(
            type="file_line",
            ref="migration/version_registry.py:SUBSYSTEM_VERSIONS",
            excerpt="subsystem registry pinned at this Spine release",
        ),
    ]
    return ToolResponse(
        status="ok", audit_id=audit_id,
        data={
            "from_version": payload.from_version,
            "to_version": payload.to_version,
            "intermediate_stops": report.plan.intermediate_stops,
            "step_count": len(report.plan.steps),
            "all_ok": report.all_ok,
            "dry_run": payload.dry_run,
            "started_at": report.started_at,
            "finished_at": report.finished_at,
            "outcomes": [
                {"handler": s.handler_id, "status": st, "message": msg}
                for (s, st, msg) in report.step_outcomes
            ],
        },
        citation=citations,
    )


# ---------------------------------------------------------------------------
# Runtime injection — Hub bootstrap calls set_runtime(...) once at startup
# ---------------------------------------------------------------------------


_RUNTIME_EXPORT_READER: Any = None
_RUNTIME_EXPORT_SIGNER: Any = None
_RUNTIME_IMPORT_VERIFIER: Any = None
_RUNTIME_IMPORT_WRITER: Any = None
_RUNTIME_ONBOARD_HTTP: Any = None
_RUNTIME_ONBOARD_SINK: Any = None
_RUNTIME_UPGRADE_EXECUTOR: Any = None


def set_runtime(
    *,
    export_reader: Any = None,
    export_signer: Any = None,
    import_verifier: Any = None,
    import_writer: Any = None,
    onboarding_http: Any = None,
    onboarding_sink: Any = None,
    upgrade_executor: Any = None,
) -> None:
    """Install runtime dependencies for the migration MCP tools.

    Called once during Hub bootstrap. Tests call this with mocks before
    invoking the tools; passing ``None`` for any arg leaves the previous
    value in place (so test fixtures can compose).
    """
    global _RUNTIME_EXPORT_READER, _RUNTIME_EXPORT_SIGNER
    global _RUNTIME_IMPORT_VERIFIER, _RUNTIME_IMPORT_WRITER
    global _RUNTIME_ONBOARD_HTTP, _RUNTIME_ONBOARD_SINK
    global _RUNTIME_UPGRADE_EXECUTOR
    if export_reader is not None:
        _RUNTIME_EXPORT_READER = export_reader
    if export_signer is not None:
        _RUNTIME_EXPORT_SIGNER = export_signer
    if import_verifier is not None:
        _RUNTIME_IMPORT_VERIFIER = import_verifier
    if import_writer is not None:
        _RUNTIME_IMPORT_WRITER = import_writer
    if onboarding_http is not None:
        _RUNTIME_ONBOARD_HTTP = onboarding_http
    if onboarding_sink is not None:
        _RUNTIME_ONBOARD_SINK = onboarding_sink
    if upgrade_executor is not None:
        _RUNTIME_UPGRADE_EXECUTOR = upgrade_executor


def clear_runtime() -> None:
    """Reset every runtime slot to ``None`` (test cleanup hook)."""
    global _RUNTIME_EXPORT_READER, _RUNTIME_EXPORT_SIGNER
    global _RUNTIME_IMPORT_VERIFIER, _RUNTIME_IMPORT_WRITER
    global _RUNTIME_ONBOARD_HTTP, _RUNTIME_ONBOARD_SINK
    global _RUNTIME_UPGRADE_EXECUTOR
    _RUNTIME_EXPORT_READER = None
    _RUNTIME_EXPORT_SIGNER = None
    _RUNTIME_IMPORT_VERIFIER = None
    _RUNTIME_IMPORT_WRITER = None
    _RUNTIME_ONBOARD_HTTP = None
    _RUNTIME_ONBOARD_SINK = None
    _RUNTIME_UPGRADE_EXECUTOR = None


def _get_runtime_export() -> tuple[Any, Any]:
    return _RUNTIME_EXPORT_READER, _RUNTIME_EXPORT_SIGNER


def _get_runtime_import() -> tuple[Any, Any]:
    return _RUNTIME_IMPORT_VERIFIER, _RUNTIME_IMPORT_WRITER


def _get_runtime_onboarding() -> tuple[Any, Any]:
    return _RUNTIME_ONBOARD_HTTP, _RUNTIME_ONBOARD_SINK


def _get_runtime_upgrade_executor() -> Any:
    return _RUNTIME_UPGRADE_EXECUTOR


__all__ = [
    "MigrationExportInput",
    "MigrationImportInput",
    "MigrationOnboardingDispatchInput",
    "MigrationVersionUpgradeInput",
    "clear_runtime",
    "migration_export",
    "migration_import",
    "migration_onboarding_dispatch",
    "migration_version_upgrade",
    "set_runtime",
]
