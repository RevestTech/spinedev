"""Approval-grant collector — narrow specialisation of role_decision.

Audit rows with ``action='approval_granted'`` are the highest-value
evidence rows in the entire chain — they prove explicit human (or
authority-delegated role) consent for state transitions. Auditors
typically want these surfaced as their own bucket rather than mixed in
with the general role_decision stream.

V25 ``evidence_type`` mapping = ``access_review``.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Iterable, Optional

from evidence._db import query_rows
from evidence._types import EvidencePayload

logger = logging.getLogger(__name__)

#: Action verbs that count as an approval grant (or its inverse).
APPROVAL_ACTIONS: tuple[str, ...] = (
    "approval_granted",
    "approval_revoked",
    "emergency_override_granted",
)


def _esc(s: str) -> str:
    return s.replace("'", "''")


def collect_approvals(
    *,
    framework: str,
    control_id: str,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    project_id: Optional[str] = None,
    approvers: Optional[Iterable[str]] = None,
    rows: Optional[Iterable[dict[str, Any]]] = None,
) -> list[EvidencePayload]:
    """Return one EvidencePayload per approval-class event.

    ``approvers`` (optional) restricts to a specific actor list — useful
    when a control requires sign-off from a named role (e.g. Master
    DevOps approvals for production deploys).
    """
    iter_rows = rows
    if iter_rows is None:
        action_csv = ", ".join("'" + _esc(a) + "'" for a in APPROVAL_ACTIONS)
        where = [f"action IN ({action_csv})"]
        if approvers:
            actor_csv = ", ".join("'" + _esc(a) + "'" for a in approvers)
            where.append(f"actor IN ({actor_csv})")
        if since:
            where.append(f"ts >= '{since.isoformat()}'::timestamptz")
        if until:
            where.append(f"ts <= '{until.isoformat()}'::timestamptz")
        if project_id:
            where.append(f"project_id::text = '{_esc(project_id)}'")
        sql = (
            "SELECT event_uuid, ts, role, actor, action, phase, "
            "       subject_type, subject_id, rationale, metadata, content_hash "
            "FROM spine_audit.audit_event "
            f"WHERE {' AND '.join(where)} "
            "ORDER BY event_id ASC"
        )
        iter_rows = query_rows(sql)

    out: list[EvidencePayload] = []
    for row in iter_rows:
        body = {
            "approval_action": row.get("action"),
            "approver_actor":  row.get("actor"),
            "approver_role":   row.get("role"),
            "phase":           row.get("phase"),
            "subject_type":    row.get("subject_type"),
            "subject_id":      row.get("subject_id"),
            "rationale":       row.get("rationale"),
            "ts":              row.get("ts"),
            "metadata":        row.get("metadata") or {},
            "content_hash":    row.get("content_hash"),
        }
        out.append(EvidencePayload(
            framework=framework,
            control_id=control_id,
            evidence_type="access_review",
            source_audit_record_id=str(row.get("event_uuid")) if row.get("event_uuid") else None,
            body=body,
        ))
    logger.info("collect_approvals: framework=%s control=%s -> %d payload(s)",
                framework, control_id, len(out))
    return out


__all__ = ["APPROVAL_ACTIONS", "collect_approvals"]
