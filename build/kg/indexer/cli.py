"""`kg-index` CLI — cold-start / incremental / status / reindex-file /
extractors. Wired by the post-commit hook in
`watcher_extension.render_post_commit_hook` and the watcher tick hook.
Exit codes: 0 success/no-op, 1 work done with errors, 2 fatal config
error (missing DATABASE_URL etc.)."""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

from .indexer import IndexResult, cold_start_index, incremental_index, reindex_file
from .parser_runtime import load_extractors

log = logging.getLogger("spine.kg.cli")


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return _dispatch(args)
    except RuntimeError as e:
        log.error("fatal: %s", e); return 2


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="kg-index", description="Spine Knowledge Graph indexer")
    p.add_argument("--database-url", default=None,
                   help="Postgres URL; defaults to $DATABASE_URL")
    sub = p.add_subparsers(dest="cmd", required=True)

    cs = sub.add_parser("cold-start", help="Index the whole repo")
    cs.add_argument("--repo", default=".", help="Repo root (default: cwd)")
    cs.add_argument("--languages", default=None,
                    help="Comma-separated language slugs to limit (default: all)")

    inc = sub.add_parser("incremental", help="Index files changed since last commit cursor")
    inc.add_argument("--repo", default=".")

    st = sub.add_parser("status", help="Show index freshness vs HEAD")
    st.add_argument("--repo", default=".")

    rf = sub.add_parser("reindex-file", help="Force re-parse one file")
    rf.add_argument("file_path")
    rf.add_argument("--repo", default=".")

    sub.add_parser("extractors", help="List available extractors")
    return p


def _dispatch(args: argparse.Namespace) -> int:
    if args.cmd == "cold-start":
        langs = [s.strip() for s in args.languages.split(",")] if args.languages else None
        return _emit(cold_start_index(Path(args.repo), langs, args.database_url))
    if args.cmd == "incremental":
        return _emit(incremental_index(Path(args.repo), database_url=args.database_url))
    if args.cmd == "reindex-file":
        return _emit(reindex_file(Path(args.repo), Path(args.file_path), args.database_url))
    if args.cmd == "status":
        return _status(Path(args.repo), args.database_url)
    if args.cmd == "extractors":
        return _list_extractors()
    return 2


def _emit(result: IndexResult) -> int:
    """JSON to stdout — machine-readable for hooks and dashboards."""
    print(json.dumps({
        "files_indexed": result.files_indexed,
        "node_count": result.node_count,
        "edge_count": result.edge_count,
        "duration_seconds": round(result.duration_seconds, 3),
        "errors": result.errors,
    }, indent=2))
    return 1 if result.errors else 0


def _status(repo_root: Path, database_url: str | None) -> int:
    """Compare `kg_index_state.last_indexed_commit_sha` to git HEAD; print
    `behind_by_commits` so dashboards/users can spot stale indexes."""
    db = database_url or os.environ.get("DATABASE_URL", "")
    if not db:
        log.error("DATABASE_URL not set"); return 2
    repo = repo_root.resolve().name
    head = _git_head(repo_root.resolve())
    last = _psql(db, f"SELECT last_indexed_commit_sha FROM spine_kg.kg_index_state "
                     f"WHERE repo = '{repo}';").strip()
    behind = _count_commits_between(repo_root, last, head) if last else None
    print(json.dumps({"repo": repo, "head": head, "last_indexed": last or None,
                      "behind_by_commits": behind, "up_to_date": last == head}, indent=2))
    return 0


def _list_extractors() -> int:
    extractors = load_extractors()
    print(json.dumps({k: {"include": v.include_globs, "exclude": v.exclude_globs,
                          "grammars": [g.get("package") for g in v.grammars]}
                      for k, v in extractors.items()}, indent=2))
    return 0


# ─── Helpers ────────────────────────────────────────────────────────


def _git_head(repo_root: Path) -> str:
    r = subprocess.run(["git", "-C", str(repo_root), "rev-parse", "HEAD"],
                       capture_output=True, text=True, check=True)
    return r.stdout.strip()


def _count_commits_between(repo_root: Path, base: str, head: str) -> int | None:
    if not base or base == head:
        return 0
    r = subprocess.run(["git", "-C", str(repo_root), "rev-list", "--count", f"{base}..{head}"],
                       capture_output=True, text=True)
    return int(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip().isdigit() else None


def _psql(db: str, sql: str) -> str:
    r = subprocess.run(["psql", db, "-At", "-v", "ON_ERROR_STOP=1", "-c", sql],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"psql failed: {r.stderr.strip()}")
    return r.stdout


if __name__ == "__main__":
    sys.exit(main())
