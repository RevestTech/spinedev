"""Tests for ``recovery.restore``."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from recovery.restore import (
    RestoreManager,
    RestoreOutcome,
    RestorePlan,
    TestRestoreReport,
)


def _run(coro):
    return asyncio.run(coro)


def _runner_succeed_all():
    def _run(argv):
        return (0, "1\n", "")
    return _run


class TestDownloadArgv:

    def test_s3(self, backup_target_s3) -> None:
        mgr = RestoreManager(target=backup_target_s3,
                             runner=_runner_succeed_all())
        argv = mgr._download_argv(
            "s3://example-spine-dr/spine-dr/snapshots/abc/postgres.tar.zst",
            Path("/tmp/x"), kms_key_ref=None,
        )
        assert argv[:3] == ["aws", "s3", "cp"]

    def test_gs(self, backup_target_gs) -> None:
        mgr = RestoreManager(target=backup_target_gs,
                             runner=_runner_succeed_all())
        argv = mgr._download_argv("gs://example-spine-dr/x",
                                  Path("/tmp/x"), kms_key_ref=None)
        assert argv[:3] == ["gcloud", "storage", "cp"]

    def test_azure(self, backup_target_azure) -> None:
        mgr = RestoreManager(target=backup_target_azure,
                             runner=_runner_succeed_all())
        uri = backup_target_azure.uri_for("foo")
        argv = mgr._download_argv(uri, Path("/tmp/x"), kms_key_ref=None)
        assert "az" in argv
        assert "download" in argv

    def test_file(self, backup_target_file) -> None:
        mgr = RestoreManager(target=backup_target_file,
                             runner=_runner_succeed_all())
        argv = mgr._download_argv(
            f"file://{backup_target_file.bucket}/x",
            Path("/tmp/x"), kms_key_ref=None,
        )
        assert argv[0] == "cp"


class TestRestoreToEnvironment:

    def test_refuses_production_env(
        self, backup_target_file, mock_secret_fetcher, mock_pool,
    ) -> None:
        mgr = RestoreManager(
            target=backup_target_file, runner=_runner_succeed_all(),
            secret_fetcher=mock_secret_fetcher,
            pool_factory=lambda: mock_pool,
        )
        plan = RestorePlan(backup_run_id=uuid4(),
                           tested_in_env="production")  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            _run(mgr.restore_to_environment(plan))

    def test_records_succeeded_row(
        self, backup_target_file, mock_secret_fetcher, mock_pool,
    ) -> None:
        # The artifact downloads are placeholder JSON manifests, so
        # any "successful download" yields a valid component restore.
        # We pre-create the artifact files via the mock runner: the
        # 'cp' runner just succeeds without touching disk, so we drop
        # placeholder files into the temp dir via a wrapper runner.
        from pathlib import Path as _P

        # Simpler path: mock _download to write a valid JSON artifact.
        manifest = json.dumps({"placeholder": True})

        class _Runner:
            calls = []

            def __call__(self, argv):
                self.calls.append(argv)
                # If this is the cp/download, materialize the dest.
                if argv[0] == "cp" and len(argv) >= 3:
                    _P(argv[2]).write_text(manifest)
                if argv[0] == "psql":
                    return (0, "1\n", "")
                if argv[0] == "pg_restore":
                    return (0, "", "")
                return (0, "", "")

        mgr = RestoreManager(
            target=backup_target_file, runner=_Runner(),
            secret_fetcher=mock_secret_fetcher,
            pool_factory=lambda: mock_pool,
        )
        plan = RestorePlan(
            backup_run_id=uuid4(),
            tested_in_env="dr-sandbox",
            components=("kg", "vault", "bundles"),  # skip postgres for simplicity
        )
        outcome = _run(mgr.restore_to_environment(plan))
        assert outcome.restore_succeeded, outcome.anomalies
        assert outcome.rto_seconds >= 0
        # Verify a row got logged.
        assert any("INSERT INTO spine_dr.restore_test" in sql
                   for sql, _ in mock_pool.executes)

    def test_postgres_failure_marks_anomalies(
        self, backup_target_file, mock_secret_fetcher, mock_pool,
    ) -> None:
        from pathlib import Path as _P

        class _Runner:
            def __call__(self, argv):
                if argv[0] == "cp" and len(argv) >= 3:
                    _P(argv[2]).write_text("{}")
                if argv[0] == "pg_restore":
                    return (1, "", "FATAL: missing role")
                return (0, "", "")

        mgr = RestoreManager(
            target=backup_target_file, runner=_Runner(),
            secret_fetcher=mock_secret_fetcher,
            pool_factory=lambda: mock_pool,
        )
        plan = RestorePlan(
            backup_run_id=uuid4(),
            tested_in_env="dr-sandbox",
            components=("postgres",),
        )
        outcome = _run(mgr.restore_to_environment(plan))
        assert not outcome.restore_succeeded
        assert outcome.error and "pg_restore" in outcome.error

    def test_corrupt_artifact_detected(
        self, backup_target_file, mock_secret_fetcher, mock_pool,
    ) -> None:
        from pathlib import Path as _P

        class _Runner:
            def __call__(self, argv):
                if argv[0] == "cp" and len(argv) >= 3:
                    _P(argv[2]).write_text("NOT JSON AT ALL")
                if argv[0] == "psql":
                    return (0, "1\n", "")
                return (0, "", "")

        mgr = RestoreManager(
            target=backup_target_file, runner=_Runner(),
            secret_fetcher=mock_secret_fetcher,
            pool_factory=lambda: mock_pool,
        )
        plan = RestorePlan(
            backup_run_id=uuid4(),
            tested_in_env="dr-sandbox",
            components=("kg",),
        )
        outcome = _run(mgr.restore_to_environment(plan))
        # Corrupt artifact surfaces as anomalies, restore_succeeded
        # = False because of malformed_artifact.
        assert "malformed_artifact" in outcome.anomalies


class TestWeeklyTest:

    def test_no_backup_run_yields_failed_report(
        self, backup_target_file, mock_secret_fetcher, mock_pool,
    ) -> None:
        # mock_pool returns no rows by default
        mgr = RestoreManager(
            target=backup_target_file, runner=_runner_succeed_all(),
            secret_fetcher=mock_secret_fetcher,
            pool_factory=lambda: mock_pool,
        )
        report: TestRestoreReport = _run(mgr.run_weekly_test())
        assert not report.all_passed
        assert len(report.outcomes) == 1
        assert "no_completed_backup_run_found" in str(
            report.outcomes[0].anomalies,
        )

    def test_pick_most_recent_backup(
        self, backup_target_file, mock_secret_fetcher, mock_pool,
    ) -> None:
        from pathlib import Path as _P

        run_uuid = uuid4()
        mock_pool.script_row({"id": run_uuid})

        class _Runner:
            def __call__(self, argv):
                if argv[0] == "cp" and len(argv) >= 3:
                    _P(argv[2]).write_text(json.dumps({"placeholder": True}))
                if argv[0] == "psql":
                    return (0, "1\n", "")
                return (0, "", "")

        mgr = RestoreManager(
            target=backup_target_file, runner=_Runner(),
            secret_fetcher=mock_secret_fetcher,
            pool_factory=lambda: mock_pool,
        )
        report = _run(mgr.run_weekly_test(actor="dr-test"))
        assert len(report.outcomes) == 1
        assert report.outcomes[0].backup_run_id == run_uuid


class TestRestoreProduction:

    def test_production_notifies(
        self, backup_target_file, mock_secret_fetcher, mock_pool,
    ) -> None:
        from pathlib import Path as _P
        notifies: list[tuple[str, str]] = []

        class _Runner:
            def __call__(self, argv):
                if argv[0] == "cp" and len(argv) >= 3:
                    _P(argv[2]).write_text("{}")
                if argv[0] == "psql":
                    return (0, "1\n", "")
                return (0, "", "")

        mgr = RestoreManager(
            target=backup_target_file, runner=_Runner(),
            secret_fetcher=mock_secret_fetcher,
            pool_factory=lambda: mock_pool,
            notify_fn=lambda s, b: notifies.append((s, b)),
        )
        plan = RestorePlan(
            backup_run_id=uuid4(),
            tested_in_env="dr-sandbox",  # gets forced to production
            components=("kg",),
        )
        outcome = _run(mgr.restore_production(plan))
        assert outcome.tested_in_env == "production"
        assert len(notifies) == 2  # start + finish
        assert "PRODUCTION RESTORE STARTED" in notifies[0][0]
        assert "PRODUCTION RESTORE" in notifies[1][0]
