"""Generic audit-chain collector — pulls from ``spine_audit.audit_event``.

Per V3 #24 every audit_event entry is potential evidence. This collector
is the default: it filters the append-only ledger by framework +
control_id (matched against the ``metadata->>'control_id'`` JSONB key
and ``metadata->>'framework'`` so existing rows can be retro-mapped
without a schema change) and returns one ``EvidencePayload`` per match.

The collector returns the audit row's ``event_uuid`` in
``source_audit_record_id`` — that UUID is also the Cite-or-Refuse
citation (per #12 the audit_record_id IS the citation).
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Iterable, Optional

from evidence._db import query_rows
from evidence._types import EvidencePayload, EvidenceType

logger = logging.getLogger(__name__)

#: Default mapping from audit ``action`` → V25 evidence_type. Anything
#: not in this table falls back to ``scan_result`` (the most permissive
#: bucket — auditors can re-tag in their GRC tool).
DEFAULT_ACTION_TYPE_MAP: dict[str, EvidenceType] = {
    "verify_audit":      "scan_result",
    "verify_finding":    "scan_result",
    "approval_granted":  "access_review",
    "gate_check":        "access_review",
    "phase_advanced":    "access_review",
    "llm_call":          "test_run",
    "directive_dispatched": "test_run",
    "config_snapshot":   "config_snapshot",
    "policy_published":  "policy_doc",
}


def _esc(s: str) -> str:
    """Single-quote escape for psql ``-c`` payloads (mirrors exporter.py)."""
    return s.replace("'", "''")


def collect_audit_chain(
    *,
    framework: str,
    control_id: str,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    project_id: Optional[str] = None,
    rows: Optional[Iterable[dict[str, Any]]] = None,
    type_map: Optional[dict[str, EvidenceType]] = None,
) -> list[EvidencePayload]:
    """Build EvidencePayloads from audit_event rows tagged for this control.

    ``rows`` is an injection seam used by tests — if supplied the function
    skips the psql roundtrip and renders the supplied row dicts directly.

    Filter strategy (live mode):
      * ``metadata->>'framework'   = framework``
      * ``metadata->>'control_id'  = control_id``
      * Optional ``ts >= since`` / ``ts <= until`` / ``project_id`` match.
    """
    mapping = dict(DEFAULT_ACTION_TYPE_MAP)
    if type_map:
        mapping.update(type_map)
    iter_rows = rows
    if iter_rows is None:
        where = [
            f"metadata->>'framework'  = '{_esc(framework)}'",
            f"metadata->>'control_id' = '{_esc(control_id)}'",
        ]
        if since:
            where.append(f"ts >= '{since.isoformat()}'::timestamptz")
        if until:
            where.append(f"ts <= '{until.isoformat()}'::timestamptz")
        if project_id:
            where.append(f"project_id::text = '{_esc(project_id)}'")
        sql = (
            "SELECT event_uuid, ts, action, subsystem, role, actor, "
            "       subject_type, subject_id, metadata, content_hash "
            "FROM spine_audit.audit_event "
            f"WHERE {' AND '.join(where)} "
            "ORDER BY event_id ASC"
        )
        iter_rows = query_rows(sql)

    out: list[EvidencePayload] = []
    for row in iter_rows:
        action = row.get("action") or ""
        ev_type: EvidenceType = mapping.get(action, "scan_result")
        body = {
            "action": action,
            "subsystem": row.get("subsystem"),
            "role": row.get("role"),
            "actor": row.get("actor"),
            "subject_type": row.get("subject_type"),
            "subject_id": row.get("subject_id"),
            "ts": row.get("ts"),
            "metadata": row.get("metadata") or {},
            "content_hash": row.get("content_hash"),
        }
        out.append(EvidencePayload(
            framework=framework,
            control_id=control_id,
            evidence_type=ev_type,
            source_audit_record_id=str(row.get("event_uuid")) if row.get("event_uuid") else None,
            body=body,
        ))
    logger.info("collect_audit_chain: framework=%s control=%s -> %d payload(s)",
                framework, control_id, len(out))
    return out


__all__ = ["DEFAULT_ACTION_TYPE_MAP", "collect_audit_chain"]
