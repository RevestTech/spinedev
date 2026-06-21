"""
Unit tests for Health check and GDPR route schemas.

Pure Pydantic schema tests + direct function tests with mocking.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock, patch

from tron.api.routes.gdpr import (
    GDPRExportResponse,
    GDPRDeleteResponse,
    RetentionPolicyResponse,
)


# ============================================================================
# Health Endpoint Tests (direct function calls)
# ============================================================================

class TestHealthEndpoint:

    async def test_health_returns_ok(self):
        from tron.api.routes.health import health
        result = await health()
        assert result["status"] == "ok"

    async def test_health_returns_service_name(self):
        from tron.api.routes.health import health
        result = await health()
        assert result["service"] == "tron-api"

    async def test_health_returns_uptime(self):
        from tron.api.routes.health import health
        result = await health()
        assert "uptime_seconds" in result
        assert isinstance(result["uptime_seconds"], float)

    async def test_health_uptime_positive(self):
        from tron.api.routes.health import health
        result = await health()
        assert result["uptime_seconds"] >= 0


# ============================================================================
# Ready Endpoint Tests
# ============================================================================

class TestReadyEndpoint:

    async def test_ready_returns_ready_when_all_ok(self):
        """When DB and Redis are healthy, returns ready."""
        from tron.api.routes.health import ready

        mock_engine = MagicMock()
        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar.return_value = 1
        mock_conn.execute = AsyncMock(return_value=mock_result)

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_engine.connect.return_value = mock_ctx

        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(return_value=True)

        with patch("tron.api.routes.health.get_engine", return_value=mock_engine), \
             patch("tron.api.routes.health.get_redis", return_value=mock_redis):
            result = await ready()
            assert result.status_code == 200

    async def test_ready_503_when_db_fails(self):
        """When DB fails, returns 503."""
        from tron.api.routes.health import ready

        mock_engine = MagicMock()
        mock_engine.connect.side_effect = Exception("DB down")

        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(return_value=True)

        with patch("tron.api.routes.health.get_engine", return_value=mock_engine), \
             patch("tron.api.routes.health.get_redis", return_value=mock_redis):
            result = await ready()
            assert result.status_code == 503

    async def test_ready_503_when_redis_fails(self):
        """When Redis fails, returns 503."""
        from tron.api.routes.health import ready

        mock_engine = MagicMock()
        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar.return_value = 1
        mock_conn.execute = AsyncMock(return_value=mock_result)
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_engine.connect.return_value = mock_ctx

        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(side_effect=Exception("Redis down"))

        with patch("tron.api.routes.health.get_engine", return_value=mock_engine), \
             patch("tron.api.routes.health.get_redis", return_value=mock_redis):
            result = await ready()
            assert result.status_code == 503


# ============================================================================
# GDPR Export Response Schema
# ============================================================================

class TestGDPRExportResponseSchema:

    def test_valid_export(self):
        now = datetime.now(timezone.utc)
        resp = GDPRExportResponse(
            user_id=uuid4(), export_timestamp=now,
            projects=[], audit_runs=[], findings=[],
            total_records=0,
        )
        assert resp.total_records == 0

    def test_export_with_data(self):
        now = datetime.now(timezone.utc)
        resp = GDPRExportResponse(
            user_id=uuid4(), export_timestamp=now,
            projects=[{"id": "1", "name": "P1"}],
            audit_runs=[{"id": "2", "status": "completed"}],
            findings=[{"id": "3", "severity": "high"}],
            total_records=3,
        )
        assert resp.total_records == 3
        assert len(resp.projects) == 1
        assert len(resp.audit_runs) == 1
        assert len(resp.findings) == 1

    def test_export_user_id_optional(self):
        now = datetime.now(timezone.utc)
        resp = GDPRExportResponse(
            user_id=None, export_timestamp=now,
            projects=[], audit_runs=[], findings=[],
            total_records=0,
        )
        assert resp.user_id is None

    def test_export_serialization(self):
        now = datetime.now(timezone.utc)
        resp = GDPRExportResponse(
            user_id=uuid4(), export_timestamp=now,
            projects=[], audit_runs=[], findings=[],
            total_records=0,
        )
        data = resp.model_dump()
        assert "export_timestamp" in data
        assert "total_records" in data


# ============================================================================
# GDPR Delete Response Schema
# ============================================================================

class TestGDPRDeleteResponseSchema:

    def test_valid_delete(self):
        now = datetime.now(timezone.utc)
        resp = GDPRDeleteResponse(
            user_id=uuid4(), deletion_timestamp=now,
            projects_deleted=5, audit_runs_deleted=10,
            findings_deleted=50, total_records_deleted=65,
        )
        assert resp.total_records_deleted == 65

    def test_zero_deletions(self):
        now = datetime.now(timezone.utc)
        resp = GDPRDeleteResponse(
            user_id=uuid4(), deletion_timestamp=now,
            projects_deleted=0, audit_runs_deleted=0,
            findings_deleted=0, total_records_deleted=0,
        )
        assert resp.total_records_deleted == 0

    def test_delete_serialization(self):
        now = datetime.now(timezone.utc)
        resp = GDPRDeleteResponse(
            user_id=uuid4(), deletion_timestamp=now,
            projects_deleted=1, audit_runs_deleted=2,
            findings_deleted=3, total_records_deleted=6,
        )
        data = resp.model_dump()
        assert data["projects_deleted"] == 1
        assert data["total_records_deleted"] == 6


# ============================================================================
# Retention Policy Response Schema
# ============================================================================

class TestRetentionPolicySchema:

    def test_default_values(self):
        now = datetime.now(timezone.utc)
        policy = RetentionPolicyResponse(last_updated=now)
        assert policy.project_retention_days == 2555
        assert policy.audit_run_retention_days == 1095
        assert policy.finding_retention_days == 1095
        assert policy.soft_delete_grace_period_days == 30

    def test_custom_values(self):
        now = datetime.now(timezone.utc)
        policy = RetentionPolicyResponse(
            project_retention_days=365,
            audit_run_retention_days=180,
            finding_retention_days=90,
            soft_delete_grace_period_days=7,
            last_updated=now,
        )
        assert policy.project_retention_days == 365

    def test_serialization(self):
        now = datetime.now(timezone.utc)
        policy = RetentionPolicyResponse(last_updated=now)
        data = policy.model_dump()
        assert "project_retention_days" in data
        assert "last_updated" in data

    def test_seven_year_project_retention(self):
        """Default project retention is ~7 years."""
        now = datetime.now(timezone.utc)
        policy = RetentionPolicyResponse(last_updated=now)
        assert policy.project_retention_days == 2555  # ~7 years

    def test_three_year_audit_retention(self):
        """Default audit retention is ~3 years."""
        now = datetime.now(timezone.utc)
        policy = RetentionPolicyResponse(last_updated=now)
        assert policy.audit_run_retention_days == 1095  # ~3 years

    def test_grace_period_30_days(self):
        """Default grace period is 30 days."""
        now = datetime.now(timezone.utc)
        policy = RetentionPolicyResponse(last_updated=now)
        assert policy.soft_delete_grace_period_days == 30


# ============================================================================
# Retention Policy Endpoint Tests (direct function call)
# ============================================================================

class TestRetentionPolicyEndpoint:

    async def test_get_retention_policy(self):
        from tron.api.routes.gdpr import get_retention_policy
        result = await get_retention_policy()
        assert isinstance(result, RetentionPolicyResponse)
        assert result.project_retention_days == 2555

    async def test_retention_policy_has_last_updated(self):
        from tron.api.routes.gdpr import get_retention_policy
        result = await get_retention_policy()
        assert result.last_updated is not None

    async def test_retention_policy_timestamp_recent(self):
        from tron.api.routes.gdpr import get_retention_policy
        before = datetime.now(timezone.utc)
        result = await get_retention_policy()
        after = datetime.now(timezone.utc)
        assert before <= result.last_updated <= after
