"""KG indexer trigger 3/3 — periodic sweep (Wave 1, V3 §1.2 SAFETY NET).

Per resolved decision 1.2:

> **periodic sweep is safety net.** Hourly default; surfaces stale KG
> via Hub UI dashboard.

Two responsibilities:

  1. Find files whose on-disk ``mtime`` is newer than the latest
     ``valid_to IS NULL`` ``spine_kg.kg_node`` row for that path —
     these are stale entries the commit hook missed.
  2. Re-index each stale file via the canonical ``reindex_file`` API.

The sweep is fully idempotent (re-running it within the cadence
produces zero work if everything is fresh). Designed to run from cron
or a Hub-side scheduler; CLI exposed for ops + manual runs.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from build.kg.indexer.indexer import IndexResult, reindex_file

logger = logging.getLogger("spine.kg.sweep")

TRIGGER_SOURCE = "sweep"
DEFAULT_DB_URL = "postgresql://spine:spine@localhost:33000/spine"
DEFAULT_CADENCE_SECONDS = 3600  # 1h per V3 §1.2 default


@dataclass
class SweepResult:
    """One sweep cycle outcome."""
    fired_trigger: str = TRIGGER_SOURCE
    files_scanned: int = 0
    files_stale: int = 0
    files_reindexed: int = 0
    nodes_added: int = 0
    edges_added: int = 0
    duration_seconds: float = 0.0
    stale_paths: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def run_sweep(
    repo_root: Path,
    *,
    database_url: Optional[str] = None,
    file_limit: Optional[int] = None,
) -> SweepResult:
    """Find KG-stale files and re-index them. Idempotent."""
    start = time.monotonic()
    result = SweepResult()
    root = repo_root.resolve()
    db = database_url or os.environ.get("SPINE_DB_URL") or os.environ.get(
        "DATABASE_URL"
    ) or DEFAULT_DB_URL
    repo = root.name
    try:
        anchors = _kg_path_anchors(db, repo)
    except Exception as exc:  # noqa: BLE001
        result.errors.append(f"kg_path_anchors: {exc}")
        result.duration_seconds = time.monotonic() - start
        return result

    for rel_path, kg_updated_at in anchors.items():
        result.files_scanned += 1
        fp = root / rel_path
        if not fp.exists():
            # Deletions are commit-hook territory; sweep doesn't close
            # nodes (avoids racing the commit hook).
            continue
        try:
            mtime = fp.stat().st_mtime
        except OSError as exc:
            result.errors.append(f"stat {rel_path}: {exc}")
            continue
        if mtime <= kg_updated_at:
            continue
        result.files_stale += 1
        result.stale_paths.append(rel_path)
        if file_limit is not None and result.files_reindexed >= file_limit:
            continue
        try:
            sub = reindex_file(root, fp, database_url=db)
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"reindex {rel_path}: {exc}")
            continue
        result.files_reindexed += 1
        result.nodes_added += sub.node_count
        result.edges_added += sub.edge_count

    result.duration_seconds = time.monotonic() - start
    return result


def run_forever(
    repo_root: Path,
    *,
    cadence_seconds: int = DEFAULT_CADENCE_SECONDS,
    database_url: Optional[str] = None,
    iterations: Optional[int] = None,
) -> None:
    """Run sweeps on a loop. ``iterations=None`` runs forever; tests pass an int."""
    n = 0
    while iterations is None or n < iterations:
        result = run_sweep(repo_root, database_url=database_url)
        logger.info(
            "sweep cycle: scanned=%d stale=%d reindexed=%d duration=%.2fs",
            result.files_scanned, result.files_stale, result.files_reindexed,
            result.duration_seconds,
        )
        n += 1
        if iterations is not None and n >= iterations:
            break
        time.sleep(max(1, cadence_seconds))


# ─── Postgres I/O ───────────────────────────────────────────────────


def _q(v: object) -> str:
    return "NULL" if v is None else "'" + str(v).replace("'", "''") + "'"


def _psql(sql: str, db_url: str) -> str:
    r = subprocess.run(
        ["psql", db_url, "-At", "-F", "\x1f",
         "-v", "ON_ERROR_STOP=1", "-c", sql],
        capture_output=True, text=True, timeout=30,
    )
    if r.returncode != 0:
        raise RuntimeError(f"psql failed: {r.stderr.strip()}")
    return r.stdout


def _kg_path_anchors(db: str, repo: str) -> dict[str, float]:
    """Return {rel_path: kg_updated_epoch_seconds} for repo's live nodes.

    Uses the most-recent ``valid_from`` per path (proxy for "when KG
    last reflected this file") since ``kg_node`` has no separate
    ``updated_at`` column.
    """
    out = _psql(
        "SELECT path, EXTRACT(EPOCH FROM MAX(valid_from)) "
        "FROM spine_kg.kg_node "
        f"WHERE repo = {_q(repo)} AND valid_to IS NULL AND path IS NOT NULL "
        "GROUP BY path;",
        db,
    )
    anchors: dict[str, float] = {}
    for line in out.splitlines():
        if not line:
            continue
        parts = line.split("\x1f")
        if len(parts) != 2:
            continue
        path = parts[0]
        try:
            ts = float(parts[1])
        except ValueError:
            continue
        anchors[path] = ts
    return anchors


# ─── CLI ────────────────────────────────────────────────────────────


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="build.kg.indexer_sweep",
        description="KG indexer trigger — periodic sweep (V3 §1.2 SAFETY NET)",
    )
    parser.add_argument("--repo", default=".", help="Repo root (default: cwd)")
    parser.add_argument(
        "--database-url", default=None,
        help="Postgres URL; defaults to $DATABASE_URL",
    )
    parser.add_argument(
        "--cadence-seconds", type=int, default=DEFAULT_CADENCE_SECONDS,
        help="Sleep between sweeps when --forever. Default 3600 (1h).",
    )
    parser.add_argument(
        "--file-limit", type=int, default=None,
        help="Cap files reindexed per sweep (None=unlimited).",
    )
    parser.add_argument(
        "--forever", action="store_true",
        help="Run sweeps on a loop (cron alternative).",
    )
    parser.add_argument(
        "--iterations", type=int, default=None,
        help="Stop after N sweeps (with --forever). Default: never.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stderr,
    )

    root = Path(args.repo).resolve()
    if args.forever:
        run_forever(
            root, cadence_seconds=args.cadence_seconds,
            database_url=args.database_url, iterations=args.iterations,
        )
        return 0

    result = run_sweep(
        root, database_url=args.database_url, file_limit=args.file_limit,
    )
    print(json.dumps({
        "trigger": result.fired_trigger,
        "files_scanned": result.files_scanned,
        "files_stale": result.files_stale,
        "files_reindexed": result.files_reindexed,
        "nodes_added": result.nodes_added,
        "edges_added": result.edges_added,
        "duration_seconds": round(result.duration_seconds, 3),
        "stale_paths": result.stale_paths[:50],  # cap output
        "errors": result.errors,
    }, indent=2))
    return 1 if result.errors else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
