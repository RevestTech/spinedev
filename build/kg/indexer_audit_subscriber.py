"""KG indexer trigger 2/3 — audit-event-driven subscriber (Wave 1, V3 §1.2 SECONDARY).

Audit events that don't ride git — bundle updates, role-charter changes,
decisions, approvals — also update KG nodes. This module:

  * Subscribes to ``shared.audit.audit_record`` writes via the same
    dispatch hook surface ``shared.memory.writer_hooks`` uses.
  * Maps each subscribed action → a KG node-touch operation.
  * Writes/updates ``spine_kg.kg_node`` rows directly (last-write-wins).
  * Logs the trigger for observability.

Conflict resolution (per V3 §1.2): last-write-wins + observed-state
validation. The commit-hook trigger and audit subscriber may race for
the same node; the latest ``valid_to IS NULL`` row is authoritative.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

logger = logging.getLogger("spine.kg.audit_subscriber")

TRIGGER_SOURCE = "audit_subscriber"
DEFAULT_DB_URL = "postgresql://spine:spine@localhost:33000/spine"

# Audit actions this subscriber listens for. Each maps to a KG node
# type/subtype convention so a queryable shape is stable.
#
#   action                            → (node_type, node_subtype)
SUBSCRIBED_ACTIONS: dict[str, tuple[str, str]] = {
    "bundle_installed":       ("standards_bundle", "install"),
    "bundle_updated":         ("standards_bundle", "update"),
    "role_charter_changed":   ("role_charter",     "change"),
    "decision_recorded":      ("decision",         "record"),
    "approval_granted":       ("approval",         "granted"),
    "approval_rejected":      ("approval",         "rejected"),
    "directive_dispatched":   ("directive",        "dispatch"),
}


@dataclass
class AuditTouch:
    """One KG node-touch derived from an audit event."""
    node_id: str
    node_type: str
    node_subtype: str
    name: Optional[str]
    properties: dict[str, Any] = field(default_factory=dict)
    repo: str = "_audit"
    commit_sha: str = "_audit"
    path: Optional[str] = None


# ─── Public surface ─────────────────────────────────────────────────


_REGISTERED = False
_REGISTRY_LOCK = threading.Lock()


def install_subscriber(
    *,
    db_url: Optional[str] = None,
    writer: Optional[Callable[[AuditTouch, str], None]] = None,
) -> None:
    """Register the subscriber callback with the audit dispatch surface.

    Idempotent. Audit events are routed through
    ``shared.memory.writer_hooks.register_hook``; we piggyback on the
    same canonical event keys plus inspect raw audit records for
    actions outside the canonical 7 (bundle updates etc.) by hooking
    a custom callback on ``approval.granted`` + ``approval.rejected``
    AND exposing :func:`handle_record` for direct callers.
    """
    global _REGISTERED
    with _REGISTRY_LOCK:
        if _REGISTERED:
            return
        _REGISTERED = True

    # Memory writer hooks already cover approval.granted/rejected. We
    # register additional callbacks there so KG node-touches fire as a
    # side effect of audit writes too. For the actions OUTSIDE the
    # canonical 7 (bundle updates, role-charter changes, directives,
    # decisions), callers invoke ``handle_record`` directly from the
    # subsystem that emits the audit (until those actions are added to
    # the canonical writer-hook keyset in a later wave).
    try:
        from shared.memory.writer_hooks import register_hook
    except Exception:  # pragma: no cover - memory pkg optional
        logger.warning("audit_subscriber: shared.memory not importable; "
                       "direct handle_record() still works")
        return

    def _on_approval_granted(record: dict[str, Any]):
        handle_record(record, db_url=db_url, writer=writer)
        return None

    def _on_approval_rejected(record: dict[str, Any]):
        handle_record(record, db_url=db_url, writer=writer)
        return None

    register_hook("approval.granted", _on_approval_granted)
    register_hook("approval.rejected", _on_approval_rejected)


def handle_record(
    record: dict[str, Any],
    *,
    db_url: Optional[str] = None,
    writer: Optional[Callable[[AuditTouch, str], None]] = None,
) -> Optional[AuditTouch]:
    """Map one audit record dict to a KG touch and persist it.

    Returns the AuditTouch produced (or ``None`` if the action is not
    one of the subscribed actions).
    """
    touch = _record_to_touch(record)
    if touch is None:
        return None
    url = db_url or os.environ.get("SPINE_DB_URL") or os.environ.get(
        "DATABASE_URL"
    ) or DEFAULT_DB_URL
    try:
        if writer is not None:
            writer(touch, url)
        else:
            _default_writer(touch, url)
    except Exception:  # pragma: no cover - defensive
        logger.exception("audit_subscriber: KG write failed for %s", touch.node_id)
        return touch
    return touch


def subscribed_actions() -> tuple[str, ...]:
    """Inspect the audit actions this subscriber knows about."""
    return tuple(SUBSCRIBED_ACTIONS)


# ─── Mapping ────────────────────────────────────────────────────────


def _record_to_touch(record: dict[str, Any]) -> Optional[AuditTouch]:
    action = (record.get("action") or "").lower()
    spec = SUBSCRIBED_ACTIONS.get(action)
    if spec is None:
        return None
    node_type, node_subtype = spec
    subject_id = record.get("subject_id") or record.get("event_uuid") or "unknown"
    node_id = f"audit:{node_type}:{subject_id}"
    meta = record.get("metadata") or {}
    properties = {
        "audit_action": action,
        "actor": record.get("actor"),
        "role": record.get("role"),
        "subsystem": record.get("subsystem"),
        "project_id": record.get("project_id"),
        "ts": _utc_iso(record.get("ts")),
        "rationale": record.get("rationale"),
        "metadata": meta,
    }
    name = (meta.get("name")
            or meta.get("bundle_id")
            or meta.get("charter_id")
            or subject_id)
    return AuditTouch(
        node_id=node_id, node_type=node_type, node_subtype=node_subtype,
        name=str(name) if name is not None else None,
        properties=properties,
    )


def _utc_iso(v: Any) -> Optional[str]:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.astimezone(timezone.utc).isoformat()
    return str(v)


# ─── Persistence ────────────────────────────────────────────────────


def _q(v: object) -> str:
    return "NULL" if v is None else "'" + str(v).replace("'", "''") + "'"


def _psql(sql: str, db_url: str) -> str:
    r = subprocess.run(
        ["psql", db_url, "-At", "-v", "ON_ERROR_STOP=1", "-c", sql],
        capture_output=True, text=True, timeout=30,
    )
    if r.returncode != 0:
        raise RuntimeError(f"psql failed: {r.stderr.strip()}")
    return r.stdout


def _default_writer(touch: AuditTouch, db_url: str) -> None:
    """Upsert one KG node row, supersede prior valid_to IS NULL row first.

    Last-write-wins per V3 §1.2 conflict resolution.
    """
    parts = ["BEGIN;"]
    # Supersede any prior live row with this node_id.
    parts.append(
        "UPDATE spine_kg.kg_node SET valid_to = now() WHERE node_id = "
        f"{_q(touch.node_id)} AND valid_to IS NULL;"
    )
    props_sql = "'" + json.dumps(touch.properties or {}).replace("'", "''") + "'::jsonb"
    parts.append(
        "INSERT INTO spine_kg.kg_node (node_id, type, subtype, repo, commit_sha, "
        "path, name, properties) VALUES ("
        f"{_q(touch.node_id)}, {_q(touch.node_type)}, {_q(touch.node_subtype)}, "
        f"{_q(touch.repo)}, {_q(touch.commit_sha)}, {_q(touch.path)}, "
        f"{_q(touch.name)}, {props_sql});"
    )
    parts.append("COMMIT;")
    _psql("\n".join(parts), db_url)


__all__ = [
    "AuditTouch",
    "SUBSCRIBED_ACTIONS",
    "TRIGGER_SOURCE",
    "handle_record",
    "install_subscriber",
    "subscribed_actions",
]
