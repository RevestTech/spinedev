"""
Unit tests for Audit route schemas and validation logic.

Pure Pydantic schema tests — no FastAPI TestClient or DB needed.
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone
from uuid import uuid4
from pydantic import ValidationError

from tron.api.routes.audits import (
    AuditCreate,
    AuditSummary,
    AuditListResponse,
    FindingResponse,
    FindingListResponse,
)


# ============================================================================
# AuditCreate Schema Validation
# ============================================================================

class TestAuditCreateSchema:

    def test_valid_create(self):
        req = AuditCreate(project_id=uuid4())
        assert req.branch == "main"
        assert req.trigger_type == "manual"

    def test_project_id_required(self):
        with pytest.raises(ValidationError):
            AuditCreate()

    def test_project_id_must_be_uuid(self):
        with pytest.raises(ValidationError):
            AuditCreate(project_id="not-a-uuid")

    def test_string_uuid_coerced(self):
        uid = uuid4()
        req = AuditCreate(project_id=str(uid))
        assert req.project_id == uid

    def test_branch_defaults_main(self):
        req = AuditCreate(project_id=uuid4())
        assert req.branch == "main"

    def test_custom_branch(self):
        req = AuditCreate(project_id=uuid4(), branch="develop")
        assert req.branch == "develop"

    def test_branch_with_slashes(self):
        req = AuditCreate(project_id=uuid4(), branch="feature/x/y")
        assert req.branch == "feature/x/y"

    def test_commit_hash_default_none(self):
        req = AuditCreate(project_id=uuid4())
        assert req.commit_hash is None

    def test_commit_hash_set(self):
        req = AuditCreate(project_id=uuid4(), commit_hash="abc123")
        assert req.commit_hash == "abc123"

    def test_full_sha_hash(self):
        sha = "a" * 40
        req = AuditCreate(project_id=uuid4(), commit_hash=sha)
        assert len(req.commit_hash) == 40

    def test_trigger_type_default_manual(self):
        req = AuditCreate(project_id=uuid4())
        assert req.trigger_type == "manual"

    def test_trigger_type_custom(self):
        for t in ["ci", "webhook", "scheduled", "api"]:
            req = AuditCreate(project_id=uuid4(), trigger_type=t)
            assert req.trigger_type == t

    def test_full_create(self):
        pid = uuid4()
        req = AuditCreate(
            project_id=pid, branch="dev",
            commit_hash="deadbeef", trigger_type="webhook",
        )
        assert req.project_id == pid
        assert req.branch == "dev"

    def test_serialization_roundtrip(self):
        pid = uuid4()
        req = AuditCreate(project_id=pid, branch="dev")
        data = req.model_dump()
        req2 = AuditCreate(**data)
        assert req2.project_id == pid


# ============================================================================
# AuditSummary Schema Tests
# ============================================================================

class TestAuditSummarySchema:

    @pytest.fixture
    def now(self):
        return datetime.now(timezone.utc)

    def test_valid_summary(self, now):
        s = AuditSummary(
            id=uuid4(), project_id=uuid4(), status="running",
            progress=50, findings_total=10, findings_critical=1,
            findings_high=3, findings_medium=4, findings_low=2,
            started_at=now, completed_at=None, error_message=None,
            created_at=now,
        )
        assert s.status == "running"
        assert s.progress == 50

    def test_completed_summary(self, now):
        s = AuditSummary(
            id=uuid4(), project_id=uuid4(), status="completed",
            progress=100, findings_total=5, findings_critical=0,
            findings_high=2, findings_medium=2, findings_low=1,
            started_at=now, completed_at=now, error_message=None,
            created_at=now,
        )
        assert s.completed_at is not None

    def test_error_summary(self, now):
        s = AuditSummary(
            id=uuid4(), project_id=uuid4(), status="failed",
            progress=30, findings_total=0, findings_critical=0,
            findings_high=0, findings_medium=0, findings_low=0,
            started_at=now, completed_at=now,
            error_message="LLM timeout", created_at=now,
        )
        assert s.error_message == "LLM timeout"

    def test_zero_findings(self, now):
        s = AuditSummary(
            id=uuid4(), project_id=uuid4(), status="completed",
            progress=100, findings_total=0, findings_critical=0,
            findings_high=0, findings_medium=0, findings_low=0,
            started_at=now, completed_at=now, error_message=None,
            created_at=now,
        )
        total = s.findings_critical + s.findings_high + s.findings_medium + s.findings_low
        assert total == 0

    def test_from_attributes_config(self):
        assert AuditSummary.model_config.get("from_attributes") is True

    def test_serialization(self, now):
        s = AuditSummary(
            id=uuid4(), project_id=uuid4(), status="running",
            progress=50, findings_total=0, findings_critical=0,
            findings_high=0, findings_medium=0, findings_low=0,
            started_at=now, completed_at=None, error_message=None,
            created_at=now,
        )
        data = s.model_dump()
        assert data["status"] == "running"
        assert data["completed_at"] is None


# ============================================================================
# AuditListResponse Schema Tests
# ============================================================================

class TestAuditListResponseSchema:

    def test_empty_list(self):
        resp = AuditListResponse(items=[], total=0, page=1, page_size=20)
        assert resp.total == 0 and len(resp.items) == 0

    def test_pagination_fields(self):
        resp = AuditListResponse(items=[], total=100, page=3, page_size=20)
        assert resp.page == 3
        assert resp.page_size == 20
        assert resp.total == 100

    def test_with_items(self):
        now = datetime.now(timezone.utc)
        item = AuditSummary(
            id=uuid4(), project_id=uuid4(), status="completed",
            progress=100, findings_total=3, findings_critical=1,
            findings_high=1, findings_medium=1, findings_low=0,
            started_at=now, completed_at=now, error_message=None,
            created_at=now,
        )
        resp = AuditListResponse(items=[item], total=1, page=1, page_size=20)
        assert len(resp.items) == 1


# ============================================================================
# FindingResponse Schema Tests
# ============================================================================

class TestFindingResponseSchema:

    def test_valid_finding(self):
        now = datetime.now(timezone.utc)
        f = FindingResponse(
            id=uuid4(), audit_run_id=uuid4(), project_id=uuid4(),
            fingerprint="abc123", rule_id="sql-injection-001",
            file_path="app.py", line_start=42, line_end=42,
            severity="critical", category="security",
            title="SQL Injection", description="User input in query",
            suggested_fix="Use parameterized queries", status="open",
            code_snippet="query = ...", created_at=now,
        )
        assert f.severity == "critical"
        assert f.file_path == "app.py"

    def test_optional_fields_none(self):
        now = datetime.now(timezone.utc)
        f = FindingResponse(
            id=uuid4(), audit_run_id=uuid4(), project_id=uuid4(),
            fingerprint="abc", rule_id="test", file_path="f.py",
            line_start=None, line_end=None, severity="low",
            category=None, title="Issue", description="Desc",
            suggested_fix=None, status="open", code_snippet=None,
            created_at=now,
        )
        assert f.line_start is None
        assert f.suggested_fix is None

    def test_from_attributes(self):
        assert FindingResponse.model_config.get("from_attributes") is True


# ============================================================================
# FindingListResponse Schema Tests
# ============================================================================

class TestFindingListResponseSchema:

    def test_empty_findings(self):
        resp = FindingListResponse(items=[], total=0, page=1, page_size=50)
        assert resp.total == 0

    def test_pagination(self):
        resp = FindingListResponse(items=[], total=500, page=5, page_size=50)
        assert resp.page == 5
        assert resp.total == 500
