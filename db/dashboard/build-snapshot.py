#!/usr/bin/env python3
"""build-snapshot.py - Capture a point-in-time snapshot of the Spine
recording layer into a single JSON file that the dashboard renders.

This is intentionally a thin script: connect, run the read-side queries
that V4/V5 already define, normalize the results, write JSON to
db/dashboard/pg-snapshot.json. The dashboard is static and loads that
JSON via fetch — no live DB connection from the browser.

Connection precedence (matches the existing team.sh _spine_pg_init):
  1. SPINE_DB_URL              — full libpq URI wins outright
  2. libpq env vars            — PGUSER / PGPASSWORD / PGDATABASE /
                                 PGHOST / PGPORT (standard libpq names)
  3. db/.env file              — POSTGRES_USER / POSTGRES_PASSWORD /
                                 POSTGRES_DB / POSTGRES_HOST_PORT
  4. Compiled defaults         — spine / spine_dev_only / spine /
                                 127.0.0.1 / 33000

We default to localhost + port 33000 because docker-compose binds the
container's 5432 to host 127.0.0.1:33000 to stay clear of any system
Postgres on 5432 or the common alt 5433.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# psycopg presence check (fail fast with a helpful hint)
# ---------------------------------------------------------------------------

try:
    import psycopg
except ImportError:
    sys.stderr.write(
        "error: psycopg is not installed on this Python.\n"
        "Install it with:\n"
        "    pip install --break-system-packages -q 'psycopg[binary]'\n"
        "or in a virtualenv:\n"
        "    python3 -m venv .venv && . .venv/bin/activate && \\\n"
        "        pip install 'psycopg[binary]'\n"
    )
    sys.exit(2)


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

HERE = Path(__file__).resolve().parent              # db/dashboard
DB_DIR = HERE.parent                                # db/
ENV_FILE = DB_DIR / ".env"
OUT_FILE = HERE / "pg-snapshot.json"


# ---------------------------------------------------------------------------
# .env parsing (minimal, no python-dotenv dep)
# ---------------------------------------------------------------------------

def parse_env_file(path: Path) -> dict[str, str]:
    """Parse a KEY=VALUE .env file. Ignores comments and blank lines.
    Strips surrounding single or double quotes. Returns {} if missing."""
    result: dict[str, str] = {}
    if not path.is_file():
        return result
    try:
        text = path.read_text()
    except OSError:
        return result
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        # strip optional surrounding quotes
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        result[key] = value
    return result


# ---------------------------------------------------------------------------
# Build the connection string
# ---------------------------------------------------------------------------

def build_conninfo() -> str:
    """Resolve connection parameters using the documented precedence chain.
    Returns a libpq-style key=value string suitable for psycopg.connect."""
    # 1. SPINE_DB_URL wins outright.
    spine_url = os.environ.get("SPINE_DB_URL")
    if spine_url:
        return spine_url

    env_file = parse_env_file(ENV_FILE)

    def pick(libpq_name: str, env_name: str, default: str) -> str:
        return (
            os.environ.get(libpq_name)
            or env_file.get(env_name)
            or default
        )

    user = pick("PGUSER", "POSTGRES_USER", "spine")
    password = pick("PGPASSWORD", "POSTGRES_PASSWORD", "spine_dev_only")
    dbname = pick("PGDATABASE", "POSTGRES_DB", "spine")
    host = os.environ.get("PGHOST") or "127.0.0.1"
    port = pick("PGPORT", "POSTGRES_HOST_PORT", "33000")

    # Use the keyword form (not URI) so passwords with special chars don't
    # need percent-encoding.
    return (
        f"host={host} port={port} dbname={dbname} "
        f"user={user} password={password}"
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cols_rows(cur: psycopg.Cursor) -> list[dict]:
    """Convert a cursor's result set to a list of dicts keyed by column name."""
    if cur.description is None:
        return []
    cols = [d.name for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _scalar(cur: psycopg.Cursor) -> object:
    """First column of the first row, or None."""
    row = cur.fetchone()
    if row is None:
        return None
    return row[0]


def _iso(value: object) -> object:
    """Convert datetime/date to ISO string, pass other values through."""
    if isinstance(value, (dt.datetime, dt.date)):
        return value.isoformat()
    return value


def _isoify_rows(rows: list[dict], keys: tuple[str, ...]) -> list[dict]:
    """In-place(ish) ISO conversion for specific keys on each row."""
    for r in rows:
        for k in keys:
            if k in r:
                r[k] = _iso(r[k])
    return rows


# ---------------------------------------------------------------------------
# Snapshot queries
# ---------------------------------------------------------------------------

def build_snapshot(conn: psycopg.Connection) -> dict:
    """Run every query the dashboard cares about. One read-only transaction
    so the snapshot is internally consistent.

    Returns the snapshot as a plain dict (no file I/O). serve.py imports
    this directly to serve live JSON; the legacy file-on-disk workflow goes
    through write_snapshot_file() below."""
    snapshot: dict = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "kpis": {},
        "recent_invocations": [],
        "cost_by_role": [],
        "cost_by_model": [],
        "active_workers": [],
        "recent_events": [],
        "event_type_counts": [],
        # Pass H: fleet of registered Spine instances (every laptop / box
        # that ran `team.sh up` against this Postgres). Always a list and
        # an object so the dashboard can render emptiness uniformly.
        "fleet": [],
        "fleet_kpis": {
            "total_instances": 0,
            "alive_instances": 0,
            "stale_instances": 0,
            "lost_instances": 0,
            "stopped_instances": 0,
            "machine_count": 0,
        },
        # Machines: every host that has ever executed a Spine agent,
        # whether or not it has registered an instance heartbeat. Derived
        # primarily from worker.host_id with optional metadata joined in
        # from spine_instance (V6+).
        "machines": [],
        # Engagements (Pass I-1): client work submitted via the dashboard
        # "New Engagement" form. Always a list and a kpis object so the
        # dashboard can render emptiness uniformly. Guarded with try/
        # except below so pre-V7 databases still serve a snapshot.
        "engagements": [],
        "engagement_kpis": {
            "total": 0,
            "by_status": {},
        },
        # Pass I-2: last 50 clarification messages across all engagements,
        # in reverse-chronological order. Empty list on pre-V8 databases.
        "recent_engagement_messages": [],
        # Pass I-3: per-engagement cost summary keyed by slug. Sourced from
        # v_engagement_costs (V9). Empty dict on pre-V9 databases.
        "engagement_costs": {},
        # Pass J: per-engagement artifact count keyed by engagement_id.
        # Sourced from artifact (V10 view v_engagement_artifacts when the
        # column is present). Empty dict pre-V10.
        "engagement_artifact_counts": {},
        # Pass K: distinct tenants observed across team/worker/engagement
        # tables. Always a list of {tenant_id, teams, workers, engagements}
        # plus a small KPI block so the dashboard can render a tenant
        # filter chip + a Tenants KPI card. Empty list on pre-V11 schemas.
        "tenants": [],
        "tenant_kpis": {"tenant_count": 0},
        # Pass L (Spine Hub Pillar 2 — code distribution): release channels
        # and per-instance version drift. Empty / unknown_channel on
        # pre-V12 databases — the dashboard renders an empty Versions tab.
        "releases_by_channel": {"stable": [], "beta": [], "canary": []},
        "release_heads": {},          # channel -> head release dict
        "instance_drift": [],         # rows from v_instance_drift
        "drift_kpis": {
            "current": 0,
            "drifted": 0,
            "unversioned": 0,
            "unknown_channel": 0,
        },
        # Pass M: per-instance vitals time-series, keyed by instance_id.
        # Each value is a list of up to ~60 points (one per heartbeat) so
        # the machines.html drill-down can render CPU / mem / load
        # sparklines without a second round-trip. Empty dict on pre-V13.
        "vitals_history": {},
        # Pass N+: per-host drill-down payload assembled host-by-host so
        # the machines.html detail view can render rich data (instance
        # row, latest vitals, vitals history, cost-by-role for this
        # host, engagements touching this host, recent invocations and
        # events) without a second round-trip. Keyed by host_id. Empty
        # dict if no hosts exist or the relevant schema isn't present.
        "machine_drilldown": {},
        "schema_version": None,
    }

    with conn.cursor() as cur:
        # ---- KPIs --------------------------------------------------------
        cur.execute("SELECT COUNT(*) FROM cost_row;")
        snapshot["kpis"]["total_invocations"] = int(_scalar(cur) or 0)

        cur.execute("SELECT COALESCE(SUM(wall_s), 0) FROM cost_row;")
        snapshot["kpis"]["total_wall_s"] = float(_scalar(cur) or 0)

        cur.execute("SELECT COALESCE(SUM(cost_usd), 0) FROM cost_row;")
        snapshot["kpis"]["total_cost_usd"] = float(_scalar(cur) or 0)

        cur.execute("SELECT COALESCE(SUM(tokens_in), 0) FROM cost_row;")
        snapshot["kpis"]["total_tokens_in"] = int(_scalar(cur) or 0)

        cur.execute("SELECT COALESCE(SUM(tokens_out), 0) FROM cost_row;")
        snapshot["kpis"]["total_tokens_out"] = int(_scalar(cur) or 0)

        cur.execute("SELECT COUNT(*) FROM worker WHERE archived_at IS NULL;")
        snapshot["kpis"]["active_workers"] = int(_scalar(cur) or 0)

        cur.execute("SELECT COUNT(*) FROM event;")
        snapshot["kpis"]["total_events"] = int(_scalar(cur) or 0)

        # ---- Recent invocations -----------------------------------------
        # Pass K: join in worker.tenant_id when available so the dashboard
        # can apply the tenant filter chip. Falls back to the unjoined
        # query on pre-V11 schemas where worker.tenant_id doesn't exist.
        recent_inv_v11_sql = """
            SELECT
              vid.started_at,
              vid.ended_at,
              EXTRACT(EPOCH FROM (vid.ended_at - vid.started_at))::float AS duration_s,
              vid.role_id,
              vid.handle,
              vid.host_id,
              vid.tier,
              vid.classification,
              vid.terminal_type,
              vid.outcome,
              w.tenant_id AS tenant_id
            FROM v_invocation_durations vid
            LEFT JOIN worker w ON w.handle = vid.handle AND w.host_id = vid.host_id
            ORDER BY vid.started_at DESC
            LIMIT 50;
        """
        recent_inv_legacy_sql = """
            SELECT
              started_at,
              ended_at,
              EXTRACT(EPOCH FROM (ended_at - started_at))::float AS duration_s,
              role_id,
              handle,
              host_id,
              tier,
              classification,
              terminal_type,
              outcome
            FROM v_invocation_durations
            ORDER BY started_at DESC
            LIMIT 50;
        """
        try:
            cur.execute(recent_inv_v11_sql)
            snapshot["recent_invocations"] = _isoify_rows(
                _cols_rows(cur), ("started_at", "ended_at")
            )
        except psycopg.errors.Error:
            conn.rollback()
            cur.execute(recent_inv_legacy_sql)
            rows = _isoify_rows(_cols_rows(cur), ("started_at", "ended_at"))
            for r in rows:
                r.setdefault("tenant_id", "default")
            snapshot["recent_invocations"] = rows

        # ---- Cost by role -----------------------------------------------
        cur.execute(
            """
            SELECT
              role_id,
              SUM(invocations)::int                                      AS invocations,
              ROUND(SUM(wall_s_total)::numeric, 1)::float                AS wall_s,
              SUM(tokens_in_total)::int                                  AS tokens_in,
              SUM(tokens_out_total)::int                                 AS tokens_out,
              ROUND(SUM(cost_usd_total)::numeric, 6)::float              AS cost_usd
            FROM v_cost_by_role_day
            GROUP BY role_id
            ORDER BY cost_usd DESC NULLS LAST;
            """
        )
        snapshot["cost_by_role"] = _cols_rows(cur)

        # ---- Cost by model ----------------------------------------------
        cur.execute(
            """
            SELECT
              model_id,
              provider_id,
              invocations::int                                           AS invocations,
              tokens_in_total::int                                       AS tokens_in,
              tokens_out_total::int                                      AS tokens_out,
              ROUND(cost_usd_total::numeric, 6)::float                   AS cost_usd
            FROM v_cost_by_model
            ORDER BY cost_usd DESC;
            """
        )
        snapshot["cost_by_model"] = _cols_rows(cur)

        # ---- Active workers ---------------------------------------------
        cur.execute(
            """
            SELECT
              handle,
              role_id,
              host_id,
              instance_id,
              status,
              lifetime_invocations::int                                  AS lifetime_invocations,
              ROUND(lifetime_cost_usd::numeric, 6)::float                AS lifetime_cost_usd,
              last_cost_ts
            FROM v_active_workers
            ORDER BY lifetime_cost_usd DESC NULLS LAST
            LIMIT 50;
            """
        )
        snapshot["active_workers"] = _isoify_rows(
            _cols_rows(cur), ("last_cost_ts",)
        )

        # ---- Recent events ----------------------------------------------
        cur.execute(
            """
            SELECT
              ts,
              type,
              role_id,
              handle,
              host_id,
              payload_json
            FROM v_recent_events
            ORDER BY ts DESC
            LIMIT 100;
            """
        )
        snapshot["recent_events"] = _isoify_rows(_cols_rows(cur), ("ts",))

        # ---- Event type counts ------------------------------------------
        cur.execute(
            """
            SELECT type, COUNT(*)::int AS n
            FROM event
            GROUP BY type
            ORDER BY n DESC;
            """
        )
        snapshot["event_type_counts"] = _cols_rows(cur)

        # ---- Fleet (Pass H, vitals-extended in Pass M) ------------------
        # The v_active_instances view ships with V6; pre-V6 databases
        # don't have it. Pass M layers v_instance_vitals_latest (V13)
        # on top via LEFT JOIN so the dashboard can render CPU / mem /
        # disk bars per machine card.
        fleet_v13_sql = """
            SELECT
              va.instance_id,
              va.host_id,
              va.os_user,
              va.project_slug,
              va.project_path,
              va.version_short,
              va.spine_version,
              va.started_at,
              va.last_seen_at,
              va.seconds_since_seen,
              va.effective_status,
              vv.cpu_pct,
              vv.mem_used_mb,
              vv.mem_total_mb,
              vv.disk_used_gb,
              vv.disk_total_gb,
              vv.load_avg_1m,
              vv.load_avg_5m,
              vv.load_avg_15m,
              vv.spine_cpu_pct,
              vv.spine_mem_mb,
              vv.spine_proc_count,
              vv.vitals_at,
              vv.mem_used_pct,
              vv.disk_used_pct,
              vv.spine_share_pct
            FROM v_active_instances va
            LEFT JOIN v_instance_vitals_latest vv
              ON vv.instance_id = va.instance_id
            ORDER BY
              CASE va.effective_status
                WHEN 'alive'   THEN 0
                WHEN 'stale'   THEN 1
                WHEN 'lost'    THEN 2
                WHEN 'stopped' THEN 3
                ELSE 4
              END,
              va.last_seen_at DESC
            LIMIT 50;
        """
        fleet_legacy_sql = """
            SELECT
              instance_id,
              host_id,
              os_user,
              project_slug,
              project_path,
              version_short,
              spine_version,
              started_at,
              last_seen_at,
              seconds_since_seen,
              effective_status
            FROM v_active_instances
            ORDER BY
              CASE effective_status
                WHEN 'alive'   THEN 0
                WHEN 'stale'   THEN 1
                WHEN 'lost'    THEN 2
                WHEN 'stopped' THEN 3
                ELSE 4
              END,
              last_seen_at DESC
            LIMIT 50;
        """
        try:
            try:
                cur.execute(fleet_v13_sql)
                snapshot["fleet"] = _isoify_rows(
                    _cols_rows(cur),
                    ("started_at", "last_seen_at", "vitals_at"),
                )
            except psycopg.errors.Error:
                conn.rollback()
                cur.execute(fleet_legacy_sql)
                snapshot["fleet"] = _isoify_rows(
                    _cols_rows(cur), ("started_at", "last_seen_at")
                )

            # Compute fleet KPIs from the materialized rows so the
            # dashboard's KPI strip and Fleet section never disagree.
            fk = {"alive": 0, "stale": 0, "lost": 0, "stopped": 0}
            for row in snapshot["fleet"]:
                s = row.get("effective_status")
                if s in fk:
                    fk[s] += 1
            snapshot["fleet_kpis"] = {
                "total_instances": len(snapshot["fleet"]),
                "alive_instances": fk["alive"],
                "stale_instances": fk["stale"],
                "lost_instances": fk["lost"],
                "stopped_instances": fk["stopped"],
                "machine_count": 0,
            }
        except psycopg.errors.Error:
            # rollback so the conn stays usable. Leave defaults in place.
            conn.rollback()

        # ---- Machines ---------------------------------------------------
        # Every host that has ever executed a Spine agent. Joins worker
        # rows (always present) with spine_instance metadata (V6+; may
        # not exist on pre-V6 databases). When spine_instance is missing
        # or a host has no heartbeat row, effective_status falls back to
        # 'unregistered' so unregistered laptops still show up.
        machines_with_inst_sql = """
            WITH worker_machines AS (
              SELECT
                w.host_id,
                MIN(w.created_at)        AS first_seen,
                MAX(COALESCE(cr.ts, w.created_at)) AS last_active,
                COUNT(DISTINCT w.worker_id) AS workers,
                COUNT(DISTINCT w.role_id)   AS roles,
                COUNT(cr.assignment_id)     AS invocations,
                ROUND(COALESCE(SUM(cr.cost_usd), 0)::numeric, 4)::float AS cost_usd,
                COALESCE(SUM(cr.wall_s), 0)::float AS wall_s
              FROM worker w
              LEFT JOIN assignment a ON a.worker_id = w.worker_id
              LEFT JOIN cost_row cr  ON cr.assignment_id = a.assignment_id
              WHERE w.archived_at IS NULL
              GROUP BY w.host_id
            ),
            inst AS (
              SELECT
                host_id,
                MAX(version_short)  AS version_short,
                MAX(project_slug)   AS project_slug,
                MAX(project_path)   AS project_path,
                MAX(os_user)        AS os_user,
                MAX(spine_version)  AS spine_version,
                MAX(last_seen_at)   AS last_seen_at,
                bool_or(EXTRACT(EPOCH FROM (now() - last_seen_at)) < 180 AND status != 'stopped') AS any_alive
              FROM spine_instance
              GROUP BY host_id
            )
            SELECT
              wm.host_id,
              COALESCE(i.project_slug, '(unknown)')   AS project_slug,
              COALESCE(i.project_path, '')            AS project_path,
              COALESCE(i.os_user, '')                 AS os_user,
              COALESCE(i.version_short, '')           AS version_short,
              COALESCE(i.spine_version, '')           AS spine_version,
              i.last_seen_at,
              CASE
                WHEN i.last_seen_at IS NULL THEN 'unregistered'
                WHEN i.any_alive THEN 'alive'
                WHEN EXTRACT(EPOCH FROM (now() - i.last_seen_at)) < 180 THEN 'stale'
                ELSE 'lost'
              END AS effective_status,
              wm.first_seen,
              wm.last_active,
              wm.workers,
              wm.roles,
              wm.invocations,
              wm.cost_usd,
              ROUND(wm.wall_s::numeric, 1)::float AS wall_s
            FROM worker_machines wm
            LEFT JOIN inst i ON i.host_id = wm.host_id
            ORDER BY wm.last_active DESC NULLS LAST, wm.host_id ASC;
        """

        # Fallback path used when spine_instance is missing (pre-V6).
        # Identical aggregation but no LEFT JOIN — every machine ends up
        # 'unregistered'.
        machines_fallback_sql = """
            WITH worker_machines AS (
              SELECT
                w.host_id,
                MIN(w.created_at)        AS first_seen,
                MAX(COALESCE(cr.ts, w.created_at)) AS last_active,
                COUNT(DISTINCT w.worker_id) AS workers,
                COUNT(DISTINCT w.role_id)   AS roles,
                COUNT(cr.assignment_id)     AS invocations,
                ROUND(COALESCE(SUM(cr.cost_usd), 0)::numeric, 4)::float AS cost_usd,
                COALESCE(SUM(cr.wall_s), 0)::float AS wall_s
              FROM worker w
              LEFT JOIN assignment a ON a.worker_id = w.worker_id
              LEFT JOIN cost_row cr  ON cr.assignment_id = a.assignment_id
              WHERE w.archived_at IS NULL
              GROUP BY w.host_id
            )
            SELECT
              wm.host_id,
              '(unknown)'::text                    AS project_slug,
              ''::text                             AS project_path,
              ''::text                             AS os_user,
              ''::text                             AS version_short,
              ''::text                             AS spine_version,
              NULL::timestamptz                    AS last_seen_at,
              'unregistered'::text                 AS effective_status,
              wm.first_seen,
              wm.last_active,
              wm.workers,
              wm.roles,
              wm.invocations,
              wm.cost_usd,
              ROUND(wm.wall_s::numeric, 1)::float  AS wall_s
            FROM worker_machines wm
            ORDER BY wm.last_active DESC NULLS LAST, wm.host_id ASC;
        """

        try:
            cur.execute(machines_with_inst_sql)
            snapshot["machines"] = _isoify_rows(
                _cols_rows(cur),
                ("first_seen", "last_active", "last_seen_at"),
            )
        except psycopg.errors.Error:
            # Most likely cause: spine_instance table doesn't exist
            # (pre-V6). Roll back and fall back to the joinless query.
            conn.rollback()
            try:
                cur.execute(machines_fallback_sql)
                snapshot["machines"] = _isoify_rows(
                    _cols_rows(cur),
                    ("first_seen", "last_active", "last_seen_at"),
                )
            except psycopg.errors.Error:
                conn.rollback()

        snapshot["fleet_kpis"]["machine_count"] = len(snapshot["machines"])

        # ---- Engagements (Pass I-1/I-2) ---------------------------------
        # Pass I-1 introduced v_engagements_overview (V7). Pass I-2 adds
        # v_engagement_detail (V8) which carries message_count plus the
        # new URI columns. Try the V8 path first; on UndefinedTable /
        # UndefinedColumn fall back to the V7 overview so the dashboard
        # still serves a snapshot against a partially-migrated DB.
        # Pass I-3: events_count + last_event_ts come from a LEFT JOIN
        # against event.engagement_id. The column is V9; we COALESCE both
        # via subqueries that themselves catch UndefinedColumn (pre-V9)
        # by being wrapped in their own try/except below — but to keep
        # the SQL simple we attempt the V9-aware query first and fall
        # back to the plain V8 query when v9 hasn't applied.
        engagements_v9_sql = """
            SELECT
              ed.engagement_id::text AS engagement_id,
              ed.slug,
              ed.title,
              ed.client,
              ed.status::text         AS status,
              ed.requirements_uri,
              ed.req_uri,
              ed.open_questions_uri,
              ed.planner_report_uri,
              ed.plan_uri,
              ed.architect_adr_uris,
              ed.created_at,
              ed.updated_at,
              ed.approved_at,
              ed.delivered_at,
              EXTRACT(EPOCH FROM (now() - ed.created_at))::int AS age_seconds,
              ed.message_count::int   AS message_count,
              COALESCE(ec.events_count, 0)::int  AS events_count,
              ec.last_event_ts                    AS last_event_ts
            FROM v_engagement_detail ed
            LEFT JOIN (
              SELECT engagement_id,
                     COUNT(*)         AS events_count,
                     MAX(ts)          AS last_event_ts
              FROM event
              WHERE engagement_id IS NOT NULL
              GROUP BY engagement_id
            ) ec ON ec.engagement_id = ed.engagement_id
            ORDER BY ed.created_at DESC
            LIMIT 50;
        """
        engagements_v8_sql = """
            SELECT
              engagement_id::text AS engagement_id,
              slug,
              title,
              client,
              status::text         AS status,
              requirements_uri,
              req_uri,
              open_questions_uri,
              planner_report_uri,
              plan_uri,
              architect_adr_uris,
              created_at,
              updated_at,
              approved_at,
              delivered_at,
              EXTRACT(EPOCH FROM (now() - created_at))::int AS age_seconds,
              message_count::int   AS message_count
            FROM v_engagement_detail
            ORDER BY created_at DESC
            LIMIT 50;
        """
        engagements_v7_sql = """
            SELECT
              engagement_id::text AS engagement_id,
              slug,
              title,
              client,
              status::text         AS status,
              requirements_uri,
              plan_uri,
              created_at,
              updated_at,
              approved_at,
              delivered_at,
              age_seconds
            FROM v_engagements_overview
            ORDER BY created_at DESC
            LIMIT 50;
        """
        try:
            try:
                cur.execute(engagements_v9_sql)
                snapshot["engagements"] = _isoify_rows(
                    _cols_rows(cur),
                    ("created_at", "updated_at", "approved_at",
                     "delivered_at", "last_event_ts"),
                )
            except psycopg.errors.Error:
                conn.rollback()
                try:
                    cur.execute(engagements_v8_sql)
                    rows = _isoify_rows(
                        _cols_rows(cur),
                        ("created_at", "updated_at", "approved_at", "delivered_at"),
                    )
                    for r in rows:
                        r.setdefault("events_count", 0)
                        r.setdefault("last_event_ts", None)
                    snapshot["engagements"] = rows
                except psycopg.errors.Error:
                    conn.rollback()
                    cur.execute(engagements_v7_sql)
                    rows = _isoify_rows(
                        _cols_rows(cur),
                        ("created_at", "updated_at", "approved_at", "delivered_at"),
                    )
                    # Fill in the V8-only fields so the dashboard JS doesn't
                    # have to special-case the pre-V8 shape.
                    for r in rows:
                        r.setdefault("req_uri", None)
                        r.setdefault("open_questions_uri", None)
                        r.setdefault("planner_report_uri", None)
                        r.setdefault("architect_adr_uris", [])
                        r.setdefault("message_count", 0)
                        r.setdefault("events_count", 0)
                        r.setdefault("last_event_ts", None)
                    snapshot["engagements"] = rows

            by_status: dict[str, int] = {}
            for row in snapshot["engagements"]:
                s = row.get("status") or "unknown"
                by_status[s] = by_status.get(s, 0) + 1
            snapshot["engagement_kpis"] = {
                "total": len(snapshot["engagements"]),
                "by_status": by_status,
            }
        except psycopg.errors.Error:
            # rollback so the conn stays usable. Leave defaults in place.
            conn.rollback()

        # ---- Recent engagement messages (Pass I-2) ----------------------
        # The last 50 clarification messages across every engagement. Used
        # later by an Activity view; for now the dashboard ignores this
        # block (it's available to anyone who fetches /pg-snapshot.json).
        # Graceful degrade when engagement_message doesn't exist (pre-V8).
        try:
            cur.execute(
                """
                SELECT
                  m.message_id::text AS message_id,
                  m.engagement_id::text AS engagement_id,
                  e.slug AS slug,
                  m.role,
                  m.kind,
                  m.body_md,
                  m.created_at
                FROM engagement_message m
                JOIN engagement e ON e.engagement_id = m.engagement_id
                ORDER BY m.created_at DESC
                LIMIT 50;
                """
            )
            snapshot["recent_engagement_messages"] = _isoify_rows(
                _cols_rows(cur), ("created_at",)
            )
        except psycopg.errors.Error:
            conn.rollback()
            snapshot.setdefault("recent_engagement_messages", [])

        # ---- Engagement costs (Pass I-3) --------------------------------
        # All rows from v_engagement_costs keyed by slug so the index page
        # can render running cost cells next to each engagement without a
        # second round-trip. Empty dict on pre-V9 databases.
        try:
            cur.execute(
                """
                SELECT
                  slug,
                  engagement_id::text AS engagement_id,
                  invocations::int    AS invocations,
                  wall_s::float       AS wall_s,
                  tokens_in::int      AS tokens_in,
                  tokens_out::int     AS tokens_out,
                  cost_usd::float     AS cost_usd,
                  roles_used::int     AS roles_used,
                  workers_used::int   AS workers_used
                FROM v_engagement_costs;
                """
            )
            rows = _cols_rows(cur)
            snapshot["engagement_costs"] = {r["slug"]: r for r in rows if r.get("slug")}
        except psycopg.errors.Error:
            conn.rollback()
            snapshot.setdefault("engagement_costs", {})

        # ---- Engagement artifact counts (Pass J) ------------------------
        # Aggregate counts of artifacts per engagement_id so the index
        # page can render a "N deliverables" badge without round-tripping
        # the full list. Empty dict when the view doesn't exist yet.
        try:
            cur.execute(
                """
                SELECT engagement_id::text AS engagement_id, COUNT(*)::int AS n
                FROM artifact
                WHERE engagement_id IS NOT NULL
                GROUP BY engagement_id;
                """
            )
            rows = _cols_rows(cur)
            snapshot["engagement_artifact_counts"] = {
                r["engagement_id"]: r["n"] for r in rows if r.get("engagement_id")
            }
        except psycopg.errors.Error:
            conn.rollback()
            snapshot.setdefault("engagement_artifact_counts", {})

        # ---- Tenants (Pass K) -------------------------------------------
        # Distinct tenants and their team / worker / engagement counts.
        # The v_tenants view ships with V11; pre-V11 databases lack both
        # the view and the tenant_id columns, so this query degrades
        # gracefully into an empty list.
        try:
            cur.execute(
                """
                SELECT
                  tenant_id,
                  teams::int       AS teams,
                  workers::int     AS workers,
                  engagements::int AS engagements
                FROM v_tenants
                ORDER BY tenant_id ASC;
                """
            )
            rows = _cols_rows(cur)
            snapshot["tenants"] = rows
            snapshot["tenant_kpis"] = {
                "tenant_count": len({r.get("tenant_id") for r in rows if r.get("tenant_id")}),
            }
        except psycopg.errors.Error:
            conn.rollback()
            snapshot.setdefault("tenants", [])
            snapshot.setdefault("tenant_kpis", {"tenant_count": 0})

        # ---- Releases + instance drift (Pass L) -------------------------
        # spine_release ships with V12. Pre-V12 databases lack the table
        # and the view, so both queries degrade gracefully to empty
        # values and the Versions tab renders a placeholder.
        try:
            cur.execute(
                """
                SELECT
                  release_id::text AS release_id,
                  channel::text    AS channel,
                  commit_sha,
                  short_sha,
                  ref,
                  notes_md,
                  promoted_by,
                  promoted_at,
                  archived_at
                FROM spine_release
                ORDER BY channel, promoted_at DESC
                LIMIT 120;
                """
            )
            rows = _isoify_rows(_cols_rows(cur), ("promoted_at", "archived_at"))
            by_channel: dict[str, list[dict]] = {
                "stable": [], "beta": [], "canary": [],
            }
            for r in rows:
                ch = r.get("channel")
                if ch in by_channel:
                    by_channel[ch].append(r)
                else:
                    by_channel.setdefault(ch or "unknown", []).append(r)
            snapshot["releases_by_channel"] = by_channel
        except psycopg.errors.Error:
            conn.rollback()
            snapshot.setdefault("releases_by_channel",
                                {"stable": [], "beta": [], "canary": []})

        try:
            cur.execute(
                """
                SELECT
                  channel,
                  commit_sha,
                  short_sha,
                  ref,
                  notes_md,
                  promoted_by,
                  promoted_at
                FROM v_release_heads
                """
            )
            heads_rows = _isoify_rows(_cols_rows(cur), ("promoted_at",))
            snapshot["release_heads"] = {
                r["channel"]: r for r in heads_rows if r.get("channel")
            }
        except psycopg.errors.Error:
            conn.rollback()
            snapshot.setdefault("release_heads", {})

        try:
            cur.execute(
                """
                SELECT
                  instance_id,
                  host_id,
                  os_user,
                  project_slug,
                  instance_short,
                  instance_sha,
                  channel,
                  head_short,
                  head_sha,
                  drift_status,
                  last_seen_at
                FROM v_instance_drift
                ORDER BY
                  CASE drift_status
                    WHEN 'drifted'         THEN 0
                    WHEN 'unknown_channel' THEN 1
                    WHEN 'unversioned'     THEN 2
                    WHEN 'current'         THEN 3
                    ELSE 4
                  END,
                  last_seen_at DESC NULLS LAST
                LIMIT 200;
                """
            )
            drift_rows = _isoify_rows(_cols_rows(cur), ("last_seen_at",))
            snapshot["instance_drift"] = drift_rows
            counts = {"current": 0, "drifted": 0,
                      "unversioned": 0, "unknown_channel": 0}
            for r in drift_rows:
                s = r.get("drift_status")
                if s in counts:
                    counts[s] += 1
            snapshot["drift_kpis"] = counts
        except psycopg.errors.Error:
            conn.rollback()
            snapshot.setdefault("instance_drift", [])

        # ---- Vitals history (Pass M) ------------------------------------
        # Per-instance, the last ~60 vital snapshots from instance_vitals
        # (about an hour of points at the default 60s heartbeat). Keyed
        # by instance_id so the machines.html drill-down can fetch
        # sparkline data with a single dict lookup. Empty dict on pre-V13.
        snapshot.setdefault("vitals_history", {})
        try:
            cur.execute(
                """
                WITH ranked AS (
                  SELECT
                    instance_id, ts,
                    cpu_pct, mem_used_mb, mem_total_mb,
                    disk_used_gb, disk_total_gb,
                    load_avg_1m, load_avg_5m, load_avg_15m,
                    spine_cpu_pct, spine_mem_mb, spine_proc_count,
                    ROW_NUMBER() OVER (
                      PARTITION BY instance_id ORDER BY ts DESC
                    ) AS rn
                  FROM instance_vitals
                )
                SELECT
                  instance_id, ts,
                  cpu_pct, mem_used_mb, mem_total_mb,
                  disk_used_gb, disk_total_gb,
                  load_avg_1m, load_avg_5m, load_avg_15m,
                  spine_cpu_pct, spine_mem_mb, spine_proc_count
                FROM ranked
                WHERE rn <= 60
                ORDER BY instance_id ASC, ts ASC;
                """
            )
            history: dict[str, list[dict]] = {}
            for row in _isoify_rows(_cols_rows(cur), ("ts",)):
                iid = row.get("instance_id")
                if not iid:
                    continue
                history.setdefault(iid, []).append(row)
            snapshot["vitals_history"] = history
        except psycopg.errors.Error:
            conn.rollback()
            snapshot.setdefault("vitals_history", {})

        # ---- Machine drill-down (Pass-detail enrichment) ----------------
        # Per-host bundle assembled for the machines.html detail view.
        # Every block is wrapped in its own try/except so a missing
        # column or view on an older schema only nulls *that* sub-block;
        # the rest of the drill-down still populates. The result is a
        # dict keyed by host_id, with each value carrying:
        #   instance, vitals_latest, vitals_history, tenant,
        #   cost_by_role, engagements, recent_invocations,
        #   recent_events, daemons_summary, release_status
        try:
            host_ids: set[str] = set()
            for m in snapshot.get("machines") or []:
                hid = m.get("host_id")
                if hid:
                    host_ids.add(hid)
            for f in snapshot.get("fleet") or []:
                hid = f.get("host_id")
                if hid:
                    host_ids.add(hid)

            # Index the data we already collected so we can dedupe by host
            # without an extra round-trip.
            drift_by_instance: dict[str, dict] = {
                r.get("instance_id"): r for r in (snapshot.get("instance_drift") or [])
                if r.get("instance_id")
            }
            fleet_by_host: dict[str, list[dict]] = {}
            for f in snapshot.get("fleet") or []:
                hid = f.get("host_id")
                if hid:
                    fleet_by_host.setdefault(hid, []).append(f)

            recent_inv_by_host: dict[str, list[dict]] = {}
            for inv in snapshot.get("recent_invocations") or []:
                hid = inv.get("host_id")
                if hid:
                    recent_inv_by_host.setdefault(hid, []).append(inv)

            recent_ev_by_host: dict[str, list[dict]] = {}
            for ev in snapshot.get("recent_events") or []:
                hid = ev.get("host_id")
                if hid:
                    recent_ev_by_host.setdefault(hid, []).append(ev)

            drilldown: dict[str, dict] = {}

            for host_id in sorted(host_ids):
                bundle: dict = {
                    "host_id": host_id,
                    "instance": None,
                    "vitals_latest": None,
                    "vitals_history": [],
                    "tenant": None,
                    "cost_by_role": [],
                    "engagements": [],
                    "recent_invocations": [],
                    "recent_events": [],
                    "daemons_summary": {
                        "workers": 0, "roles": 0, "last_pickup_ts": None,
                    },
                    "release_status": None,
                    "windowed_kpis": {
                        "today":    {"invocations": 0, "wall_s": 0.0, "cost_usd": 0.0},
                        "week":     {"invocations": 0, "wall_s": 0.0, "cost_usd": 0.0},
                        "lifetime": {"invocations": 0, "wall_s": 0.0, "cost_usd": 0.0},
                    },
                }

                # ---- Recent invocations / events from this host -----
                bundle["recent_invocations"] = list(recent_inv_by_host.get(host_id, [])[:20])
                bundle["recent_events"] = list(recent_ev_by_host.get(host_id, [])[:30])

                # ---- Pick freshest instance row for this host -------
                f_rows = fleet_by_host.get(host_id) or []
                f_rows.sort(
                    key=lambda r: r.get("last_seen_at") or "",
                    reverse=True,
                )
                best_inst = f_rows[0] if f_rows else None
                if best_inst:
                    bundle["instance"] = dict(best_inst)
                    iid = best_inst.get("instance_id")
                    # vitals_latest from instance row (Pass M cols)
                    if any(k in best_inst for k in ("cpu_pct", "mem_used_mb", "vitals_at")):
                        bundle["vitals_latest"] = {
                            k: best_inst.get(k) for k in (
                                "cpu_pct", "mem_used_mb", "mem_total_mb",
                                "disk_used_gb", "disk_total_gb",
                                "load_avg_1m", "load_avg_5m", "load_avg_15m",
                                "spine_cpu_pct", "spine_mem_mb",
                                "spine_proc_count", "vitals_at",
                                "mem_used_pct", "disk_used_pct",
                                "spine_share_pct",
                            )
                        }
                    if iid:
                        bundle["vitals_history"] = list(
                            (snapshot.get("vitals_history") or {}).get(iid, [])
                        )
                        # Drift status by instance.
                        drow = drift_by_instance.get(iid)
                        if drow:
                            bundle["release_status"] = {
                                "current_short": drow.get("instance_short"),
                                "head_short":    drow.get("head_short"),
                                "drift_status":  drow.get("drift_status"),
                                "channel":       drow.get("channel"),
                            }

                # ---- Tenant -----------------------------------------
                # Try worker.tenant_id first (V11+). Fall back to instance
                # metadata if available.
                try:
                    cur.execute(
                        """
                        SELECT DISTINCT tenant_id
                        FROM worker
                        WHERE host_id = %s AND tenant_id IS NOT NULL
                        LIMIT 1;
                        """,
                        (host_id,),
                    )
                    row = cur.fetchone()
                    if row and row[0]:
                        bundle["tenant"] = row[0]
                except psycopg.errors.Error:
                    conn.rollback()

                # ---- Daemons summary --------------------------------
                try:
                    cur.execute(
                        """
                        SELECT
                          COUNT(DISTINCT w.worker_id)::int AS workers,
                          COUNT(DISTINCT w.role_id)::int   AS roles,
                          MAX(cr.ts)                       AS last_pickup_ts
                        FROM worker w
                        LEFT JOIN assignment a ON a.worker_id = w.worker_id
                        LEFT JOIN cost_row  cr ON cr.assignment_id = a.assignment_id
                        WHERE w.host_id = %s AND w.archived_at IS NULL;
                        """,
                        (host_id,),
                    )
                    row = cur.fetchone()
                    if row:
                        bundle["daemons_summary"] = {
                            "workers": int(row[0] or 0),
                            "roles": int(row[1] or 0),
                            "last_pickup_ts": _iso(row[2]),
                        }
                except psycopg.errors.Error:
                    conn.rollback()

                # ---- Windowed KPIs (today / week / lifetime) --------
                try:
                    cur.execute(
                        """
                        SELECT
                          COUNT(cr.assignment_id) FILTER (WHERE cr.ts >= now() - interval '24 hours')::int AS inv_today,
                          COALESCE(SUM(cr.wall_s)   FILTER (WHERE cr.ts >= now() - interval '24 hours'),0)::float AS wall_today,
                          COALESCE(SUM(cr.cost_usd) FILTER (WHERE cr.ts >= now() - interval '24 hours'),0)::float AS cost_today,
                          COUNT(cr.assignment_id) FILTER (WHERE cr.ts >= now() - interval '7 days')::int AS inv_week,
                          COALESCE(SUM(cr.wall_s)   FILTER (WHERE cr.ts >= now() - interval '7 days'),0)::float AS wall_week,
                          COALESCE(SUM(cr.cost_usd) FILTER (WHERE cr.ts >= now() - interval '7 days'),0)::float AS cost_week,
                          COUNT(cr.assignment_id)::int AS inv_life,
                          COALESCE(SUM(cr.wall_s),0)::float AS wall_life,
                          COALESCE(SUM(cr.cost_usd),0)::float AS cost_life
                        FROM worker w
                        LEFT JOIN assignment a ON a.worker_id = w.worker_id
                        LEFT JOIN cost_row  cr ON cr.assignment_id = a.assignment_id
                        WHERE w.host_id = %s AND w.archived_at IS NULL;
                        """,
                        (host_id,),
                    )
                    row = cur.fetchone()
                    if row:
                        bundle["windowed_kpis"] = {
                            "today":    {"invocations": int(row[0] or 0),
                                         "wall_s": float(row[1] or 0),
                                         "cost_usd": float(row[2] or 0)},
                            "week":     {"invocations": int(row[3] or 0),
                                         "wall_s": float(row[4] or 0),
                                         "cost_usd": float(row[5] or 0)},
                            "lifetime": {"invocations": int(row[6] or 0),
                                         "wall_s": float(row[7] or 0),
                                         "cost_usd": float(row[8] or 0)},
                        }
                except psycopg.errors.Error:
                    conn.rollback()

                # ---- Cost by role (host-scoped) ----------------------
                try:
                    cur.execute(
                        """
                        SELECT w.role_id,
                               COUNT(cr.assignment_id)::int            AS invocations,
                               COALESCE(SUM(cr.wall_s),0)::float       AS wall_s,
                               COALESCE(SUM(cr.cost_usd),0)::float     AS cost_usd,
                               COALESCE(SUM(cr.tokens_in),0)::int      AS tokens_in,
                               COALESCE(SUM(cr.tokens_out),0)::int     AS tokens_out
                        FROM worker w
                        LEFT JOIN assignment a ON a.worker_id = w.worker_id
                        LEFT JOIN cost_row cr ON cr.assignment_id = a.assignment_id
                        WHERE w.host_id = %s AND w.archived_at IS NULL
                        GROUP BY w.role_id
                        ORDER BY cost_usd DESC NULLS LAST, role_id;
                        """,
                        (host_id,),
                    )
                    bundle["cost_by_role"] = _cols_rows(cur)
                except psycopg.errors.Error:
                    conn.rollback()
                    bundle["cost_by_role"] = []

                # ---- Engagements touching this host ------------------
                try:
                    cur.execute(
                        """
                        SELECT e.engagement_id::text AS engagement_id,
                               e.slug,
                               e.title,
                               e.status::text AS status,
                               COALESCE(SUM(cr.cost_usd),0)::float AS my_cost_usd,
                               COUNT(DISTINCT cr.assignment_id)::int AS my_invocations,
                               MAX(cr.ts) AS last_activity_ts
                        FROM engagement e
                        LEFT JOIN cost_row cr ON cr.engagement_id = e.engagement_id
                        LEFT JOIN assignment a ON a.assignment_id = cr.assignment_id
                        LEFT JOIN worker w ON w.worker_id = a.worker_id
                        WHERE w.host_id = %s
                        GROUP BY e.engagement_id, e.slug, e.title, e.status
                        HAVING COUNT(cr.assignment_id) > 0
                        ORDER BY MAX(cr.ts) DESC NULLS LAST
                        LIMIT 20;
                        """,
                        (host_id,),
                    )
                    bundle["engagements"] = _isoify_rows(
                        _cols_rows(cur), ("last_activity_ts",)
                    )
                except psycopg.errors.Error:
                    conn.rollback()
                    bundle["engagements"] = []

                drilldown[host_id] = bundle

            snapshot["machine_drilldown"] = drilldown
        except psycopg.errors.Error:
            conn.rollback()
            snapshot.setdefault("machine_drilldown", {})

        # ---- Schema version ---------------------------------------------
        # flyway_schema_history may not exist if migrations haven't been
        # applied yet — guard with a try/except.
        try:
            cur.execute(
                """
                SELECT version, description, installed_on
                FROM flyway_schema_history
                ORDER BY installed_rank DESC
                LIMIT 1;
                """
            )
            row = cur.fetchone()
            if row is not None:
                snapshot["schema_version"] = {
                    "version": row[0],
                    "description": row[1],
                    "installed_on": _iso(row[2]),
                }
        except psycopg.errors.Error:
            # rollback so the conn stays usable; we're read-only anyway.
            conn.rollback()

    return snapshot


# ---------------------------------------------------------------------------
# Backwards-compat alias
# ---------------------------------------------------------------------------
# The function used to be called collect_snapshot(); keep the old name
# pointing at the new one so any external imports keep working.
collect_snapshot = build_snapshot


# ---------------------------------------------------------------------------
# File writer (the original top-level behavior)
# ---------------------------------------------------------------------------

def write_snapshot_file(path: Path = OUT_FILE) -> dict:
    """Connect, build a snapshot, write it to `path`, return the snapshot.
    Raises psycopg.OperationalError if the DB is unreachable — callers in
    script mode catch and translate that to a friendly stderr message."""
    conninfo = build_conninfo()
    conn = psycopg.connect(conninfo, autocommit=True)
    try:
        snapshot = build_snapshot(conn)
    finally:
        try:
            conn.close()
        except Exception:
            pass

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, default=str, indent=2))
    return snapshot


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    try:
        snapshot = write_snapshot_file(OUT_FILE)
    except psycopg.OperationalError as e:
        sys.stderr.write(
            "error: could not connect to Postgres.\n"
            f"  conninfo: {_sanitize_conninfo(build_conninfo())}\n"
            f"  reason:   {e}\n"
            "Is Postgres running? Try:\n"
            "    make up && make migrate\n"
            "Or override with SPINE_DB_URL=postgresql://... \n"
        )
        return 2

    kpis = snapshot["kpis"]
    sys.stdout.write(
        f"wrote {OUT_FILE} "
        f"({kpis.get('total_invocations', 0)} invocations, "
        f"{kpis.get('total_events', 0)} events, "
        f"{kpis.get('active_workers', 0)} active workers)\n"
    )
    return 0


def _sanitize_conninfo(s: str) -> str:
    """Strip password from a conninfo string for error logging."""
    out_parts: list[str] = []
    for part in s.split():
        if part.lower().startswith("password="):
            out_parts.append("password=***")
        else:
            out_parts.append(part)
    return " ".join(out_parts) if out_parts else s


if __name__ == "__main__":
    sys.exit(main())
