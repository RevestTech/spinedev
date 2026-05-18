"""Tests for ``shared/mcp/tools/recovery.py``.

Per design decision #12 (Cite-or-Refuse), ``recovery_snapshot`` and
``recovery_restore`` are tagged ``requires_citation=True`` and MUST
return at least one Citation on success. These tests verify the tag is
applied + the citations are non-empty on a happy-path run.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import pytest

from shared.mcp.tools import TOOL_REGISTRY


def _force_registration() -> None:
    """Importing the module triggers @register_tool decorators."""
    import shared.mcp.tools.recovery  # noqa: F401


class TestRegistration:

    def test_all_five_tools_registered(self) -> None:
        _force_registration()
        for name in (
            "recovery_snapshot", "recovery_restore",
            "recovery_test", "recovery_health", "recovery_runbook_export",
        ):
            assert name in TOOL_REGISTRY, f"{name} not registered"

    def test_snapshot_requires_citation(self) -> None:
        _force_registration()
        spec = TOOL_REGISTRY["recovery_snapshot"]
        assert spec.requires_citation is True

    def test_restore_requires_citation(self) -> None:
        _force_registration()
        spec = TOOL_REGISTRY["recovery_restore"]
        assert spec.requires_citation is True

    def test_test_does_NOT_require_citation(self) -> None:
        _force_registration()
        spec = TOOL_REGISTRY["recovery_test"]
        assert spec.requires_citation is False

    def test_health_does_NOT_require_citation(self) -> None:
        _force_registration()
        spec = TOOL_REGISTRY["recovery_health"]
        assert spec.requires_citation is False

    def test_runbook_export_does_NOT_require_citation(self) -> None:
        _force_registration()
        spec = TOOL_REGISTRY["recovery_runbook_export"]
        assert spec.requires_citation is False


class TestRecoverySnapshot:

    def test_snapshot_returns_citation(self, monkeypatch, tmp_path) -> None:
        _force_registration()
        from shared.mcp.tools import recovery as rec_mod
        from recovery.backup import BackupOutcome

        outcome = BackupOutcome(
            run_id=uuid4(), run_type="snapshot", status="completed",
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
            size_bytes=2048,
            target_uri="s3://example/snap",
            encryption_kms_key_ref="arn:test-kms",
            components_uploaded=("postgres",),
        )

        class FakeMgr:
            def __init__(self, *_a, **_kw): pass

            async def run_snapshot(self, plan): return outcome

        # Patch the dynamic import in the tool body.
        import recovery.backup as backup_mod
        monkeypatch.setattr(backup_mod, "BackupManager", FakeMgr)

        payload = rec_mod.RecoverySnapshotInput(
            project_id="proj1", actor="devops",
            components=("postgres",), target={"bucket": "example"},
        )
        resp = rec_mod.recovery_snapshot(payload)
        assert resp.status == "ok"
        assert len(resp.citation) >= 1
        # At least one audit_hash citation.
        types = {c.type for c in resp.citation}
        assert "audit_hash" in types

    def test_snapshot_invalid_target_returns_error(self) -> None:
        _force_registration()
        from shared.mcp.tools import recovery as rec_mod

        # Missing "bucket" → BackupTarget.from_bundle KeyError →
        # tool catches and returns snapshot_failed.
        payload = rec_mod.RecoverySnapshotInput(
            project_id="proj1", actor="devops",
            target={},  # no bucket key
        )
        resp = rec_mod.recovery_snapshot(payload)
        assert resp.status == "error"


class TestRecoveryRestore:

    def test_invalid_uuid_returns_error(self) -> None:
        _force_registration()
        from shared.mcp.tools import recovery as rec_mod
        payload = rec_mod.RecoveryRestoreInput(
            project_id="proj1", actor="devops",
            backup_run_id="not-a-uuid",
            tested_in_env="dr-sandbox",
            target={"bucket": "example"},
        )
        resp = rec_mod.recovery_restore(payload)
        assert resp.status == "error"
        assert resp.error and "invalid" in resp.error.code.lower()

    def test_restore_returns_citation(self, monkeypatch) -> None:
        _force_registration()
        from shared.mcp.tools import recovery as rec_mod
        from recovery.restore import RestoreOutcome
        from uuid import uuid4 as _uu

        outcome = RestoreOutcome(
            restore_test_id=_uu(), backup_run_id=_uu(),
            tested_at=datetime.now(timezone.utc),
            tested_in_env="dr-sandbox",
            restore_succeeded=True,
            rto_seconds=42,
            anomalies={},
            components_restored=("postgres",),
        )

        class FakeMgr:
            def __init__(self, *_a, **_kw): pass

            async def restore_to_environment(self, plan): return outcome

        import recovery.restore as restore_mod
        monkeypatch.setattr(restore_mod, "RestoreManager", FakeMgr)

        payload = rec_mod.RecoveryRestoreInput(
            project_id="proj1", actor="devops",
            backup_run_id=str(_uu()),
            tested_in_env="dr-sandbox",
            target={"bucket": "example"},
        )
        resp = rec_mod.recovery_restore(payload)
        assert resp.status == "ok"
        assert len(resp.citation) >= 1


class TestRecoveryHealth:

    def test_health_returns_report_dict(self, monkeypatch) -> None:
        _force_registration()
        from shared.mcp.tools import recovery as rec_mod
        from recovery.health import HealthProber, HealthReport, ProbeOutcome
        from uuid import uuid4 as _uu

        async def fake_report(self):
            return HealthReport(
                report_id=_uu(),
                generated_at=datetime.now(timezone.utc),
                outcomes=(ProbeOutcome(component="hub", status="healthy",
                                       latency_ms=1),),
            )

        monkeypatch.setattr(HealthProber, "generate_report", fake_report)

        payload = rec_mod.RecoveryHealthInput(
            project_id="proj1", actor="system",
        )
        resp = rec_mod.recovery_health(payload)
        assert resp.status == "ok"
        assert resp.data["overall_status"] == "healthy"
        assert resp.data["components"][0]["component"] == "hub"


class TestRecoveryRunbookExport:

    def test_runbook_returns_markdown(self) -> None:
        _force_registration()
        from shared.mcp.tools import recovery as rec_mod
        payload = rec_mod.RecoveryRunbookExportInput(
            project_id="proj1", actor="devops",
            deployment_shape="customer-cloud",
            customer_name="acme",
            primary_region="us-east-1",
            pager_rotation=("a@x", "b@y"),
            storage_target_uri="s3://acme-dr/",
            kms_key_ref="recovery/kms/prod/key_id",
            cross_region_licensed=False,
        )
        resp = rec_mod.recovery_runbook_export(payload)
        assert resp.status == "ok"
        assert "acme" in resp.data["body_markdown"]
        assert len(resp.data["content_hash"]) == 64
        assert resp.data["byte_count"] > 0


class TestRecoveryTest:

    def test_test_runs_and_returns(self, monkeypatch) -> None:
        _force_registration()
        from shared.mcp.tools import recovery as rec_mod
        from recovery.restore import TestRestoreReport, RestoreOutcome
        from uuid import uuid4 as _uu

        report = TestRestoreReport(
            cycle_id=_uu(),
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
            outcomes=(RestoreOutcome(
                restore_test_id=_uu(), backup_run_id=_uu(),
                tested_at=datetime.now(timezone.utc),
                tested_in_env="dr-sandbox",
                restore_succeeded=True, rto_seconds=10,
                anomalies={}, components_restored=("postgres",),
            ),),
            all_passed=True,
        )

        class FakeMgr:
            def __init__(self, *_a, **_kw): pass

            async def run_weekly_test(self, **_kw): return report

        import recovery.restore as restore_mod
        monkeypatch.setattr(restore_mod, "RestoreManager", FakeMgr)

        payload = rec_mod.RecoveryTestInput(
            project_id="proj1", actor="dr-test-cron",
            target={"bucket": "example"},
        )
        resp = rec_mod.recovery_test(payload)
        assert resp.status == "ok"
        assert resp.data["all_passed"] is True
        assert resp.data["worst_rto_seconds"] == 10
