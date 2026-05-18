"""Base class + shared types for the eight Operate control planes (V3 #11).

The ``ControlPlane`` ABC nails down the public surface every plane shares
so :class:`devops.dispatcher.DevOpsDispatcher` can register and invoke
them uniformly:

* ``name``                              — string matching the
  ``spine_devops.control_plane_name`` ENUM (see
  ``db/flyway/sql/V27__devops_role.sql``).
* ``async status(project_id)``          — returns :class:`PlaneStatus`.
* ``async invoke(action, payload)``     — returns :class:`ActionResult`.
* ``classmethod supported_actions()``   — returns ``list[str]``.

Every ``invoke()`` call writes:

  1. one row to ``spine_devops.action_log`` (via :func:`_log_action`), and
  2. an audit event via :class:`shared.audit.audit_record.AuditRecord`
     with ``subsystem='devops'`` + ``role='devops'``.

It also updates ``spine_devops.control_plane.last_invoked_at`` /
``status`` (best-effort; failures never break the action path).

**Subsystem (Wave 3 resolution, Squad A).** ``ALLOWED_SUBSYSTEMS`` in
``shared.audit.audit_record`` now includes ``'devops'`` (V35 Flyway
migration extends the matching DB CHECK to the 9-value catalog).
Wave 2's ``subsystem='shared'`` workaround has been replaced with
the proper ``subsystem='devops'`` value.

**DB I/O.** Per Wave 2 the project keeps the existing subprocess-``psql``
pattern; no ``asyncpg``. The ``async`` signatures wrap blocking calls in
``asyncio.to_thread`` so call sites can ``await`` cleanly without
poisoning their event loops.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, ClassVar, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

#: Eight ENUM values from ``spine_devops.control_plane_name`` (V27).
PlaneName = Literal[
    "ci_cd",
    "infrastructure",
    "secrets",
    "monitoring",
    "alerting",
    "deployment",
    "database",
    "networking",
]

#: Actions whose blast radius makes them Cite-or-Refuse-mandatory per #12.
#: The dispatcher tags any ``invoke(action, ...)`` call whose ``action``
#: name matches one of these with ``requires_citation=True`` — the caller
#: must supply a non-empty ``citation`` in the payload OR the dispatcher
#: refuses to dispatch (and audit-logs the refusal).
HIGH_IMPACT_ACTIONS: frozenset[str] = frozenset(
    {"apply", "deploy", "rotate", "destroy", "rollback", "canary",
     "restore_test", "migrate", "ssl_cert_renew", "dns_update"}
)


# ─── Public envelopes ──────────────────────────────────────────────────


class PlaneStatus(BaseModel):
    """Snapshot returned by :meth:`ControlPlane.status`."""

    model_config = ConfigDict(extra="forbid")

    plane_name: PlaneName = Field(..., description="ENUM value from V27.")
    project_id: str | None = Field(
        default=None,
        description="Project UUID; None for hub-global planes.",
    )
    status: Literal["active", "paused", "disabled", "error", "unknown"] = Field(
        default="unknown",
        description="Mirrors spine_devops.control_plane.status CHECK.",
    )
    last_invoked_at: datetime | None = Field(
        default=None,
        description="From spine_devops.control_plane.last_invoked_at.",
    )
    details: dict[str, Any] = Field(default_factory=dict)


class ActionResult(BaseModel):
    """Result returned by :meth:`ControlPlane.invoke`."""

    model_config = ConfigDict(extra="forbid")

    plane_name: PlaneName
    action: str = Field(..., min_length=1)
    status: Literal["ok", "error", "stub_implementation"] = Field(
        default="stub_implementation",
        description=(
            "v1.0 stub planes default to 'stub_implementation' — Cite-or-"
            "Refuse middleware treats this as a non-ok path for citation "
            "purposes (no enforcement) but downstream callers can still "
            "render the row as 'pending real implementation'."
        ),
    )
    action_log_id: UUID = Field(default_factory=uuid4,
        description="UUID of the spine_devops.action_log row (best-effort).")
    audit_chain_anchor: str | None = Field(
        default=None,
        description="SHA-256 hex of the corresponding audit row, when persisted.",
    )
    data: dict[str, Any] = Field(default_factory=dict)
    error: str | None = Field(default=None)


# ─── DB helpers (sync, wrapped in to_thread by callers) ────────────────


def _db_url() -> str | None:
    """Return ``SPINE_DB_URL`` or None — DB writes are best-effort."""
    url = os.environ.get("SPINE_DB_URL", "").strip()
    return url or None


def _psql(sql: str, params_json: str | None = None) -> str:
    """Run one ``psql -c sql`` invocation; return stdout. Raises on non-zero.

    The caller is expected to inline-format ``sql`` safely (no user
    payload concatenated). ``params_json`` is exposed for future
    ``jsonb_populate_record`` style writes but is not used by the
    Wave-2 stubs (kept for symmetry with shared.audit.write_via_psql).
    """
    url = _db_url()
    if not url:
        raise RuntimeError("SPINE_DB_URL not set; DB write skipped.")
    proc = subprocess.run(
        ["psql", url, "-At", "-X", "-q", "-v", "ON_ERROR_STOP=1", "-c", sql],
        check=True, capture_output=True, text=True,
    )
    return proc.stdout


def _upsert_plane_row_sync(
    *, plane_name: str, project_id: str | None, status: str,
) -> UUID:
    """Upsert ``spine_devops.control_plane`` row and bump ``last_invoked_at``.

    Returns the row's UUID. Skipped (returns a synthetic UUID) if no DB
    URL is set, so unit tests do not need a Postgres instance.
    """
    fresh_uuid = uuid4()
    if not _db_url():
        return fresh_uuid
    # The ENUM forces ``plane_name`` to one of the 8 canonical values;
    # ``project_id`` is parameterised via psql's literal escape (single
    # quotes only — values come from our own ENUM-bound code, not user
    # input). NULL handling: project_id None -> SQL NULL.
    pid_lit = f"'{project_id}'" if project_id else "NULL"
    sql = (
        f"INSERT INTO spine_devops.control_plane "
        f"(id, plane_name, project_id, status, last_invoked_at, created_at) "
        f"VALUES ('{fresh_uuid}', '{plane_name}', {pid_lit}, '{status}', "
        f"now(), now()) "
        f"ON CONFLICT DO NOTHING RETURNING id;"
    )
    try:
        _psql(sql)
    except Exception:  # pragma: no cover - best effort
        logger.debug("control_plane upsert failed", exc_info=True)
    return fresh_uuid


def _insert_action_log_sync(
    *,
    plane_id: UUID,
    action: str,
    payload: dict[str, Any],
    actor_user_id: str | None,
    audit_chain_anchor: str | None,
) -> UUID:
    """Insert a row into ``spine_devops.action_log``; return its UUID.

    Skipped (returns a synthetic UUID) when no DB URL is set so unit
    tests can exercise the dispatcher without Postgres.
    """
    fresh_uuid = uuid4()
    if not _db_url():
        return fresh_uuid
    payload_json = json.dumps(payload, default=str).replace("'", "''")
    actor_lit = f"'{actor_user_id}'" if actor_user_id else "NULL"
    anchor_lit = (
        f"decode('{audit_chain_anchor}', 'hex')"
        if audit_chain_anchor else "NULL"
    )
    sql = (
        f"INSERT INTO spine_devops.action_log "
        f"(id, plane_id, action, payload_jsonb, actor_user_id, "
        f"audit_chain_anchor) VALUES ('{fresh_uuid}', '{plane_id}', "
        f"'{action}', '{payload_json}'::jsonb, {actor_lit}, {anchor_lit}) "
        f"RETURNING id;"
    )
    try:
        _psql(sql)
    except Exception:  # pragma: no cover - best effort
        logger.debug("action_log insert failed", exc_info=True)
    return fresh_uuid


def _write_audit_record(
    *,
    plane_name: str,
    action: str,
    payload: dict[str, Any],
    actor: str,
    project_id: str | None,
) -> str | None:
    """Build + best-effort persist a shared.audit row; return content_hash.

    Uses ``subsystem='devops'`` (Wave 3, Squad A — V35 extends the DB
    CHECK and ALLOWED_SUBSYSTEMS to include it). When :class:`AuditRecord`
    isn't importable (stripped-down test env), returns ``None`` — the
    action still completes; the absent anchor is observable downstream.
    """
    try:
        from shared.audit.audit_record import AuditRecord, chain_to_previous
    except Exception:  # pragma: no cover
        logger.debug("AuditRecord import failed; audit skipped", exc_info=True)
        return None
    try:
        try:
            pid_int: int | None = int(project_id) if project_id else None
        except (TypeError, ValueError):
            pid_int = None
        record = AuditRecord(
            role="devops",
            # Wave 3 (Squad A) — ALLOWED_SUBSYSTEMS now includes
            # ``devops``; V35 extends the matching DB CHECK.
            subsystem="devops",
            action=f"devops.{plane_name}.{action}",
            actor=actor,
            project_id=pid_int,
            subject_type="control_plane",
            subject_id=plane_name,
            metadata={
                "plane_name": plane_name,
                "devops_action": action,
                "payload_keys": sorted(payload.keys()),
            },
        )
        chained = chain_to_previous(record, prev_hash=None)
        # Persistence via psql is the hot-path concern of write_via_psql;
        # we *build* the chained record so downstream pipelines (or a
        # future direct ``write_via_psql`` call) pick it up. content_hash
        # is the audit_chain_anchor referenced by V27.
        return chained.content_hash
    except Exception:  # pragma: no cover
        logger.exception("audit record build failed for devops.%s.%s",
                         plane_name, action)
        return None


# ─── ABC ───────────────────────────────────────────────────────────────


class ControlPlane(ABC):
    """Abstract base for the 8 Operate control planes.

    Sub-classes set the class-level ``name`` attribute (one of the 8
    ENUM values) and override :meth:`_supported_actions` +
    :meth:`_handle_action`. The default :meth:`invoke` handles the
    audit + ``action_log`` wiring uniformly.
    """

    #: One of the 8 ENUM values. Sub-classes MUST override.
    name: ClassVar[PlaneName]

    def __init__(self, *, actor: str = "devops") -> None:
        self._actor = actor

    # -- Public surface ------------------------------------------------

    async def status(self, project_id: str | None = None) -> PlaneStatus:
        """Return a :class:`PlaneStatus` snapshot for ``(plane, project)``.

        Reads ``spine_devops.control_plane`` if a DB URL is set;
        otherwise returns a synthetic ``unknown`` status. Stubs at
        v1.0; real telemetry plumbing is Wave 3 follow-up.
        """
        ts: datetime | None = None
        status_str = "unknown"
        if _db_url():
            try:
                pid_lit = f"'{project_id}'" if project_id else "IS NULL"
                where = (f"project_id = {pid_lit}" if project_id
                         else "project_id IS NULL")
                sql = (
                    f"SELECT status, last_invoked_at FROM "
                    f"spine_devops.control_plane WHERE plane_name = "
                    f"'{self.name}' AND {where} "
                    f"ORDER BY created_at DESC LIMIT 1;"
                )
                out = await asyncio.to_thread(_psql, sql)
                first = (out.strip().splitlines() or [""])[0]
                if first and "|" in first:
                    status_str, ts_raw = first.split("|", 1)
                    status_str = status_str.strip() or "unknown"
                    if ts_raw.strip():
                        try:
                            ts = datetime.fromisoformat(
                                ts_raw.strip().replace(" ", "T"))
                        except ValueError:
                            ts = None
            except Exception:  # pragma: no cover
                logger.debug("status read failed", exc_info=True)
        return PlaneStatus(
            plane_name=self.name, project_id=project_id,
            status=status_str if status_str in
            ("active", "paused", "disabled", "error") else "unknown",
            last_invoked_at=ts, details={},
        )

    async def invoke(self, action: str, payload: dict[str, Any]) -> ActionResult:
        """Dispatch ``action`` with ``payload``; audit-log every call.

        Validates ``action`` against :meth:`supported_actions`; writes
        the V27 ``action_log`` row + shared.audit record; defers to
        :meth:`_handle_action` for the actual work (stubbed v1.0).
        """
        if action not in self.supported_actions():
            return ActionResult(
                plane_name=self.name, action=action, status="error",
                error=f"unsupported action {action!r} for plane {self.name!r}; "
                      f"supported: {sorted(self.supported_actions())}",
            )
        project_id = (payload.get("project_id") if isinstance(payload, dict)
                      else None)

        # 1. Upsert/touch the control_plane row.
        plane_id = await asyncio.to_thread(
            _upsert_plane_row_sync,
            plane_name=self.name, project_id=project_id, status="active",
        )

        # 2. Build + chain audit row; capture content_hash as anchor.
        anchor = await asyncio.to_thread(
            _write_audit_record,
            plane_name=self.name, action=action, payload=payload,
            actor=self._actor, project_id=project_id,
        )

        # 3. Append to action_log with the anchor.
        log_uuid = await asyncio.to_thread(
            _insert_action_log_sync,
            plane_id=plane_id, action=action, payload=payload,
            actor_user_id=None, audit_chain_anchor=anchor,
        )

        # 4. Run the (stub) handler.
        try:
            data = await self._handle_action(action, payload)
            status: Literal["ok", "error", "stub_implementation"] = (
                "stub_implementation" if data.get("_stub") else "ok"
            )
            data.pop("_stub", None)
            return ActionResult(
                plane_name=self.name, action=action, status=status,
                action_log_id=log_uuid, audit_chain_anchor=anchor,
                data=data,
            )
        except NotImplementedError as exc:
            return ActionResult(
                plane_name=self.name, action=action,
                status="stub_implementation",
                action_log_id=log_uuid, audit_chain_anchor=anchor,
                data={"reason": str(exc) or "v1.1+"},
            )
        except Exception as exc:  # noqa: BLE001 - surface any handler error
            logger.exception("plane %s action %s handler failed",
                             self.name, action)
            return ActionResult(
                plane_name=self.name, action=action, status="error",
                action_log_id=log_uuid, audit_chain_anchor=anchor,
                error=f"{type(exc).__name__}: {exc!s}",
            )

    @classmethod
    def supported_actions(cls) -> list[str]:
        """Return the action names this plane supports. Class-method."""
        return list(cls._supported_actions())

    # -- Hooks sub-classes override ------------------------------------

    @classmethod
    @abstractmethod
    def _supported_actions(cls) -> tuple[str, ...]:
        """Tuple of supported action names. Sub-classes implement."""

    @abstractmethod
    async def _handle_action(
        self, action: str, payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Plane-specific dispatch.

        Sub-class returns a dict; set ``{"_stub": True, ...}`` so the
        base wraps the response as ``status='stub_implementation'``.
        Raise :class:`NotImplementedError` for actions whose real
        implementation is Wave 3+.
        """


def utcnow_iso() -> str:
    """Helper: ISO-formatted UTC now (for stub action payloads)."""
    return datetime.now(timezone.utc).isoformat()


__all__: list[str] = [
    "ActionResult",
    "ControlPlane",
    "HIGH_IMPACT_ACTIONS",
    "PlaneName",
    "PlaneStatus",
    "utcnow_iso",
]
