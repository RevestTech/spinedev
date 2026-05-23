#!/usr/bin/env python3
"""serve.py - Live HTTP server for the Spine recording-layer dashboard.

Drop-in replacement for `python3 -m http.server` that serves the static
dashboard files AND exposes a live /pg-snapshot.json endpoint backed by an
on-demand call into build_snapshot().

Design notes
------------
- Stdlib only: http.server + threading + psycopg 3 (already required by
  build-snapshot.py). No new dependencies.
- Single long-lived psycopg connection, lazily opened on first request.
  This means the server starts cleanly even when Postgres is down — the
  first browser request will be the one that surfaces the connection error
  (as a 503 JSON response, not a crash).
- 2-second TTL cache in front of the snapshot builder so simultaneous tabs
  / refresh-spam don't hammer Postgres.
- Connection error recovery: on OperationalError or InterfaceError we
  close, reopen, retry once, then 503.
- Default bind: 127.0.0.1:33002 (33001 is the Postgres host port).

Routes
------
  GET /                       -> dashboard/index.html
  GET /index.html             -> dashboard/index.html
  GET /pg-snapshot.json       -> live snapshot, no-store, JSON
  GET /health                 -> JSON: ok, db_connected, cached_age_s
  GET /<other static file>    -> served from dashboard/

Environment
-----------
  DASHBOARD_HOST     bind address (default 127.0.0.1)
  DASHBOARD_PORT     bind port    (default 33002)
  SNAPSHOT_TTL_S     snapshot cache TTL in seconds (default 2.0)
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import mimetypes
import os
import re
import signal
import sys
import threading
import time
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

# ---------------------------------------------------------------------------
# psycopg presence check (mirror build-snapshot.py's behavior)
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
# Import refactored helpers from build-snapshot.py
# ---------------------------------------------------------------------------
# build-snapshot.py has a hyphen in the name, so we need importlib.
import importlib.util

HERE = Path(__file__).resolve().parent
_SPEC = importlib.util.spec_from_file_location(
    "build_snapshot_mod", HERE / "build-snapshot.py"
)
if _SPEC is None or _SPEC.loader is None:
    sys.stderr.write("error: could not load build-snapshot.py\n")
    sys.exit(2)
_BS = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_BS)

build_conninfo = _BS.build_conninfo
build_snapshot = _BS.build_snapshot
_sanitize_conninfo = _BS._sanitize_conninfo


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

HOST = os.environ.get("DASHBOARD_HOST") or "127.0.0.1"
try:
    PORT = int(os.environ.get("DASHBOARD_PORT") or "33002")
except ValueError:
    PORT = 33002

try:
    TTL_S = float(os.environ.get("SNAPSHOT_TTL_S") or "2.0")
except ValueError:
    TTL_S = 2.0


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("dashboard")


# ---------------------------------------------------------------------------
# Connection + snapshot cache (thread-safe singleton)
# ---------------------------------------------------------------------------

class SnapshotProvider:
    """Owns the lazy psycopg connection and the TTL snapshot cache."""

    def __init__(self, conninfo_factory, ttl_s: float):
        self._conninfo_factory = conninfo_factory
        self._ttl_s = ttl_s
        self._lock = threading.Lock()
        self._conn = None
        self._cached_snapshot: dict | None = None
        self._cached_at: float = 0.0  # monotonic seconds
        # Whether the last DB attempt succeeded — used by /health.
        self._db_connected: bool = False

    # ---- connection lifecycle ------------------------------------------

    def _open(self) -> None:
        """Open a fresh connection. Caller MUST hold self._lock."""
        conninfo = self._conninfo_factory()
        log.info("opening Postgres connection (%s)",
                 _sanitize_conninfo(conninfo))
        self._conn = psycopg.connect(conninfo, autocommit=True)
        self._db_connected = True

    def _close(self) -> None:
        """Close the connection ignoring errors. Caller MUST hold lock."""
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None
        self._db_connected = False

    def close(self) -> None:
        """Public shutdown hook."""
        with self._lock:
            self._close()

    # ---- snapshot fetching ---------------------------------------------

    def _is_fresh(self) -> bool:
        if self._cached_snapshot is None:
            return False
        return (time.monotonic() - self._cached_at) < self._ttl_s

    def cached_age_s(self) -> float:
        if self._cached_snapshot is None:
            return float("inf")
        return time.monotonic() - self._cached_at

    def db_connected(self) -> bool:
        return self._db_connected

    def get(self) -> tuple[dict, bool]:
        """Return (snapshot, from_cache). Raises psycopg.Error on failure
        after one retry. Thread-safe."""
        with self._lock:
            if self._is_fresh():
                age = time.monotonic() - self._cached_at
                log.info("cache hit (age=%.2fs)", age)
                return self._cached_snapshot, True  # type: ignore[return-value]

            # Cache miss — try to (open and) query.
            last_err: Exception | None = None
            for attempt in range(2):
                if self._conn is None:
                    try:
                        self._open()
                    except psycopg.OperationalError as e:
                        last_err = e
                        log.warning(
                            "connect failed (attempt %d/2): %s", attempt + 1, e
                        )
                        # No conn to close; just retry the open on next loop.
                        continue
                t0 = time.monotonic()
                try:
                    snap = build_snapshot(self._conn)
                    dur_ms = (time.monotonic() - t0) * 1000.0
                    self._cached_snapshot = snap
                    self._cached_at = time.monotonic()
                    log.info("snapshot built in %.1fms", dur_ms)
                    return snap, False
                except (psycopg.OperationalError, psycopg.InterfaceError) as e:
                    last_err = e
                    log.warning(
                        "query failed (attempt %d/2): %s — recycling conn",
                        attempt + 1, e,
                    )
                    self._close()
                    # loop will reopen and retry once
                except psycopg.Error as e:
                    # other DB errors are not connection-level — surface them
                    last_err = e
                    log.error("query failed: %s", e)
                    break

            assert last_err is not None
            raise last_err


PROVIDER = SnapshotProvider(build_conninfo, TTL_S)


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

DASHBOARD_DIR = HERE
INDEX_FILE = DASHBOARD_DIR / "index.html"

# ---------------------------------------------------------------------------
# Engagement intake (Pass I-1)
# ---------------------------------------------------------------------------
#
# The dashboard backend is the only place that knows how to materialize a
# brand-new engagement on disk and on the bus. The watcher then picks the
# event up from the top-level outbox and projects it into Postgres.
#
# Flow when a user submits the "New Engagement" form:
#   1. Validate title + requirements_md (400 on missing/empty)
#   2. Generate slug from title + date stamp (-YYYY-MM-DD)
#   3. Verify slug matches ^[a-z0-9-]+$ (defense in depth; the generator
#      already enforces this, but the regex check protects against any
#      future code that constructs a slug differently)
#   4. Write <project_root>/engagements/<slug>/requirements.md (rejects
#      collisions on disk by suffixing -2, -3, ... until unique)
#   5. Write the product-role directive at
#      .planning/orchestration/agent-handoff/teams/product/directive.md
#   6. Append a {"type":"engagement","event_type":"EngagementCreated",...}
#      line to the top-level instance outbox so the watcher inserts the
#      row into Postgres on its next tick.
#   7. Return 201 with engagement_id + slug + status + requirements_uri.
#
# Path safety: every filesystem write is rooted at PROJECT_ROOT and
# validated relative_to() that root before opening.

# Resolve project root from a known anchor: this file lives at
# <project>/db/dashboard/serve.py so two parents up is <project>. Anchoring
# from __file__ (not cwd) means the server works no matter where it is
# launched from.
PROJECT_ROOT = HERE.parent.parent

# Engagements directory (where requirements.md and later artifacts live).
# Overridable for testing via SPINE_ENGAGEMENTS_DIR.
ENGAGEMENTS_DIR = Path(
    os.environ.get("SPINE_ENGAGEMENTS_DIR")
    or (PROJECT_ROOT / "engagements")
).resolve()

# Product-role directive (where the daemon picks up the next request).
# The directive file is overwritten on each new engagement — the daemon's
# directive-pickup logic already handles "new content same path", so this
# is enough to route a new brief to the product role.
PRODUCT_DIRECTIVE = (
    PROJECT_ROOT
    / ".planning" / "orchestration" / "agent-handoff"
    / "teams" / "product" / "directive.md"
)

# Top-level instance outbox (same file the watcher already reads for
# InstanceStarted / InstanceHeartbeat / InstanceStopped). Overridable via
# SPINE_INSTANCE_OUTBOX for testing.
INSTANCE_OUTBOX = Path(
    os.environ.get("SPINE_INSTANCE_OUTBOX")
    or (PROJECT_ROOT
        / ".planning" / "orchestration" / "agent-handoff"
        / ".instance-outbox.jsonl")
).resolve()

# Strict slug pattern: lowercase letters, digits, hyphen. Matches what
# slugify() emits below.
SLUG_RE = re.compile(r"^[a-z0-9-]+$")


def slugify_title(title: str, today_iso: str) -> str:
    """Convert a free-form title into a url-safe slug suffixed with the
    submission date so two engagements with the same title submitted on
    different days don't collide.

    "Build a marketing site!" + "2026-05-12"
        -> "build-a-marketing-site-2026-05-12"
    """
    s = title.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    if not s:
        s = "engagement"
    return f"{s}-{today_iso}"


def _under_root(path: Path, root: Path) -> bool:
    """Path-safety check: is `path` strictly under `root` after resolve?"""
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _build_directive_md(title: str, slug: str, engagement_id: str) -> str:
    """Compose the product-role directive markdown. Kept inline (not a
    template file) so the dashboard backend has no external dependencies
    when materializing a new engagement.
    """
    return (
        f"# Directive — Engagement intake: {title}\n"
        f"\n"
        f"## Tier hint: medium\n"
        f"\n"
        f"## Engagement-Id: {engagement_id}\n"
        f"\n"
        f"## Engagement\n"
        f"- id: {engagement_id}\n"
        f"- slug: {slug}\n"
        f"- requirements: engagements/{slug}/requirements.md\n"
        f"\n"
        f"## What to do\n"
        f"1. Read engagements/{slug}/requirements.md (the client's brief).\n"
        f"2. If anything is ambiguous, missing, or contradictory, reply with "
        f"`# Open Questions — {slug}` containing a numbered list of "
        f"clarifying questions. Do NOT proceed to a REQ until those are "
        f"answered.\n"
        f"3. If the brief is complete enough, draft a normative REQ document "
        f"at engagements/{slug}/REQ.md following "
        f"templates/program/REQ_TEMPLATE.md. When done, reply with "
        f"`# Report — REQ drafted for {slug}` and reference "
        f"engagements/{slug}/REQ.md.\n"
        f"\n"
        f"## Files touched\n"
        f"Use engagements/{slug}/ for any new files you create. Do not touch "
        f"other parts of the repo.\n"
    )


def _append_outbox_line(outbox: Path, line: str) -> None:
    """Append one JSONL line to the top-level instance outbox.

    Mirrors lib/db-outbox.sh's belt-and-braces strategy: a single append on
    a small line is effectively atomic on POSIX, and the watcher's per-
    line cursor tolerates concurrent writes. We do NOT take a file lock
    here -- the watcher reads with a byte-offset cursor and only advances
    on success, so a torn write would be re-read next tick.
    """
    outbox.parent.mkdir(parents=True, exist_ok=True)
    with outbox.open("ab") as fh:
        fh.write((line + "\n").encode("utf-8"))


def _engagement_dir_for(slug: str) -> Path:
    """Return the directory we'd materialize an engagement into. Caller is
    responsible for verifying it's under ENGAGEMENTS_DIR before writing."""
    return ENGAGEMENTS_DIR / slug


def create_engagement(payload: dict) -> tuple[int, dict]:
    """Materialize a new engagement on disk + emit EngagementCreated.

    Returns (http_status, response_dict). Pure helper so it can be unit
    tested without spinning up the HTTPServer.

    Errors:
      400 -- missing/empty title or requirements_md
      400 -- slug format invalid (defensive; shouldn't happen given the
             slugify_title logic)
      409 -- engagement directory already exists for this slug AND a
             counter-suffix would collide too (extremely rare)
      500 -- filesystem write failed
    """
    title = (payload.get("title") or "").strip()
    requirements_md = payload.get("requirements_md") or ""
    if not title:
        return 400, {"error": "missing_title",
                     "detail": "title is required"}
    if not requirements_md.strip():
        return 400, {"error": "missing_requirements_md",
                     "detail": "requirements_md is required"}

    client = (payload.get("client") or "").strip() or os.environ.get(
        "USER", "anonymous"
    )

    today = dt.date.today().isoformat()
    base_slug = slugify_title(title, today)
    if not SLUG_RE.match(base_slug):
        return 400, {"error": "slug_invalid",
                     "detail": f"generated slug {base_slug!r} failed validation"}

    # Find a free slug on disk by trying base, base-2, base-3, ... up to
    # base-99. After that, give up and 409. In practice the (team_id,
    # slug) DB unique constraint also guards uniqueness; this is the
    # filesystem-side check.
    slug = base_slug
    eng_dir = _engagement_dir_for(slug)
    if not _under_root(eng_dir, ENGAGEMENTS_DIR):
        return 400, {"error": "slug_invalid",
                     "detail": "slug resolves outside engagements root"}
    counter = 2
    while eng_dir.exists():
        slug = f"{base_slug}-{counter}"
        eng_dir = _engagement_dir_for(slug)
        if not _under_root(eng_dir, ENGAGEMENTS_DIR):
            return 400, {"error": "slug_invalid",
                         "detail": "slug resolves outside engagements root"}
        counter += 1
        if counter > 100:
            return 409, {"error": "slug_collision",
                         "detail": f"slug {base_slug!r} already used too many times today"}

    if not SLUG_RE.match(slug):
        return 400, {"error": "slug_invalid",
                     "detail": f"final slug {slug!r} failed validation"}

    engagement_id = str(uuid.uuid4())
    requirements_rel = f"engagements/{slug}/requirements.md"
    requirements_uri = f"file://{requirements_rel}"

    # ---- Disk writes ------------------------------------------------------
    # Atomicity: write requirements.md first, then the directive. If the
    # outbox append fails we still leave the on-disk artifacts in place --
    # the next manual retry can re-emit the event, and the directive
    # itself is enough for the product daemon to act on. Documented in
    # the report.
    try:
        eng_dir.mkdir(parents=True, exist_ok=False)
        req_path = eng_dir / "requirements.md"
        if not _under_root(req_path, ENGAGEMENTS_DIR):
            return 400, {"error": "path_invalid",
                         "detail": "requirements path escapes engagements root"}
        req_path.write_text(requirements_md, encoding="utf-8")
    except FileExistsError:
        # Race: another request created the same dir between the exists()
        # check and the mkdir. Re-raise as 409.
        return 409, {"error": "slug_collision",
                     "detail": f"engagement dir {slug!r} appeared during write"}
    except OSError as e:
        return 500, {"error": "disk_write_failed",
                     "detail": f"requirements.md: {e}"}

    try:
        if not _under_root(PRODUCT_DIRECTIVE, PROJECT_ROOT):
            return 500, {"error": "path_invalid",
                         "detail": "product directive path escapes project root"}
        PRODUCT_DIRECTIVE.parent.mkdir(parents=True, exist_ok=True)
        PRODUCT_DIRECTIVE.write_text(
            _build_directive_md(title, slug, engagement_id),
            encoding="utf-8",
        )
    except OSError as e:
        return 500, {"error": "disk_write_failed",
                     "detail": f"directive.md: {e}"}

    # ---- Emit EngagementCreated to the top-level instance outbox ---------
    event = {
        "type": "engagement",
        "ts": dt.datetime.now(dt.timezone.utc).isoformat().replace(
            "+00:00", "Z"
        ),
        "event_type": "EngagementCreated",
        "engagement_id": engagement_id,
        "group_id": os.environ.get("SPINE_GROUP_ID", ""),
        "host_id": os.environ.get("SPINE_HOST_ID", ""),
        "payload": {
            "title": title,
            "slug": slug,
            "client": client,
            "requirements_uri": requirements_uri,
        },
    }
    try:
        _append_outbox_line(INSTANCE_OUTBOX, json.dumps(event))
    except OSError as e:
        log.warning(
            "engagement event emit failed (engagement_id=%s slug=%s): %s; "
            "disk artifacts kept, retry will be needed to project to DB",
            engagement_id, slug, e,
        )

    return 201, {
        "engagement_id": engagement_id,
        "slug": slug,
        "status": "intake",
        "requirements_uri": requirements_uri,
    }


# ---------------------------------------------------------------------------
# Engagement detail / clarification / promotion (Pass I-2)
# ---------------------------------------------------------------------------
#
# The detail endpoint queries v_engagement_detail (V8) + engagement_message
# directly so the dashboard can render the conversation thread without
# round-tripping through the snapshot cache. The /answer and /promote
# endpoints both append to the directive file AND emit an outbox event so
# the watcher projects the state into Postgres on the next tick.
#
# All three endpoints take a slug (string) -- never an engagement_id -- so
# the URLs match the engagement.html page's primary key (?slug=<slug>).
# The slug is unique per (team_id, slug); for Pass I-2 we are single-team
# so the slug alone is enough.

# Engagement-status transition graph used by /promote. Maps from -> set
# of statuses you're allowed to manually push it to. Mirrors the natural
# lifecycle: intake -> hardening -> planning -> awaiting_approval ->
# executing -> delivered, with cancelled reachable from any non-terminal
# state. delivered is terminal; promotion away from it is rejected.
LEGAL_PROMOTIONS: dict[str, set[str]] = {
    "intake":            {"hardening", "planning", "cancelled"},
    "hardening":         {"planning", "cancelled"},
    "planning":          {"awaiting_approval", "hardening", "cancelled"},
    "awaiting_approval": {"executing", "planning", "cancelled"},
    "executing":         {"delivered", "cancelled"},
    "delivered":         set(),
    "cancelled":         set(),
}


# Pass I-3: conductor directive lives one level below TEAM_BASE under
# "conductor/directive.md", same convention as every other manager team.
# The approve endpoint overwrites this file with the dispatch directive
# below; the daemon's pickup logic re-hashes on every poll, so an
# overwrite triggers a fresh invocation.
CONDUCTOR_DIRECTIVE = (
    PROJECT_ROOT
    / ".planning" / "orchestration" / "agent-handoff"
    / "teams" / "conductor" / "directive.md"
)


def _eng_dir_for_slug(slug: str) -> Path | None:
    """Resolve the engagement directory for a slug, with path safety.
    Returns None if the slug escapes the engagements root."""
    if not SLUG_RE.match(slug):
        return None
    p = (ENGAGEMENTS_DIR / slug).resolve()
    if not _under_root(p, ENGAGEMENTS_DIR):
        return None
    return p


def _emit_engagement_event(engagement_id: str, event_type: str,
                            payload: dict) -> None:
    """Append one engagement event to the top-level instance outbox.
    Mirrors the EngagementCreated emit path used by create_engagement().
    """
    event = {
        "type": "engagement",
        "ts": dt.datetime.now(dt.timezone.utc).isoformat().replace(
            "+00:00", "Z"
        ),
        "event_type": event_type,
        "engagement_id": engagement_id,
        "group_id": os.environ.get("SPINE_GROUP_ID", ""),
        "host_id": os.environ.get("SPINE_HOST_ID", ""),
        "payload": payload,
    }
    _append_outbox_line(INSTANCE_OUTBOX, json.dumps(event))


def fetch_engagement_detail(slug: str) -> tuple[int, dict]:
    """Fetch one engagement + its messages.

    Returns (status_code, body_dict). 200 with payload on success, 404 if
    no engagement matches the slug, 503 if the DB is unavailable. Falls
    back gracefully when V8 is not applied yet (no engagement_message
    table, no v_engagement_detail view) by querying v_engagements_overview
    and returning an empty messages list.
    """
    # We acquire our own short-lived connection for detail queries so
    # /api/engagements/<slug> doesn't share a transaction with concurrent
    # snapshot work. Simpler than reasoning about psycopg autocommit.
    try:
        conn = psycopg.connect(build_conninfo(), autocommit=True)
    except psycopg.OperationalError as e:
        return 503, {"error": "db_unavailable", "detail": str(e)}

    eng: dict | None = None
    messages: list[dict] = []
    # Pass I-3: per-engagement timeline + cost summary, populated below
    # against V9 views. Pre-V9 databases return empty/None and the
    # frontend renders a "no telemetry yet" placeholder.
    timeline: list[dict] = []
    cost_summary: dict | None = None
    # Pass J: per-engagement artifacts (last 100). Empty on pre-V10
    # databases where the view doesn't exist yet.
    artifacts: list[dict] = []
    try:
        with conn.cursor() as cur:
            # Prefer the V8 view; fall back to V7 overview if V8 hasn't
            # been applied. The fallback returns the same shape but with
            # message_count=0 and the new URI columns set to None.
            try:
                cur.execute(
                    """
                    SELECT
                      engagement_id::text AS engagement_id,
                      slug, title, client, status::text AS status,
                      requirements_uri, req_uri, open_questions_uri,
                      planner_report_uri, plan_uri,
                      architect_adr_uris,
                      created_at, updated_at, approved_at, delivered_at,
                      message_count::int AS message_count
                    FROM v_engagement_detail
                    WHERE slug = %s
                    LIMIT 1
                    """,
                    (slug,),
                )
                row = cur.fetchone()
                if row is not None:
                    cols = [d.name for d in cur.description or []]
                    eng = dict(zip(cols, row))
            except psycopg.errors.Error:
                conn.rollback()
                eng = None

            if eng is None:
                # V8 view absent OR engagement missing — try v7 overview.
                try:
                    cur.execute(
                        """
                        SELECT
                          engagement_id::text AS engagement_id,
                          slug, title, client, status::text AS status,
                          requirements_uri, plan_uri,
                          created_at, updated_at, approved_at, delivered_at
                        FROM v_engagements_overview
                        WHERE slug = %s
                        LIMIT 1
                        """,
                        (slug,),
                    )
                    row = cur.fetchone()
                    if row is not None:
                        cols = [d.name for d in cur.description or []]
                        eng = dict(zip(cols, row))
                        # Defaults for V8-only fields.
                        eng.setdefault("req_uri", None)
                        eng.setdefault("open_questions_uri", None)
                        eng.setdefault("planner_report_uri", None)
                        eng.setdefault("architect_adr_uris", [])
                        eng.setdefault("message_count", 0)
                except psycopg.errors.Error:
                    conn.rollback()
                    eng = None

            if eng is None:
                return 404, {"error": "not_found",
                             "detail": f"no engagement with slug {slug!r}"}

            # Messages — best-effort. Pre-V8 the table doesn't exist.
            try:
                cur.execute(
                    """
                    SELECT
                      message_id::text AS message_id,
                      role, kind, body_md,
                      created_at, metadata_json
                    FROM engagement_message
                    WHERE engagement_id = %s::uuid
                    ORDER BY created_at ASC, message_id ASC
                    """,
                    (eng["engagement_id"],),
                )
                cols = [d.name for d in cur.description or []]
                messages = [dict(zip(cols, r)) for r in cur.fetchall()]
            except psycopg.errors.Error:
                conn.rollback()
                messages = []

            # Pass I-3: timeline (last 100 events from v_engagement_timeline).
            # Best-effort: pre-V9 the view doesn't exist and we leave the
            # list empty so the dashboard renders the placeholder.
            try:
                cur.execute(
                    """
                    SELECT
                      event_id::text AS event_id,
                      ts, type, role_id, handle, host_id, payload_json
                    FROM v_engagement_timeline
                    WHERE engagement_id = %s::uuid
                    ORDER BY ts DESC
                    LIMIT 100
                    """,
                    (eng["engagement_id"],),
                )
                cols = [d.name for d in cur.description or []]
                timeline = [dict(zip(cols, r)) for r in cur.fetchall()]
            except psycopg.errors.Error:
                conn.rollback()
                timeline = []

            # Pass J: per-engagement artifacts (last 100). Best-effort:
            # pre-V10 the view doesn't exist and we leave the list empty.
            try:
                cur.execute(
                    """
                    SELECT
                      artifact_id::text AS artifact_id,
                      kind::text        AS kind,
                      uri,
                      title,
                      metadata_json,
                      created_at,
                      role_id,
                      handle
                    FROM v_engagement_artifacts
                    WHERE engagement_id = %s::uuid
                    ORDER BY created_at DESC
                    LIMIT 100
                    """,
                    (eng["engagement_id"],),
                )
                cols = [d.name for d in cur.description or []]
                artifacts = [dict(zip(cols, r)) for r in cur.fetchall()]
            except psycopg.errors.Error:
                conn.rollback()
                artifacts = []

            # Pass I-3: cost_summary (single row from v_engagement_costs).
            try:
                cur.execute(
                    """
                    SELECT
                      invocations::int    AS invocations,
                      wall_s::float       AS wall_s,
                      tokens_in::int      AS tokens_in,
                      tokens_out::int     AS tokens_out,
                      cost_usd::float     AS cost_usd,
                      roles_used::int     AS roles_used,
                      workers_used::int   AS workers_used
                    FROM v_engagement_costs
                    WHERE engagement_id = %s::uuid
                    """,
                    (eng["engagement_id"],),
                )
                row = cur.fetchone()
                if row is not None:
                    cols = [d.name for d in cur.description or []]
                    cost_summary = dict(zip(cols, row))
            except psycopg.errors.Error:
                conn.rollback()
                cost_summary = None
    finally:
        try:
            conn.close()
        except Exception:
            pass

    # ISO-ify timestamps
    for key in ("created_at", "updated_at", "approved_at", "delivered_at"):
        if key in eng and isinstance(eng[key], (dt.datetime, dt.date)):
            eng[key] = eng[key].isoformat()
    for m in messages:
        if isinstance(m.get("created_at"), (dt.datetime, dt.date)):
            m["created_at"] = m["created_at"].isoformat()
    for ev in timeline:
        if isinstance(ev.get("ts"), (dt.datetime, dt.date)):
            ev["ts"] = ev["ts"].isoformat()
    for a in artifacts:
        if isinstance(a.get("created_at"), (dt.datetime, dt.date)):
            a["created_at"] = a["created_at"].isoformat()

    return 200, {
        "engagement": eng,
        "messages": messages,
        "timeline": timeline,
        "cost_summary": cost_summary,
        "artifacts": artifacts,
    }


def _append_human_answer_to_directive(slug: str, body_md: str) -> None:
    """Append a `### Human answer` section to the product directive.

    The daemon's pickup logic re-hashes the directive on every poll, so
    appending content causes a re-pickup. The product role's prompt
    documents that an answer arrives as a `### Human answer` section in
    its directive on the next tick.

    Best-effort: missing directive file logs but doesn't fail the answer
    (the event still goes into the conversation thread). Path-safety
    enforced against PROJECT_ROOT.
    """
    if not _under_root(PRODUCT_DIRECTIVE, PROJECT_ROOT):
        log.warning("answer append: product directive path escapes project root")
        return
    if not PRODUCT_DIRECTIVE.is_file():
        log.warning("answer append: product directive missing at %s",
                    PRODUCT_DIRECTIVE)
        return
    try:
        ts = dt.datetime.now(dt.timezone.utc).isoformat().replace(
            "+00:00", "Z"
        )
        addition = (
            f"\n\n### Human answer ({slug} @ {ts})\n\n"
            f"{body_md.rstrip()}\n"
        )
        with PRODUCT_DIRECTIVE.open("ab") as fh:
            fh.write(addition.encode("utf-8"))
    except OSError as e:
        log.warning("answer append failed: %s", e)


def post_answer(slug: str, payload: dict) -> tuple[int, dict]:
    """POST /api/engagements/<slug>/answer.

    Body: {"body_md": "..."}.
      1. Append the human's answer to the product directive so the daemon
         picks it up on the next poll.
      2. Emit an EngagementMessage event with role=human kind=answer.
      3. Return 201 with {message_id, engagement_id}.
    """
    body_md = (payload.get("body_md") or "").strip()
    if not body_md:
        return 400, {"error": "missing_body_md",
                     "detail": "body_md is required"}

    # We need the engagement_id to attach the message. Use the same
    # detail fetcher.
    status, detail = fetch_engagement_detail(slug)
    if status != 200:
        return status, detail
    eng = detail["engagement"]
    engagement_id = eng["engagement_id"]

    _append_human_answer_to_directive(slug, body_md)

    # Generate a client-side message_id so the response carries it back
    # immediately (the watcher will assign its own DB id; the client uses
    # the response value only as a render hint).
    message_id = str(uuid.uuid4())
    try:
        _emit_engagement_event(
            engagement_id,
            "EngagementMessage",
            {
                "role": "human",
                "kind": "answer",
                "body_md": body_md,
                "metadata": {"client_message_id": message_id, "slug": slug},
            },
        )
    except OSError as e:
        return 500, {"error": "outbox_emit_failed", "detail": str(e)}

    return 201, {
        "message_id": message_id,
        "engagement_id": engagement_id,
        "status": eng["status"],
    }


def post_promote(slug: str, payload: dict) -> tuple[int, dict]:
    """POST /api/engagements/<slug>/promote.

    Body: {"to": "planning" | "awaiting_approval" | ...}.
    Validates the requested transition against LEGAL_PROMOTIONS and emits
    an EngagementStatusChanged event. Returns 200 with the new status.
    """
    target = (payload.get("to") or "").strip()
    if not target:
        return 400, {"error": "missing_to",
                     "detail": "'to' (target status) is required"}
    if target not in LEGAL_PROMOTIONS and target != "intake":
        return 400, {"error": "invalid_target",
                     "detail": f"unknown status {target!r}"}

    status, detail = fetch_engagement_detail(slug)
    if status != 200:
        return status, detail
    eng = detail["engagement"]
    current = eng["status"]
    engagement_id = eng["engagement_id"]

    allowed = LEGAL_PROMOTIONS.get(current, set())
    if target not in allowed:
        return 409, {
            "error": "illegal_transition",
            "detail": f"cannot promote from {current!r} to {target!r}",
            "current_status": current,
            "allowed": sorted(allowed),
        }

    try:
        _emit_engagement_event(
            engagement_id,
            "EngagementStatusChanged",
            {"new_status": target,
             "metadata": {"source": "dashboard_promote", "slug": slug}},
        )
    except OSError as e:
        return 500, {"error": "outbox_emit_failed", "detail": str(e)}

    return 200, {
        "engagement_id": engagement_id,
        "previous_status": current,
        "status": target,
    }


# ---------------------------------------------------------------------------
# Pass I-3: approve / reject — kick the conductor off, or kill the engagement
# ---------------------------------------------------------------------------
#
# The approve flow has three side effects, in order:
#   1. Append `## Approved by: <approver> @ <ts>` to the plan.md file so
#      the audit trail lives next to the plan.
#   2. Overwrite the conductor's `directive.md` with the dispatch markdown
#      (see _build_conductor_dispatch_md). The conductor's daemon picks
#      that up on its next poll, parses the plan, and fans out
#      sub-directives — that fan-out behavior is the agent's job, not the
#      backend's.
#   3. Emit an EngagementStatusChanged event with new_status=executing.
#
# Reject is much simpler: append a rejection line to plan.md and emit
# EngagementStatusChanged with new_status=cancelled.
#
# Both endpoints check status before mutating, so a duplicate submit
# (browser retry) returns 409 with the current status rather than
# double-firing the conductor or stamping cancellation twice.


def _build_conductor_dispatch_md(engagement: dict) -> str:
    """Compose the conductor dispatch directive for an approved plan.

    The directive carries the engagement's primary keys + URIs and tells
    the conductor to fan out sub-directives by role. Each sub-directive
    the conductor writes MUST carry the parent Engagement-Id so the
    daemon's outbox helper attributes downstream cost rows and events
    back to this engagement.
    """
    title = engagement.get("title") or engagement.get("slug") or "(untitled)"
    slug = engagement.get("slug") or ""
    eid = engagement.get("engagement_id") or ""
    plan_uri = engagement.get("plan_uri") or ""
    req_uri = engagement.get("req_uri") or ""
    requirements_uri = engagement.get("requirements_uri") or ""
    return (
        f"# Directive — Execute engagement: {title}\n"
        f"\n"
        f"## Tier hint: medium\n"
        f"\n"
        f"## Engagement-Id: {eid}\n"
        f"\n"
        f"## Engagement\n"
        f"- slug: {slug}\n"
        f"- plan: {plan_uri}\n"
        f"- requirements: {requirements_uri}\n"
        f"- req: {req_uri}\n"
        f"\n"
        f"## What to do\n"
        f"1. Read the approved plan at {plan_uri}. It contains role "
        f"assignments and a work breakdown.\n"
        f"2. For each role assignment in the plan, write a sub-directive "
        f"into the corresponding team's directive.md (or into conductor's "
        f"`workers/NN-directive.md` slots if you prefer manager-mediated "
        f"fan-out — your call based on the plan's complexity).\n"
        f"3. Each sub-directive you create MUST include "
        f"`## Engagement-Id: {eid}` so cost rows and events get "
        f"attributed.\n"
        f"4. When all sub-directives are reported back, aggregate into a "
        f"final report. Then emit "
        f"`## Spine-Hub: status=delivered plan_uri={plan_uri}` so the "
        f"engagement transitions to delivered.\n"
        f"\n"
        f"## Report format\n"
        f"Replace this directive with `# Report — Engagement {slug} "
        f"dispatched` listing every sub-directive you wrote and the role "
        f"each went to.\n"
    )


def _resolve_local_uri(uri: str) -> Path | None:
    """Translate a stored URI ("file://engagements/foo/plan.md" or a bare
    relative path) to a real Path under PROJECT_ROOT. Returns None when
    the URI is empty, opaque (e.g., http://...), or escapes the project
    root after resolution."""
    if not uri:
        return None
    if uri.startswith("file://"):
        rel = uri[len("file://"):]
    elif "://" in uri:
        # http:// / https:// / s3:// — we can't append to those.
        return None
    else:
        rel = uri
    candidate = (PROJECT_ROOT / rel).resolve()
    if not _under_root(candidate, PROJECT_ROOT):
        return None
    return candidate


def _append_to_plan(plan_uri: str, line: str) -> bool:
    """Append `line` (with a leading and trailing newline) to plan.md.

    Returns True on success, False on any path / IO failure. Failures are
    logged but never raised so the caller can keep emitting the event
    (the disk artifact is best-effort; the event is the audit source of
    truth)."""
    target = _resolve_local_uri(plan_uri)
    if target is None:
        log.warning("plan append: cannot resolve plan_uri=%r", plan_uri)
        return False
    if not target.is_file():
        log.warning("plan append: file missing at %s", target)
        return False
    try:
        with target.open("ab") as fh:
            fh.write(b"\n")
            fh.write(line.encode("utf-8"))
            fh.write(b"\n")
        return True
    except OSError as e:
        log.warning("plan append failed: %s", e)
        return False


def _write_conductor_directive(content: str) -> bool:
    """Overwrite the conductor directive with `content`. Returns True on
    success, False on failure. Path-safety enforced."""
    if not _under_root(CONDUCTOR_DIRECTIVE, PROJECT_ROOT):
        log.warning(
            "conductor directive path %s escapes project root",
            CONDUCTOR_DIRECTIVE,
        )
        return False
    try:
        CONDUCTOR_DIRECTIVE.parent.mkdir(parents=True, exist_ok=True)
        CONDUCTOR_DIRECTIVE.write_text(content, encoding="utf-8")
        return True
    except OSError as e:
        log.warning("conductor directive write failed: %s", e)
        return False


def post_approve(slug: str, payload: dict) -> tuple[int, dict]:
    """POST /api/engagements/<slug>/approve.

    Body: {"approver": "khash"} (defaults to $USER, then "anonymous").

    1. Look up engagement. 409 if status != 'awaiting_approval'.
    2. Append `## Approved by: <approver> @ <ts>` to plan.md.
    3. Write conductor dispatch directive.
    4. Emit EngagementStatusChanged(new_status=executing).
    5. Return 200 with the updated engagement detail.
    """
    approver = (payload.get("approver") or "").strip() or os.environ.get(
        "USER", "anonymous"
    )

    status, detail = fetch_engagement_detail(slug)
    if status != 200:
        return status, detail
    eng = detail["engagement"]
    current = eng.get("status")
    engagement_id = eng["engagement_id"]

    if current != "awaiting_approval":
        return 409, {
            "error": "wrong_status",
            "detail": f"engagement not awaiting approval (status: {current})",
            "current_status": current,
        }

    ts = dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")

    plan_uri = eng.get("plan_uri") or ""
    plan_appended = _append_to_plan(
        plan_uri,
        f"## Approved by: {approver} @ {ts}",
    )

    directive_md = _build_conductor_dispatch_md(eng)
    directive_written = _write_conductor_directive(directive_md)

    try:
        _emit_engagement_event(
            engagement_id,
            "EngagementStatusChanged",
            {
                "new_status": "executing",
                "metadata": {
                    "source": "dashboard_approve",
                    "approver": approver,
                    "approved_at": ts,
                    "slug": slug,
                    "plan_appended": plan_appended,
                    "directive_written": directive_written,
                },
            },
        )
    except OSError as e:
        return 500, {"error": "outbox_emit_failed", "detail": str(e)}

    # Re-fetch to return current state (the watcher hasn't projected the
    # status yet, but the engagement row is otherwise authoritative).
    _, fresh = fetch_engagement_detail(slug)
    fresh.setdefault("approval", {})
    fresh["approval"] = {
        "approver": approver,
        "approved_at": ts,
        "plan_appended": plan_appended,
        "directive_written": directive_written,
    }
    return 200, fresh


def post_reject(slug: str, payload: dict) -> tuple[int, dict]:
    """POST /api/engagements/<slug>/reject.

    Body: {"reason": "..."}. Minimum 5 characters (the dashboard already
    enforces this; the backend re-checks).

    1. Append `## Rejected: <reason> @ <ts>` to plan.md (best-effort).
    2. Emit EngagementStatusChanged(new_status=cancelled).
    3. Return 200.
    """
    reason = (payload.get("reason") or "").strip()
    if len(reason) < 5:
        return 400, {
            "error": "missing_reason",
            "detail": "reason is required (minimum 5 characters)",
        }

    status, detail = fetch_engagement_detail(slug)
    if status != 200:
        return status, detail
    eng = detail["engagement"]
    current = eng.get("status")
    engagement_id = eng["engagement_id"]

    if current not in {"awaiting_approval", "planning", "hardening", "intake"}:
        return 409, {
            "error": "wrong_status",
            "detail": f"cannot reject from status {current!r}",
            "current_status": current,
        }

    ts = dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")
    plan_uri = eng.get("plan_uri") or ""
    # Best-effort: when there's no plan yet (rejected from hardening)
    # the append silently no-ops.
    _append_to_plan(plan_uri, f"## Rejected: {reason} @ {ts}")

    try:
        _emit_engagement_event(
            engagement_id,
            "EngagementStatusChanged",
            {
                "new_status": "cancelled",
                "metadata": {
                    "source": "dashboard_reject",
                    "reason": reason,
                    "rejected_at": ts,
                    "slug": slug,
                },
            },
        )
    except OSError as e:
        return 500, {"error": "outbox_emit_failed", "detail": str(e)}

    _, fresh = fetch_engagement_detail(slug)
    fresh["rejection"] = {"reason": reason, "rejected_at": ts}
    return 200, fresh


# ---------------------------------------------------------------------------
# Releases (Pass L) — admin endpoints for the Spine Hub Pillar 2 code
# distribution flow. The dashboard backend lets an admin promote a specific
# commit of the SpineDevelopment template to one of three release channels
# (stable / beta / canary) and archive bad releases. Fleet members'
# updater.sh daemons poll v_release_heads on every tick and fast-forward
# to whatever's pinned.
# ---------------------------------------------------------------------------

RELEASE_CHANNELS = {"stable", "beta", "canary"}
SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")


def _connect_db_for_releases():
    """Open a short-lived autocommit connection for the release endpoints.
    Returns (conn, None) on success or (None, (status, body)) on failure."""
    try:
        return psycopg.connect(build_conninfo(), autocommit=True), None
    except psycopg.OperationalError as e:
        return None, (503, {"error": "db_unavailable", "detail": str(e)})


def create_release(payload: dict) -> tuple[int, dict]:
    """POST /api/releases — promote a commit to a channel.

    Body:
      {
        "channel":     "stable" | "beta" | "canary",
        "commit_sha":  "<40-hex>",
        "ref":         "main",            # optional
        "notes_md":    "...",             # optional
        "promoted_by": "khash"            # optional (falls back to $USER)
      }

    Returns 201 with the inserted row on success, 4xx with an error body on
    validation failure, 503 when the DB is unavailable, or 500 on insert
    failure (e.g., V12 not applied yet).
    """
    channel = (payload.get("channel") or "").strip().lower()
    if channel not in RELEASE_CHANNELS:
        return 400, {"error": "invalid_channel",
                     "detail": f"channel must be one of {sorted(RELEASE_CHANNELS)}"}
    commit_sha = (payload.get("commit_sha") or "").strip().lower()
    if not SHA_RE.match(commit_sha):
        return 400, {"error": "invalid_commit_sha",
                     "detail": "commit_sha must be 40 hex characters"}
    short_sha = commit_sha[:12]
    ref = payload.get("ref") or None
    if ref is not None:
        ref = str(ref).strip() or None
    notes_md = payload.get("notes_md") or None
    if notes_md is not None:
        notes_md = str(notes_md)
    promoted_by = (payload.get("promoted_by") or "").strip() or os.environ.get(
        "USER", "anonymous"
    )

    conn, err = _connect_db_for_releases()
    if err is not None:
        return err
    try:
        with conn.cursor() as cur:
            try:
                cur.execute(
                    """
                    INSERT INTO spine_release
                      (channel, commit_sha, short_sha, ref, notes_md, promoted_by)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING
                      release_id::text AS release_id,
                      channel::text    AS channel,
                      commit_sha,
                      short_sha,
                      ref,
                      notes_md,
                      promoted_by,
                      promoted_at,
                      archived_at
                    """,
                    (channel, commit_sha, short_sha, ref, notes_md, promoted_by),
                )
            except psycopg.errors.UniqueViolation:
                return 409, {"error": "duplicate",
                             "detail": "this (channel, commit_sha) is already promoted"}
            except psycopg.errors.UndefinedTable:
                return 500, {"error": "v12_missing",
                             "detail": "spine_release table not present; apply V12"}
            row = cur.fetchone()
            cols = [d.name for d in cur.description or []]
            release = dict(zip(cols, row))
            if isinstance(release.get("promoted_at"), (dt.datetime, dt.date)):
                release["promoted_at"] = release["promoted_at"].isoformat()
            if isinstance(release.get("archived_at"), (dt.datetime, dt.date)):
                release["archived_at"] = release["archived_at"].isoformat()
            return 201, release
    finally:
        try:
            conn.close()
        except Exception:
            pass


def list_releases(channel: str | None) -> tuple[int, dict]:
    """GET /api/releases?channel=stable — return release history (latest 20).
    When channel is None, returns the last 20 across every channel."""
    if channel is not None:
        channel = channel.strip().lower()
        if channel not in RELEASE_CHANNELS:
            return 400, {"error": "invalid_channel",
                         "detail": f"channel must be one of {sorted(RELEASE_CHANNELS)}"}
    conn, err = _connect_db_for_releases()
    if err is not None:
        return err
    try:
        with conn.cursor() as cur:
            try:
                if channel is None:
                    cur.execute(
                        """
                        SELECT
                          release_id::text AS release_id,
                          channel::text    AS channel,
                          commit_sha, short_sha, ref, notes_md,
                          promoted_by, promoted_at, archived_at
                        FROM spine_release
                        ORDER BY promoted_at DESC
                        LIMIT 20
                        """
                    )
                else:
                    cur.execute(
                        """
                        SELECT
                          release_id::text AS release_id,
                          channel::text    AS channel,
                          commit_sha, short_sha, ref, notes_md,
                          promoted_by, promoted_at, archived_at
                        FROM spine_release
                        WHERE channel = %s::release_channel
                        ORDER BY promoted_at DESC
                        LIMIT 20
                        """,
                        (channel,),
                    )
            except psycopg.errors.UndefinedTable:
                return 200, {"releases": [], "v12_missing": True}
            rows = []
            cols = [d.name for d in cur.description or []]
            for r in cur.fetchall():
                d = dict(zip(cols, r))
                for k in ("promoted_at", "archived_at"):
                    if isinstance(d.get(k), (dt.datetime, dt.date)):
                        d[k] = d[k].isoformat()
                rows.append(d)
            return 200, {"releases": rows}
    finally:
        try:
            conn.close()
        except Exception:
            pass


def archive_release(release_id: str) -> tuple[int, dict]:
    """POST /api/releases/<release_id>/archive — soft-delete a release.
    Sets archived_at = now(). Fleet members fall back to the next-newest
    non-archived release for the channel on the next pull-pin tick."""
    # Validate UUID shape defensively. psycopg will also reject malformed
    # UUIDs but we want a clean 400 instead of leaking the DB error.
    try:
        uuid.UUID(release_id)
    except (ValueError, AttributeError):
        return 400, {"error": "invalid_release_id",
                     "detail": "release_id must be a UUID"}

    conn, err = _connect_db_for_releases()
    if err is not None:
        return err
    try:
        with conn.cursor() as cur:
            try:
                cur.execute(
                    """
                    UPDATE spine_release
                    SET archived_at = now()
                    WHERE release_id = %s::uuid
                      AND archived_at IS NULL
                    RETURNING
                      release_id::text AS release_id,
                      channel::text    AS channel,
                      commit_sha, short_sha, ref,
                      promoted_at, archived_at
                    """,
                    (release_id,),
                )
            except psycopg.errors.UndefinedTable:
                return 500, {"error": "v12_missing",
                             "detail": "spine_release table not present; apply V12"}
            row = cur.fetchone()
            if row is None:
                return 404, {"error": "not_found",
                             "detail": "no live release with that id (already archived?)"}
            cols = [d.name for d in cur.description or []]
            d = dict(zip(cols, row))
            for k in ("promoted_at", "archived_at"):
                if isinstance(d.get(k), (dt.datetime, dt.date)):
                    d[k] = d[k].isoformat()
            return 200, d
    finally:
        try:
            conn.close()
        except Exception:
            pass


def list_engagements_from_snapshot() -> list[dict]:
    """Return the engagements array from a fresh snapshot. Used by GET
    /api/engagements so the frontend can refresh after a POST without a
    full page reload. Reuses the same provider + cache as /pg-snapshot.
    """
    try:
        snap, _from_cache = PROVIDER.get()
    except psycopg.Error:
        # Treat DB unavailability as "no engagements yet" rather than a
        # hard error -- the form has already succeeded on disk + outbox,
        # the watcher will project the row when the DB is back.
        return []
    return snap.get("engagements") or []


def _safe_static_path(url_path: str) -> Path | None:
    """Resolve a URL path to a file under DASHBOARD_DIR, blocking traversal.
    Returns None if the resolved path escapes the dashboard dir."""
    # Strip leading slashes; treat / as index.html.
    rel = url_path.lstrip("/")
    if rel == "":
        rel = "index.html"
    candidate = (DASHBOARD_DIR / rel).resolve()
    try:
        candidate.relative_to(DASHBOARD_DIR.resolve())
    except ValueError:
        return None
    return candidate


class Handler(BaseHTTPRequestHandler):
    # http.server logs every request to stderr by default. Silence it; we
    # log explicitly inline.
    def log_message(self, fmt: str, *args) -> None:  # noqa: D401
        return

    # ---- writers -------------------------------------------------------

    def _send_json(self, status: int, payload: dict, *, cache: str = "no-store") -> None:
        body = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _send_static(self, path: Path) -> None:
        if not path.is_file():
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        ctype, _ = mimetypes.guess_type(str(path))
        if ctype is None:
            ctype = "application/octet-stream"
        try:
            data = path.read_bytes()
        except OSError as e:
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"error": "read_failed", "detail": str(e)},
            )
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        # index.html and pg-snapshot.json should never be cached aggressively,
        # but other static assets (if any are added later) can be.
        if path.name in ("index.html",):
            self.send_header("Cache-Control", "no-store")
        else:
            self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    # ---- routes --------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802 (http.server API)
        parsed = urlsplit(self.path)
        path = parsed.path

        if path == "/pg-snapshot.json":
            self._handle_snapshot()
            return

        if path == "/health":
            self._handle_health()
            return

        if path == "/api/engagements":
            self._handle_engagements_list()
            return

        # Pass I-2: GET /api/engagements/<slug> — detail + messages.
        m = re.match(r"^/api/engagements/([a-z0-9-]+)$", path)
        if m is not None:
            self._handle_engagement_detail(m.group(1))
            return

        # Pass L: GET /api/releases[?channel=stable] — release history.
        if path == "/api/releases":
            from urllib.parse import parse_qs
            qs = parse_qs(parsed.query or "")
            channel_param = (qs.get("channel") or [None])[0]
            status, body = list_releases(channel_param)
            log.info("GET /api/releases?channel=%s -> %d",
                     channel_param, status)
            self._send_json(status, body)
            return

        # Pretty-URL aliases for the static pages (strip the .html).
        # Keeps URLs like /about and /tech clean while the static files on
        # disk are still about.html and tech.html.
        if path in ("/about", "/tech", "/machines", "/engagement", "/versions"):
            path = path + ".html"

        # everything else: static
        resolved = _safe_static_path(path)
        if resolved is None:
            self._send_json(HTTPStatus.FORBIDDEN, {"error": "forbidden"})
            return
        self._send_static(resolved)

    def do_POST(self) -> None:  # noqa: N802 (http.server API)
        parsed = urlsplit(self.path)
        path = parsed.path

        if path == "/api/engagements":
            self._handle_engagements_create()
            return

        # Pass I-2: POST /api/engagements/<slug>/answer  (clarification reply)
        # Pass I-2: POST /api/engagements/<slug>/promote (manual override)
        # Pass I-3: POST /api/engagements/<slug>/approve (kick off conductor)
        # Pass I-3: POST /api/engagements/<slug>/reject  (cancel + reason)
        m = re.match(
            r"^/api/engagements/([a-z0-9-]+)/(answer|promote|approve|reject)$",
            path,
        )
        if m is not None:
            self._handle_engagement_action(m.group(1), m.group(2))
            return

        # Pass L: POST /api/releases — promote a commit to a channel.
        if path == "/api/releases":
            self._handle_release_create()
            return

        # Pass L: POST /api/releases/<release_id>/archive
        m = re.match(
            r"^/api/releases/([0-9a-fA-F-]{36})/archive$", path
        )
        if m is not None:
            self._handle_release_archive(m.group(1))
            return

        self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    # ---- handlers ------------------------------------------------------

    def _handle_snapshot(self) -> None:
        t0 = time.monotonic()
        try:
            snap, from_cache = PROVIDER.get()
        except (psycopg.OperationalError, psycopg.InterfaceError) as e:
            log.error("snapshot endpoint: db unavailable: %s", e)
            self._send_json(
                HTTPStatus.SERVICE_UNAVAILABLE,
                {"error": "db_unavailable", "detail": str(e)},
            )
            return
        except psycopg.Error as e:
            log.error("snapshot endpoint: query error: %s", e)
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"error": "query_failed", "detail": str(e)},
            )
            return

        dur_ms = (time.monotonic() - t0) * 1000.0
        log.info(
            "GET /pg-snapshot.json %s in %.1fms",
            "(cached)" if from_cache else "(fresh)", dur_ms,
        )
        # snap may contain datetime values that already went through _iso
        # in build_snapshot; default=str catches stragglers defensively.
        body = json.dumps(snap, default=str).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _handle_engagements_list(self) -> None:
        """GET /api/engagements -> return the engagements array from a
        fresh snapshot. Same shape as snapshot.engagements so the frontend
        can splice the result straight into state.lastSnapshot.engagements.
        """
        engagements = list_engagements_from_snapshot()
        self._send_json(HTTPStatus.OK, {"engagements": engagements})

    def _handle_engagements_create(self) -> None:
        """POST /api/engagements -> create a new engagement.

        Body: {"title": "...", "requirements_md": "...", "client": "..."}
        Errors as documented on create_engagement().
        """
        length = int(self.headers.get("Content-Length") or "0")
        if length <= 0:
            self._send_json(HTTPStatus.BAD_REQUEST,
                            {"error": "empty_body"})
            return
        # Cap body at 1 MiB. Requirements briefs are markdown; anything
        # larger is almost certainly a mistake or an attempted abuse.
        if length > 1_048_576:
            self._send_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                            {"error": "body_too_large",
                             "detail": "max 1 MiB"})
            return

        try:
            raw = self.rfile.read(length)
        except (OSError, ConnectionResetError) as e:
            self._send_json(HTTPStatus.BAD_REQUEST,
                            {"error": "read_failed", "detail": str(e)})
            return

        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            self._send_json(HTTPStatus.BAD_REQUEST,
                            {"error": "invalid_json", "detail": str(e)})
            return
        if not isinstance(payload, dict):
            self._send_json(HTTPStatus.BAD_REQUEST,
                            {"error": "invalid_json",
                             "detail": "body must be a JSON object"})
            return

        status, body = create_engagement(payload)
        log.info("POST /api/engagements -> %d (slug=%s)",
                 status, body.get("slug"))
        self._send_json(status, body)

    def _handle_engagement_detail(self, slug: str) -> None:
        """GET /api/engagements/<slug> -> full detail + messages."""
        status, body = fetch_engagement_detail(slug)
        log.info("GET /api/engagements/%s -> %d", slug, status)
        self._send_json(status, body)

    def _handle_engagement_action(self, slug: str, action: str) -> None:
        """Shared POST handler for /<slug>/answer and /<slug>/promote.

        Reads, size-caps, and JSON-parses the body, then dispatches to
        post_answer / post_promote.
        """
        length = int(self.headers.get("Content-Length") or "0")
        if length <= 0:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "empty_body"})
            return
        if length > 1_048_576:
            self._send_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                            {"error": "body_too_large",
                             "detail": "max 1 MiB"})
            return
        try:
            raw = self.rfile.read(length)
        except (OSError, ConnectionResetError) as e:
            self._send_json(HTTPStatus.BAD_REQUEST,
                            {"error": "read_failed", "detail": str(e)})
            return
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            self._send_json(HTTPStatus.BAD_REQUEST,
                            {"error": "invalid_json", "detail": str(e)})
            return
        if not isinstance(payload, dict):
            self._send_json(HTTPStatus.BAD_REQUEST,
                            {"error": "invalid_json",
                             "detail": "body must be a JSON object"})
            return
        if action == "answer":
            status, body = post_answer(slug, payload)
        elif action == "promote":
            status, body = post_promote(slug, payload)
        elif action == "approve":
            status, body = post_approve(slug, payload)
        elif action == "reject":
            status, body = post_reject(slug, payload)
        else:
            status, body = 404, {"error": "not_found"}
        log.info("POST /api/engagements/%s/%s -> %d", slug, action, status)
        self._send_json(status, body)

    def _handle_release_create(self) -> None:
        """POST /api/releases — promote a commit to a channel."""
        length = int(self.headers.get("Content-Length") or "0")
        if length <= 0:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "empty_body"})
            return
        if length > 1_048_576:
            self._send_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                            {"error": "body_too_large",
                             "detail": "max 1 MiB"})
            return
        try:
            raw = self.rfile.read(length)
        except (OSError, ConnectionResetError) as e:
            self._send_json(HTTPStatus.BAD_REQUEST,
                            {"error": "read_failed", "detail": str(e)})
            return
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            self._send_json(HTTPStatus.BAD_REQUEST,
                            {"error": "invalid_json", "detail": str(e)})
            return
        if not isinstance(payload, dict):
            self._send_json(HTTPStatus.BAD_REQUEST,
                            {"error": "invalid_json",
                             "detail": "body must be a JSON object"})
            return
        status, body = create_release(payload)
        log.info("POST /api/releases -> %d (channel=%s sha=%s)",
                 status,
                 (payload.get("channel") or "")[:16],
                 (payload.get("commit_sha") or "")[:12])
        self._send_json(status, body)

    def _handle_release_archive(self, release_id: str) -> None:
        """POST /api/releases/<release_id>/archive — soft-delete a release."""
        status, body = archive_release(release_id)
        log.info("POST /api/releases/%s/archive -> %d", release_id[:8], status)
        self._send_json(status, body)

    def _handle_health(self) -> None:
        age = PROVIDER.cached_age_s()
        payload = {
            "ok": True,
            "db_connected": PROVIDER.db_connected(),
            "cached_age_s": None if age == float("inf") else round(age, 3),
        }
        self._send_json(HTTPStatus.OK, payload)


# ---------------------------------------------------------------------------
# Server lifecycle
# ---------------------------------------------------------------------------

def _install_signal_handlers(server: ThreadingHTTPServer) -> None:
    def _shutdown(signum, _frame):
        log.info("received signal %s, shutting down", signum)
        # shutdown() must run on a different thread than serve_forever().
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)


def main() -> int:
    log.info(
        "starting dashboard server on http://%s:%d/ (ttl=%.1fs)",
        HOST, PORT, TTL_S,
    )
    if not INDEX_FILE.is_file():
        log.warning("index.html not found at %s — / will 404", INDEX_FILE)

    server = ThreadingHTTPServer((HOST, PORT), Handler)
    _install_signal_handlers(server)
    log.info("ready — open http://%s:%d/", HOST, PORT)

    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        log.info("closing connection and exiting")
        PROVIDER.close()
        try:
            server.server_close()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
