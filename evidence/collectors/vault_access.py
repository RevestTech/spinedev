"""Vault-access collector — captures vault read/write events.

Pulls from ``spine_audit.audit_event`` where ``subsystem='shared'`` and
``action`` is one of the canonical vault verbs. These rows are highly
sensitive — they prove who accessed what secret and when, which is the
direct evidence for SOC 2 CC6.x access-control controls.

V25 ``evidence_type`` mapping = ``access_review``.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Iterable, Optional

from evidence._db import query_rows
from evidence._types import EvidencePayload

logger = logging.getLogger(__name__)

#: Vault verb taxonomy. Mirrors the actions ``shared.secrets`` records
#: on every adapter call (vault_read / vault_write / vault_delete /
#: vault_list). ``vault_denied`` is the audited form of
#: ``SecretAccessDenied`` so a refused read still produces evidence.
VAULT_ACTIONS: tuple[str, ...] = (
    "vault_read",
    "vault_write",
    "vault_delete",
    "vault_list",
    "vault_denied",
    "vault_rotated",
)


def _esc(s: str) -> str:
    return s.replace("'", "''")


def collect_vault_access(
    *,
    framework: str,
    control_id: str,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    project_id: Optional[str] = None,
    paths: Optional[Iterable[str]] = None,
    rows: Optional[Iterable[dict[str, Any]]] = None,
) -> list[EvidencePayload]:
    """Return one EvidencePayload per vault access event.

    ``paths`` (optional) restricts to specific vault paths matched
    against ``metadata->>'path'``. Useful for control-scoped evidence
    such as "all reads of evidence/vanta/*" for the Vanta export
    credential.
    """
    iter_rows = rows
    if iter_rows is None:
        action_csv = ", ".join("'" + _esc(a) + "'" for a in VAULT_ACTIONS)
        where = [
            "subsystem = 'shared'",
            f"action IN ({action_csv})",
        ]
        if paths:
            path_csv = ", ".join("'" + _esc(p) + "'" for p in paths)
            where.append(f"(metadata->>'path') IN ({path_csv})")
        if since:
            where.append(f"ts >= '{since.isoformat()}'::timestamptz")
        if until:
            where.append(f"ts <= '{until.isoformat()}'::timestamptz")
        if project_id:
            where.append(f"project_id::text = '{_esc(project_id)}'")
        sql = (
            "SELECT event_uuid, ts, role, actor, action, subject_id, "
            "       rationale, metadata, content_hash "
            "FROM spine_audit.audit_event "
            f"WHERE {' AND '.join(where)} "
            "ORDER BY event_id ASC"
        )
        iter_rows = query_rows(sql)

    out: list[EvidencePayload] = []
    for row in iter_rows:
        meta = row.get("metadata") or {}
        body = {
            "vault_action": row.get("action"),
            "vault_path": meta.get("path"),
            "actor": row.get("actor"),
            "role": row.get("role"),
            "adapter": meta.get("adapter"),
            "outcome": "denied" if row.get("action") == "vault_denied" else "ok",
            "ts": row.get("ts"),
            "rationale": row.get("rationale"),
            "metadata": meta,
            "content_hash": row.get("content_hash"),
        }
        out.append(EvidencePayload(
            framework=framework,
            control_id=control_id,
            evidence_type="access_review",
            source_audit_record_id=str(row.get("event_uuid")) if row.get("event_uuid") else None,
            body=body,
        ))
    logger.info("collect_vault_access: framework=%s control=%s -> %d payload(s)",
                framework, control_id, len(out))
    return out


__all__ = ["VAULT_ACTIONS", "collect_vault_access"]
