"""
Integration tests for Audit Run API route handlers.

Tests four endpoint handler functions directly:
  create_audit, list_audits, get_audit, list_audit_findings

Uses in-memory SQLite via the sqlite_db fixture.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import BackgroundTasks, HTTPException

from tron.api.routes.audits import (
    AuditCreate,
    create_audit,
    get_audit,
    list_audit_findings,
    list_audits,
)
from tron.domain.models import AuditRun, Finding, Project


@pytest.fixture
async def session(sqlite_db):
    """Yield a single async session for direct handler calls."""
    async with sqlite_db() as s:
        yield s


@pytest.fixture
async def project_id(session):
    """Create a project and return its UUID."""
    project = Project(name="Test Project", default_branch="main", status="active")
    session.add(project)
    await session.flush()
    await session.refresh(project)
    return project.id


@pytest.fixture
async def audit_id(session, project_id):
    """Create an audit run and return its UUID."""
    audit = AuditRun(
        project_id=project_id,
        workflow_id=f"audit-{project_id}",
        workflow_run_id=f"run-{project_id}",
        status="completed",
        progress=100,
        findings_total=2,
        findings_critical=1,
        findings_high=1,
    )
    session.add(audit)
    await session.flush()
    await session.refresh(audit)
    return audit.id


@pytest.fixture
async def findings(session, project_id, audit_id):
    """Create findings attached to the audit."""
    f1 = Finding(
        audit_run_id=audit_id,
        project_id=project_id,
        fingerprint="fp-001",
        rule_id="B101",
        file_path="app.py",
        line_start=10,
        severity="critical",
        category="security",
        title="SQL injection",
        description="SQL injection via string concat",
        status="open",
    )
    f2 = Finding(
        audit_run_id=audit_id,
        project_id=project_id,
        fingerprint="fp-002",
        rule_id="B102",
        file_path="app.py",
        line_start=20,
        severity="high",
        category="security",
        title="Hardcoded secret",
        description="Hardcoded password in source",
        status="open",
    )
    session.add_all([f1, f2])
    await session.flush()
    return [f1, f2]


# ── create_audit ────────────────────────────────────────────────────


class TestCreateAudit:

    @patch("tron.api.routes.audits.settings")
    async def test_create_success(self, mock_settings, session, project_id):
        mock_settings.temporal_enabled = False
        body = AuditCreate(project_id=project_id, branch="main", trigger_type="manual")
        bg = BackgroundTasks()
        result = await create_audit(body=body, background_tasks=bg, session=session)
        assert result.status == "queued"
        assert result.progress == 0
        assert result.project_id == project_id

    @patch("tron.api.routes.audits.settings")
    async def test_create_with_commit_hash(self, mock_settings, session, project_id):
        mock_settings.temporal_enabled = False
        body = AuditCreate(
            project_id=project_id, branch="feature/x",
            commit_hash="abc123", trigger_type="ci",
        )
        bg = BackgroundTasks()
        result = await create_audit(body=body, background_tasks=bg, session=session)
        assert result.branch == "feature/x"
        assert result.commit_hash == "abc123"
        assert result.trigger_type == "ci"

    @patch("tron.api.routes.audits.settings")
    async def test_create_project_not_found(self, mock_settings, session):
        mock_settings.temporal_enabled = False
        body = AuditCreate(project_id=uuid.uuid4())
        bg = BackgroundTasks()
        with pytest.raises(HTTPException) as exc_info:
            await create_audit(body=body, background_tasks=bg, session=session)
        assert exc_info.value.status_code == 404

    @patch("tron.api.routes.audits.settings")
    @patch("tron.api.routes.audits._dispatch_temporal_audit", new_callable=AsyncMock)
    async def test_create_dispatches_temporal(self, mock_dispatch, mock_settings, session, project_id):
        mock_settings.temporal_enabled = True
        body = AuditCreate(project_id=project_id)
        bg = BackgroundTasks()
        result = await create_audit(body=body, background_tasks=bg, session=session)
        assert result.status == "queued"
        mock_dispatch.assert_called_once()


# ── list_audits ─────────────────────────────────────────────────────


class TestListAudits:

    async def test_list_empty(self, session):
        result = await list_audits(project_id=None, status=None, page=1, page_size=20, session=session)
        assert result.items == []
        assert result.total == 0

    async def test_list_with_audits(self, session, audit_id):
        result = await list_audits(project_id=None, status=None, page=1, page_size=20, session=session)
        assert result.total >= 1

    async def test_list_filter_by_project(self, session, project_id, audit_id):
        result = await list_audits(project_id=project_id, status=None, page=1, page_size=20, session=session)
        assert result.total >= 1
        for item in result.items:
            assert item.project_id == project_id

    async def test_list_filter_by_status(self, session, audit_id):
        result = await list_audits(project_id=None, status="completed", page=1, page_size=20, session=session)
        assert result.total >= 1

        result2 = await list_audits(project_id=None, status="running", page=1, page_size=20, session=session)
        assert result2.total == 0

    async def test_list_pagination(self, session, audit_id):
        result = await list_audits(project_id=None, status=None, page=1, page_size=1, session=session)
        assert result.page == 1
        assert result.page_size == 1
        assert len(result.items) <= 1


# ── get_audit ───────────────────────────────────────────────────────


class TestGetAudit:

    async def test_get_success(self, session, audit_id):
        result = await get_audit(audit_id=audit_id, session=session)
        assert result.id == audit_id
        assert result.status == "completed"

    async def test_get_not_found(self, session):
        with pytest.raises(HTTPException) as exc_info:
            await get_audit(audit_id=uuid.uuid4(), session=session)
        assert exc_info.value.status_code == 404


# ── list_audit_findings ─────────────────────────────────────────────


class TestListFindings:

    async def test_list_success(self, session, audit_id, findings):
        result = await list_audit_findings(
            audit_id=audit_id, severity=None, status=None,
            page=1, page_size=50, session=session,
        )
        assert result.total == 2
        assert len(result.items) == 2

    async def test_filter_severity(self, session, audit_id, findings):
        result = await list_audit_findings(
            audit_id=audit_id, severity="critical", status=None,
            page=1, page_size=50, session=session,
        )
        assert result.total == 1
        assert result.items[0].severity == "critical"

    async def test_filter_status(self, session, audit_id, findings):
        result = await list_audit_findings(
            audit_id=audit_id, severity=None, status="open",
            page=1, page_size=50, session=session,
        )
        assert result.total == 2

        result2 = await list_audit_findings(
            audit_id=audit_id, severity=None, status="resolved",
            page=1, page_size=50, session=session,
        )
        assert result2.total == 0

    async def test_audit_not_found(self, session):
        with pytest.raises(HTTPException) as exc_info:
            await list_audit_findings(
                audit_id=uuid.uuid4(), severity=None, status=None,
                page=1, page_size=50, session=session,
            )
        assert exc_info.value.status_code == 404

    async def test_pagination(self, session, audit_id, findings):
        result = await list_audit_findings(
            audit_id=audit_id, severity=None, status=None,
            page=1, page_size=1, session=session,
        )
        assert result.total == 2
        assert len(result.items) == 1

    async def test_empty_findings(self, session, audit_id):
        """Audit exists but has no findings."""
        result = await list_audit_findings(
            audit_id=audit_id, severity=None, status=None,
            page=1, page_size=50, session=session,
        )
        assert result.total == 0
        assert result.items == []
