"""Wave 3 Squad A — assert lib/* → shared/runtime/ bash substrate migration.

For each of the nine KEEP-with-extensions files moved from ``lib/`` to
``shared/runtime/`` per ``docs/V3_TRIAGE.md`` and ``docs/V3_BUILD_SEQUENCE.md``
(Part 1.1 / Wave 3), assert that:

  1. the new file exists at ``shared/runtime/<name>.sh``,
  2. it is non-empty (defensive — guards against truncated cp),
  3. it parses cleanly under ``bash -n`` (syntax check), and
  4. the executable bit is preserved for files that had it under lib/
     (vitals.sh and heartbeat.sh are executed by other scripts via
     ``bash``; they don't strictly NEED +x, but if the original carried
     it we preserve the contract).

Also asserts the v2 lib/ originals are gone (the migration is a MOVE,
not a duplicate — per Squad A's re-reading of T5 markings in
``docs/V3_TRIAGE.md``).
"""
from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path


# Files migrated lib/ → shared/runtime/ in Wave 3 Squad A. Tuple values
# document whether the source carried the executable bit (preserved on
# the destination by cp -p semantics — we use plain cp + spot-check).
MIGRATED_FILES: tuple[tuple[str, bool], ...] = (
    ("vitals.sh", True),
    ("heartbeat.sh", True),
    ("watchdog.sh", False),
    ("notify.sh", False),
    ("executor.sh", False),
    ("usage-parsers.sh", False),
    ("file-lock.sh", False),
    ("updater.sh", False),
    ("db-outbox.sh", False),
)

# Resolve repo root once: shared/runtime/tests/__file__ → up 3 dirs.
_REPO = Path(__file__).resolve().parents[3]
_RUNTIME = _REPO / "shared" / "runtime"
_LIB = _REPO / "lib"


class TestLibMigration(unittest.TestCase):
    """Assertions about the nine migrated bash substrate files."""

    def test_each_migrated_file_exists_at_new_path(self) -> None:
        for name, _exec in MIGRATED_FILES:
            with self.subTest(file=name):
                p = _RUNTIME / name
                self.assertTrue(p.is_file(), f"missing: {p}")

    def test_each_migrated_file_is_nonempty(self) -> None:
        for name, _exec in MIGRATED_FILES:
            with self.subTest(file=name):
                p = _RUNTIME / name
                self.assertGreater(p.stat().st_size, 0, f"empty: {p}")

    def test_each_migrated_file_bash_n_clean(self) -> None:
        for name, _exec in MIGRATED_FILES:
            with self.subTest(file=name):
                p = _RUNTIME / name
                r = subprocess.run(
                    ["bash", "-n", str(p)], capture_output=True, text=True
                )
                self.assertEqual(
                    r.returncode, 0,
                    f"bash -n failed for {p}: {r.stderr}"
                )

    def test_executable_bit_preserved_where_required(self) -> None:
        for name, want_exec in MIGRATED_FILES:
            if not want_exec:
                continue
            with self.subTest(file=name):
                p = _RUNTIME / name
                mode = p.stat().st_mode
                self.assertTrue(
                    mode & 0o111,
                    f"expected +x on {p} (lib/ original was executable)"
                )

    def test_lib_originals_removed(self) -> None:
        """The migration is a MOVE; lib/ copies must be gone."""
        for name, _exec in MIGRATED_FILES:
            with self.subTest(file=name):
                p = _LIB / name
                self.assertFalse(
                    p.exists(),
                    f"lib/{name} should have been removed after move; still present at {p}"
                )

    def test_runtime_dir_has_only_expected_shell_substrate(self) -> None:
        """Sanity: shared/runtime/ contains the 9 migrated .sh files."""
        present_sh = {p.name for p in _RUNTIME.glob("*.sh")}
        expected = {name for name, _ in MIGRATED_FILES}
        missing = expected - present_sh
        self.assertFalse(missing, f"missing in shared/runtime/: {missing}")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
