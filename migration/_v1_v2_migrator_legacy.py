#!/usr/bin/env python3
# Historical v1 -> v2 migrator preserved per #33 as canonical example.
# Imports may break (this file refers to legacy .planning/orchestration/schema/v2.sql
# and lib/team-agent-daemon.sh paths that no longer exist in the v3 layout).
# Kept verbatim under migration/ as documentation of the original migrator
# shape that motivated the four-concern migration design (Wave 5 Squad F).
# Do NOT call this file from new code; use migration.export / migration.import_
# / migration.spine_version / migration.onboarding instead.
"""
spine-migrate.py — v1 → v2 migration for Spine

Reads the live v1 disk layout under .planning/orchestration/agent-handoff/teams/
and seeds a v2 SQLite database (see .planning/orchestration/schema/v2.sql) with
Team / Worker / Assignment / Directive / CostRow / RollbackEntry rows that
correspond to what's on disk today.

The script is **idempotent**: re-running merges new rows and updates existing
ones (rather than inserting duplicates). It uses stable IDs derived from
filesystem paths + content hashes so re-runs are safe.

Usage (from repo root after `install.sh`, which copies this file to `scripts/`):

    # Default paths
    python3 scripts/spine-migrate.py

    # Package maintainers may run from the bundled copy:
    #   python3 lib/spine-migrate.py

    # Custom paths / fresh DB
    python3 scripts/spine-migrate.py \\
        --teams-dir .planning/orchestration/agent-handoff/teams \\
        --schema    .planning/orchestration/schema/v2.sql \\
        --db        .planning/orchestration/state/spine.db \\
        --reset

Flags:
    --reset             Drop the DB file before applying schema (destructive)
    --team NAME         Migrate into Team with this name (default: 'default')
    --dry-run           Read & report; don't write to the DB

The script never modifies the v1 disk layout. The v1 paths remain readable
(and the dashboard keeps reading them) until you explicitly retire them with
the F1 backlog item.

Mapping notes (v1 → v2):
    teams/<role>/                                → Worker handle '<role>-alpha'
                                                   under Team --team (default).
    teams/<role>/directive.md                    → Assignment(active) + Directive
    teams/<role>/state/costs.csv                 → CostRow rows
    teams/<role>/state/rollback-stack.csv        → RollbackEntry rows
    teams/<role>/workers/<NN>-directive.md       → child Worker
                                                   '<role>-<phonetic(NN)>' with
                                                   parent_worker_id = root.
    Special-case role IDs:
        engineering-backend  → role_id 'engineer-backend'  (v2 disciplined)
        engineering-frontend → role_id 'engineer-frontend' (v2 disciplined)
        all others           → role_id matches the v1 directory name (the
                               generic 'engineer' role row is seeded in v2.sql
                               for the v1 engineer mapping to satisfy the
                               foreign key).
"""

from __future__ import annotations

import argparse
import csv
import datetime as _dt
import hashlib
import json
import re
import sqlite3
import subprocess
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

# Phonetic alphabet — used for worker handle suffixes.
PHONETIC = [
    "alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf",
    "hotel", "india", "juliet", "kilo", "lima", "mike", "november",
    "oscar", "papa", "quebec", "romeo", "sierra", "tango", "uniform",
    "victor", "whiskey", "xray", "yankee", "zulu",
]

# v1 role-folder name → v2 role_id mapping (most are identity).
V1_TO_V2_ROLE = {
    "engineering-backend":  "engineer-backend",
    "engineering-frontend": "engineer-frontend",
}


def slot_to_phonetic(slot: str) -> str:
    """Map slot strings ('01'..'10') to phonetic letters; falls back to slot itself."""
    try:
        i = int(slot)
        if 1 <= i <= len(PHONETIC):
            return PHONETIC[i - 1]
    except ValueError:
        pass
    return slot


def stable_uuid(*parts: str) -> str:
    """Deterministic UUID from concatenated string parts. Lets re-runs be idempotent."""
    h = hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()
    return str(uuid.UUID(h[:32]))


def first_line(text: str) -> str:
    for line in text.splitlines():
        s = line.strip()
        if s:
            return s
    return ""


def classify_directive_status(header: str) -> str:
    """Map directive header to Assignment.status for v2."""
    h = header.lower()
    if h.startswith("# report") or h.startswith("# worker report") or h.startswith("# status"):
        return "done"
    if h.startswith("# (idle"):
        return "abandoned"
    return "active"


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class Stats:
    teams: int = 0
    workers: int = 0
    assignments_active: int = 0
    assignments_closed: int = 0
    directives: int = 0
    reports: int = 0
    cost_rows: int = 0
    rollback_rows: int = 0
    skipped_role_dirs: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def report(self) -> str:
        lines = [
            f"Teams seeded:         {self.teams}",
            f"Workers seeded:       {self.workers}",
            f"Assignments (active): {self.assignments_active}",
            f"Assignments (closed): {self.assignments_closed}",
            f"Directives:           {self.directives}",
            f"Reports:              {self.reports}",
            f"Cost rows:            {self.cost_rows}",
            f"Rollback rows:        {self.rollback_rows}",
        ]
        if self.skipped_role_dirs:
            lines.append("Skipped (no directive.md): " + ", ".join(self.skipped_role_dirs))
        if self.warnings:
            lines.append("Warnings:")
            for w in self.warnings:
                lines.append(f"  - {w}")
        return "\n".join(lines)


def open_db(db_path: Path, schema_path: Path, reset: bool) -> sqlite3.Connection:
    if reset and db_path.exists():
        db_path.unlink()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON;")
    schema_sql = schema_path.read_text(encoding="utf-8")
    conn.executescript(schema_sql)
    conn.commit()
    return conn


def upsert_team(conn: sqlite3.Connection, name: str) -> str:
    row = conn.execute("SELECT team_id FROM team WHERE name = ?", (name,)).fetchone()
    if row:
        return row[0]
    team_id = stable_uuid("team", name)
    conn.execute(
        "INSERT INTO team (team_id, name) VALUES (?, ?)",
        (team_id, name),
    )
    return team_id


def upsert_worker(
    conn: sqlite3.Connection,
    team_id: str,
    role_id: str,
    handle: str,
    parent_worker_id: Optional[str],
    status: str = "idle",
) -> tuple[str, bool]:
    """Return (worker_id, created) — `created=True` only on first insert."""
    row = conn.execute(
        "SELECT worker_id FROM worker WHERE team_id = ? AND handle = ?",
        (team_id, handle),
    ).fetchone()
    if row:
        return row[0], False
    worker_id = stable_uuid("worker", team_id, handle)
    conn.execute(
        """INSERT INTO worker
              (worker_id, team_id, role_id, parent_worker_id, handle, status)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (worker_id, team_id, role_id, parent_worker_id, handle, status),
    )
    return worker_id, True


def role_exists(conn: sqlite3.Connection, role_id: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM role WHERE role_id = ?", (role_id,)
    ).fetchone() is not None


def map_role_id(conn: sqlite3.Connection, v1_dirname: str, stats: Stats) -> Optional[str]:
    candidate = V1_TO_V2_ROLE.get(v1_dirname, v1_dirname)
    if role_exists(conn, candidate):
        return candidate
    stats.warnings.append(
        f"v1 role directory '{v1_dirname}' has no v2 role row "
        f"(tried role_id='{candidate}'); skipping."
    )
    return None


def upsert_assignment_with_directive(
    conn: sqlite3.Connection,
    worker_id: str,
    directive_path: Path,
    directive_text: str,
    orch_root: Path,
    stats: Stats,
) -> Optional[str]:
    if not directive_text.strip():
        return None
    header = first_line(directive_text)
    status = classify_directive_status(header)
    try:
        rel_uri = str(directive_path.resolve().relative_to(orch_root.resolve()))
    except ValueError:
        rel_uri = str(directive_path.resolve())
    body_hash = sha256(directive_text)

    # One assignment per (worker, directive content). Re-runs with same content
    # are no-ops; new content makes a new Assignment.
    assignment_id = stable_uuid("assignment", worker_id, body_hash)

    existing = conn.execute(
        "SELECT assignment_id, status FROM assignment WHERE assignment_id = ?",
        (assignment_id,),
    ).fetchone()
    if not existing:
        # Any prior "active" assignment for this worker is now stale (the
        # disk content has changed). Mark it abandoned so the snapshot
        # exporter doesn't keep showing the previous task's header.
        conn.execute(
            """UPDATE assignment
                  SET status = 'abandoned',
                      ended_at = COALESCE(ended_at, CURRENT_TIMESTAMP)
                WHERE worker_id = ? AND status = 'active' AND assignment_id != ?""",
            (worker_id, assignment_id),
        )
        conn.execute(
            """INSERT INTO assignment
                  (assignment_id, worker_id, status, idempotency_key)
               VALUES (?, ?, ?, ?)""",
            (assignment_id, worker_id, status, body_hash[:32]),
        )
        if status == "active":
            stats.assignments_active += 1
        else:
            stats.assignments_closed += 1
    else:
        if existing[1] != status:
            conn.execute(
                "UPDATE assignment SET status = ? WHERE assignment_id = ?",
                (status, assignment_id),
            )

    # Directive (when active) or Report (when closed).
    if status == "active":
        conn.execute(
            """INSERT INTO directive (assignment_id, header, body_md_uri, body_md_hash)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(assignment_id) DO UPDATE SET
                   header       = excluded.header,
                   body_md_uri  = excluded.body_md_uri,
                   body_md_hash = excluded.body_md_hash""",
            (assignment_id, header[:512], rel_uri, body_hash),
        )
        stats.directives += 1
    else:
        # Treat closed Assignments' directive.md as the Report body.
        conn.execute(
            """INSERT INTO report (assignment_id, header, body_md_uri, body_md_hash)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(assignment_id) DO UPDATE SET
                   header       = excluded.header,
                   body_md_uri  = excluded.body_md_uri,
                   body_md_hash = excluded.body_md_hash""",
            (assignment_id, header[:512], rel_uri, body_hash),
        )
        stats.reports += 1

    return assignment_id


_COST_HEADERS = {"timestamp", "ts", "role", "mode", "slot", "phase",
                 "tier", "wall_s", "rc"}


def import_costs_csv(
    conn: sqlite3.Connection,
    csv_path: Path,
    fallback_assignment_id: Optional[str],
    stats: Stats,
) -> None:
    if not csv_path.exists() or fallback_assignment_id is None:
        return

    # Discover the worker that owns the current (latest) assignment so we can
    # consolidate cost rows that may have been attributed to prior, now-
    # abandoned assignments from earlier directive→report cycles.
    worker_row = conn.execute(
        "SELECT worker_id FROM assignment WHERE assignment_id = ?",
        (fallback_assignment_id,),
    ).fetchone()
    worker_id = worker_row[0] if worker_row else None

    with csv_path.open(newline="", encoding="utf-8") as fh:
        sniff = fh.read(2048)
        fh.seek(0)
        if not sniff.strip():
            return
        reader = csv.DictReader(fh)
        if not reader.fieldnames:
            return

        for row in reader:
            ts = (row.get("timestamp") or row.get("ts") or "").strip()
            if not ts:
                continue
            tier = (row.get("tier") or "").strip().lower() or None
            # Accept "medium" (current daemon output) AND legacy "med"/"mid" as
            # aliases — older CSVs may contain either. Normalize to "medium".
            if tier in {"med", "mid"}:
                tier = "medium"
            tier_id = tier if tier in {"low", "medium", "high"} else None
            try:
                wall_s = float(row.get("wall_s") or 0)
            except ValueError:
                wall_s = 0.0
            try:
                rc = int(row.get("rc")) if row.get("rc") not in (None, "") else None
            except ValueError:
                rc = None

            # Drop any duplicates of this (worker, ts) cost row that ended up
            # on superseded assignments. Each CSV row should map to exactly
            # one cost_row in the DB, attached to the worker's current asg.
            if worker_id is not None:
                conn.execute(
                    """DELETE FROM cost_row
                        WHERE ts = ?
                          AND assignment_id IN (
                              SELECT a.assignment_id FROM assignment a
                               WHERE a.worker_id = ?
                                 AND a.assignment_id != ?
                          )""",
                    (ts, worker_id, fallback_assignment_id),
                )

            try:
                cur = conn.execute(
                    """INSERT OR IGNORE INTO cost_row
                          (assignment_id, ts, tier_id, mode, phase, wall_s, rc)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        fallback_assignment_id,
                        ts,
                        tier_id,
                        (row.get("mode") or "").strip() or None,
                        (row.get("phase") or "").strip() or None,
                        wall_s,
                        rc,
                    ),
                )
                if cur.rowcount > 0:
                    stats.cost_rows += 1
            except sqlite3.IntegrityError as e:
                stats.warnings.append(f"cost_row insert skipped ({csv_path}): {e}")


def import_rollback_csv(
    conn: sqlite3.Connection,
    csv_path: Path,
    worker_id: str,
    stats: Stats,
) -> None:
    if not csv_path.exists():
        return
    with csv_path.open(newline="", encoding="utf-8") as fh:
        sniff = fh.read(2048)
        fh.seek(0)
        if not sniff.strip():
            return
        reader = csv.reader(fh)
        # Header detection: skip first row if it looks like a header.
        rows = list(reader)
        if not rows:
            return
        header = rows[0]
        data = rows[1:] if any(h.lower() in {"timestamp", "ts"} for h in header) else rows

        for r in data:
            if not r or not r[0].strip():
                continue
            ts = r[0].strip()
            action = (r[1] if len(r) > 1 else "") or "unknown"
            target = (r[2] if len(r) > 2 else "") or ""
            sha = (r[3] if len(r) > 3 else "") or None
            try:
                cur = conn.execute(
                    """INSERT OR IGNORE INTO rollback_entry
                          (worker_id, ts, action, target, sha)
                       VALUES (?, ?, ?, ?, ?)""",
                    (worker_id, ts, action, target, sha),
                )
                if cur.rowcount > 0:
                    stats.rollback_rows += 1
            except sqlite3.IntegrityError as e:
                stats.warnings.append(f"rollback_entry insert skipped ({csv_path}): {e}")


_SLOT_FILE_RE = re.compile(r"^(\d{2})-directive\.md$")


def migrate_role_dir(
    conn: sqlite3.Connection,
    role_dir: Path,
    team_id: str,
    orch_root: Path,
    stats: Stats,
) -> None:
    v1_role = role_dir.name
    role_id = map_role_id(conn, v1_role, stats)
    if role_id is None:
        return

    # Root worker for this role: handle = '<v1-name>-alpha' (use v1 name to keep
    # the handle stable across re-runs; v2 disciplined names like
    # 'engineer-backend' would cause the handle to change if we ever map
    # differently, breaking idempotency).
    root_handle = f"{v1_role}-{PHONETIC[0]}"
    directive_md = role_dir / "directive.md"
    if not directive_md.exists():
        stats.skipped_role_dirs.append(v1_role)
        return

    root_worker_id, created = upsert_worker(
        conn, team_id, role_id, root_handle, parent_worker_id=None,
        status="active",
    )
    if created:
        stats.workers += 1

    # Root assignment + directive/report
    text = directive_md.read_text(encoding="utf-8", errors="replace")
    root_assignment_id = upsert_assignment_with_directive(
        conn, root_worker_id, directive_md, text, orch_root, stats,
    )

    # Per-role costs / rollback
    import_costs_csv(conn, role_dir / "state" / "costs.csv",
                     root_assignment_id, stats)
    import_rollback_csv(conn, role_dir / "state" / "rollback-stack.csv",
                        root_worker_id, stats)

    # Child workers from worker slots
    workers_dir = role_dir / "workers"
    if workers_dir.is_dir():
        for child_md in sorted(workers_dir.iterdir()):
            m = _SLOT_FILE_RE.match(child_md.name)
            if not m:
                continue
            slot = m.group(1)
            phon = slot_to_phonetic(slot)
            child_handle = f"{v1_role}-{phon}"
            child_worker_id, child_created = upsert_worker(
                conn, team_id, role_id, child_handle,
                parent_worker_id=root_worker_id,
                status="active",
            )
            if child_created:
                stats.workers += 1
            child_text = child_md.read_text(encoding="utf-8", errors="replace")
            upsert_assignment_with_directive(
                conn, child_worker_id, child_md, child_text, orch_root, stats,
            )


def iter_role_dirs(teams_dir: Path) -> Iterable[Path]:
    if not teams_dir.is_dir():
        return []
    return [p for p in sorted(teams_dir.iterdir())
            if p.is_dir() and not p.name.startswith(("_archived", "."))]


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    default_teams = repo_root / ".planning/orchestration/agent-handoff/teams"
    default_schema = repo_root / ".planning/orchestration/schema/v2.sql"
    default_db = repo_root / ".planning/orchestration/state/spine.db"

    p = argparse.ArgumentParser(description="Migrate v1 Spine state into a v2 SQLite DB")
    p.add_argument("--teams-dir", default=str(default_teams), type=Path)
    p.add_argument("--schema",    default=str(default_schema), type=Path)
    p.add_argument("--db",        default=str(default_db),    type=Path)
    p.add_argument("--team",      default="default",
                   help="Team name to migrate v1 roles under (default: 'default')")
    p.add_argument("--reset",     action="store_true",
                   help="Drop the DB before applying schema (destructive)")
    p.add_argument("--dry-run",   action="store_true",
                   help="Read & report; do not write to the DB")
    p.add_argument("--snapshot",
                   nargs="?",
                   const=str(repo_root / ".planning/orchestration/dashboard/snapshot.json"),
                   default=None,
                   help="Also export a JSON snapshot the dashboard can fetch "
                        "(default: dashboard/snapshot.json). Pass --snapshot=<path> "
                        "to override.")
    p.add_argument("--watch", type=int, metavar="SECONDS", default=0,
                   help="After the first run, re-migrate every N seconds (Ctrl-C to stop). "
                        "Implies --snapshot.")
    args = p.parse_args()
    if args.watch and not args.snapshot:
        args.snapshot = str(repo_root / ".planning/orchestration/dashboard/snapshot.json")

    teams_dir: Path = args.teams_dir
    schema:   Path  = args.schema
    db_path:  Path  = args.db

    if not teams_dir.is_dir():
        print(f"ERROR: teams dir not found: {teams_dir}", file=sys.stderr)
        return 2
    if not schema.is_file():
        print(f"ERROR: schema not found: {schema}", file=sys.stderr)
        return 2

    stats = Stats()
    role_dirs = list(iter_role_dirs(teams_dir))

    if args.dry_run:
        print(f"DRY RUN — would migrate {len(role_dirs)} role dir(s) into "
              f"team '{args.team}' at db={db_path}")
        for r in role_dirs:
            print(f"  • {r.name}")
        return 0

    conn = open_db(db_path, schema, args.reset)
    try:
        team_id = upsert_team(conn, args.team)
        stats.teams = 1

        # teams_dir = .planning/orchestration/agent-handoff/teams
        # orch_root = .planning/orchestration (so URIs are 'agent-handoff/teams/<role>/directive.md',
        #                                     which resolves to '../<uri>' from /dashboard/)
        orch_root = teams_dir.parent.parent
        for role_dir in role_dirs:
            migrate_role_dir(conn, role_dir, team_id, orch_root, stats)

        conn.commit()
    finally:
        conn.close()

    print(f"Migrated → {db_path}")
    print(stats.report())

    if args.snapshot:
        snap_path = Path(args.snapshot)
        export_snapshot(db_path, snap_path)
        print(f"Snapshot → {snap_path}")

    if args.watch and args.watch > 0:
        import time as _time
        print(f"Watching: re-migrating every {args.watch}s (Ctrl-C to stop)…")
        try:
            while True:
                _time.sleep(args.watch)
                conn = open_db(db_path, schema, reset=False)
                try:
                    team_id = upsert_team(conn, args.team)
                    orch_root_w = teams_dir.parent.parent
                    refresh_stats = Stats()
                    for role_dir in iter_role_dirs(teams_dir):
                        migrate_role_dir(conn, role_dir, team_id, orch_root_w, refresh_stats)
                    conn.commit()
                finally:
                    conn.close()
                if args.snapshot:
                    export_snapshot(db_path, Path(args.snapshot))
                ts = _dt.datetime.now().strftime("%H:%M:%S")
                print(f"[{ts}] refreshed (workers+{refresh_stats.workers} "
                      f"assignments+{refresh_stats.assignments_active + refresh_stats.assignments_closed} "
                      f"costs+{refresh_stats.cost_rows})")
        except KeyboardInterrupt:
            print("\nWatch stopped.")
            return 0

    return 0


# ──────────────────────────────────────────────────────────────────────
# Snapshot exporter (used by the dashboard)
# ──────────────────────────────────────────────────────────────────────

def export_snapshot(db_path: Path, out_path: Path) -> None:
    """Read the v2 DB and write a JSON snapshot the dashboard can fetch.

    Schema is intentionally flat / human-readable. The dashboard treats this
    as the source of truth when present and falls back to v1 file walking
    when absent.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Capture which Spine daemons are currently alive. The daemon command line
    # is: `bash scripts/team-agent-daemon.sh <role> manager` or
    #     `bash scripts/team-agent-daemon.sh <role> worker <NN>`.
    daemon_index = _scan_daemons()

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        teams = [dict(r) for r in conn.execute(
            "SELECT team_id, name, created_at FROM team WHERE archived_at IS NULL"
        )]
        roles = [dict(r) for r in conn.execute("""
            SELECT r.role_id, r.name, r.family_id, r.level_id, r.discipline_id,
                   r.default_tier_id
            FROM role r
        """)]

        # Workers + their currently-active or most-recent assignment summary.
        worker_rows = list(conn.execute("""
            SELECT
                w.worker_id, w.team_id, w.role_id, w.parent_worker_id,
                w.handle, w.display_name, w.status, w.created_at
            FROM worker w
            WHERE w.archived_at IS NULL
            ORDER BY w.handle
        """))

        # Reverse mapping for v2 role_id → v1 directory name (for detail drawer
        # fallback fetches into the live v1 disk layout).
        v2_to_v1 = {v: k for k, v in V1_TO_V2_ROLE.items()}

        workers = []
        for w in worker_rows:
            wid = w["worker_id"]
            # latest assignment by start time. The migration creates a new
            # assignment row whenever the directive.md content (and therefore
            # the body_hash that derives assignment_id) changes — so the
            # newest one reflects current disk state, regardless of its
            # status. (Older "active" rows may exist from prior content.)
            asg = conn.execute("""
                SELECT a.assignment_id, a.task_id, a.parent_assignment_id,
                       a.task_ref, a.started_at, a.ended_at, a.status,
                       COALESCE(d.header, r.header) AS directive_header,
                       d.body_md_uri               AS directive_uri,
                       r.body_md_uri               AS report_uri
                FROM assignment a
                LEFT JOIN directive d ON d.assignment_id = a.assignment_id
                LEFT JOIN report    r ON r.assignment_id = a.assignment_id
                WHERE a.worker_id = ?
                ORDER BY a.started_at DESC, a.assignment_id DESC
                LIMIT 1
            """, (wid,)).fetchone()

            cost_summary = conn.execute("""
                SELECT COUNT(*) AS n,
                       COALESCE(SUM(c.wall_s), 0)   AS wall_s,
                       COALESCE(SUM(c.cost_usd), 0) AS cost_usd,
                       COALESCE(SUM(c.tokens_in), 0)  AS tokens_in,
                       COALESCE(SUM(c.tokens_out), 0) AS tokens_out
                FROM cost_row c
                JOIN assignment a ON a.assignment_id = c.assignment_id
                WHERE a.worker_id = ?
            """, (wid,)).fetchone()

            v1_dirname = v2_to_v1.get(w["role_id"], v2_to_v1.get(w["role_id"].split("-")[0] if "-" in w["role_id"] else w["role_id"], w["role_id"]))
            role_info = daemon_index.get(v1_dirname, {})
            slot_states = role_info.get("workers", [False] * 10)
            workers.append({
                **dict(w),
                "v1_dirname": v1_dirname,
                "daemon_manager_alive": bool(role_info.get("manager")),
                "daemon_worker_alive":  list(slot_states),
                "assignment": dict(asg) if asg else None,
                "cost":      dict(cost_summary) if cost_summary else None,
            })

        cost_rows = [dict(r) for r in conn.execute("""
            SELECT c.assignment_id, c.ts, c.tier_id, c.model_id, c.mode, c.phase,
                   c.tokens_in, c.tokens_out, c.wall_s, c.cost_usd, c.rc,
                   a.worker_id, w.handle AS worker_handle
            FROM cost_row c
            JOIN assignment a ON a.assignment_id = c.assignment_id
            JOIN worker w     ON w.worker_id     = a.worker_id
            ORDER BY c.ts DESC
            LIMIT 200
        """)]

        snapshot = {
            "version": 2,
            "generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
            "db_path": str(db_path),
            "teams": teams,
            "roles": roles,
            "workers": workers,
            "cost_rows_recent": cost_rows,
            "daemons": daemon_index,
        }
    finally:
        conn.close()

    out_path.write_text(json.dumps(snapshot, indent=2, default=str), encoding="utf-8")


# ── daemon scanner ──────────────────────────────────────────────────

_DAEMON_RE = re.compile(
    r"team-agent-daemon\.sh\s+(\S+)\s+(manager|worker)(?:\s+(\d{1,2}))?"
)


def _scan_daemons() -> dict:
    """Return {role: {manager: bool, workers: [bool*10], pids: [...]}} for
    every Spine daemon currently in the process table.

    Uses `ps -eo pid,args` so we don't need the `psutil` third-party package.
    """
    out: dict[str, dict] = {}
    try:
        res = subprocess.run(
            ["ps", "-eo", "pid=,args="],
            capture_output=True, text=True, check=False, timeout=5,
        )
        if res.returncode != 0:
            return out
        for line in res.stdout.splitlines():
            line = line.strip()
            if not line or "team-agent-daemon.sh" not in line:
                continue
            parts = line.split(None, 1)
            if len(parts) != 2:
                continue
            try:
                pid = int(parts[0])
            except ValueError:
                continue
            m = _DAEMON_RE.search(parts[1])
            if not m:
                continue
            role, kind, slot_s = m.group(1), m.group(2), m.group(3)
            row = out.setdefault(role, {"manager": False, "workers": [False] * 10, "pids": []})
            row["pids"].append(pid)
            if kind == "manager":
                row["manager"] = True
            elif kind == "worker" and slot_s:
                try:
                    s = int(slot_s) - 1
                    if 0 <= s < 10:
                        row["workers"][s] = True
                except ValueError:
                    pass
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return out
    return out


if __name__ == "__main__":
    raise SystemExit(main())
