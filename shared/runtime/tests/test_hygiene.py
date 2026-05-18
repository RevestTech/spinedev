"""Unit tests for shared.runtime.hygiene (workspace hygiene per #34)."""
from __future__ import annotations

import asyncio
import os
import tempfile
import time
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from shared.runtime import hygiene
from shared.runtime.hygiene import (HygieneSweep, Workspace, _validate_run_id,
                                    project_is_clean, workspace)


class _IsolatedHomeMixin:
    """Each test class points SPINE_HOME at a fresh tempdir."""

    def setUp(self) -> None:  # type: ignore[override]
        self._tmp = tempfile.TemporaryDirectory()
        self._prev_home = os.environ.get("SPINE_HOME")
        os.environ["SPINE_HOME"] = self._tmp.name

    def tearDown(self) -> None:  # type: ignore[override]
        if self._prev_home is None:
            os.environ.pop("SPINE_HOME", None)
        else:
            os.environ["SPINE_HOME"] = self._prev_home
        self._tmp.cleanup()


class RunIdValidationTests(unittest.TestCase):
    def test_valid_ids(self) -> None:
        for v in ("abc", "run_1", "RUN-42", "a" * 64):
            self.assertEqual(_validate_run_id(v), v)

    def test_invalid_ids(self) -> None:
        for v in ("", "../etc", "a/b", "x" * 65, "no spaces", "a!b"):
            with self.assertRaises(ValueError, msg=f"should reject {v!r}"):
                _validate_run_id(v)


class WorkspaceLifecycleTests(_IsolatedHomeMixin, unittest.TestCase):
    def test_write_creates_file_under_workspace(self) -> None:
        ws = Workspace("run-1")
        p = ws.write("plan.md", "hello")
        self.assertTrue(p.exists())
        self.assertEqual(p.read_text(), "hello")
        # ``_safe_join`` resolves symlinks (Path.resolve()) so on macOS
        # ``p`` will be under ``/private/var/...`` while ``ws.root`` may
        # still be ``/var/...``. Compare resolved forms.
        self.assertTrue(
            str(p).startswith(str(ws.root.resolve())),
            f"{p} not under {ws.root.resolve()}",
        )

    def test_write_bytes(self) -> None:
        ws = Workspace("run-2")
        ws.write("data.bin", b"\x00\x01\x02")
        self.assertEqual((ws.root / "data.bin").read_bytes(), b"\x00\x01\x02")

    def test_write_nested_path_ok(self) -> None:
        ws = Workspace("run-3")
        ws.write("nested/dir/note.txt", "x")
        self.assertTrue((ws.root / "nested" / "dir" / "note.txt").exists())

    def test_write_rejects_escaping_relpath(self) -> None:
        ws = Workspace("run-4")
        with self.assertRaises(ValueError):
            ws.write("../outside.txt", "x")
        with self.assertRaises(ValueError):
            ws.write("/abs.txt", "x")

    def test_promote_moves_to_target(self) -> None:
        ws = Workspace("run-5")
        ws.write("artifact.md", "FINAL")
        target = Path(self._tmp.name) / "out" / "artifact.md"
        ws.promote("artifact.md", target)
        self.assertTrue(target.exists())
        self.assertEqual(target.read_text(), "FINAL")
        self.assertFalse((ws.root / "artifact.md").exists())

    def test_close_archives_and_deletes_live_tree(self) -> None:
        ws = Workspace("run-6")
        ws.write("scratch.txt", "tmp")
        live_root = ws.root
        ws.close(archive=True)
        self.assertFalse(live_root.exists(), "live tree must be deleted")
        # An archive (either .tar.zst or .tar.gz) should exist.
        archive_root = Path(self._tmp.name) / "archive"
        archives = list(archive_root.rglob("run-6.*"))
        self.assertTrue(archives, f"no archive found under {archive_root}")
        self.assertTrue(
            any(str(a).endswith((".tar.zst", ".tar.gz")) for a in archives),
            f"unexpected archive ext: {archives}",
        )

    def test_close_without_archive_skips_tar(self) -> None:
        ws = Workspace("run-7")
        ws.write("scratch.txt", "tmp")
        ws.close(archive=False)
        archive_root = Path(self._tmp.name) / "archive"
        self.assertFalse(any(archive_root.rglob("run-7.*")))

    def test_close_is_idempotent(self) -> None:
        ws = Workspace("run-8")
        ws.close()
        ws.close()  # no error


class AsyncWorkspaceTests(_IsolatedHomeMixin, unittest.TestCase):
    def test_context_manager_archives_on_normal_exit(self) -> None:
        async def go() -> None:
            async with workspace("run-cm-1") as ws:
                ws.write("a.txt", "x")
                self.assertTrue(ws.root.exists())
            # Live tree gone after exit.
            self.assertFalse(ws.root.exists())

        asyncio.run(go())

    def test_context_manager_archives_on_exception(self) -> None:
        async def go() -> None:
            with self.assertRaises(RuntimeError):
                async with workspace("run-cm-2") as ws:
                    ws.write("a.txt", "x")
                    raise RuntimeError("boom")
            # Even on exception, the cleanup ran.
            self.assertFalse(Path(self._tmp.name, "work", "run-cm-2").exists())

        asyncio.run(go())


class HygieneSweepTests(_IsolatedHomeMixin, unittest.TestCase):
    def test_sweep_stale_workspaces_dry_run_does_not_delete(self) -> None:
        ws_root = Path(self._tmp.name) / "work"
        old = ws_root / "old-run"
        old.mkdir(parents=True)
        (old / ".created").write_text("x")
        # Backdate mtime by 48 hours.
        past = time.time() - 48 * 3600
        os.utime(old, (past, past))

        cleaned = HygieneSweep.sweep(dry_run=True)
        self.assertIn(old, cleaned)
        self.assertTrue(old.exists(), "dry_run must not delete")

        cleaned2 = HygieneSweep.sweep(dry_run=False)
        self.assertIn(old, cleaned2)
        self.assertFalse(old.exists(), "live sweep must delete")

    def test_sweep_skips_fresh_workspaces(self) -> None:
        ws_root = Path(self._tmp.name) / "work"
        fresh = ws_root / "fresh"
        fresh.mkdir(parents=True)
        cleaned = HygieneSweep.sweep(dry_run=False)
        self.assertNotIn(fresh, cleaned)
        self.assertTrue(fresh.exists())

    def test_sweep_archive_past_retention(self) -> None:
        arc = Path(self._tmp.name) / "archive" / "2024-01-01"
        arc.mkdir(parents=True)
        past = time.time() - 60 * 24 * 3600
        os.utime(arc, (past, past))
        cleaned = HygieneSweep.sweep(dry_run=False)
        self.assertIn(arc, cleaned)
        self.assertFalse(arc.exists())

    def test_sweep_pycache_when_not_gitignored(self) -> None:
        tmp = Path(self._tmp.name) / "code"
        tmp.mkdir()
        pyc = tmp / "pkg" / "__pycache__"
        pyc.mkdir(parents=True)
        (pyc / "x.pyc").write_text("x")
        cleaned = HygieneSweep.sweep(dry_run=False, scan_pycache_under=tmp)
        self.assertIn(pyc, cleaned)

    def test_sweep_skips_pycache_when_gitignored(self) -> None:
        tmp = Path(self._tmp.name) / "code2"
        tmp.mkdir()
        (tmp / ".gitignore").write_text("__pycache__/\n")
        pyc = tmp / "pkg" / "__pycache__"
        pyc.mkdir(parents=True)
        (pyc / "x.pyc").write_text("x")
        cleaned = HygieneSweep.sweep(dry_run=False, scan_pycache_under=tmp)
        self.assertNotIn(pyc, cleaned)
        self.assertTrue(pyc.exists())


class ProjectIsCleanTests(_IsolatedHomeMixin, unittest.TestCase):
    def test_clean_project_returns_true(self) -> None:
        ok, reasons = project_is_clean("proj1")
        self.assertTrue(ok)
        self.assertEqual(reasons, [])

    def test_dirty_project_returns_false_with_reason(self) -> None:
        ws_root = Path(self._tmp.name) / "work"
        live = ws_root / "proj1-runX"
        live.mkdir(parents=True)
        ok, reasons = project_is_clean("proj1")
        self.assertFalse(ok)
        self.assertTrue(any("proj1-runX" in r for r in reasons))

    def test_invalid_project_id_refuses_to_certify(self) -> None:
        ok, reasons = project_is_clean("../etc")
        self.assertFalse(ok)
        self.assertTrue(any("invalid project_id" in r for r in reasons))


class CLITests(_IsolatedHomeMixin, unittest.TestCase):
    def test_cli_no_args_returns_usage_exit(self) -> None:
        self.assertEqual(hygiene._cli([]), 64)

    def test_cli_sweep_dry_run(self) -> None:
        # Should complete without raising.
        self.assertEqual(hygiene._cli(["sweep", "--dry-run"]), 0)

    def test_cli_check_clean(self) -> None:
        self.assertEqual(hygiene._cli(["check", "p1"]), 0)

    def test_cli_check_dirty(self) -> None:
        live = Path(self._tmp.name) / "work" / "p1-r"
        live.mkdir(parents=True)
        self.assertEqual(hygiene._cli(["check", "p1"]), 1)

    def test_cli_unknown_command(self) -> None:
        self.assertEqual(hygiene._cli(["frobnicate"]), 64)


if __name__ == "__main__":
    unittest.main()
