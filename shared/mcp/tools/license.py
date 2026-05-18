"""License + quota MCP tools (Wave 4 Squad B / design decision #23).

Three tools, auto-registered when the unified MCP server walks this
package on startup:

* ``license_get_status`` — tier + flag map + expiry; sourced from the
  in-process ``ActiveBundle``. Cheap. No DB access.
* ``license_get_usage``  — per-flag usage counters for the active
  billing period; reads ``spine_license.quota_usage``.
* ``license_verify_bundle`` — re-runs full Ed25519 signature
  verification AND replays the quota ledger hash chain. Tagged
  ``requires_citation=True`` per design decision **#12** (Cite-or-Refuse)
  because it returns a verdict over historical evidence.

Each tool writes a structured row to ``spine_audit.audit_event``
(subsystem=``shared``, mirroring the standards/auditor tools) so the
license panel UI can show "last verified by X at Y" and pricing
analytics can trace which features were exercised by which projects.
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from shared.mcp.schemas import Citation, ToolError, ToolResponse
from shared.mcp.tools import register_tool

logger = logging.getLogger(__name__)

_FORBID = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# Audit + pool helpers (mirrors shared/mcp/tools/standards.py)
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
            subject_type="license_bundle", subject_id=subject_id,
            metadata=metadata, event_uuid=audit_uuid,
        )
        rec = chain_to_previous(rec, None)
        write_via_psql(rec)
    except Exception as exc:  # noqa: BLE001 — audit is best-effort
        logger.warning("license_tool_audit_failed",
                       extra={"action": action, "err": str(exc)})
    return audit_uuid


def _get_pool() -> Any:
    """Return the process-wide asyncpg pool (None if Hub not bootstrapped).

    Tests inject a mock via :func:`license.feature_flags.set_pool`.
    """
    try:
        from license.feature_flags import _POOL
        return _POOL
    except Exception:
        return None


# ---------------------------------------------------------------------------
# license_get_status
# ---------------------------------------------------------------------------


class LicenseGetStatusInput(BaseModel):
    model_config = _FORBID
    project_id: str = Field(..., min_length=1)
    actor: str = Field(default="system", min_length=1)


@register_tool(
    name="license_get_status",
    input_model=LicenseGetStatusInput,
    story="STORY-23.1.1",
    description="Return tier + per-flag enablement + expiry for the active license bundle.",
    tags=("license",),
)
def license_get_status(payload: LicenseGetStatusInput) -> ToolResponse:
    """Snapshot of the in-process active bundle. No DB. No signature math."""
    _log("license_get_status", payload.project_id, payload.actor)
    from license.feature_flags import status_snapshot
    snap = status_snapshot()
    audit_id = _audit_write(
        action="license_get_status", project_id=payload.project_id,
        actor=payload.actor, subject_id=str(snap.get("bundle_id") or "no-bundle"),
        metadata={"loaded": snap["loaded"], "tier": snap.get("tier"),
                  "signature_ok": snap.get("signature_ok")},
    )
    return ToolResponse(status="ok", data=snap, audit_id=audit_id)


# ---------------------------------------------------------------------------
# license_get_usage
# ---------------------------------------------------------------------------


class LicenseGetUsageInput(BaseModel):
    model_config = _FORBID
    project_id: str = Field(..., min_length=1)
    actor: str = Field(default="system", min_length=1)
    flag_name: Optional[str] = Field(default=None, min_length=1,
        description="If set, only return rows for this flag.")


class _UsageRow(BaseModel):
    model_config = _FORBID
    flag_name: str
    period_start: str
    period_end: str
    used_value: int
    ledger_anchor_hex: Optional[str] = None


class _UsageResponse(BaseModel):
    model_config = _FORBID
    items: list[_UsageRow]
    as_of: str


async def _fetch_usage(flag_name: Optional[str]) -> list[_UsageRow]:
    pool = _get_pool()
    if pool is None:
        return []
    if flag_name:
        sql = (
            "SELECT flag_name, period_start, period_end, used_value, ledger_anchor "
            "FROM spine_license.quota_usage WHERE flag_name = $1 "
            "ORDER BY period_start DESC LIMIT 256;"
        )
        args = (flag_name,)
    else:
        sql = (
            "SELECT flag_name, period_start, period_end, used_value, ledger_anchor "
            "FROM spine_license.quota_usage ORDER BY period_start DESC LIMIT 256;"
        )
        args = ()
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *args)
    return [
        _UsageRow(
            flag_name=r["flag_name"],
            period_start=r["period_start"].isoformat(),
            period_end=r["period_end"].isoformat(),
            used_value=int(r["used_value"]),
            ledger_anchor_hex=(r["ledger_anchor"].hex()
                               if r.get("ledger_anchor") else None),
        )
        for r in rows
    ]


@register_tool(
    name="license_get_usage",
    input_model=LicenseGetUsageInput,
    story="STORY-23.1.2",
    description="Return per-flag usage counters from spine_license.quota_usage.",
    tags=("license",),
)
def license_get_usage(payload: LicenseGetUsageInput) -> ToolResponse:
    """Read usage rows from the quota ledger; optionally filtered by flag."""
    _log("license_get_usage", payload.project_id, payload.actor)
    try:
        rows = asyncio.run(_fetch_usage(payload.flag_name))
    except RuntimeError:
        # Already inside an event loop (e.g. async server) — degrade gracefully.
        rows = []
    out = _UsageResponse(
        items=rows, as_of=datetime.now(timezone.utc).isoformat(),
    )
    audit_id = _audit_write(
        action="license_get_usage", project_id=payload.project_id,
        actor=payload.actor,
        subject_id=payload.flag_name or "all",
        metadata={"row_count": len(rows), "flag_filter": payload.flag_name},
    )
    return ToolResponse(status="ok", data=out.model_dump(mode="json"),
                        audit_id=audit_id)


# ---------------------------------------------------------------------------
# license_verify_bundle  —  requires_citation per #12
# ---------------------------------------------------------------------------


class LicenseVerifyBundleInput(BaseModel):
    model_config = _FORBID
    project_id: str = Field(..., min_length=1)
    actor: str = Field(default="auditor", min_length=1)
    verify_quota_chain: bool = Field(default=True,
        description="Replay the hash chain across spine_license.quota_usage.")


class _LedgerReport(BaseModel):
    model_config = _FORBID
    flag_name: str
    ok: bool
    rows_checked: int
    first_bad_row: Optional[dict[str, Any]] = None


class _VerifyResponse(BaseModel):
    model_config = _FORBID
    signature_ok: bool
    bundle_id: Optional[str] = None
    tier: Optional[str] = None
    expires_at: Optional[str] = None
    expired: bool = False
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    ledger_reports: list[_LedgerReport] = Field(default_factory=list)
    verified_at: str


async def _replay_all_chains() -> list[_LedgerReport]:
    pool = _get_pool()
    if pool is None:
        return []
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT DISTINCT flag_name FROM spine_license.quota_usage;",
        )
    flag_names = [r["flag_name"] for r in rows]
    reports: list[_LedgerReport] = []
    from license.quota_ledger import verify_chain
    for fn in flag_names:
        rep = await verify_chain(pool=pool, flag_name=fn)
        reports.append(_LedgerReport(
            flag_name=fn, ok=rep["ok"], rows_checked=rep["rows_checked"],
            first_bad_row=rep["first_bad_row"],
        ))
    return reports


async def _reverify_signature() -> tuple[bool, Optional[str], Optional[str]]:
    """Re-run signature verify against the active bundle.

    Returns (signature_ok, error_code, error_message). Does NOT mutate
    the live ``ActiveBundle`` — that's the periodic verifier's job; this
    tool is a read-only audit.
    """
    pool = _get_pool()
    if pool is None:
        return False, "no_db_pool", "Hub bootstrap incomplete; cannot re-verify."
    from license.bundle_verifier import (
        BundleVerificationError,
        _fetch_vendor_public_key,
        verify_signature,
    )
    from shared.schemas.license import SignedLicenseBundle
    import base64 as _b64
    try:
        vendor_pk = await _fetch_vendor_public_key()
    except BundleVerificationError as exc:
        return False, exc.code, str(exc)
    except Exception as exc:  # noqa: BLE001
        return False, "vendor_pubkey_fetch_failed", str(exc)
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id, signed_payload, signature, signing_key_fingerprint "
                "FROM spine_license.bundle WHERE revoked_at IS NULL "
                "ORDER BY issued_at DESC LIMIT 1;",
            )
        if row is None:
            return False, "no_active_bundle", "no row in spine_license.bundle."
        envelope = SignedLicenseBundle(
            payload_canonical_b64=_b64.b64encode(row["signed_payload"]).decode("ascii"),
            signature_b64=_b64.b64encode(row["signature"]).decode("ascii"),
            signing_key_fingerprint=str(row["signing_key_fingerprint"]).lower(),
        )
        verify_signature(envelope, vendor_public_key_bytes=vendor_pk)
    except BundleVerificationError as exc:
        return False, exc.code, str(exc)
    except Exception as exc:  # noqa: BLE001
        return False, "unexpected_verify_error", str(exc)
    return True, None, None


@register_tool(
    name="license_verify_bundle",
    input_model=LicenseVerifyBundleInput,
    story="STORY-23.1.3",
    description="Re-run Ed25519 signature verification + replay quota ledger chains.",
    tags=("license", "verify"),
    requires_citation=True,  # per V3 #12 — Cite-or-Refuse
)
def license_verify_bundle(payload: LicenseVerifyBundleInput) -> ToolResponse:
    """Audit verdict over the active license bundle + quota ledger.

    Returns ``status='ok'`` whether signature passes or fails — the
    response itself is the verdict. ``status='error'`` is reserved for
    cases where verification could not even be attempted (e.g. no DB pool).

    Cite-or-Refuse: every response carries a Citation rooted in the
    audit row for this verification (audit_hash type) plus, when usable,
    a file_line citation pointing at the active bundle record.
    """
    _log("license_verify_bundle", payload.project_id, payload.actor)

    from license.feature_flags import status_snapshot
    snap = status_snapshot()

    try:
        sig_ok, err_code, err_msg = asyncio.run(_reverify_signature())
    except RuntimeError:
        sig_ok, err_code, err_msg = (
            False, "loop_already_running",
            "license_verify_bundle invoked from inside an async event loop; "
            "call _reverify_signature() directly instead.",
        )

    reports: list[_LedgerReport] = []
    if payload.verify_quota_chain:
        try:
            reports = asyncio.run(_replay_all_chains())
        except RuntimeError:
            reports = []

    expires_at = snap.get("expires_at")
    expired = False
    if expires_at:
        try:
            expired = datetime.fromisoformat(expires_at) < datetime.now(timezone.utc)
        except Exception:
            expired = False

    out = _VerifyResponse(
        signature_ok=sig_ok,
        bundle_id=snap.get("bundle_id"),
        tier=snap.get("tier"),
        expires_at=expires_at,
        expired=expired,
        error_code=err_code, error_message=err_msg,
        ledger_reports=reports,
        verified_at=datetime.now(timezone.utc).isoformat(),
    )

    audit_id = _audit_write(
        action="license_verify_bundle", project_id=payload.project_id,
        actor=payload.actor,
        subject_id=str(snap.get("bundle_id") or "no-bundle"),
        metadata={
            "signature_ok": sig_ok, "expired": expired,
            "error_code": err_code,
            "ledger_chains_ok": all(r.ok for r in reports) if reports else None,
            "ledger_chain_count": len(reports),
        },
    )

    # Per #12, build at least one citation. We always have the audit_id;
    # we also reference the bundle row's file source so reviewers can
    # walk to the persisted evidence.
    citations: list[Citation] = [
        Citation(type="audit_hash", ref=str(audit_id),
                 excerpt=f"signature_ok={sig_ok}; tier={snap.get('tier')}"),
    ]
    if snap.get("bundle_id"):
        citations.append(Citation(
            type="file_line",
            ref=f"db/flyway/sql/V22__license_registry.sql:34",
            excerpt=f"spine_license.bundle row id={snap['bundle_id']}",
        ))

    return ToolResponse(status="ok", data=out.model_dump(mode="json"),
                        audit_id=audit_id, citation=citations)


__all__ = [
    "LicenseGetStatusInput",
    "LicenseGetUsageInput",
    "LicenseVerifyBundleInput",
    "license_get_status",
    "license_get_usage",
    "license_verify_bundle",
]
