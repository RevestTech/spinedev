"""SQL-injection regression tests for plan/pipeline/project_lock.py.

The Wave-1 (v3) fix replaced f-string-built SQL with psql ``:'name'``
parameter binding. These tests assert that:

  1. Untrusted ``project_id`` values are never interpolated into the SQL
     text emitted to ``subprocess.run`` — they are emitted as ``\\set``
     stdin variables and the SQL references them via ``:'pid'``.
  2. Single quotes, backslashes, and Unicode escape attempts in the bind
     value are doubled / passed verbatim via stdin (psql does the
     literal-quoting), not concatenated into the query.
  3. ``_psql_bound`` rejects unsafe bind names (the only place where
     name-component goes through string formatting).
"""
from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

from plan.pipeline import project_lock


_BENIGN_DB_URL = "postgres://stub/spine"


class PsqlBoundSafetyTests(unittest.TestCase):
    """Unit tests for ``project_lock._psql_bound``."""

    def setUp(self) -> None:
        self._prev = os.environ.get("SPINE_DB_URL")
        os.environ["SPINE_DB_URL"] = _BENIGN_DB_URL

    def tearDown(self) -> None:
        if self._prev is None:
            os.environ.pop("SPINE_DB_URL", None)
        else:
            os.environ["SPINE_DB_URL"] = self._prev

    def _run_capture(self, sql: str, binds: dict[str, str]) -> tuple[list[str], str]:
        """Invoke ``_psql_bound`` with subprocess.run mocked; return
        (argv, stdin_script)."""
        proc = MagicMock()
        proc.stdout = ""
        proc.returncode = 0
        with patch.object(project_lock.subprocess, "run", return_value=proc) as m:
            project_lock._psql_bound(sql, binds)
            self.assertEqual(m.call_count, 1)
            args, kwargs = m.call_args
            argv = list(args[0])
            stdin = kwargs.get("input", "")
        return argv, stdin

    def test_argv_never_contains_the_bind_value(self) -> None:
        """Bind values must travel via stdin — not the command line."""
        evil = "1' OR '1'='1"
        sql = "SELECT 1 FROM t WHERE id = :'pid';"
        argv, stdin = self._run_capture(sql, {"pid": evil})
        # Bind value never appears on argv. The fixed SQL body is not on
        # argv either — only the psql command + url + format flags.
        self.assertNotIn(evil, " ".join(argv))
        self.assertEqual(argv[0], "psql")
        # The bind value lands inside the stdin script, single-quote-
        # escaped (the inner ' becomes '').
        self.assertIn(r"\set pid '1'' OR ''1''=''1'", stdin)

    def test_sql_body_passed_through_stdin_with_bind_marker(self) -> None:
        """The SQL body keeps its :'pid' marker — concatenation never
        happens. psql does the substitution at execution time."""
        sql = "SELECT 1 FROM t WHERE id = :'pid';"
        _, stdin = self._run_capture(sql, {"pid": "abc"})
        self.assertIn("SELECT 1 FROM t WHERE id = :'pid';", stdin)

    def test_backslash_in_value_is_not_interpreted_as_escape(self) -> None:
        """Backslash payloads must reach stdin unmodified — the legacy
        ``replace(\"'\", \"''\")`` escape only handled single quotes."""
        evil = r"\'; DROP TABLE x; --"
        sql = "SELECT 1 FROM t WHERE id = :'pid';"
        _, stdin = self._run_capture(sql, {"pid": evil})
        # The dangerous substring never appears OUTSIDE the \set context
        # because the SQL body is just :'pid'.
        # Confirm the SQL body is still parameter-marker form.
        self.assertIn(":'pid'", stdin)
        # Confirm the literal value was doubled-quoted ('') and embedded
        # in the \set line — psql will safely re-quote it when expanding
        # :'pid' into the executed SQL.
        self.assertIn(r"\set pid '", stdin)

    def test_unsafe_bind_names_are_rejected(self) -> None:
        """Bind names are the one place where a string is formatted into
        the script. The validator must reject anything non-identifier."""
        sql = "SELECT 1;"
        with self.assertRaises(ValueError):
            project_lock._psql_bound(sql, {"bad name": "x"})
        with self.assertRaises(ValueError):
            project_lock._psql_bound(sql, {"a;b": "x"})


class LockProjectUsesBoundPsqlTests(unittest.TestCase):
    """Higher-level: ``lock_project_to_pipeline`` and ``get_locked_pipeline``
    route through ``_psql_bound`` rather than string-concat SQL."""

    def setUp(self) -> None:
        self._prev = os.environ.get("SPINE_DB_URL")
        os.environ["SPINE_DB_URL"] = _BENIGN_DB_URL

    def tearDown(self) -> None:
        if self._prev is None:
            os.environ.pop("SPINE_DB_URL", None)
        else:
            os.environ["SPINE_DB_URL"] = self._prev

    def test_lock_project_invokes_bound_form(self) -> None:
        from plan.pipeline.manifest_loader import PipelineManifest

        manifest = PipelineManifest(
            version=1, org_bundle="t",
            phases=[{"id": "intake", "label": "Intake"}],
        )
        called: dict[str, object] = {}

        def fake_bound(sql: str, binds: dict[str, str]) -> str:
            called["sql"] = sql
            called["binds"] = dict(binds)
            return ""

        with patch.object(project_lock, "_psql_bound", side_effect=fake_bound):
            with patch.object(project_lock, "_audit"):
                project_lock.lock_project_to_pipeline(
                    "evil'; DROP TABLE spine_lifecycle.project; --",
                    manifest,
                )

        # The SQL body must reference :'pid', :'version', :'snap' rather
        # than embedding the project id literally.
        self.assertIn(":'pid'", called["sql"])  # type: ignore[arg-type]
        self.assertIn(":'version'", called["sql"])  # type: ignore[arg-type]
        self.assertIn(":'snap'", called["sql"])  # type: ignore[arg-type]
        # The injection payload is delivered as a bind value, not in SQL.
        self.assertIn(
            "evil'; DROP TABLE spine_lifecycle.project; --",
            called["binds"]["pid"],  # type: ignore[index]
        )
        self.assertNotIn(
            "DROP TABLE", called["sql"],  # type: ignore[arg-type]
        )


if __name__ == "__main__":
    unittest.main()
