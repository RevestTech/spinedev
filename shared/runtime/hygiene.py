"""shared.runtime.hygiene — workspace hygiene as architectural concern (#34).

Per V3 design decision #34 (``docs/V3_DESIGN_DECISIONS.md``):

    Spine must own workspace hygiene as a first-class architectural
    concern, not a manual cleanup chore. Every agent / subagent
    invocation gets ``.spine/work/<run_id>/``. Final artifacts are
    explicitly **promoted** before close. The workspace is **archived**
    on completion and **deleted from the live tree**. A periodic
    **sweep** command cleans orphans, stale archives, and ``__pycache__``
    that isn't gitignored. The **Conductor role refuses to mark a
    project done** while uncleaned workspace state exists.

Public API
==========

::

    class Workspace:
        def __init__(self, run_id: str, *, retention_days: int = 30): ...
        def write(self, relpath: str, content: bytes | str) -> Path: ...
        def promote(self, relpath: str, target: Path) -> None: ...
        def close(self, *, archive: bool = True) -> None: ...

    @asynccontextmanager
    async def workspace(run_id: str) -> AsyncIterator[Workspace]: ...

    class HygieneSweep:
        @staticmethod
        def sweep(*, dry_run: bool = False) -> list[Path]: ...

    def project_is_clean(project_id: str) -> tuple[bool, list[str]]: ...

CLI
===

::

    python3 -m shared.runtime.hygiene sweep            # apply
    python3 -m shared.runtime.hygiene sweep --dry-run  # report-only
    python3 -m shared.runtime.hygiene check <project>  # gate query

Design notes
============

  * **Run-id safety.** ``run_id`` is constrained to ``[A-Za-z0-9_-]{1,64}``
    so paths can never escape the workspace root. Validated at every
    entry point.
  * **Archive format.** ``tar.zst`` when zstandard is importable; falls
    back to ``tar.gz`` (stdlib) when not. The reader code in
    ``recovery/`` understands both; tests pin the fallback path so we
    don't take a hard zstandard dep here.
  * **No DB I/O.** All hygiene operations are filesystem-local; the
    Conductor gate queries this module by directory inspection, not by
    issuing SQL. Federation visibility comes later via an audit-event
    emission (Wave 1+).
  * **Best-effort archival.** If archive creation fails, the workspace
    is preserved on disk + the error logged — never silently deleted.
"""
from __future__ import annotations

import contextlib
import logging
import os
import re
import shutil
import sys
import tarfile
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import AsyncIterator, Iterable

_log = logging.getLogger("spine.runtime.hygiene")


# ──────────────────────────────────────────────────────────────────────
# Constants + helpers
# ──────────────────────────────────────────────────────────────────────


#: Validates a single ``run_id`` path component. Restricting to
#: ``[A-Za-z0-9_-]`` avoids any need to escape FS-special characters.
_RUN_ID_PATTERN = re.compile(r"\A[A-Za-z0-9_-]{1,64}\Z")


def _spine_home() -> Path:
    """Resolve the ``.spine`` root.

    Same convention as ``shared.notify.notifier``: prefer ``SPINE_HOME``,
    fall back to ``~/.spine``. (``SPINE_HOME`` is a non-secret config
    pointer, not a credential — vault-only rule per V3 #9 does not
    apply.)
    """
    return Path(os.environ.get("SPINE_HOME", str(Path.home() / ".spine")))


def _work_root() -> Path:
    """Live workspace root: ``<SPINE_HOME>/work``."""
    return _spine_home() / "work"


def _archive_root() -> Path:
    """Archived workspace root: ``<SPINE_HOME>/archive``."""
    return _spine_home() / "archive"


def _validate_run_id(run_id: str) -> str:
    if not _RUN_ID_PATTERN.match(run_id or ""):
        raise ValueError(
            f"invalid run_id {run_id!r}; must match [A-Za-z0-9_-]{{1,64}}"
        )
    return run_id


def _safe_join(root: Path, relpath: str) -> Path:
    """Resolve ``relpath`` under ``root`` and assert containment.

    Prevents ``../`` escapes from agent-controlled paths.
    """
    if not relpath or relpath.startswith(("/", "\\")) or ".." in Path(relpath).parts:
        raise ValueError(f"unsafe relpath: {relpath!r}")
    out = (root / relpath).resolve()
    root_resolved = root.resolve()
    if not str(out).startswith(str(root_resolved) + os.sep) and out != root_resolved:
        raise ValueError(f"relpath escapes workspace root: {relpath!r}")
    return out


# ──────────────────────────────────────────────────────────────────────
# Workspace
# ──────────────────────────────────────────────────────────────────────


@dataclass
class _PromotionRecord:
    """One ``promote(src, target)`` call, recorded for audit + sweep
    truth-tracking. Keeps the workspace honest: anything not promoted
    will be archived + deleted on ``close``."""
    rel_src: str
    target: Path
    promoted_at: float


class Workspace:
    """Per-agent-run scratch directory under ``.spine/work/<run_id>/``.

    Lifecycle:
        1. ``Workspace(run_id)`` creates the directory (idempotent).
        2. ``write(rel, content)`` drops intermediate files. Nested
           directories are auto-created under the workspace root.
        3. ``promote(rel, target)`` moves a final artifact out of the
           workspace and into the canonical location (copies if target
           is on a different filesystem; falls back to copy + remove).
        4. ``close(archive=True)`` archives the workspace tarball to
           ``.spine/archive/<YYYY-MM-DD>/<run_id>.tar.(zst|gz)`` and
           deletes the live tree. ``close(archive=False)`` skips archival
           (used for explicit discard).
    """

    def __init__(self, run_id: str, *, retention_days: int = 30) -> None:
        self.run_id = _validate_run_id(run_id)
        self.retention_days = int(retention_days)
        self.root: Path = _work_root() / self.run_id
        self.root.mkdir(parents=True, exist_ok=True)
        self._promotions: list[_PromotionRecord] = []
        self._closed = False
        # Touchstone file so the sweep can tell live workspaces apart
        # from leftover empty dirs.
        (self.root / ".created").write_text(
            datetime.now(timezone.utc).isoformat() + "\n",
            encoding="utf-8",
        )

    # ── Writes / promotions ──────────────────────────────────────────

    def write(self, relpath: str, content: bytes | str) -> Path:
        """Drop ``content`` at ``<workspace>/<relpath>`` and return the
        full path. Creates parent directories as needed."""
        if self._closed:
            raise RuntimeError("workspace already closed")
        target = _safe_join(self.root, relpath)
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, str):
            target.write_text(content, encoding="utf-8")
        else:
            target.write_bytes(content)
        return target

    def promote(self, relpath: str, target: Path) -> None:
        """Move ``<workspace>/<relpath>`` -> ``target``.

        Final-artifact gate per #34: anything that should outlive the
        workspace MUST be promoted explicitly. Anything not promoted
        gets archived + deleted on ``close``.

        Args:
            relpath: path inside the workspace.
            target: destination (may be absolute; parent will be
                created if missing).
        """
        if self._closed:
            raise RuntimeError("workspace already closed")
        src = _safe_join(self.root, relpath)
        if not src.exists():
            raise FileNotFoundError(f"workspace file not found: {relpath!r}")
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.move(str(src), str(target))
        except OSError:
            # Cross-FS or permission issue → copy + remove.
            shutil.copy2(str(src), str(target))
            src.unlink(missing_ok=True)
        self._promotions.append(
            _PromotionRecord(
                rel_src=relpath, target=target, promoted_at=time.time(),
            ),
        )

    # ── Close / archive ──────────────────────────────────────────────

    def close(self, *, archive: bool = True) -> None:
        """Archive (optional) + delete the live workspace tree."""
        if self._closed:
            return
        self._closed = True
        if archive:
            try:
                self._archive()
            except Exception as exc:  # noqa: BLE001
                _log.error(
                    "hygiene: archive failed for %s — preserving live tree "
                    "(error: %s)", self.run_id, exc,
                )
                return
        shutil.rmtree(self.root, ignore_errors=True)

    def _archive(self) -> Path:
        """Write the workspace to ``.spine/archive/<date>/<run_id>.tar.<ext>``.

        Prefers ``.tar.zst`` when the ``zstandard`` package is importable
        (smaller archives, faster decompression). Falls back to
        ``.tar.gz`` so this module has no hard external dep.
        """
        archive_root = _archive_root() / datetime.now(timezone.utc).strftime("%Y-%m-%d")
        archive_root.mkdir(parents=True, exist_ok=True)
        zst_path = archive_root / f"{self.run_id}.tar.zst"
        gz_path = archive_root / f"{self.run_id}.tar.gz"
        # Try zstandard first.
        try:
            import zstandard  # noqa: PLC0415, F401
            return self._write_tar_zst(zst_path)
        except ImportError:
            return self._write_tar_gz(gz_path)

    def _write_tar_zst(self, path: Path) -> Path:
        import io  # noqa: PLC0415
        import zstandard  # noqa: PLC0415

        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tar:
            tar.add(str(self.root), arcname=self.run_id)
        cctx = zstandard.ZstdCompressor(level=10)
        path.write_bytes(cctx.compress(buf.getvalue()))
        return path

    def _write_tar_gz(self, path: Path) -> Path:
        with tarfile.open(str(path), "w:gz") as tar:
            tar.add(str(self.root), arcname=self.run_id)
        return path


@asynccontextmanager
async def workspace(run_id: str) -> AsyncIterator[Workspace]:
    """Async context manager around ``Workspace``.

    Idiomatic agent loop::

        async with workspace(run_id) as ws:
            ws.write("plan.md", "...")
            ws.promote("plan.md", Path("/repo/docs/plan.md"))
        # workspace archived + deleted here, even on exception
    """
    ws = Workspace(run_id)
    try:
        yield ws
    finally:
        with contextlib.suppress(Exception):
            ws.close(archive=True)


# ──────────────────────────────────────────────────────────────────────
# HygieneSweep
# ──────────────────────────────────────────────────────────────────────


class HygieneSweep:
    """Periodic cleanup. Configured per-bundle in production (per #34);
    defaults here are sensible for laptop / dev installs."""

    #: Default age past which an unfinished workspace is considered
    #: orphaned. 24h covers the longest reasonable agent run.
    DEFAULT_MAX_WORKSPACE_AGE = timedelta(hours=24)

    #: Default retention for archived workspaces.
    DEFAULT_ARCHIVE_RETENTION = timedelta(days=30)

    @staticmethod
    def sweep(
        *,
        dry_run: bool = False,
        max_workspace_age: timedelta | None = None,
        archive_retention: timedelta | None = None,
        scan_pycache_under: Path | None = None,
    ) -> list[Path]:
        """Run a full hygiene sweep. Returns the list of paths cleaned
        (or that would be cleaned, when ``dry_run=True``).

        Sweep targets (per #34):

          1. Stale workspaces under ``.spine/work/`` older than
             ``max_workspace_age``.
          2. Archive bundles under ``.spine/archive/<date>/`` older
             than ``archive_retention``.
          3. ``/tmp/spine-*`` orphan directories older than
             ``max_workspace_age``.
          4. ``__pycache__/`` directories under ``scan_pycache_under``
             that are not covered by a sibling / ancestor ``.gitignore``.

        Args:
            dry_run: when True, no filesystem changes; just report
                what would be cleaned.
            max_workspace_age: override the stale-workspace threshold.
            archive_retention: override archive retention.
            scan_pycache_under: when set, also sweep stray
                ``__pycache__`` dirs rooted here.
        """
        max_age = max_workspace_age or HygieneSweep.DEFAULT_MAX_WORKSPACE_AGE
        retention = archive_retention or HygieneSweep.DEFAULT_ARCHIVE_RETENTION
        cleaned: list[Path] = []

        cleaned.extend(HygieneSweep._sweep_stale_workspaces(max_age, dry_run))
        cleaned.extend(HygieneSweep._sweep_archive(retention, dry_run))
        cleaned.extend(HygieneSweep._sweep_tmp_orphans(max_age, dry_run))
        if scan_pycache_under is not None:
            cleaned.extend(
                HygieneSweep._sweep_pycache(scan_pycache_under, dry_run),
            )
        return cleaned

    # ── Per-target sweeps ────────────────────────────────────────────

    @staticmethod
    def _sweep_stale_workspaces(
        max_age: timedelta, dry_run: bool,
    ) -> list[Path]:
        root = _work_root()
        if not root.is_dir():
            return []
        cutoff = time.time() - max_age.total_seconds()
        out: list[Path] = []
        for child in root.iterdir():
            if not child.is_dir():
                continue
            try:
                age_ok = child.stat().st_mtime < cutoff
            except OSError:
                continue
            if not age_ok:
                continue
            out.append(child)
            if not dry_run:
                shutil.rmtree(child, ignore_errors=True)
        return out

    @staticmethod
    def _sweep_archive(retention: timedelta, dry_run: bool) -> list[Path]:
        root = _archive_root()
        if not root.is_dir():
            return []
        cutoff = time.time() - retention.total_seconds()
        out: list[Path] = []
        for date_dir in root.iterdir():
            if not date_dir.is_dir():
                continue
            try:
                age_ok = date_dir.stat().st_mtime < cutoff
            except OSError:
                continue
            if not age_ok:
                continue
            out.append(date_dir)
            if not dry_run:
                shutil.rmtree(date_dir, ignore_errors=True)
        return out

    @staticmethod
    def _sweep_tmp_orphans(
        max_age: timedelta, dry_run: bool,
    ) -> list[Path]:
        tmp = Path("/tmp")
        if not tmp.is_dir():
            return []
        cutoff = time.time() - max_age.total_seconds()
        out: list[Path] = []
        try:
            entries = list(tmp.iterdir())
        except OSError:
            return []
        for child in entries:
            if not child.name.startswith("spine-"):
                continue
            try:
                age_ok = child.stat().st_mtime < cutoff
            except OSError:
                continue
            if not age_ok:
                continue
            out.append(child)
            if dry_run:
                continue
            try:
                if child.is_dir():
                    shutil.rmtree(child, ignore_errors=True)
                else:
                    child.unlink(missing_ok=True)
            except OSError:
                pass
        return out

    @staticmethod
    def _sweep_pycache(root: Path, dry_run: bool) -> list[Path]:
        if not root.is_dir():
            return []
        out: list[Path] = []
        for pyc in root.rglob("__pycache__"):
            if not pyc.is_dir():
                continue
            if HygieneSweep._is_gitignored_pycache(pyc):
                continue
            out.append(pyc)
            if not dry_run:
                shutil.rmtree(pyc, ignore_errors=True)
        return out

    @staticmethod
    def _is_gitignored_pycache(pycache_dir: Path) -> bool:
        """True iff a ``.gitignore`` between ``pycache_dir`` and the
        filesystem root contains ``__pycache__/``.

        Best-effort: doesn't fully reimplement gitignore semantics, just
        looks for the canonical pattern. This is enough for the
        "is this pycache covered" check #34 calls out.
        """
        cur = pycache_dir.parent.resolve()
        # Walk upward looking for any .gitignore that mentions
        # __pycache__ (the common entry).
        while True:
            gi = cur / ".gitignore"
            if gi.is_file():
                try:
                    text = gi.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    text = ""
                for line in text.splitlines():
                    s = line.strip()
                    if s.startswith("#") or not s:
                        continue
                    if "__pycache__" in s:
                        return True
            if cur.parent == cur:
                return False
            cur = cur.parent


# ──────────────────────────────────────────────────────────────────────
# Conductor gate helper
# ──────────────────────────────────────────────────────────────────────


def project_is_clean(project_id: str) -> tuple[bool, list[str]]:
    """Return ``(is_clean, reasons)`` for the Conductor's release gate.

    Per #34, the Conductor refuses to mark a project done while
    uncleaned workspace state exists for it. We treat a workspace as
    "belonging to" a project when its ``run_id`` carries the project_id
    as a prefix in the form ``<project_id>-*`` OR ``<project_id>_*``
    (Spine's run-id convention). Callers may pre-tag run_ids however
    they like; we provide both separators because both appear in the
    wild.

    Returns:
        (True, []) when the project's workspace footprint is empty.
        (False, [reason, ...]) listing every uncleaned location.
    """
    if not project_id or not _RUN_ID_PATTERN.match(project_id):
        # Conservative — if we can't safely match a run_id prefix,
        # refuse to certify clean.
        return False, [f"invalid project_id {project_id!r}"]
    work_root = _work_root()
    reasons: list[str] = []
    if work_root.is_dir():
        for child in work_root.iterdir():
            if not child.is_dir():
                continue
            name = child.name
            if name.startswith(f"{project_id}-") or name.startswith(f"{project_id}_"):
                reasons.append(f"live workspace: {child}")
    return (not reasons), reasons


# ──────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────


def _cli(argv: list[str]) -> int:
    """``python3 -m shared.runtime.hygiene <cmd> [args]``."""
    if not argv:
        print(
            "usage: python3 -m shared.runtime.hygiene "
            "{sweep [--dry-run] | check <project_id>}",
            file=sys.stderr,
        )
        return 64

    cmd, *rest = argv
    if cmd == "sweep":
        dry = "--dry-run" in rest
        cleaned = HygieneSweep.sweep(
            dry_run=dry,
            scan_pycache_under=Path.cwd(),
        )
        prefix = "[dry-run] would clean" if dry else "cleaned"
        for path in cleaned:
            print(f"{prefix}: {path}")
        print(f"{prefix} {len(cleaned)} path(s)")
        return 0

    if cmd == "check" and rest:
        ok, reasons = project_is_clean(rest[0])
        if ok:
            print(f"project {rest[0]!r}: clean")
            return 0
        print(f"project {rest[0]!r}: NOT CLEAN")
        for r in reasons:
            print(f"  - {r}")
        return 1

    print(f"unknown command {cmd!r}", file=sys.stderr)
    return 64


if __name__ == "__main__":  # pragma: no cover — exercised via tests
    sys.exit(_cli(sys.argv[1:]))


__all__ = [
    "HygieneSweep",
    "Workspace",
    "project_is_clean",
    "workspace",
]
