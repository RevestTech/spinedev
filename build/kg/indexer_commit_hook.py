"""KG indexer trigger 1/3 — per-commit hook (Wave 1, V3 §1.2 PRIMARY).

Per resolved decision 1.2 in ``docs/V3_BUILD_SEQUENCE.md``:

> **per-commit hook is primary; audit-event-driven is secondary; periodic
> sweep is safety net.**

This module is invocable two ways:

* As a Git ``post-commit`` hook: install via ``install_post_commit_hook``
  (writes ``.git/hooks/post-commit``). The hook runs in the background so
  it cannot block ``git commit``.
* Directly as a CLI:
  ``python3 -m build.kg.indexer_commit_hook <commit_sha>``

It always defers to the canonical incremental indexer in
``build/kg/indexer/indexer.py`` for the actual KG writes, then records
the trigger source in ``spine_kg.kg_index_state`` metadata (best-effort).

Failure mode (per spec): indexer crash → next sweep catches it. We
deliberately ``exit 0`` even on indexer failure so a misbehaving indexer
cannot block commits.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from build.kg.indexer.indexer import IndexResult, incremental_index

logger = logging.getLogger("spine.kg.commit_hook")

TRIGGER_SOURCE = "commit_hook"
POST_COMMIT_HOOK_BODY = """#!/bin/sh
# Spine KG indexer — installed by build/kg/indexer_commit_hook.py
# Per V3_BUILD_SEQUENCE §1.2: must NEVER block the commit.
# Background dispatch; output to .git/hooks/.spine-kg.log so debugging
# is possible without polluting the terminal.
{python} -m build.kg.indexer_commit_hook --quiet "$(git rev-parse HEAD)" \
    >> "$(git rev-parse --git-dir)/hooks/.spine-kg.log" 2>&1 &
exit 0
"""


@dataclass
class CommitHookResult:
    """One commit-hook invocation outcome."""
    commit_sha: str
    repo_root: str
    result: IndexResult
    fired_trigger: str = TRIGGER_SOURCE


def run_commit_hook(
    commit_sha: str,
    repo_root: Optional[Path] = None,
    database_url: Optional[str] = None,
) -> CommitHookResult:
    """Fire the incremental indexer for ``commit_sha``.

    Returns a result with the IndexResult attached; never raises so a
    git hook caller can ``exit 0`` unconditionally.
    """
    root = (repo_root or Path.cwd()).resolve()
    if not commit_sha or not _looks_like_sha(commit_sha):
        return CommitHookResult(
            commit_sha=commit_sha, repo_root=str(root),
            result=IndexResult(errors=[f"invalid commit_sha: {commit_sha!r}"]),
        )
    try:
        result = incremental_index(
            root, commit_sha=commit_sha, database_url=database_url,
        )
    except Exception as exc:  # noqa: BLE001 — defensive
        logger.exception("commit_hook: incremental_index raised")
        result = IndexResult(errors=[f"incremental_index raised: {exc}"])
    return CommitHookResult(
        commit_sha=commit_sha, repo_root=str(root), result=result,
    )


def install_post_commit_hook(
    repo_root: Path, python: str = sys.executable,
) -> Path:
    """Write ``.git/hooks/post-commit`` that backgrounds this module.

    Idempotent; overwrites any prior post-commit hook (caller's
    responsibility to back up).
    """
    git_dir = Path(
        subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "--git-dir"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    )
    if not git_dir.is_absolute():
        git_dir = (repo_root / git_dir).resolve()
    hooks_dir = git_dir / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    hook_path = hooks_dir / "post-commit"
    hook_path.write_text(
        POST_COMMIT_HOOK_BODY.format(python=python), encoding="utf-8",
    )
    hook_path.chmod(0o755)
    return hook_path


# ─── Helpers ────────────────────────────────────────────────────────


def _looks_like_sha(s: str) -> bool:
    return 4 <= len(s) <= 64 and all(c in "0123456789abcdefABCDEF" for c in s)


# ─── CLI ────────────────────────────────────────────────────────────


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="build.kg.indexer_commit_hook",
        description="KG incremental indexer trigger — per-commit hook (V3 §1.2)",
    )
    parser.add_argument("commit_sha", help="SHA of the commit just made")
    parser.add_argument("--repo", default=".", help="Repo root (default: cwd)")
    parser.add_argument(
        "--database-url", default=None, help="Postgres URL; defaults to $DATABASE_URL",
    )
    parser.add_argument(
        "--install-hook", action="store_true",
        help="Install .git/hooks/post-commit (then exit).",
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="Suppress JSON output; only log to stderr (hook-friendly).",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stderr,
    )

    if args.install_hook:
        path = install_post_commit_hook(Path(args.repo).resolve())
        print(json.dumps({"installed": str(path)}))
        return 0

    out = run_commit_hook(
        args.commit_sha, repo_root=Path(args.repo).resolve(),
        database_url=args.database_url,
    )
    if not args.quiet:
        print(json.dumps({
            "trigger": out.fired_trigger,
            "commit_sha": out.commit_sha,
            "files_indexed": out.result.files_indexed,
            "node_count": out.result.node_count,
            "edge_count": out.result.edge_count,
            "duration_seconds": round(out.result.duration_seconds, 3),
            "errors": out.result.errors,
        }, indent=2))
    # Per spec: never block commits — exit 0 even on indexer error.
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
