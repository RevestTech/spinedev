"""Deploy collector — pulls from ``spine_devops.action_log``.

V27 (Operate / DevOps subsystem #11) introduced ``spine_devops.action_log``
as the append-only ledger of every devops action across the 8 control
planes. Deploy events (``action ∈ deploy, rollback, scale_up, drain``)
are direct SOC 2 evidence — they prove what code was promoted to which
environment by whom, with the optional ``audit_chain_anchor`` linking
back to ``spine_audit.audit_event`` for hash-chain corroboration.

V25 ``evidence_type`` mapping = ``config_snapshot`` (each deploy IS a
config snapshot of the deployed system).
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Iterable, Optional

from evidence._db import query_rows
from evidence._types import EvidencePayload

logger = logging.getLogger(__name__)

#: Action verbs that count as a "deploy" for evidence purposes.
DEPLOY_ACTIONS: tuple[str, ...] = (
    "deploy",
    "rollback",
    "scale_up",
    "scale_down",
    "drain",
    "restart",
    "rotate_secret",
)


def _esc(s: str) -> str:
    return s.replace("'", "''")


def collect_deploys(
    *,
    framework: str,
    control_id: str,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    project_id: Optional[str] = None,
    actions: Optional[Iterable[str]] = None,
    rows: Optional[Iterable[dict[str, Any]]] = None,
) -> list[EvidencePayload]:
    """Return one EvidencePayload per deploy-class action in V27 schema.

    Joins ``spine_devops.action_log`` to ``spine_devops.control_plane``
    so the resulting payload carries ``plane_name`` (one of the 8
    canonical Operate planes).

    ``source_audit_record_id`` is populated from the action_log row's
    ``audit_chain_anchor`` when present — that bytea hash is the
    hash-chained corroboration of the deploy back into the main audit
    ledger (per #24 two-party attestation).
    """
    use_actions = tuple(actions) if actions else DEPLOY_ACTIONS
    iter_rows = rows
    if iter_rows is None:
        action_csv = ", ".join("'" + _esc(a) + "'" for a in use_actions)
        where = [f"a.action IN ({action_csv})"]
        if since:
            where.append(f"a.ts >= '{since.isoformat()}'::timestamptz")
        if until:
            where.append(f"a.ts <= '{until.isoformat()}'::timestamptz")
        if project_id:
            where.append(f"p.project_id::text = '{_esc(project_id)}'")
        sql = (
            "SELECT a.id AS action_id, a.ts, a.action, a.payload_jsonb, "
            "       a.actor_user_id, encode(a.audit_chain_anchor, 'hex') AS audit_anchor_hex, "
            "       p.plane_name, p.project_id "
            "FROM spine_devops.action_log a "
            "JOIN spine_devops.control_plane p ON p.id = a.plane_id "
            f"WHERE {' AND '.join(where)} "
            "ORDER BY a.ts ASC"
        )
        iter_rows = query_rows(sql)

    out: list[EvidencePayload] = []
    for row in iter_rows:
        body = {
            "deploy_action":  row.get("action"),
            "plane_name":     row.get("plane_name"),
            "actor_user_id":  row.get("actor_user_id"),
            "project_id":     row.get("project_id"),
            "ts":             row.get("ts"),
            "payload":        row.get("payload_jsonb") or {},
            "audit_anchor":   row.get("audit_anchor_hex"),
        }
        out.append(EvidencePayload(
            framework=framework,
            control_id=control_id,
            evidence_type="config_snapshot",
            source_audit_record_id=row.get("audit_anchor_hex"),
            body=body,
        ))
    logger.info("collect_deploys: framework=%s control=%s -> %d payload(s)",
                framework, control_id, len(out))
    return out


__all__ = ["DEPLOY_ACTIONS", "collect_deploys"]
