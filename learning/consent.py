"""Cross-org opt-in consent registry — Wave 4 Squad D / V3 #27.

Persists customer admin consent decisions into
``spine_learning.scope_policy`` (V29). Cross-org consent is **default
OFF** (#27); this module is the only sanctioned path that flips it on.
Granular per-category consent (e.g. only ``calibration_outcomes`` but
not ``role_success_rates``) is supported via the
``granular_consent_jsonb`` column.

Public surface
--------------

    grant_cross_org_consent(record, *, db_url=None, writer=None)
        Upsert a consent row; ``record.granular`` is merged with whatever
        is already in the DB so granting one category does not clobber
        another.

    revoke_cross_org_consent(hub_id, project_id, *, category=None, ...)
        Either revoke a single category (granular[category]=False) or
        revoke everything (cross_org_consent=False AND granular={}).

    list_cross_org_consents(hub_id=None, *, reader=None)
        Read-only enumerator for Hub UI / audit purposes.

All write paths also emit an audit row tagged ``learning_consent_*``
(best-effort — failures don't block the write) so the consent decision
itself is part of the audit chain.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from .scope import KNOWN_DATA_CATEGORIES, ScopePolicy

logger = logging.getLogger(__name__)

DEFAULT_DB_URL = "postgresql://spine:spine@localhost:33000/spine"


@dataclass(frozen=True)
class ConsentRecord:
    """Inbound payload for :func:`grant_cross_org_consent`."""
    hub_id: Optional[str]
    project_id: Optional[str] = None
    cross_org_consent: bool = True
    # category -> bool. ``True`` opts in to that category; ``False``
    # explicitly opts OUT even if cross_org_consent is True.
    granular: dict[str, bool] = field(default_factory=dict)
    granted_by: str = "admin"
    rationale: str = ""

    def validate(self) -> None:
        if not self.hub_id and not self.project_id:
            raise ValueError("ConsentRecord must scope to at least hub_id or project_id")
        # Unknown categories are tolerated but logged — the spec
        # explicitly anticipates future categories beyond the 3 named.
        for cat in self.granular:
            if cat not in KNOWN_DATA_CATEGORIES:
                logger.info("consent: non-canonical data_category=%s", cat)


@dataclass(frozen=True)
class ConsentDecision:
    """Result of a grant or revoke."""
    hub_id: Optional[str]
    project_id: Optional[str]
    operation: str  # 'grant' | 'revoke' | 'revoke_category'
    effective_policy: ScopePolicy
    actor: str
    decided_at: datetime


# ─── Writer + reader signatures ─────────────────────────────────────


ConsentWriter = Callable[[ConsentRecord, dict[str, Any]], ScopePolicy]
"""(record, extras) -> effective ScopePolicy after upsert."""

ConsentReader = Callable[[Optional[str], dict[str, Any]], list[ScopePolicy]]
"""(hub_id, extras) -> list of ScopePolicy snapshots."""


# ─── DB helpers ──────────────────────────────────────────────────────


def _q(v: object) -> str:
    return "NULL" if v is None else "'" + str(v).replace("'", "''") + "'"


def _psql(sql: str, db_url: str) -> str:
    r = subprocess.run(
        ["psql", db_url, "-At", "-F", "\x1f", "-v", "ON_ERROR_STOP=1", "-c", sql],
        capture_output=True, text=True, timeout=30,
    )
    if r.returncode != 0:
        raise RuntimeError(f"psql failed: {r.stderr.strip()}")
    return r.stdout


def _resolve_db_url(extras: dict[str, Any]) -> str:
    return (
        extras.get("db_url")
        or os.environ.get("SPINE_DB_URL")
        or os.environ.get("DATABASE_URL")
        or DEFAULT_DB_URL
    )


def _merge_granular(
    existing: dict[str, bool], incoming: dict[str, bool],
) -> dict[str, bool]:
    """Last-write-wins per key; never silently drops existing keys."""
    out = dict(existing)
    for k, v in incoming.items():
        out[str(k)] = bool(v)
    return out


# ─── Default writer ─────────────────────────────────────────────────


def _default_writer(record: ConsentRecord, extras: dict[str, Any]) -> ScopePolicy:
    """Upsert ``spine_learning.scope_policy``; merge granular consent."""
    db_url = _resolve_db_url(extras)
    # Load existing row (if any) for merge.
    hub_sql = (
        "hub_id IS NULL" if record.hub_id is None
        else f"hub_id = {_q(record.hub_id)}::uuid"
    )
    proj_sql = (
        "project_id IS NULL" if record.project_id is None
        else f"project_id = {_q(record.project_id)}::uuid"
    )
    sel = (
        "SELECT COALESCE(granular_consent_jsonb::text, '{}') "
        f"FROM spine_learning.scope_policy WHERE {hub_sql} AND {proj_sql} LIMIT 1;"
    )
    out = _psql(sel, db_url).strip()
    existing_g: dict[str, bool] = {}
    if out:
        try:
            existing_g = {str(k): bool(v) for k, v in json.loads(out).items()}
        except (ValueError, TypeError):
            existing_g = {}
    merged = _merge_granular(existing_g, record.granular)
    merged_json = json.dumps(merged, sort_keys=True)
    hub_val = "NULL::uuid" if record.hub_id is None else f"{_q(record.hub_id)}::uuid"
    proj_val = "NULL::uuid" if record.project_id is None else f"{_q(record.project_id)}::uuid"
    upsert = (
        "INSERT INTO spine_learning.scope_policy "
        "(hub_id, project_id, within_hub_enabled, cross_org_consent, granular_consent_jsonb) "
        f"VALUES ({hub_val}, {proj_val}, true, {str(bool(record.cross_org_consent)).lower()}, "
        f"{_q(merged_json)}::jsonb) "
        "ON CONFLICT (hub_id, project_id) DO UPDATE "
        "SET cross_org_consent = EXCLUDED.cross_org_consent, "
        "    granular_consent_jsonb = EXCLUDED.granular_consent_jsonb, "
        "    updated_at = now();"
    )
    _psql(upsert, db_url)
    return ScopePolicy(
        hub_id=record.hub_id,
        project_id=record.project_id,
        within_hub_enabled=True,
        cross_org_consent=bool(record.cross_org_consent),
        granular_consent=merged,
    )


def _default_reader(hub_id: Optional[str], extras: dict[str, Any]) -> list[ScopePolicy]:
    db_url = _resolve_db_url(extras)
    where = "" if hub_id is None else f"WHERE hub_id = {_q(hub_id)}::uuid"
    sql = (
        "SELECT hub_id::text, project_id::text, within_hub_enabled, "
        "cross_org_consent, COALESCE(granular_consent_jsonb::text, '{}') "
        f"FROM spine_learning.scope_policy {where};"
    )
    out = _psql(sql, db_url)
    policies: list[ScopePolicy] = []
    for line in out.splitlines():
        if not line:
            continue
        parts = line.split("\x1f")
        if len(parts) < 5:
            continue
        hub_v, proj_v, within, cross, gj = parts[0], parts[1], parts[2], parts[3], parts[4]
        try:
            g = {str(k): bool(v) for k, v in json.loads(gj or "{}").items()}
        except (ValueError, TypeError):
            g = {}
        policies.append(ScopePolicy(
            hub_id=hub_v or None,
            project_id=proj_v or None,
            within_hub_enabled=(within.lower() in ("t", "true")),
            cross_org_consent=(cross.lower() in ("t", "true")),
            granular_consent=g,
        ))
    return policies


# ─── Audit emit (best-effort) ───────────────────────────────────────


def _emit_audit(
    *, action: str, record: ConsentRecord,
    effective: ScopePolicy, actor: str,
) -> None:
    try:
        from shared.audit.audit_record import (  # type: ignore
            AuditRecord, chain_to_previous, write_via_psql,
        )
        meta = {
            "hub_id": record.hub_id,
            "project_id": record.project_id,
            "cross_org_consent": effective.cross_org_consent,
            "granular": effective.granular_consent,
            "rationale": record.rationale,
        }
        rec = AuditRecord(
            role=actor, subsystem="learning", action=action, actor=actor,
            subject_type="scope_policy",
            subject_id=str(record.hub_id or record.project_id or "global"),
            metadata=meta,
        )
        rec = chain_to_previous(rec, None)
        write_via_psql(rec)
    except Exception as exc:  # noqa: BLE001 — audit is best-effort
        logger.info("consent_audit_failed action=%s err=%s", action, exc)


# ─── Public API ─────────────────────────────────────────────────────


def grant_cross_org_consent(
    record: ConsentRecord,
    *,
    writer: Optional[ConsentWriter] = None,
    writer_extras: Optional[dict[str, Any]] = None,
) -> ConsentDecision:
    """Persist a cross-org learning consent grant.

    This is the ONLY sanctioned path to flip ``cross_org_consent=True``;
    the underlying V29 default is False per #27.
    """
    record.validate()
    extras = dict(writer_extras or {})
    w = writer or _default_writer
    effective = w(record, extras)
    _emit_audit(
        action="learning_consent_grant", record=record,
        effective=effective, actor=record.granted_by,
    )
    return ConsentDecision(
        hub_id=record.hub_id,
        project_id=record.project_id,
        operation="grant",
        effective_policy=effective,
        actor=record.granted_by,
        decided_at=datetime.now(timezone.utc),
    )


def revoke_cross_org_consent(
    hub_id: Optional[str],
    project_id: Optional[str] = None,
    *,
    category: Optional[str] = None,
    actor: str = "admin",
    rationale: str = "",
    writer: Optional[ConsentWriter] = None,
    writer_extras: Optional[dict[str, Any]] = None,
) -> ConsentDecision:
    """Revoke consent. ``category=None`` revokes everything for the scope.

    If a category is named, only that category's granular flag flips to
    False; the umbrella ``cross_org_consent`` stays as-is so other
    categories keep their existing per-category state.
    """
    if category is None:
        # Full revoke: wipe both umbrella and granular.
        rec = ConsentRecord(
            hub_id=hub_id, project_id=project_id,
            cross_org_consent=False,
            granular={cat: False for cat in KNOWN_DATA_CATEGORIES},
            granted_by=actor, rationale=rationale,
        )
        op = "revoke"
    else:
        rec = ConsentRecord(
            hub_id=hub_id, project_id=project_id,
            cross_org_consent=True,  # keep umbrella; granular wins anyway
            granular={category: False},
            granted_by=actor, rationale=rationale,
        )
        op = "revoke_category"
    rec.validate()
    extras = dict(writer_extras or {})
    w = writer or _default_writer
    effective = w(rec, extras)
    _emit_audit(
        action=f"learning_consent_{op}", record=rec,
        effective=effective, actor=actor,
    )
    return ConsentDecision(
        hub_id=hub_id,
        project_id=project_id,
        operation=op,
        effective_policy=effective,
        actor=actor,
        decided_at=datetime.now(timezone.utc),
    )


def list_cross_org_consents(
    hub_id: Optional[str] = None,
    *,
    reader: Optional[ConsentReader] = None,
    reader_extras: Optional[dict[str, Any]] = None,
) -> list[ScopePolicy]:
    """Enumerate consent rows; optional ``hub_id`` filter."""
    r = reader or _default_reader
    return r(hub_id, dict(reader_extras or {}))


__all__ = [
    "ConsentDecision",
    "ConsentReader",
    "ConsentRecord",
    "ConsentWriter",
    "grant_cross_org_consent",
    "list_cross_org_consents",
    "revoke_cross_org_consent",
]
