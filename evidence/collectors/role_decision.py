"""Role-decision collector — captures role decision events.

Role decisions (any audit row where a role made an explicit pass/fail
decision: ``gate_check``, ``phase_advanced``, ``cite_or_refuse_refused``,
verify pass/fail) are gold-standard SOC 2 evidence — they're the
documented "human in the loop" the auditor wants to see.

V25 ``evidence_type`` mapping = ``access_review`` (every decision is a
reviewable record of who allowed what).
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Iterable, Optional

from evidence._db import query_rows
from evidence._types import EvidencePayload

logger = logging.getLogger(__name__)

#: Actions that count as a "role decision" for evidence purposes.
ROLE_DECISION_ACTIONS: tuple[str, ...] = (
    "gate_check",
    "phase_advanced",
    "approval_granted",
    "cite_or_refuse_refused",
    "verify_audit",
    "policy_published",
    "directive_dispatched",
)


def _esc(s: str) -> str:
    return s.replace("'", "''")


def collect_role_decisions(
    *,
    framework: str,
    control_id: str,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    project_id: Optional[str] = None,
    roles: Optional[Iterable[str]] = None,
    rows: Optional[Iterable[dict[str, Any]]] = None,
) -> list[EvidencePayload]:
    """Return one EvidencePayload per role decision event.

    Filter strategy:
      * ``action IN ROLE_DECISION_ACTIONS``
      * Optional role filter (``role IN (...)``)
      * Optional time window + project filter.
    """
    iter_rows = rows
    if iter_rows is None:
        action_csv = ", ".join("'" + _esc(a) + "'" for a in ROLE_DECISION_ACTIONS)
        where = [f"action IN ({action_csv})"]
        if roles:
            role_csv = ", ".join("'" + _esc(r) + "'" for r in roles)
            where.append(f"role IN ({role_csv})")
        if since:
            where.append(f"ts >= '{since.isoformat()}'::timestamptz")
        if until:
            where.append(f"ts <= '{until.isoformat()}'::timestamptz")
        if project_id:
            where.append(f"project_id::text = '{_esc(project_id)}'")
        sql = (
            "SELECT event_uuid, ts, role, actor, action, subject_type, "
            "       subject_id, rationale, metadata, content_hash "
            "FROM spine_audit.audit_event "
            f"WHERE {' AND '.join(where)} "
            "ORDER BY event_id ASC"
        )
        iter_rows = query_rows(sql)

    out: list[EvidencePayload] = []
    for row in iter_rows:
        body = {
            "decision_action": row.get("action"),
            "role": row.get("role"),
            "actor": row.get("actor"),
            "subject_type": row.get("subject_type"),
            "subject_id": row.get("subject_id"),
            "rationale": row.get("rationale"),
            "ts": row.get("ts"),
            "metadata": row.get("metadata") or {},
            "content_hash": row.get("content_hash"),
        }
        out.append(EvidencePayload(
            framework=framework,
            control_id=control_id,
            evidence_type="access_review",
            source_audit_record_id=str(row.get("event_uuid")) if row.get("event_uuid") else None,
            body=body,
        ))
    logger.info("collect_role_decisions: framework=%s control=%s -> %d payload(s)",
                framework, control_id, len(out))
    return out


__all__ = ["ROLE_DECISION_ACTIONS", "collect_role_decisions"]
