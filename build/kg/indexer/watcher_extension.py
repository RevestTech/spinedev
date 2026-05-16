"""Hook the KG indexer into the existing `db/watcher/` daemon
(STORY-6.4.1). Does NOT modify `spine_watcher.py`; the watcher imports
`kg_tick` from here and calls it once per tick. Two wire-in shapes:
(a) watcher-tick callback (polling fallback), (b) git post-commit hook
(fastest path — see `indexer_README.md` §wiring + §git-hooks). Per-repo
last-seen-commit is cached at `~/.spine/kg/<repo>.cursor` so a watcher
restart doesn't re-fire work another invocation already covered."""

from __future__ import annotations

import json
import logging
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .indexer import IndexResult, incremental_index

log = logging.getLogger("spine.kg.watcher_extension")

DEFAULT_CURSOR_DIR = Path(os.environ.get("SPINE_KG_CURSOR_DIR",
                                          str(Path.home() / ".spine" / "kg")))


@dataclass
class KGTickState:
    """Per-repo memoization. The DB is the source of truth (kg_index_state);
    this local file is a fast-path cache so the tick callback can short-
    circuit without a `psql` round-trip when nothing has moved."""
    repo_root: Path
    last_seen_commit: str | None = None
    cursor_path: Path | None = None


# ─── Public hook ─────────────────────────────────────────────────────


def kg_tick(repo_root: Path, database_url: str | None = None,
            state: KGTickState | None = None) -> IndexResult | None:
    """Called once per watcher tick. Returns an `IndexResult` when work
    was done; `None` when HEAD hasn't moved (cheap fast-path). The
    watcher logs the result via its existing logger."""
    repo_root = repo_root.resolve()
    state = state or _load_state(repo_root)
    try:
        head = _git_head(repo_root)
    except subprocess.CalledProcessError as e:
        log.warning("kg_tick: cannot read HEAD in %s: %s", repo_root, e)
        return None
    if state.last_seen_commit == head:
        return None
    log.info("kg_tick: HEAD moved %s → %s; running incremental index",
             state.last_seen_commit or "(none)", head[:8])
    try:
        result = incremental_index(repo_root, commit_sha=head, database_url=database_url)
    except Exception as e:  # noqa: BLE001
        log.exception("kg_tick: incremental_index failed: %s", e)
        return None
    state.last_seen_commit = head
    _save_state(state)
    _emit_structured_log(repo_root, head, result)
    return result


# ─── State persistence ──────────────────────────────────────────────


def _load_state(repo_root: Path) -> KGTickState:
    DEFAULT_CURSOR_DIR.mkdir(parents=True, exist_ok=True)
    cursor = DEFAULT_CURSOR_DIR / f"{repo_root.name}.cursor"
    last = None
    if cursor.exists():
        try:
            last = json.loads(cursor.read_text()).get("last_seen_commit")
        except (ValueError, OSError) as e:
            log.warning("kg_tick: cursor %s unreadable: %s", cursor, e)
    return KGTickState(repo_root=repo_root, last_seen_commit=last, cursor_path=cursor)


def _save_state(state: KGTickState) -> None:
    if state.cursor_path is None:
        return
    try:
        state.cursor_path.write_text(json.dumps({
            "repo_root": str(state.repo_root),
            "last_seen_commit": state.last_seen_commit,
        }))
    except OSError as e:
        log.warning("kg_tick: cannot persist cursor %s: %s", state.cursor_path, e)


# ─── Helpers ────────────────────────────────────────────────────────


def _git_head(repo_root: Path) -> str:
    r = subprocess.run(["git", "-C", str(repo_root), "rev-parse", "HEAD"],
                       capture_output=True, text=True, check=True)
    return r.stdout.strip()


def _emit_structured_log(repo_root: Path, commit_sha: str, result: IndexResult) -> None:
    """Structured one-line JSON log so the watcher / dashboard can grep
    KG indexer activity out of the same log stream as the outbox drain."""
    log.info("kg_index_event %s", json.dumps({
        "event": "incremental_index_done",
        "repo": repo_root.name,
        "commit_sha": commit_sha,
        "files_indexed": result.files_indexed,
        "node_count": result.node_count,
        "edge_count": result.edge_count,
        "duration_s": round(result.duration_seconds, 3),
        "errors": len(result.errors),
    }))


# ─── Post-commit hook one-liner generator ───────────────────────────


def render_post_commit_hook(python_bin: str = "python3") -> str:
    """Returns the shell script body for `.git/hooks/post-commit`. The
    installer (or a human) writes this to the hook path and `chmod +x`s
    it. Kept here so the wiring contract lives next to the consumer."""
    return (
        "#!/bin/sh\n"
        "# Spine KG indexer — auto-installed by build/kg/indexer.\n"
        "# Runs incremental graph update after every commit. Failures are\n"
        "# logged but do NOT block the commit (post-commit is informational).\n"
        f'exec {python_bin} -m build.kg.indexer.cli incremental '
        '--repo "$(git rev-parse --show-toplevel)" >>/tmp/spine-kg-index.log 2>&1 &\n'
    )
