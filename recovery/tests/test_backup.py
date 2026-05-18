"""Tests for ``recovery.backup``."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from recovery.backup import (
    BackupManager,
    BackupOutcome,
    BackupTarget,
    SnapshotPlan,
    WalPlan,
)


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# BackupTarget
# ---------------------------------------------------------------------------


class TestBackupTarget:

    def test_uri_for_s3(self, backup_target_s3: BackupTarget) -> None:
        uri = backup_target_s3.uri_for("snapshots", "abc", "postgres.tar.zst")
        assert uri == "s3://example-spine-dr/spine-dr/snapshots/abc/postgres.tar.zst"

    def test_uri_for_gs(self, backup_target_gs: BackupTarget) -> None:
        uri = backup_target_gs.uri_for("wal", "spine_dr_wal")
        assert uri == "gs://example-spine-dr/spine-dr/wal/spine_dr_wal"

    def test_uri_for_azure(self, backup_target_azure: BackupTarget) -> None:
        uri = backup_target_azure.uri_for("snapshots", "x")
        assert uri.startswith("azure://examplespinedr/")

    def test_from_bundle_defaults(self) -> None:
        t = BackupTarget.from_bundle({"bucket": "b"})
        assert t.scheme == "s3"
        assert t.bucket == "b"
        assert t.prefix == "spine-dr"

    def test_from_bundle_full(self) -> None:
        t = BackupTarget.from_bundle({
            "scheme": "gs", "bucket": "b", "prefix": "p",
            "kms_key_ref": "vault/kms",
        })
        assert t.scheme == "gs"
        assert t.kms_key_ref == "vault/kms"


# ---------------------------------------------------------------------------
# BackupManager._upload_argv per scheme (tests assert exact argv shape)
# ---------------------------------------------------------------------------


class TestUploadArgv:

    def test_s3_with_kms(self, backup_target_s3, mock_runner) -> None:
        mgr = BackupManager(target=backup_target_s3, runner=mock_runner)
        argv = mgr._upload_argv(
            Path("/tmp/foo"), "s3://example-spine-dr/spine-dr/foo",
            kms_key_ref="arn:aws:kms:us-east-1:123:key/abc",
        )
        assert argv[:3] == ["aws", "s3", "cp"]
        assert "--sse" in argv
        assert "aws:kms" in argv
        assert "--sse-kms-key-id" in argv
        assert "arn:aws:kms:us-east-1:123:key/abc" in argv

    def test_s3_minio_endpoint(self) -> None:
        target = BackupTarget(
            scheme="minio", bucket="b", endpoint_url="http://minio:9000",
            kms_key_ref=None,
        )
        mgr = BackupManager(target=target, runner=lambda a: (0, "", ""))
        argv = mgr._upload_argv(Path("/tmp/x"), "s3://b/x", kms_key_ref=None)
        assert "--endpoint-url" in argv
        assert "http://minio:9000" in argv
        assert "--sse" not in argv  # no KMS, no SSE flags

    def test_gs_with_kms(self, backup_target_gs) -> None:
        mgr = BackupManager(target=backup_target_gs, runner=lambda a: (0, "", ""))
        argv = mgr._upload_argv(
            Path("/tmp/foo"), "gs://example-spine-dr/spine-dr/foo",
            kms_key_ref="projects/p/locations/l/keyRings/r/cryptoKeys/k",
        )
        assert argv[:3] == ["gcloud", "storage", "cp"]
        assert "--kms-key" in argv

    def test_azure(self, backup_target_azure) -> None:
        mgr = BackupManager(target=backup_target_azure,
                            runner=lambda a: (0, "", ""))
        uri = backup_target_azure.uri_for("foo")
        argv = mgr._upload_argv(Path("/tmp/foo"), uri, kms_key_ref=None)
        assert argv[:5] == ["az", "storage", "blob", "upload",
                            "--account-name"]
        assert "--container-name" in argv

    def test_file_scheme_for_tests(self, backup_target_file) -> None:
        mgr = BackupManager(target=backup_target_file,
                            runner=lambda a: (0, "", ""))
        argv = mgr._upload_argv(
            Path("/tmp/foo"),
            f"file://{backup_target_file.bucket}/x",
            kms_key_ref=None,
        )
        assert argv[0] == "cp"

    def test_unknown_scheme_raises(self) -> None:
        # Literal in @dataclass(frozen=True) isn't enforced at runtime
        # by Python, so an unknown scheme propagates to the dispatcher;
        # the dispatcher MUST raise ValueError.
        target = BackupTarget(scheme="ftp", bucket="b")  # type: ignore[arg-type]
        mgr = BackupManager(target=target, runner=lambda a: (0, "", ""))
        with pytest.raises(ValueError):
            mgr._upload_argv(Path("/tmp/x"), "ftp://b/x", kms_key_ref=None)


# ---------------------------------------------------------------------------
# BackupManager.run_snapshot end-to-end (mocked subprocess + KMS)
# ---------------------------------------------------------------------------


class TestRunSnapshot:

    def test_snapshot_writes_backup_run_rows(
        self, backup_target_file, mock_runner, mock_secret_fetcher, mock_pool,
    ) -> None:
        mgr = BackupManager(
            target=backup_target_file,
            runner=mock_runner,
            secret_fetcher=mock_secret_fetcher,
            pool_factory=lambda: mock_pool,
        )
        plan = SnapshotPlan(components=("postgres",))
        outcome = _run(mgr.run_snapshot(plan))
        assert outcome.status == "completed"
        assert outcome.encryption_kms_key_ref == \
            "arn:aws:kms:us-east-1:123:key/test-kms-key"
        # 1 INSERT + 1 UPDATE finalize
        executes = [sql for sql, _ in mock_pool.executes]
        assert any("INSERT INTO spine_dr.backup_run" in s for s in executes)
        assert any("UPDATE spine_dr.backup_run" in s for s in executes)
        assert "postgres" in outcome.components_uploaded

    def test_snapshot_failure_records_failed_row(
        self, backup_target_file, mock_secret_fetcher, mock_pool,
    ) -> None:
        # Runner: succeed on pg_basebackup, fail on the upload.
        class _Runner:
            calls = []

            def __call__(self, argv):
                self.calls.append(argv)
                if argv[0] in ("aws", "cp", "gcloud", "az"):
                    return (1, "", "permission denied")
                return (0, "", "")

        mgr = BackupManager(
            target=backup_target_file,
            runner=_Runner(),
            secret_fetcher=mock_secret_fetcher,
            pool_factory=lambda: mock_pool,
        )
        outcome = _run(mgr.run_snapshot(SnapshotPlan(components=("postgres",))))
        assert outcome.status == "failed"
        assert outcome.error and "upload" in outcome.error.lower() or "permission" in outcome.error.lower()

    def test_snapshot_kms_missing_in_vault_raises(
        self, backup_target_file, mock_runner, mock_pool,
    ) -> None:
        async def empty_fetcher(path: str) -> str:
            raise KeyError(path)

        mgr = BackupManager(
            target=backup_target_file,
            runner=mock_runner,
            secret_fetcher=empty_fetcher,
            pool_factory=lambda: mock_pool,
        )
        outcome = _run(mgr.run_snapshot(SnapshotPlan(components=("postgres",))))
        assert outcome.status == "failed"
        assert "kms" in (outcome.error or "").lower()

    def test_snapshot_uses_all_default_components(
        self, backup_target_file, mock_runner, mock_secret_fetcher, mock_pool,
    ) -> None:
        mgr = BackupManager(
            target=backup_target_file, runner=mock_runner,
            secret_fetcher=mock_secret_fetcher,
            pool_factory=lambda: mock_pool,
        )
        outcome = _run(mgr.run_snapshot(SnapshotPlan()))
        assert outcome.status == "completed"
        assert set(outcome.components_uploaded) == {
            "postgres", "kg", "vault", "bundles",
        }


# ---------------------------------------------------------------------------
# WAL stream
# ---------------------------------------------------------------------------


class TestWalStream:

    def test_start_wal_stream_invokes_pg_receivewal(
        self, backup_target_file, mock_runner, mock_secret_fetcher, mock_pool,
    ) -> None:
        mgr = BackupManager(
            target=backup_target_file, runner=mock_runner,
            secret_fetcher=mock_secret_fetcher,
            pool_factory=lambda: mock_pool,
        )
        outcome = _run(mgr.start_wal_stream(WalPlan()))
        assert outcome.run_type == "continuous"
        assert outcome.status == "in_progress"
        # Runner saw pg_receivewal as first arg of the streaming call.
        assert any(c[0] == "pg_receivewal" for c in mock_runner.calls)

    def test_start_wal_stream_failure_marked(
        self, backup_target_file, mock_secret_fetcher, mock_pool,
    ) -> None:
        runner = lambda a: (2, "", "could not connect")
        mgr = BackupManager(
            target=backup_target_file, runner=runner,
            secret_fetcher=mock_secret_fetcher,
            pool_factory=lambda: mock_pool,
        )
        outcome = _run(mgr.start_wal_stream(WalPlan()))
        assert outcome.status == "failed"
        assert "could not connect" in (outcome.error or "")


class TestOutcomeMetadata:

    def test_as_audit_metadata_has_essentials(self) -> None:
        from datetime import datetime, timezone
        from uuid import uuid4
        outcome = BackupOutcome(
            run_id=uuid4(), run_type="snapshot", status="completed",
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
            size_bytes=1024, target_uri="file:///tmp/x",
            encryption_kms_key_ref="arn:test",
            components_uploaded=("postgres",),
        )
        meta = outcome.as_audit_metadata()
        assert "run_id" in meta
        assert meta["status"] == "completed"
        assert meta["size_bytes"] == 1024
        assert meta["components_uploaded"] == ["postgres"]
