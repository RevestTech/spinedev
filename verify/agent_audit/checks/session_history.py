"""L02 session_history — stale directive workspace + hygiene check.

Spine runs each role dispatch under
``.spine/work/<project_uuid>/directives/<directive_id>/`` (see
``shared/runtime/role_runtime.py``). The failure mode this layer guards
against is *context bleed*: an old directive's ``report.md`` lingering in
the workspace and leaking into a new directive in the same run.

The check is deliberately on-disk only; no runtime signals required.
"""
from __future__ import annotations

import time
from pathlib import Path

from verify.agent_audit.twelve_layer import LayerFinding

LAYER_ID = "L02_session_history"

# 30 days in seconds — anything older than this without an archive trace
# counts as potential stale-context bleed.
_STALE_AGE_SECONDS = 30 * 24 * 60 * 60

# Cap on workspace tree depth before we flag it as hygiene drift.
_MAX_TREE_DEPTH = 100

# Forbidden scratch / backup patterns per #34 workspace hygiene.
_FORBIDDEN_GLOBS = ("*.bak", "*.swp", "scratch.*")

# Very old pycache age threshold (same window as stale directives).
_OLD_PYCACHE_AGE_SECONDS = _STALE_AGE_SECONDS


def _archive_trace_exists(repo_root: Path, directive_dir: Path) -> bool:
    """Best-effort: an archive trace = a tarball/dir named after the
    directive_id under ``.spine/archive/``. Absence of the archive
    directory itself means no traces exist."""
    archive_root = repo_root / ".spine" / "archive"
    if not archive_root.is_dir():
        return False
    needle = directive_dir.name
    for entry in archive_root.iterdir():
        if needle in entry.name:
            return True
    return False


def _is_stale(status_path: Path, now: float) -> bool:
    try:
        mtime = status_path.stat().st_mtime
    except OSError:
        return False
    return (now - mtime) > _STALE_AGE_SECONDS


def _tree_depth(root: Path) -> int:
    """Maximum directory depth under ``root`` (root itself = 0)."""
    max_depth = 0
    root_parts = len(root.parts)
    for path in root.rglob("*"):
        if not path.is_dir():
            continue
        depth = len(path.parts) - root_parts
        if depth > max_depth:
            max_depth = depth
        # Short-circuit: once we exceed the cap, no need to keep walking.
        if max_depth > _MAX_TREE_DEPTH:
            return max_depth
    return max_depth


def check_session_history_layer(
    repo_root: Path,
    signals: dict,
) -> LayerFinding:
    """L02 — directive workspace freshness + hygiene.

    Statuses:
      * ``instrumentation_pending`` — no ``.spine/work/`` yet (no runs).
      * ``warning`` (medium) — stale directives without archive trace,
        excessive depth, old ``__pycache__``, or forbidden patterns.
      * ``clean`` — workspace tidy.
    """
    work_root = repo_root / ".spine" / "work"
    if not work_root.is_dir():
        return LayerFinding(
            layer=LAYER_ID,
            status="instrumentation_pending",
            summary=(
                ".spine/work/ not present — no directive runs to audit "
                "(directory appears after first orchestrator dispatch)"
            ),
            severity="low",
        )

    now = time.time()
    stale_evidence: list[str] = []
    hygiene_evidence: list[str] = []

    # Walk one level deep: .spine/work/<project_uuid>/directives/<directive_id>/.
    for project_dir in sorted(work_root.iterdir()):
        if not project_dir.is_dir():
            continue
        directives_root = project_dir / "directives"
        if not directives_root.is_dir():
            continue
        for directive_dir in sorted(directives_root.iterdir()):
            if not directive_dir.is_dir():
                continue
            status_path = directive_dir / "status.json"
            if not status_path.exists():
                continue
            if not _is_stale(status_path, now):
                continue
            if _archive_trace_exists(repo_root, directive_dir):
                continue
            rel = directive_dir.relative_to(repo_root)
            stale_evidence.append(str(rel))

    # Depth check across the whole work tree.
    depth = _tree_depth(work_root)
    if depth > _MAX_TREE_DEPTH:
        hygiene_evidence.append(f"workspace depth {depth} > {_MAX_TREE_DEPTH}")

    # Forbidden patterns.
    for pattern in _FORBIDDEN_GLOBS:
        hits = sorted(work_root.rglob(pattern))
        if hits:
            sample = ", ".join(str(p.relative_to(repo_root)) for p in hits[:3])
            hygiene_evidence.append(
                f"forbidden pattern {pattern!r}: {len(hits)} hit(s) ({sample})"
            )

    # Very old __pycache__ dirs.
    for pyc_dir in work_root.rglob("__pycache__"):
        if not pyc_dir.is_dir():
            continue
        try:
            mtime = pyc_dir.stat().st_mtime
        except OSError:
            continue
        if (now - mtime) > _OLD_PYCACHE_AGE_SECONDS:
            hygiene_evidence.append(
                f"old __pycache__: {pyc_dir.relative_to(repo_root)}"
            )

    if stale_evidence or hygiene_evidence:
        next_actions: list[str] = []
        if stale_evidence:
            next_actions.append(
                "archive stale directives via `make hygiene` (per #34) "
                "to prevent context bleed into new runs"
            )
        if hygiene_evidence:
            next_actions.append(
                "sweep workspace cruft (forbidden patterns / old pycache "
                "/ depth) with `make hygiene`"
            )
        evidence = tuple(stale_evidence + hygiene_evidence)
        stale_n = len(stale_evidence)
        hygiene_n = len(hygiene_evidence)
        return LayerFinding(
            layer=LAYER_ID,
            status="warning",
            summary=(
                f"{stale_n} stale directive(s) + {hygiene_n} hygiene "
                "issue(s) under .spine/work/"
            ),
            severity="medium",
            evidence=evidence,
            next_actions=tuple(next_actions),
        )

    return LayerFinding(
        layer=LAYER_ID,
        status="clean",
        summary=".spine/work/ directives fresh; no hygiene drift detected",
        severity="low",
    )


__all__ = ["check_session_history_layer"]
