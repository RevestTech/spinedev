"""spine_watcher.py - Drain per-role outbox.jsonl files into Postgres.

Pass B of the Spine Postgres integration.

Architecture
------------
The bash daemon writes one JSON line per cost row to
    <TEAM_BASE>/<role>/state/outbox.jsonl
alongside the existing costs.csv. This watcher process is the ONLY
consumer that advances the per-file byte-offset cursor stored at
    <TEAM_BASE>/<role>/state/outbox.cursor
The file bus remains source of truth; Postgres is a projection. If the
DB is down or this process dies, the daemon keeps writing CSV + JSONL
and the watcher catches up on restart.

Operational model
-----------------
- Single-process, single-connection. We use psycopg 3 with autocommit
  disabled and one transaction per JSONL line so that a poisoned line
  cannot poison earlier successful inserts. We did NOT use a connection
  pool: this process is single-threaded and has no use for one - a pool
  would add reconnect complexity without throughput benefit.
- Per-line failures (parse error, FK miss, etc.) are logged and skip
  the line; the cursor stops at the failing offset so the line stays
  in the outbox and a future tick can retry once the root cause clears.
- Connection failures trigger an exponential backoff reconnect (1s, 2s,
  4s, ... capped at 60s) and a fresh tick.
- SIGTERM / SIGINT: finish the current file's batch, commit, then exit
  cleanly. No work is dropped because the cursor is only advanced after
  a successful commit.

Deterministic UUIDs
-------------------
All UUIDs are uuid5() with a single namespace so re-runs converge and
multiple watcher instances (a future possibility) cannot create
duplicate org rows for the same logical entity.

Env vars
--------
DATABASE_URL      postgresql://...     (required)
TEAM_BASE         /path/to/teams       (required)
CURSOR_BASE       /path/for/cursors    (optional)
    When set, cursor files are written to <CURSOR_BASE>/<role>.cursor
    instead of next to the outbox file. This lets you mount TEAM_BASE
    read-only (as the docker-compose service does) while still
    persisting cursor state. When unset, cursors live next to the
    outbox at <TEAM_BASE>/<role>/state/outbox.cursor.
POLL_INTERVAL_S   5                    (default)
LOG_LEVEL         INFO                 (default)
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import signal
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import psycopg
from psycopg import errors as pg_errors


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Single namespace for every deterministic UUID this watcher produces. Picked
# arbitrarily but stable - changing it would orphan every previously-ingested
# row, so don't.
SPINE_NS = uuid.UUID("3f0c0b1d-8a0e-5f1d-9b6a-7c2e3d4f5061")

TEAM_NAME_DEFAULT = "default"


def _parse_engagement_id(obj: dict) -> str | None:
    """Pass I-3: extract a valid engagement_id from an outbox line.

    Returns the UUID string if obj["engagement_id"] is a non-empty string
    that parses as a UUID; None when missing, null, empty, or malformed.
    Malformed values log a warning so a buggy emitter doesn't go silent.
    """
    raw = obj.get("engagement_id")
    if raw is None:
        return None
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        uuid.UUID(raw)
    except (ValueError, AttributeError):
        log.warning("ignoring malformed engagement_id=%r on outbox line", raw)
        return None
    return raw


def _parse_tenant_id(obj: dict) -> str:
    """Pass K: extract tenant_id from an outbox line. Returns "default"
    when missing / malformed so the DB-side default holds and pre-K
    daemons (which don't emit the field) continue to ingest cleanly.
    """
    raw = obj.get("tenant_id")
    if raw is None:
        return "default"
    if not isinstance(raw, str):
        return "default"
    raw = raw.strip()
    if not raw:
        return "default"
    # 64 chars is plenty for a tenant slug. Trim defensively.
    return raw[:64]


# Pass K: cache of which tables actually have a tenant_id column. We
# probe information_schema once per process and once per table (lazy) so
# pre-V11 schemas don't hit UndefinedColumn mid-transaction (which would
# abort the txn and force a rollback). Key: table name; Value: True if
# the column exists, False otherwise.
_TENANT_COL_PRESENT: dict[str, bool] = {}


def _tenant_col(conn: psycopg.Connection, table: str) -> bool:
    """Return True if `table` has a `tenant_id` column. Result is cached
    per process; the cache key is the table name (no schema qualifier
    because every Spine table lives in the default 'public' schema).

    We deliberately swallow OperationalError because that is handled by
    the outer reconnect loop; here we just answer "no" so the caller
    falls back to the pre-V11 insert path and the outer loop reconnects
    on the next tick.
    """
    if table in _TENANT_COL_PRESENT:
        return _TENANT_COL_PRESENT[table]
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = %s AND column_name = 'tenant_id' LIMIT 1",
                (table,),
            )
            present = cur.fetchone() is not None
    except (psycopg.OperationalError, psycopg.InterfaceError):
        raise
    except pg_errors.Error:
        conn.rollback()
        present = False
    _TENANT_COL_PRESENT[table] = present
    if not present:
        log.warning(
            "%s.tenant_id missing (pre-V11 schema); ingesting without "
            "tenant attribution for this table. Run flyway migrate to "
            "apply V11.", table,
        )
    return present


# Pass M: cached column-presence flags for the V13 vitals projection.
# Mirrors the V11 tenant_id pattern: probe information_schema once per
# process so a pre-V13 schema doesn't UndefinedColumn mid-transaction.
_VITALS_COL_PRESENT: dict[str, bool] = {}


def _vitals_cols_present(conn: psycopg.Connection) -> bool:
    """Return True if spine_instance has the V13 vitals columns. Cached
    per process. Mirrors _tenant_col semantics."""
    key = "spine_instance.cpu_pct"
    if key in _VITALS_COL_PRESENT:
        return _VITALS_COL_PRESENT[key]
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = 'spine_instance' "
                "AND column_name = 'cpu_pct' LIMIT 1"
            )
            present = cur.fetchone() is not None
    except (psycopg.OperationalError, psycopg.InterfaceError):
        raise
    except pg_errors.Error:
        conn.rollback()
        present = False
    _VITALS_COL_PRESENT[key] = present
    if not present:
        log.warning(
            "spine_instance.cpu_pct missing (pre-V13 schema); ingesting "
            "without machine vitals projection. Run flyway migrate to "
            "apply V13.",
        )
    return present


def _instance_vitals_table_present(conn: psycopg.Connection) -> bool:
    """Return True if instance_vitals exists (V13+). Cached per process."""
    key = "instance_vitals"
    if key in _VITALS_COL_PRESENT:
        return _VITALS_COL_PRESENT[key]
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_name = 'instance_vitals' LIMIT 1"
            )
            present = cur.fetchone() is not None
    except (psycopg.OperationalError, psycopg.InterfaceError):
        raise
    except pg_errors.Error:
        conn.rollback()
        present = False
    _VITALS_COL_PRESENT[key] = present
    return present


def _extract_vitals(payload: object) -> dict | None:
    """Pull a clean dict of vital fields from the payload.vitals object.

    Returns None when vitals is missing / not a dict / all fields drop
    out as None — caller can short-circuit. Coerces numeric strings to
    float / int defensively; anything non-numeric becomes None and is
    skipped at write time.
    """
    if not isinstance(payload, dict):
        return None
    vitals = payload.get("vitals")
    if not isinstance(vitals, dict) or not vitals:
        return None
    out: dict = {}
    for k in VITAL_FIELDS:
        v = vitals.get(k)
        if v is None:
            continue
        # Integer fields stay int; float fields stay float. We don't
        # need to be strict here — psycopg coerces on the way in.
        if k in ("mem_used_mb", "mem_total_mb", "spine_mem_mb", "spine_proc_count"):
            try:
                out[k] = int(v)
            except (TypeError, ValueError):
                continue
        else:
            try:
                out[k] = float(v)
            except (TypeError, ValueError):
                continue
    return out or None


def _project_vitals(
    conn: psycopg.Connection,
    cur: psycopg.Cursor,
    instance_id: str,
    ts: dt.datetime,
    vitals: dict,
) -> None:
    """Project a vitals dict onto spine_instance (latest snapshot) and
    instance_vitals (time-series). No-op when the V13 schema isn't
    present. Caller has already opened a cursor inside a transaction.
    """
    if not _vitals_cols_present(conn):
        return
    # Build the UPDATE column list dynamically so missing fields stay
    # at their previous value rather than being clobbered to NULL.
    set_parts: list[str] = []
    params: list = []
    for k in VITAL_FIELDS:
        if k in vitals:
            set_parts.append(f"{k} = %s")
            params.append(vitals[k])
    set_parts.append("vitals_at = %s")
    params.append(ts)
    params.append(instance_id)
    try:
        cur.execute(
            "UPDATE spine_instance SET " + ", ".join(set_parts)
            + " WHERE instance_id = %s",
            params,
        )
    except pg_errors.UndefinedColumn:
        # Schema was rolled back between our probe and now — flag and bail.
        _VITALS_COL_PRESENT["spine_instance.cpu_pct"] = False
        conn.rollback()
        return

    # Append to the time-series table when it exists.
    if not _instance_vitals_table_present(conn):
        return
    cols = ["instance_id", "ts"]
    vals: list = [instance_id, ts]
    for k in VITAL_FIELDS:
        cols.append(k)
        vals.append(vitals.get(k))
    placeholders = ", ".join(["%s"] * len(cols))
    try:
        cur.execute(
            f"INSERT INTO instance_vitals ({', '.join(cols)}) "
            f"VALUES ({placeholders}) "
            f"ON CONFLICT (instance_id, ts) DO NOTHING",
            vals,
        )
    except pg_errors.UndefinedTable:
        _VITALS_COL_PRESENT["instance_vitals"] = False
        conn.rollback()


def _parse_idempotency_key(obj: dict) -> str | None:
    """Pass J F3: extract a non-empty string idempotency_key, or None.

    Unlike engagement_id we don't try to validate the shape — the daemon
    emits a sha-256 hex digest but a fallback host-and-counter string is
    also allowed. Any non-empty string is accepted; non-strings / blank
    values become None so the watcher can use ON CONFLICT to dedupe by
    (worker_id, idempotency_key) only when a key is actually present.
    """
    raw = obj.get("idempotency_key")
    if raw is None:
        return None
    if not isinstance(raw, str):
        return None
    raw = raw.strip()
    if not raw:
        return None
    # 256 chars is plenty (sha-256 hex is 64). Guard against accidental
    # blob writes.
    return raw[:256]

# Cost-row JSON contract emitted by lib/team-agent-daemon.sh::log_cost.
#
# REQUIRED fields — every outbox line must have these. The daemon has
# emitted these since Pass B, so adding a missing-field check is safe.
COST_REQUIRED_FIELDS = {
    "ts", "role", "mode", "slot", "phase", "tier",
    "wall_s", "rc", "outcome", "host_id", "instance_id",
}

# OPTIONAL fields — added in Pass C for token-level cost tracking. Older
# outbox lines written before this change are missing them; the watcher
# treats them as zero / NULL so backfill ingest stays compatible.
COST_OPTIONAL_FIELDS = {"tokens_in", "tokens_out", "cost_usd", "model_id"}

# Pass D: lifecycle-event JSON contract emitted by db-outbox.sh::
# spine_outbox_emit_event. Required fields for the event-table projection.
EVENT_REQUIRED_FIELDS = {
    "event_type", "ts", "role", "mode", "slot",
    "host_id", "instance_id", "payload",
}

# Pass H: instance-lifecycle event contract emitted by db-outbox.sh::
# spine_outbox_emit_instance_event. Routed into the spine_instance table.
# Required fields below are the minimum the V6 schema needs; the rest of
# the columns (os_user, project_*, version_*, spine_version) are nice-to-
# have and fall back to NULL / empty string when absent.
INSTANCE_EVENT_REQUIRED_FIELDS = {
    "event_type", "ts", "group_id", "host_id",
}
INSTANCE_EVENT_TYPES = {
    "InstanceStarted", "InstanceHeartbeat", "InstanceStopped",
}

# Pass M: machine vitals projected from InstanceHeartbeat (and the
# initial InstanceStarted) payloads. The bash side embeds these as a
# flat object under payload.vitals. The watcher copies them onto the
# spine_instance row (latest values) and appends a full snapshot row to
# instance_vitals (history). Both writes are guarded by a column-presence
# probe so pre-V13 schemas continue to ingest cleanly.
VITAL_FIELDS = (
    "cpu_pct", "mem_used_mb", "mem_total_mb",
    "disk_used_gb", "disk_total_gb",
    "load_avg_1m", "load_avg_5m", "load_avg_15m",
    "spine_cpu_pct", "spine_mem_mb", "spine_proc_count",
)

# Pass I-1: engagement-lifecycle event contract emitted by db-outbox.sh::
# spine_outbox_emit_engagement_event. Routed into the engagement table.
# Lives on the SAME top-level instance outbox as InstanceStarted etc., so
# discovery requires no new file. Only EngagementCreated writes a new
# engagement row this pass; EngagementStatusChanged is wired but accepted
# (logged) without mutating state -- later passes own that projection.
ENGAGEMENT_EVENT_REQUIRED_FIELDS = {
    "event_type", "ts", "engagement_id",
}
ENGAGEMENT_EVENT_TYPES = {
    "EngagementCreated", "EngagementStatusChanged", "EngagementMessage",
    "ArtifactCreated",
}

# Pass J: allowed artifact_kind values, matching the V1 enum exactly.
# Anything else from a buggy hook is coerced to 'other' so the FK doesn't
# fail.
ARTIFACT_KIND_VALUES = {"pr", "file", "test_report", "deploy", "memo", "other"}

# Pass I-2: the set of engagement.status values the watcher is willing to
# write. Guards against a buggy hook emitting `status=foo`. Kept in sync
# with the engagement_status enum in V7.
ENGAGEMENT_STATUS_VALUES = {
    "intake", "hardening", "planning", "awaiting_approval",
    "executing", "delivered", "cancelled",
}

# Pass I-2: roles allowed on engagement_message rows. The dashboard's
# /answer endpoint always emits role=human; the hook emits role=product
# (or planner/architect). Anything else is logged and skipped.
ENGAGEMENT_MESSAGE_ROLES = {
    "product", "planner", "architect", "conductor", "human",
}

# Pass I-2: allowed engagement_message.kind values.
ENGAGEMENT_MESSAGE_KINDS = {"question", "answer", "comment"}

# Map daemon tier vocabulary -> tier_id in the tier lookup table.
# The daemon parses "low" | "medium" | "high"; tier_id values are
# "low" | "medium" | "high" (see R__seed_lookups.sql). Identity map but
# explicit so a future rename can't silently corrupt the projection.
TIER_ID_MAP = {"low": "low", "medium": "medium", "high": "high"}

# Connection retry: 1, 2, 4, 8, 16, 32, 60, 60, ...
BACKOFF_CAP_S = 60


# ---------------------------------------------------------------------------
# Logging + signal handling
# ---------------------------------------------------------------------------

log = logging.getLogger("spine.watcher")


def _setup_logging() -> None:
    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,
    )


class _Shutdown:
    """SIGTERM/SIGINT-aware run flag. Set once, never cleared."""

    def __init__(self) -> None:
        self._stop = False

    def request(self, signum: int, _frame: object) -> None:
        log.info("shutdown signal %s received; will exit after current batch", signum)
        self._stop = True

    @property
    def requested(self) -> bool:
        return self._stop


# ---------------------------------------------------------------------------
# UUID helpers (deterministic)
# ---------------------------------------------------------------------------

def team_uuid(name: str) -> uuid.UUID:
    return uuid.uuid5(SPINE_NS, f"https://spine.local/team/{name}")


def worker_uuid(host_id: str, instance_id: str, team: str, handle: str) -> uuid.UUID:
    return uuid.uuid5(
        SPINE_NS,
        f"https://spine.local/worker/{host_id}/{instance_id}/{team}/{handle}",
    )


def assignment_uuid(worker_id: uuid.UUID, day: dt.date) -> uuid.UUID:
    return uuid.uuid5(
        SPINE_NS,
        f"https://spine.local/assignment/{worker_id}/{day.isoformat()}",
    )


# ---------------------------------------------------------------------------
# Role resolution
# ---------------------------------------------------------------------------

def resolve_role_id(conn: psycopg.Connection, daemon_role: str) -> str | None:
    """Return a role_id that exists in the role table for this daemon role.

    The daemon-side role vocabulary (engineer, planner, ...) matches the
    seeded role_id values directly except for engineer-discipline variants.
    Strategy:
      1. Exact match on role.role_id.
      2. Fall back to job_family lookup ('engineer' -> any role with that
         family_id, prefer the bare 'engineer' generic).
      3. Return None - caller logs a warning and skips.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM role WHERE role_id = %s", (daemon_role,))
        if cur.fetchone() is not None:
            return daemon_role

        cur.execute(
            "SELECT role_id FROM role WHERE family_id = %s "
            "ORDER BY (role_id = family_id) DESC, role_id ASC LIMIT 1",
            (daemon_role,),
        )
        row = cur.fetchone()
        if row is not None:
            return row[0]

    return None


def resolve_model_id(conn: psycopg.Connection, model_id: str | None) -> str | None:
    """Return model_id if a row exists in the model table, else None.

    Pass C: the daemon emits a model identifier picked up from the agent log
    (e.g., 'claude-sonnet-4-6'). The model table is seeded via
    R__model_pricing.sql but is a best-effort lookup table — unknown models
    must NOT FK-fail the cost row. We log a warning and write NULL into
    cost_row.model_id, which is allowed by the schema.
    """
    if not model_id:
        return None
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM model WHERE model_id = %s", (model_id,))
        if cur.fetchone() is not None:
            return model_id
    log.warning(
        "unknown model_id=%r in cost row; inserting NULL into cost_row.model_id. "
        "Add this model to R__model_pricing.sql to get FK-linked pricing.",
        model_id,
    )
    return None


# ---------------------------------------------------------------------------
# Outbox file discovery + cursor
# ---------------------------------------------------------------------------

@dataclass
class OutboxFile:
    role: str
    jsonl_path: Path
    cursor_path: Path

    @property
    def cursor_offset(self) -> int:
        try:
            return int(self.cursor_path.read_text().strip() or "0")
        except FileNotFoundError:
            return 0
        except (ValueError, OSError) as e:
            log.warning("cursor for %s unreadable (%s); resetting to 0", self.role, e)
            return 0

    def advance_cursor(self, new_offset: int) -> None:
        # Atomic write: tmp + rename so a crash mid-write doesn't corrupt.
        tmp = self.cursor_path.with_suffix(self.cursor_path.suffix + ".tmp")
        tmp.write_text(str(new_offset))
        os.replace(tmp, self.cursor_path)


#: Pseudo-role name used for the top-level instance outbox so its cursor
#: file stays distinct from any actual role's cursor. Underscore-prefixed
#: so it can never collide with a real role_id (which are seeded as
#: lowercase letters/dashes).
INSTANCE_OUTBOX_ROLE = "_instance"


def discover_outboxes(team_base: Path, cursor_base: Path | None) -> list[OutboxFile]:
    """Find every role's outbox.jsonl under TEAM_BASE, plus the single
    top-level instance outbox one level above (Pass H).

    Layout:
      jsonl:    <TEAM_BASE>/<role>/state/outbox.jsonl  (read-only in docker)
      cursor:   <CURSOR_BASE>/<role>.cursor            (writable; preferred)
                OR <TEAM_BASE>/<role>/state/outbox.cursor (legacy, when
                CURSOR_BASE is unset)
      instance: <TEAM_BASE>/../.instance-outbox.jsonl  (Pass H)
      cursor:   <CURSOR_BASE>/_instance.cursor         (preferred)
                OR next-to-outbox .instance-outbox.cursor (legacy fallback)
    """
    result: list[OutboxFile] = []
    if not team_base.is_dir():
        log.debug("team_base %s does not exist yet", team_base)
        return result

    for jsonl in sorted(team_base.glob("*/state/outbox.jsonl")):
        # role dir is two levels above the file: <role>/state/outbox.jsonl
        role = jsonl.parent.parent.name
        if cursor_base is not None:
            cursor_base.mkdir(parents=True, exist_ok=True)
            cursor = cursor_base / f"{role}.cursor"
        else:
            cursor = jsonl.with_name("outbox.cursor")
        result.append(OutboxFile(role=role, jsonl_path=jsonl, cursor_path=cursor))

    # Pass H: the instance outbox sits one level above the per-role
    # outboxes so the daemon never has to know about a "role" when
    # writing instance events.
    instance_jsonl = team_base.parent / ".instance-outbox.jsonl"
    if instance_jsonl.is_file():
        if cursor_base is not None:
            cursor_base.mkdir(parents=True, exist_ok=True)
            cursor = cursor_base / f"{INSTANCE_OUTBOX_ROLE}.cursor"
        else:
            cursor = instance_jsonl.with_name(".instance-outbox.cursor")
        result.append(OutboxFile(
            role=INSTANCE_OUTBOX_ROLE,
            jsonl_path=instance_jsonl,
            cursor_path=cursor,
        ))
    return result


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------

def _parse_ts(ts_str: str) -> dt.datetime:
    """Parse the daemon's ISO timestamp. The daemon writes UTC with a Z
    suffix; Python's fromisoformat accepts '+00:00' but not 'Z' before
    3.11 (3.11+ does). Normalize defensively."""
    if ts_str.endswith("Z"):
        ts_str = ts_str[:-1] + "+00:00"
    return dt.datetime.fromisoformat(ts_str)


def resolve_org_ids(
    conn: psycopg.Connection,
    cur: psycopg.Cursor,
    *,
    role: str,
    slot: str,
    host_id: str,
    instance_id: str,
    ts: dt.datetime,
    idempotency_key: str | None = None,
    tenant_id: str = "default",
) -> tuple[uuid.UUID, uuid.UUID | None, uuid.UUID | None, str | None]:
    """Resolve / upsert the (team, worker, assignment, role_id) tuple.

    Shared by cost and event ingest so both projections converge on the
    same UUIDs. Mirrors the original cost-path logic exactly:
      1. team_uuid('default') is the canonical team.
      2. worker handle is "<role>-<slot>" (slot != '-') else "<role>-manager".
      3. If a worker row already exists under (team_id, handle) we reuse
         that worker_id rather than the deterministic one we computed —
         this preserves identity across daemon restarts with new pids.
      4. assignment_uuid is re-derived from the *actual* worker_id so
         re-runs on the same day stay idempotent.

    Returns (team_id, worker_id, assignment_id, role_id). worker_id and
    assignment_id are None ONLY when role_id resolution fails — callers
    treat that as "skip this row, advance cursor".
    """
    handle = f"{role}-{slot}" if slot and slot != "-" else f"{role}-manager"
    tid = team_uuid(TEAM_NAME_DEFAULT)
    wid = worker_uuid(host_id, instance_id, TEAM_NAME_DEFAULT, handle)
    aid = assignment_uuid(wid, ts.date())

    # 1. Team (idempotent). Pass K: include tenant_id when V11 has been
    # applied; fall back to the bare insert against pre-V11 schemas.
    if _tenant_col(conn, "team"):
        cur.execute(
            "INSERT INTO team (team_id, name, tenant_id) "
            "VALUES (%s, %s, %s) "
            "ON CONFLICT (name) DO NOTHING",
            (tid, TEAM_NAME_DEFAULT, tenant_id),
        )
    else:
        cur.execute(
            "INSERT INTO team (team_id, name) VALUES (%s, %s) "
            "ON CONFLICT (name) DO NOTHING",
            (tid, TEAM_NAME_DEFAULT),
        )

    # 2. Resolve role_id and insert worker.
    role_id = resolve_role_id(conn, role)
    if role_id is None:
        log.warning(
            "no role_id found for daemon role=%r; skipping row at %s",
            role, ts.isoformat(),
        )
        return tid, None, None, None

    if _tenant_col(conn, "worker"):
        cur.execute(
            "INSERT INTO worker (worker_id, team_id, role_id, handle, "
            " host_id, instance_id, status, tenant_id) "
            "VALUES (%s, %s, %s, %s, %s, %s, 'idle', %s) "
            "ON CONFLICT (team_id, handle) DO NOTHING",
            (wid, tid, role_id, handle, host_id, instance_id, tenant_id),
        )
    else:
        cur.execute(
            "INSERT INTO worker (worker_id, team_id, role_id, handle, host_id, instance_id, status) "
            "VALUES (%s, %s, %s, %s, %s, %s, 'idle') "
            "ON CONFLICT (team_id, handle) DO NOTHING",
            (wid, tid, role_id, handle, host_id, instance_id),
        )

    # Re-resolve worker_id in case the worker already existed under a
    # different (host_id, instance_id). Keep aid in sync.
    cur.execute(
        "SELECT worker_id FROM worker WHERE team_id = %s AND handle = %s",
        (tid, handle),
    )
    row = cur.fetchone()
    if row is not None:
        wid = row[0]
        aid = assignment_uuid(wid, ts.date())

    # 3. Assignment (one per worker-day).
    #
    # Pass J F3: when an idempotency_key was supplied by the caller, write
    # it onto the assignment row. The (worker_id, idempotency_key) UNIQUE
    # index dedupes retried invocations across daemon restarts. We first
    # insert the assignment with the key; if the (worker_id, ts) row
    # already exists we update its idempotency_key only when it is NULL.
    # A separate INSERT-with-key probe lets the caller detect the
    # "duplicate ingest avoided" path -- but we keep the API simple by
    # surfacing it via assignment.idempotency_key inspection.
    has_assn_tenant = _tenant_col(conn, "assignment")
    if idempotency_key:
        try:
            if has_assn_tenant:
                cur.execute(
                    "INSERT INTO assignment "
                    "(assignment_id, worker_id, status, host_id, instance_id, "
                    " idempotency_key, tenant_id) "
                    "VALUES (%s, %s, 'active', %s, %s, %s, %s) "
                    "ON CONFLICT (assignment_id) DO UPDATE SET "
                    "  idempotency_key = COALESCE(assignment.idempotency_key, "
                    "                             EXCLUDED.idempotency_key)",
                    (aid, wid, host_id, instance_id, idempotency_key, tenant_id),
                )
            else:
                cur.execute(
                    "INSERT INTO assignment "
                    "(assignment_id, worker_id, status, host_id, instance_id, "
                    " idempotency_key) "
                    "VALUES (%s, %s, 'active', %s, %s, %s) "
                    "ON CONFLICT (assignment_id) DO UPDATE SET "
                    "  idempotency_key = COALESCE(assignment.idempotency_key, "
                    "                             EXCLUDED.idempotency_key)",
                    (aid, wid, host_id, instance_id, idempotency_key),
                )
        except pg_errors.UniqueViolation:
            # Another assignment row for this worker already carries this
            # idempotency_key -- a retried outbox line. Roll the savepoint
            # back at the caller level by re-raising; the caller treats
            # this as "duplicate ingest avoided".
            raise
    else:
        if has_assn_tenant:
            cur.execute(
                "INSERT INTO assignment "
                "(assignment_id, worker_id, status, host_id, instance_id, tenant_id) "
                "VALUES (%s, %s, 'active', %s, %s, %s) "
                "ON CONFLICT (assignment_id) DO NOTHING",
                (aid, wid, host_id, instance_id, tenant_id),
            )
        else:
            cur.execute(
                "INSERT INTO assignment "
                "(assignment_id, worker_id, status, host_id, instance_id) "
                "VALUES (%s, %s, 'active', %s, %s) "
                "ON CONFLICT (assignment_id) DO NOTHING",
                (aid, wid, host_id, instance_id),
            )

    return tid, wid, aid, role_id


def ingest_cost_line(conn: psycopg.Connection, line: str) -> None:
    """Parse one JSONL line and insert into Postgres in a single tx.

    Raises on parse errors and DB errors. Callers decide how to react
    (skip vs. retry). Idempotent: re-running the same line is a no-op
    thanks to ON CONFLICT DO NOTHING on every insert.
    """
    obj = json.loads(line)

    missing = COST_REQUIRED_FIELDS - obj.keys()
    if missing:
        raise ValueError(f"cost row missing fields: {sorted(missing)}")

    ts = _parse_ts(obj["ts"])
    role = obj["role"]
    mode = obj["mode"]
    slot = obj["slot"]
    phase = obj["phase"]
    tier = obj["tier"]
    wall_s = float(obj["wall_s"])
    rc = int(obj["rc"])
    host_id = obj["host_id"]
    instance_id = obj["instance_id"]

    # Pass C: optional token/cost fields. Old outbox lines (pre-Pass-C) lack
    # these — default to zero / empty so legacy lines continue to ingest.
    def _opt_int(key: str) -> int:
        v = obj.get(key, 0)
        try:
            return int(v) if v is not None else 0
        except (TypeError, ValueError):
            return 0

    def _opt_float(key: str) -> float:
        v = obj.get(key, 0)
        try:
            return float(v) if v is not None else 0.0
        except (TypeError, ValueError):
            return 0.0

    tokens_in = _opt_int("tokens_in")
    tokens_out = _opt_int("tokens_out")
    cost_usd = _opt_float("cost_usd")
    raw_model_id = obj.get("model_id") or None
    if isinstance(raw_model_id, str) and not raw_model_id.strip():
        raw_model_id = None

    tier_id = TIER_ID_MAP.get(tier)
    # tier_id may be None if the daemon ever emits a new tier value.

    # Pass I-3: optional engagement attribution. NULL when unset / pre-V9
    # outbox lines. When the V9 columns are missing (engagement_links
    # migration not yet applied) we retry the INSERT without the column
    # and log a one-shot warning.
    engagement_id = _parse_engagement_id(obj)

    # Pass J F3: optional idempotency key. Daemon emits a sha-256 hex
    # digest combining directive hash + instance id + invocation counter.
    # Watcher stamps it onto assignment.idempotency_key (UNIQUE constraint
    # on (worker_id, idempotency_key)). A second outbox line carrying the
    # same key is detected by the UniqueViolation and the whole cost
    # ingest is skipped to avoid double-counting.
    idempotency_key = _parse_idempotency_key(obj)

    # Pass K: tenant scoping.
    tenant_id = _parse_tenant_id(obj)

    try:
        with conn.transaction():
            with conn.cursor() as cur:
                tid, wid, aid, role_id = resolve_org_ids(
                    conn, cur,
                    role=role, slot=slot,
                    host_id=host_id, instance_id=instance_id, ts=ts,
                    idempotency_key=idempotency_key,
                    tenant_id=tenant_id,
                )
                _ingest_cost_body(
                    conn, cur,
                    tid=tid, wid=wid, aid=aid, role_id=role_id,
                    ts=ts, tier_id=tier_id, mode=mode,
                    phase=phase, wall_s=wall_s, rc=rc,
                    tokens_in=tokens_in, tokens_out=tokens_out,
                    cost_usd=cost_usd, raw_model_id=raw_model_id,
                    engagement_id=engagement_id, obj=obj,
                    tenant_id=tenant_id,
                )
    except pg_errors.UniqueViolation:
        # Pass J F3: dedupe path. Another outbox line already wrote an
        # assignment row carrying this idempotency_key, so the current
        # line is a retry. Cost row + audit event are intentionally
        # skipped to avoid double-counting.
        if idempotency_key:
            log.info(
                "duplicate ingest avoided (idempotency_key=%s, role=%s, "
                "host=%s, instance=%s, ts=%s)",
                idempotency_key, role, host_id, instance_id, ts.isoformat(),
            )
        else:
            # Without a key, a UniqueViolation here would be a genuine
            # programming error -- re-raise.
            raise
    return


def _ingest_cost_body(
    conn: psycopg.Connection,
    cur: psycopg.Cursor,
    *,
    tid: uuid.UUID,
    wid: uuid.UUID | None,
    aid: uuid.UUID | None,
    role_id: str | None,
    ts: dt.datetime,
    tier_id: str | None,
    mode: str,
    phase: str,
    wall_s: float,
    rc: int,
    tokens_in: int,
    tokens_out: int,
    cost_usd: float,
    raw_model_id: str | None,
    engagement_id: str | None,
    obj: dict,
    tenant_id: str = "default",
) -> None:
    """Body of ingest_cost_line that runs INSIDE the transaction context.

    Factored out so the UniqueViolation handler in ingest_cost_line can
    cleanly bail without leaking partial inserts. Behavior preserved
    1:1 from the pre-Pass-J code path.
    """
    if role_id is None:
        # Unknown role — resolve_org_ids already logged. Treat as
        # success so the cursor advances and we don't get wedged.
        return

    # Cost row (PK on assignment_id, ts).
    #
    # Pass C: also project tokens_in / tokens_out / cost_usd / model_id.
    # Pass I-3: also project engagement_id when present.
    # Pass K: also project tenant_id; falls back to the bare-V9 insert
    # on pre-V11 schemas, then again to the bare-V1 insert on pre-V9.
    # model_id is resolved against the model lookup table; unknown
    # values become NULL rather than FK-failing the whole insert.
    resolved_model_id = resolve_model_id(conn, raw_model_id)
    has_cost_tenant = _tenant_col(conn, "cost_row")
    if has_cost_tenant:
        try:
            cur.execute(
                "INSERT INTO cost_row "
                "(assignment_id, ts, tier_id, mode, phase, wall_s, rc, "
                " tokens_in, tokens_out, cost_usd, model_id, engagement_id, tenant_id) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (assignment_id, ts) DO NOTHING",
                (aid, ts, tier_id, mode, phase, wall_s, rc,
                 tokens_in, tokens_out, cost_usd, resolved_model_id,
                 engagement_id, tenant_id),
            )
        except pg_errors.UndefinedColumn:
            # Should not happen: _tenant_col already said the column
            # exists. Surface and fall back.
            log.warning(
                "cost_row insert with tenant_id failed; retrying without."
            )
            _TENANT_COL_PRESENT["cost_row"] = False
            has_cost_tenant = False
    if not has_cost_tenant:
        try:
            cur.execute(
                "INSERT INTO cost_row "
                "(assignment_id, ts, tier_id, mode, phase, wall_s, rc, "
                " tokens_in, tokens_out, cost_usd, model_id, engagement_id) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (assignment_id, ts) DO NOTHING",
                (aid, ts, tier_id, mode, phase, wall_s, rc,
                 tokens_in, tokens_out, cost_usd, resolved_model_id,
                 engagement_id),
            )
        except pg_errors.UndefinedColumn:
            # Pre-V9: cost_row.engagement_id doesn't exist yet. Re-do
            # the insert without that column so ingestion still
            # succeeds; the column will be backfilled (left NULL) once
            # the migration applies.
            log.warning(
                "cost_row.engagement_id missing (pre-V9 schema); "
                "ingesting without engagement attribution. Run flyway "
                "migrate to apply V9 and pick this up."
            )
            cur.execute(
                "INSERT INTO cost_row "
                "(assignment_id, ts, tier_id, mode, phase, wall_s, rc, "
                " tokens_in, tokens_out, cost_usd, model_id) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (assignment_id, ts) DO NOTHING",
                (aid, ts, tier_id, mode, phase, wall_s, rc,
                 tokens_in, tokens_out, cost_usd, resolved_model_id),
            )

    # Audit event with the original JSON line as payload.
    # Pass I-3: stamp engagement_id on the audit event too so
    # v_engagement_timeline picks it up alongside lifecycle events.
    # Pass K: stamp tenant_id when V11 has been applied.
    has_event_tenant = _tenant_col(conn, "event")
    if has_event_tenant:
        try:
            cur.execute(
                "INSERT INTO event (ts, type, team_id, worker_id, "
                "assignment_id, payload_json, engagement_id, tenant_id) "
                "VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s)",
                (ts, "IngestedCostRow", tid, wid, aid,
                 json.dumps(obj), engagement_id, tenant_id),
            )
        except pg_errors.UndefinedColumn:
            log.warning(
                "event insert with tenant_id failed; retrying without."
            )
            _TENANT_COL_PRESENT["event"] = False
            has_event_tenant = False
    if not has_event_tenant:
        try:
            cur.execute(
                "INSERT INTO event (ts, type, team_id, worker_id, "
                "assignment_id, payload_json, engagement_id) "
                "VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s)",
                (ts, "IngestedCostRow", tid, wid, aid,
                 json.dumps(obj), engagement_id),
            )
        except pg_errors.UndefinedColumn:
            log.warning(
                "event.engagement_id missing (pre-V9 schema); "
                "ingesting audit event without engagement attribution."
            )
            cur.execute(
                "INSERT INTO event (ts, type, team_id, worker_id, "
                "assignment_id, payload_json) "
                "VALUES (%s, %s, %s, %s, %s, %s::jsonb)",
                (ts, "IngestedCostRow", tid, wid, aid, json.dumps(obj)),
            )


# Pass E: lifecycle events that mark the END of an invocation. The
# watcher uses these to set assignment.ended_at and (for the manager/
# worker-completion variants) flip assignment.status -> 'done'.
EVENT_TERMINAL_TYPES = {
    "Reaped", "ReportWritten", "PlanWritten",
    "AggregateCompleted", "WorkerCompleted",
}
# Subset of EVENT_TERMINAL_TYPES that also marks the assignment 'done'.
# PlanWritten / Reaped do NOT — a plan is followed by an aggregate step,
# and a Reaped event represents a bad outcome that the human still wants
# to inspect as 'active'.
EVENT_DONE_TYPES = {"ReportWritten", "AggregateCompleted", "WorkerCompleted"}


def ingest_event_line(conn: psycopg.Connection, obj: dict) -> None:
    """Pass D: project one lifecycle event line into the event table.

    Unlike cost lines, lifecycle events do NOT touch cost_row. The whole
    outer outbox JSON is stuffed into payload_json so we keep full
    provenance (event_type, host_id, instance_id, the inner payload, etc.)
    rather than just the inner payload.

    Required outer fields are validated against EVENT_REQUIRED_FIELDS.
    The watcher's outer router has already confirmed type == 'event'.

    Re-running the same line will create a duplicate row in the event
    table — the event table has no natural unique key and is append-only
    by design. The cursor file prevents replays in normal operation.

    Pass E: in addition to the event insert, project specific event types
    onto the assignment row:
      * InvocationStarted   -> assignment.started_at = LEAST(existing, ts)
      * Reaped/ReportWritten/PlanWritten/AggregateCompleted/WorkerCompleted
                            -> assignment.ended_at   = GREATEST(existing, ts)
      * ReportWritten/AggregateCompleted/WorkerCompleted
                            -> assignment.status = 'done' (only when 'active')
    All projections are idempotent — re-ingesting the same event line is
    a no-op against assignment because LEAST/GREATEST already match.
    """
    missing = EVENT_REQUIRED_FIELDS - obj.keys()
    if missing:
        raise ValueError(f"event row missing fields: {sorted(missing)}")

    ts = _parse_ts(obj["ts"])
    event_type = obj["event_type"]
    role = obj["role"]
    slot = obj["slot"]
    host_id = obj["host_id"]
    instance_id = obj["instance_id"]

    if not isinstance(event_type, str) or not event_type:
        raise ValueError(f"event_type must be non-empty string, got {event_type!r}")

    # Pass I-3: optional engagement attribution. Same shape and fallbacks
    # as ingest_cost_line.
    engagement_id = _parse_engagement_id(obj)
    # Pass K: tenant scoping.
    tenant_id = _parse_tenant_id(obj)

    with conn.transaction():
        with conn.cursor() as cur:
            tid, wid, aid, role_id = resolve_org_ids(
                conn, cur,
                role=role, slot=slot,
                host_id=host_id, instance_id=instance_id, ts=ts,
                tenant_id=tenant_id,
            )
            if role_id is None:
                # Unknown role: log + skip so the cursor advances. Same
                # contract as ingest_cost_line.
                return

            has_event_tenant = _tenant_col(conn, "event")
            if has_event_tenant:
                try:
                    cur.execute(
                        "INSERT INTO event (ts, type, team_id, worker_id, "
                        "assignment_id, payload_json, engagement_id, tenant_id) "
                        "VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s)",
                        (ts, event_type, tid, wid, aid,
                         json.dumps(obj), engagement_id, tenant_id),
                    )
                except pg_errors.UndefinedColumn:
                    _TENANT_COL_PRESENT["event"] = False
                    has_event_tenant = False
            if not has_event_tenant:
                try:
                    cur.execute(
                        "INSERT INTO event (ts, type, team_id, worker_id, "
                        "assignment_id, payload_json, engagement_id) "
                        "VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s)",
                        (ts, event_type, tid, wid, aid,
                         json.dumps(obj), engagement_id),
                    )
                except pg_errors.UndefinedColumn:
                    log.warning(
                        "event.engagement_id missing (pre-V9 schema); "
                        "ingesting lifecycle event without engagement "
                        "attribution. Apply V9 to pick this up."
                    )
                    cur.execute(
                        "INSERT INTO event (ts, type, team_id, worker_id, "
                        "assignment_id, payload_json) "
                        "VALUES (%s, %s, %s, %s, %s, %s::jsonb)",
                        (ts, event_type, tid, wid, aid, json.dumps(obj)),
                    )

            # Pass E: project terminal/start events back onto assignment.
            # COALESCE wraps the existing value so a NULL started_at /
            # ended_at gets replaced (LEAST/GREATEST in Postgres return
            # NULL on any NULL argument otherwise). Idempotent.
            if event_type == "InvocationStarted":
                cur.execute(
                    "UPDATE assignment "
                    "SET started_at = LEAST(COALESCE(started_at, %s), %s) "
                    "WHERE assignment_id = %s",
                    (ts, ts, aid),
                )
            elif event_type in EVENT_TERMINAL_TYPES:
                cur.execute(
                    "UPDATE assignment "
                    "SET ended_at = GREATEST(COALESCE(ended_at, %s), %s) "
                    "WHERE assignment_id = %s",
                    (ts, ts, aid),
                )
                if event_type in EVENT_DONE_TYPES:
                    # Guard with status='active' so we don't downgrade an
                    # already-terminal state (e.g., a previous abandon).
                    cur.execute(
                        "UPDATE assignment SET status = 'done' "
                        "WHERE assignment_id = %s AND status = 'active'",
                        (aid,),
                    )


def ingest_instance_event(conn: psycopg.Connection, obj: dict) -> None:
    """Pass H: project one instance-lifecycle event into the spine_instance
    table. Unlike the per-role event projection this one does NOT touch
    cost_row / assignment / event — instances stand alone.

    Routing by event_type:
      * InstanceStarted   -> UPSERT row, status='alive', set started/last_seen
                             to ts, refresh captured fields. Restarted
                             instance (same group_id) keeps started_at
                             pinned to the earlier value (LEAST).
      * InstanceHeartbeat -> UPDATE last_seen_at + status='alive'. If 0
                             rows affected (heartbeat before start),
                             ignore silently — shouldn't normally happen.
      * InstanceStopped   -> UPDATE stopped_at + last_seen_at + status='stopped'.

    All projections are idempotent. Unknown event_type logs and skips
    (cursor still advances) so a future schema bump from the daemon side
    doesn't wedge the watcher.
    """
    missing = INSTANCE_EVENT_REQUIRED_FIELDS - obj.keys()
    if missing:
        raise ValueError(f"instance event missing fields: {sorted(missing)}")

    ts = _parse_ts(obj["ts"])
    event_type = obj["event_type"]
    group_id = obj["group_id"]
    host_id = obj["host_id"]

    if not isinstance(group_id, str) or not group_id:
        raise ValueError(f"instance event group_id must be non-empty string, got {group_id!r}")
    if event_type not in INSTANCE_EVENT_TYPES:
        log.warning("skip unknown instance event_type=%r", event_type)
        return

    os_user = obj.get("os_user") or None
    project_path = obj.get("project_path") or None
    project_slug = obj.get("project_slug") or None
    version_sha = obj.get("version_sha") or None
    version_short = obj.get("version_short") or None
    spine_version = obj.get("spine_version") or None
    # Pass K: tenant scoping for instance rows.
    tenant_id = _parse_tenant_id(obj)

    # Pass L: channel scoping. The daemon emits a top-level "channel" key on
    # the instance event payload (set from SPINE_UPDATE_CHANNEL). We persist
    # it into spine_instance.metadata_json so v_instance_drift can compute
    # per-channel drift status. Missing channel -> we don't overwrite the
    # existing metadata so the InstanceHeartbeat path can run without
    # stomping a channel set by InstanceStarted.
    payload = obj.get("payload") or {}
    channel = None
    if isinstance(payload, dict):
        c = payload.get("channel")
        if isinstance(c, str) and c.strip():
            channel = c.strip()

    # Pass M: pull machine vitals out of the payload if present. Stored
    # both as the latest snapshot on spine_instance and as one row in
    # the instance_vitals time series. Missing -> None -> no-op.
    vitals = _extract_vitals(payload)

    with conn.transaction():
        with conn.cursor() as cur:
            if event_type == "InstanceStarted":
                # UPSERT. ON CONFLICT keeps the earliest started_at
                # (LEAST) so a restart reuses the original birth time,
                # but bumps last_seen_at and refreshes the captured
                # version metadata.
                # Pass L: when a channel was provided on the payload,
                # merge it into metadata_json. Use jsonb || to preserve
                # any other keys callers might add later. When channel
                # is None we leave metadata_json untouched.
                channel_jsonb = (
                    json.dumps({"channel": channel}) if channel else None
                )
                # Pass K: include tenant_id when V11 has been applied.
                has_inst_tenant = _tenant_col(conn, "spine_instance")
                if has_inst_tenant:
                    try:
                        cur.execute(
                            """
                            INSERT INTO spine_instance (
                              instance_id, host_id, os_user, project_path, project_slug,
                              version_sha, version_short, spine_version,
                              started_at, last_seen_at, status, tenant_id,
                              metadata_json
                            ) VALUES (
                              %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'alive', %s,
                              COALESCE(%s::jsonb, '{}'::jsonb)
                            )
                            ON CONFLICT (instance_id) DO UPDATE SET
                              host_id       = EXCLUDED.host_id,
                              os_user       = COALESCE(EXCLUDED.os_user, spine_instance.os_user),
                              project_path  = COALESCE(EXCLUDED.project_path, spine_instance.project_path),
                              project_slug  = COALESCE(EXCLUDED.project_slug, spine_instance.project_slug),
                              version_sha   = COALESCE(EXCLUDED.version_sha, spine_instance.version_sha),
                              version_short = COALESCE(EXCLUDED.version_short, spine_instance.version_short),
                              spine_version = COALESCE(EXCLUDED.spine_version, spine_instance.spine_version),
                              started_at    = LEAST(spine_instance.started_at, EXCLUDED.started_at),
                              last_seen_at  = GREATEST(spine_instance.last_seen_at, EXCLUDED.last_seen_at),
                              status        = 'alive',
                              stopped_at    = NULL,
                              tenant_id     = COALESCE(spine_instance.tenant_id, EXCLUDED.tenant_id),
                              metadata_json = CASE
                                WHEN %s::jsonb IS NULL THEN spine_instance.metadata_json
                                ELSE spine_instance.metadata_json || %s::jsonb
                              END
                            """,
                            (group_id, host_id, os_user, project_path, project_slug,
                             version_sha, version_short, spine_version, ts, ts, tenant_id,
                             channel_jsonb,
                             channel_jsonb, channel_jsonb),
                        )
                        # Pass M: initial vitals snapshot, if provided.
                        if vitals is not None:
                            _project_vitals(conn, cur, group_id, ts, vitals)
                        return
                    except pg_errors.UndefinedColumn:
                        _TENANT_COL_PRESENT["spine_instance"] = False

                cur.execute(
                    """
                    INSERT INTO spine_instance (
                      instance_id, host_id, os_user, project_path, project_slug,
                      version_sha, version_short, spine_version,
                      started_at, last_seen_at, status, metadata_json
                    ) VALUES (
                      %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'alive',
                      COALESCE(%s::jsonb, '{}'::jsonb)
                    )
                    ON CONFLICT (instance_id) DO UPDATE SET
                      host_id       = EXCLUDED.host_id,
                      os_user       = COALESCE(EXCLUDED.os_user, spine_instance.os_user),
                      project_path  = COALESCE(EXCLUDED.project_path, spine_instance.project_path),
                      project_slug  = COALESCE(EXCLUDED.project_slug, spine_instance.project_slug),
                      version_sha   = COALESCE(EXCLUDED.version_sha, spine_instance.version_sha),
                      version_short = COALESCE(EXCLUDED.version_short, spine_instance.version_short),
                      spine_version = COALESCE(EXCLUDED.spine_version, spine_instance.spine_version),
                      started_at    = LEAST(spine_instance.started_at, EXCLUDED.started_at),
                      last_seen_at  = GREATEST(spine_instance.last_seen_at, EXCLUDED.last_seen_at),
                      status        = 'alive',
                      stopped_at    = NULL,
                      metadata_json = CASE
                        WHEN %s::jsonb IS NULL THEN spine_instance.metadata_json
                        ELSE spine_instance.metadata_json || %s::jsonb
                      END
                    """,
                    (group_id, host_id, os_user, project_path, project_slug,
                     version_sha, version_short, spine_version, ts, ts,
                     channel_jsonb,
                     channel_jsonb, channel_jsonb),
                )
                # Pass M: initial vitals snapshot, if provided.
                if vitals is not None:
                    _project_vitals(conn, cur, group_id, ts, vitals)
            elif event_type == "InstanceHeartbeat":
                # Pass L: heartbeats may carry an updated channel; merge it
                # into metadata_json the same way InstanceStarted does so
                # the drift view stays accurate across restarts.
                channel_jsonb = (
                    json.dumps({"channel": channel}) if channel else None
                )
                cur.execute(
                    """
                    UPDATE spine_instance
                    SET last_seen_at = GREATEST(last_seen_at, %s),
                        status = CASE WHEN status = 'stopped' THEN status ELSE 'alive' END,
                        metadata_json = CASE
                          WHEN %s::jsonb IS NULL THEN metadata_json
                          ELSE metadata_json || %s::jsonb
                        END
                    WHERE instance_id = %s
                    """,
                    (ts, channel_jsonb, channel_jsonb, group_id),
                )
                # rowcount == 0 means a heartbeat arrived before the
                # InstanceStarted (shouldn't normally happen). Silent
                # skip so the cursor advances. Operators can grep
                # heartbeats in the watcher log if they care.
                # Pass M: project vitals onto spine_instance + append to
                # instance_vitals. Only writes when the row exists (the
                # FK on instance_vitals would fail otherwise).
                if vitals is not None and cur.rowcount > 0:
                    _project_vitals(conn, cur, group_id, ts, vitals)
            elif event_type == "InstanceStopped":
                cur.execute(
                    """
                    UPDATE spine_instance
                    SET stopped_at = %s,
                        last_seen_at = GREATEST(last_seen_at, %s),
                        status = 'stopped'
                    WHERE instance_id = %s
                    """,
                    (ts, ts, group_id),
                )


def ingest_engagement_event(conn: psycopg.Connection, obj: dict) -> None:
    """Pass I-1: project one engagement-lifecycle event into the engagement
    table. Lives on the same top-level instance outbox as InstanceStarted
    etc.; routing happens on the outer "type":"engagement" field.

    EngagementCreated:
      INSERT a new engagement row using the payload fields. ON CONFLICT
      (team_id, slug) DO NOTHING so re-ingesting the same line is a no-op.
      team_id is resolved via team_uuid(TEAM_NAME_DEFAULT) -- Pass I-1 is
      single-team; multi-team gets a payload.team_name in a later pass.

    EngagementStatusChanged:
      Accepted (logged) without mutating state. Pass I-2 / I-3 will own
      the status-transition projection; emitting it now lets the dashboard
      backend wire the call site without a watcher change later.

    Unknown event_type logs and skips (cursor still advances).
    """
    missing = ENGAGEMENT_EVENT_REQUIRED_FIELDS - obj.keys()
    if missing:
        raise ValueError(f"engagement event missing fields: {sorted(missing)}")

    ts = _parse_ts(obj["ts"])
    event_type = obj["event_type"]
    engagement_id = obj["engagement_id"]

    if not isinstance(engagement_id, str) or not engagement_id:
        raise ValueError(
            f"engagement event engagement_id must be non-empty string, "
            f"got {engagement_id!r}"
        )
    if event_type not in ENGAGEMENT_EVENT_TYPES:
        log.warning("skip unknown engagement event_type=%r", event_type)
        return

    payload = obj.get("payload") or {}
    if not isinstance(payload, dict):
        # Defensive: payload was expected to be an object. Treat anything
        # else as empty so we don't crash on a malformed line we can still
        # partially honor (the engagement_id + event_type are enough to
        # log).
        payload = {}

    # Pass K: tenant scoping for engagement-derived rows.
    tenant_id = _parse_tenant_id(obj)

    tid = team_uuid(TEAM_NAME_DEFAULT)

    with conn.transaction():
        with conn.cursor() as cur:
            # Ensure the default team exists (mirrors resolve_org_ids).
            if _tenant_col(conn, "team"):
                cur.execute(
                    "INSERT INTO team (team_id, name, tenant_id) "
                    "VALUES (%s, %s, %s) "
                    "ON CONFLICT (name) DO NOTHING",
                    (tid, TEAM_NAME_DEFAULT, tenant_id),
                )
            else:
                cur.execute(
                    "INSERT INTO team (team_id, name) VALUES (%s, %s) "
                    "ON CONFLICT (name) DO NOTHING",
                    (tid, TEAM_NAME_DEFAULT),
                )

            if event_type == "EngagementCreated":
                title = payload.get("title") or "(untitled)"
                slug = payload.get("slug")
                if not slug:
                    raise ValueError(
                        "EngagementCreated payload requires a 'slug' field"
                    )
                client = payload.get("client") or None
                requirements_uri = payload.get("requirements_uri") or None
                metadata_json = json.dumps(payload.get("metadata") or {})

                has_eng_tenant = _tenant_col(conn, "engagement")
                if has_eng_tenant:
                    try:
                        cur.execute(
                            "INSERT INTO engagement "
                            "(engagement_id, team_id, title, slug, client, "
                            " status, requirements_uri, metadata_json, "
                            " created_at, updated_at, tenant_id) "
                            "VALUES (%s, %s, %s, %s, %s, 'intake', %s, %s::jsonb, "
                            "%s, %s, %s) "
                            "ON CONFLICT (team_id, slug) DO NOTHING",
                            (engagement_id, tid, title, slug, client,
                             requirements_uri, metadata_json, ts, ts, tenant_id),
                        )
                    except pg_errors.UndefinedColumn:
                        _TENANT_COL_PRESENT["engagement"] = False
                        has_eng_tenant = False
                if not has_eng_tenant:
                    cur.execute(
                        "INSERT INTO engagement "
                        "(engagement_id, team_id, title, slug, client, "
                        " status, requirements_uri, metadata_json, "
                        " created_at, updated_at) "
                        "VALUES (%s, %s, %s, %s, %s, 'intake', %s, %s::jsonb, "
                        "%s, %s) "
                        "ON CONFLICT (team_id, slug) DO NOTHING",
                        (engagement_id, tid, title, slug, client,
                         requirements_uri, metadata_json, ts, ts),
                    )
            elif event_type == "EngagementStatusChanged":
                # Pass I-2: project the new status (and optional URI
                # columns) onto the engagement row. The payload may carry
                # any subset of new_status / req_uri / open_questions_uri
                # / plan_uri / planner_report_uri / architect_adr_uris.
                # We build the UPDATE dynamically so an unset key stays
                # at its previous DB value rather than being clobbered to
                # NULL.
                new_status = payload.get("new_status")
                if new_status is not None and new_status not in ENGAGEMENT_STATUS_VALUES:
                    log.warning(
                        "EngagementStatusChanged: unknown new_status=%r for "
                        "engagement_id=%s; skipping status mutation",
                        new_status, engagement_id,
                    )
                    new_status = None

                set_parts: list[str] = []
                params: list[object] = []

                if new_status is not None:
                    set_parts.append("status = %s::engagement_status")
                    params.append(new_status)
                    # approved_at / delivered_at audit timestamps follow
                    # well-known transitions. Use COALESCE so re-ingesting
                    # the same event doesn't overwrite an earlier value.
                    if new_status == "awaiting_approval":
                        set_parts.append("approved_at = COALESCE(approved_at, %s)")
                        params.append(ts)
                    elif new_status == "delivered":
                        set_parts.append("delivered_at = COALESCE(delivered_at, %s)")
                        params.append(ts)
                    elif new_status == "cancelled":
                        set_parts.append("closed_at = COALESCE(closed_at, %s)")
                        params.append(ts)

                for key in (
                    "req_uri", "open_questions_uri",
                    "planner_report_uri", "plan_uri",
                ):
                    val = payload.get(key)
                    if val is not None:
                        set_parts.append(f"{key} = %s")
                        params.append(val)

                adr_uris = payload.get("architect_adr_uris")
                if adr_uris is not None:
                    # Accept either a list or a JSON-encoded string. The
                    # column is JSONB so we encode here.
                    if isinstance(adr_uris, str):
                        try:
                            adr_uris = json.loads(adr_uris)
                        except json.JSONDecodeError:
                            adr_uris = None
                    if isinstance(adr_uris, list):
                        set_parts.append("architect_adr_uris = %s::jsonb")
                        params.append(json.dumps(adr_uris))

                if not set_parts:
                    log.info(
                        "EngagementStatusChanged engagement_id=%s carried no "
                        "actionable fields; payload=%s",
                        engagement_id, payload,
                    )
                else:
                    params.append(engagement_id)
                    sql = (
                        "UPDATE engagement SET "
                        + ", ".join(set_parts)
                        + " WHERE engagement_id = %s"
                    )
                    cur.execute(sql, tuple(params))
                    if cur.rowcount == 0:
                        log.warning(
                            "EngagementStatusChanged engagement_id=%s did not "
                            "match an engagement row (Created event lost?)",
                            engagement_id,
                        )

            elif event_type == "ArtifactCreated":
                # Pass J: insert one row into the artifact table tagged
                # with this engagement_id. artifact_id is uuid5 of
                # (namespace, engagement_id, uri) so re-runs of the same
                # hook (e.g., the same report file picked up twice) are
                # naturally idempotent without relying on ON CONFLICT.
                raw_kind  = (payload.get("kind") or "other").lower().strip()
                kind      = raw_kind if raw_kind in ARTIFACT_KIND_VALUES else "other"
                uri       = payload.get("uri") or ""
                title     = payload.get("title") or None
                assn_raw  = payload.get("assignment_id")
                metadata  = payload.get("metadata") or {}
                if not isinstance(metadata, dict):
                    metadata = {}
                if not uri or not isinstance(uri, str):
                    log.warning(
                        "ArtifactCreated skipped: missing/blank uri for "
                        "engagement_id=%s", engagement_id,
                    )
                    return
                if raw_kind != kind:
                    log.warning(
                        "ArtifactCreated kind=%r coerced to 'other' "
                        "for engagement_id=%s uri=%s",
                        raw_kind, engagement_id, uri,
                    )
                artifact_id = uuid.uuid5(
                    SPINE_NS,
                    f"https://spine.local/artifact/{engagement_id}/{uri}",
                )

                # Optional assignment_id (UUID-validated).
                assignment_id: str | None = None
                if isinstance(assn_raw, str) and assn_raw.strip():
                    try:
                        uuid.UUID(assn_raw)
                        assignment_id = assn_raw
                    except (ValueError, AttributeError):
                        log.warning(
                            "ArtifactCreated: ignoring malformed "
                            "assignment_id=%r", assn_raw,
                        )

                # Pass K: try V11 path (with tenant_id), V10 path
                # (engagement_id), then V1 (assignment_id only).
                inserted = False
                if _tenant_col(conn, "artifact"):
                    try:
                        cur.execute(
                            "INSERT INTO artifact "
                            "(artifact_id, assignment_id, engagement_id, "
                            " kind, uri, title, metadata_json, created_at, tenant_id) "
                            "VALUES (%s, %s, %s, %s::artifact_kind, %s, %s, "
                            "        %s::jsonb, %s, %s) "
                            "ON CONFLICT (artifact_id) DO NOTHING",
                            (artifact_id, assignment_id, engagement_id,
                             kind, uri, title, json.dumps(metadata), ts, tenant_id),
                        )
                        inserted = True
                    except pg_errors.UndefinedColumn:
                        _TENANT_COL_PRESENT["artifact"] = False
                if not inserted:
                    try:
                        cur.execute(
                            "INSERT INTO artifact "
                            "(artifact_id, assignment_id, engagement_id, "
                            " kind, uri, title, metadata_json, created_at) "
                            "VALUES (%s, %s, %s, %s::artifact_kind, %s, %s, "
                            "        %s::jsonb, %s) "
                            "ON CONFLICT (artifact_id) DO NOTHING",
                            (artifact_id, assignment_id, engagement_id,
                             kind, uri, title, json.dumps(metadata), ts),
                        )
                    except pg_errors.UndefinedColumn:
                        # Pre-V10: artifact.engagement_id doesn't exist yet.
                        # Insert without the column AND skip when there's no
                        # assignment_id (the column is still NOT NULL pre-V10).
                        log.warning(
                            "artifact.engagement_id missing (pre-V10 schema); "
                            "ingesting artifact without engagement attribution. "
                            "Run flyway migrate to apply V10."
                        )
                        if assignment_id is None:
                            log.warning(
                                "ArtifactCreated dropped on pre-V10 schema "
                                "(no assignment_id to anchor to): "
                                "engagement_id=%s uri=%s",
                                engagement_id, uri,
                            )
                        else:
                            cur.execute(
                                "INSERT INTO artifact "
                                "(artifact_id, assignment_id, kind, uri, "
                                " title, metadata_json, created_at) "
                                "VALUES (%s, %s, %s::artifact_kind, %s, %s, "
                                "        %s::jsonb, %s) "
                                "ON CONFLICT (artifact_id) DO NOTHING",
                                (artifact_id, assignment_id, kind, uri,
                                 title, json.dumps(metadata), ts),
                            )

            elif event_type == "EngagementMessage":
                # Pass I-2: insert one row into engagement_message. The
                # engagement_message table ships with V8 — pre-V8
                # databases will raise UndefinedTable here and the line
                # will get logged + stuck (the outbox cursor stops at
                # the failure, which is the right behavior: ingestion
                # resumes once migrations catch up).
                msg_role = payload.get("role")
                msg_kind = payload.get("kind")
                body_md = payload.get("body_md") or ""
                if msg_role not in ENGAGEMENT_MESSAGE_ROLES:
                    log.warning(
                        "EngagementMessage skipped: unknown role=%r "
                        "engagement_id=%s",
                        msg_role, engagement_id,
                    )
                    return
                if msg_kind not in ENGAGEMENT_MESSAGE_KINDS:
                    log.warning(
                        "EngagementMessage skipped: unknown kind=%r "
                        "engagement_id=%s",
                        msg_kind, engagement_id,
                    )
                    return
                msg_meta = payload.get("metadata") or {}
                if not isinstance(msg_meta, dict):
                    msg_meta = {}
                if _tenant_col(conn, "engagement_message"):
                    try:
                        cur.execute(
                            "INSERT INTO engagement_message "
                            "(engagement_id, role, kind, body_md, "
                            " created_at, metadata_json, tenant_id) "
                            "VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s)",
                            (engagement_id, msg_role, msg_kind, body_md,
                             ts, json.dumps(msg_meta), tenant_id),
                        )
                        return
                    except pg_errors.UndefinedColumn:
                        _TENANT_COL_PRESENT["engagement_message"] = False
                cur.execute(
                    "INSERT INTO engagement_message "
                    "(engagement_id, role, kind, body_md, "
                    " created_at, metadata_json) "
                    "VALUES (%s, %s, %s, %s, %s, %s::jsonb)",
                    (engagement_id, msg_role, msg_kind, body_md,
                     ts, json.dumps(msg_meta)),
                )


def ingest_outbox_line(conn: psycopg.Connection, line: str) -> None:
    """Pass D router. Parses the outer JSON envelope and dispatches by `type`.

    - "cost"       -> ingest_cost_line (legacy cost-row projection)
    - "event"      -> ingest_event_line (lifecycle event projection)
    - "instance"   -> ingest_instance_event (Pass H instance registry)
    - "engagement" -> ingest_engagement_event (Pass I-1 engagement table)
    - other        -> log warning and return (cursor advances)

    Raises on JSON parse errors / DB errors so drain_file's per-line
    failure handling stays unchanged.
    """
    obj = json.loads(line)
    kind = obj.get("type")
    if kind == "cost":
        # ingest_cost_line re-parses to preserve its existing contract;
        # the double-parse cost is negligible vs. the DB round-trips.
        ingest_cost_line(conn, line)
    elif kind == "event":
        ingest_event_line(conn, obj)
    elif kind == "instance":
        ingest_instance_event(conn, obj)
    elif kind == "engagement":
        ingest_engagement_event(conn, obj)
    else:
        log.warning("skip unknown outbox line type=%r", kind)


# ---------------------------------------------------------------------------
# File-level draining
# ---------------------------------------------------------------------------

def _split_complete_lines(buf: bytes) -> tuple[list[str], int]:
    """Split bytes into (decoded complete lines, bytes_consumed).

    A line is "complete" only if it ends in '\\n'. Anything after the
    last newline is a partial write the daemon is still flushing - we
    leave it for the next tick. Returns the decoded lines (without the
    trailing newline) and how many bytes of `buf` we consumed.
    """
    if not buf:
        return [], 0
    last_nl = buf.rfind(b"\n")
    if last_nl == -1:
        return [], 0
    complete = buf[: last_nl + 1]
    consumed = len(complete)
    lines = complete.decode("utf-8", errors="replace").splitlines()
    return lines, consumed


def drain_file(conn: psycopg.Connection, ob: OutboxFile) -> None:
    """Read all complete lines since the cursor and ingest each.

    Stops advancing the cursor at the first failing line. Per-line
    parse errors are logged at ERROR level. A DB connection error
    bubbles up so the outer loop can reconnect.
    """
    offset = ob.cursor_offset
    try:
        with ob.jsonl_path.open("rb") as fh:
            fh.seek(offset)
            data = fh.read()
    except FileNotFoundError:
        log.debug("outbox vanished: %s", ob.jsonl_path)
        return
    except OSError as e:
        log.error("cannot read %s: %s", ob.jsonl_path, e)
        return

    lines, consumed = _split_complete_lines(data)
    if not lines:
        return

    log.debug("draining %d lines from %s (offset %d -> %d)",
              len(lines), ob.role, offset, offset + consumed)

    # We advance the cursor line-by-line so a poisoned line in the middle
    # of a batch doesn't lose the successfully-ingested rows after it...
    # except that we want to STOP at the first failing line per the spec.
    # So we track per-line byte offsets and only persist the cursor at
    # the end of a fully-successful prefix.
    running_offset = offset
    for line in lines:
        line_bytes = len(line.encode("utf-8")) + 1  # +1 for the newline
        stripped = line.strip()
        if not stripped:
            running_offset += line_bytes
            continue
        try:
            ingest_outbox_line(conn, stripped)
        except (psycopg.OperationalError, psycopg.InterfaceError):
            # Connection problem - re-raise so the main loop reconnects.
            # Cursor stays where it is; we'll retry this line next tick.
            raise
        except (json.JSONDecodeError, ValueError) as e:
            log.error("malformed outbox line in %s at offset %d: %s; line=%r",
                      ob.role, running_offset, e, line[:200])
            # Stop here per spec: bad line stays in outbox, cursor doesn't
            # advance past it. Operators can inspect and fix.
            break
        except pg_errors.Error as e:
            log.error("db error ingesting line in %s at offset %d: %s",
                      ob.role, running_offset, e)
            # Also stop. The transaction was rolled back by `with
            # conn.transaction()` so the connection is still usable.
            break
        running_offset += line_bytes

    if running_offset > offset:
        ob.advance_cursor(running_offset)
        log.info("ingested %d bytes for role=%s (cursor %d -> %d)",
                 running_offset - offset, ob.role, offset, running_offset)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def connect_with_retry(database_url: str, shutdown: _Shutdown) -> psycopg.Connection:
    """Open a DB connection with capped exponential backoff. Returns when
    a connection is successfully opened; raises only if shutdown is
    requested before a connection succeeds."""
    delay = 1
    attempt = 0
    while not shutdown.requested:
        attempt += 1
        try:
            conn = psycopg.connect(database_url, autocommit=False)
            log.info("connected to postgres (attempt %d)", attempt)
            return conn
        except psycopg.OperationalError as e:
            log.warning("db connect attempt %d failed: %s; retrying in %ds",
                        attempt, e, delay)
            for _ in range(delay):
                if shutdown.requested:
                    raise RuntimeError("shutdown requested during reconnect") from None
                time.sleep(1)
            delay = min(delay * 2, BACKOFF_CAP_S)
    raise RuntimeError("shutdown requested before any DB connection succeeded")


def tick(conn: psycopg.Connection, team_base: Path, cursor_base: Path | None) -> None:
    outboxes = discover_outboxes(team_base, cursor_base)
    if not outboxes:
        log.debug("no outbox files under %s yet", team_base)
        return
    for ob in outboxes:
        drain_file(conn, ob)


def main() -> int:
    _setup_logging()

    database_url = os.environ.get("DATABASE_URL")
    team_base_raw = os.environ.get("TEAM_BASE")
    cursor_base_raw = os.environ.get("CURSOR_BASE")
    poll_interval = float(os.environ.get("POLL_INTERVAL_S", "5"))

    if not database_url:
        log.error("DATABASE_URL is required")
        return 2
    if not team_base_raw:
        log.error("TEAM_BASE is required")
        return 2

    team_base = Path(team_base_raw)
    cursor_base = Path(cursor_base_raw) if cursor_base_raw else None

    shutdown = _Shutdown()
    signal.signal(signal.SIGTERM, shutdown.request)
    signal.signal(signal.SIGINT, shutdown.request)

    log.info(
        "spine_watcher starting (team_base=%s, cursor_base=%s, poll=%.1fs)",
        team_base, cursor_base if cursor_base else "(next to outbox)", poll_interval,
    )

    # Initial DB connect: retry up to 5 attempts, then proceed with the
    # main loop which will continue to retry indefinitely. The 5-attempt
    # gate at startup catches "you ran me with no DB at all" mistakes.
    startup_attempts = 0
    conn: psycopg.Connection | None = None
    while startup_attempts < 5 and not shutdown.requested:
        try:
            conn = psycopg.connect(database_url, autocommit=False)
            log.info("initial db connection established")
            break
        except psycopg.OperationalError as e:
            startup_attempts += 1
            wait = min(2 ** startup_attempts, BACKOFF_CAP_S)
            log.warning("startup db connect %d/5 failed: %s; sleeping %ds",
                        startup_attempts, e, wait)
            time.sleep(wait)
    if conn is None:
        if shutdown.requested:
            return 0
        log.error("could not connect to DB after 5 startup attempts; giving up")
        return 1

    try:
        while not shutdown.requested:
            try:
                tick(conn, team_base, cursor_base)
            except (psycopg.OperationalError, psycopg.InterfaceError) as e:
                log.warning("db connection lost: %s; reconnecting", e)
                try:
                    conn.close()
                except Exception:
                    pass
                conn = connect_with_retry(database_url, shutdown)
                continue

            # Sleep in 1s chunks so SIGTERM responsiveness is good.
            slept = 0.0
            while slept < poll_interval and not shutdown.requested:
                time.sleep(min(1.0, poll_interval - slept))
                slept += 1.0
    finally:
        try:
            conn.close()
        except Exception:
            pass

    log.info("spine_watcher exited cleanly")
    return 0


if __name__ == "__main__":
    sys.exit(main())
