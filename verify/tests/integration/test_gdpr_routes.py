"""
Integration tests for GDPR Data Subject Rights endpoints.

Tests all three endpoint handler functions directly:
  export_user_data, delete_user_data, get_retention_policy

Uses in-memory SQLite via the sqlite_db fixture.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from tron.api.routes.gdpr import (
    export_user_data,
    delete_user_data,
    get_retention_policy,
)
from tron.domain.models import AuditRun, Finding, Project


@pytest.fixture
async def session(sqlite_db):
    """Yield a single async session for direct handler calls."""
    async with sqlite_db() as s:
        yield s


USER_ID = uuid.uuid4()


async def _seed_project(session, user_id=USER_ID, name="GDPR Project"):
    """Create a project for the given user."""
    p = Project(name=name, created_by=user_id, status="active")
    session.add(p)
    await session.flush()
    return p


async def _seed_audit(session, project_id):
    """Create an audit run for the given project."""
    a = AuditRun(
        project_id=project_id,
        workflow_id="wf-test",
        workflow_run_id="run-test",
        status="completed",
        findings_total=1,
    )
    session.add(a)
    await session.flush()
    return a


async def _seed_finding(session, audit_run_id, project_id):
    """Create a finding for the given audit run."""
    f = Finding(
        audit_run_id=audit_run_id,
        project_id=project_id,
        fingerprint="abc123",
        rule_id="SEC-001",
        file_path="src/main.py",
        severity="high",
        title="Test Finding",
        description="A test finding",
        status="open",
    )
    session.add(f)
    await session.flush()
    return f


# ── export_user_data ──


class TestExportUserData:

    async def test_export_empty(self, session):
        result = await export_user_data(user_id=uuid.uuid4(), session=session)
        assert result.projects == []
        assert result.audit_runs == []
        assert result.findings == []
        assert result.total_records == 0

    async def test_export_with_data(self, session):
        proj = await _seed_project(session)
        audit = await _seed_audit(session, proj.id)
        await _seed_finding(session, audit.id, proj.id)

        result = await export_user_data(user_id=USER_ID, session=session)
        assert len(result.projects) == 1
        assert result.projects[0]["name"] == "GDPR Project"
        assert len(result.audit_runs) == 1
        assert len(result.findings) == 1
        assert result.total_records == 3

    async def test_export_all_no_user_filter(self, session):
        await _seed_project(session)
        result = await export_user_data(user_id=None, session=session)
        assert len(result.projects) >= 1

    async def test_export_excludes_deleted(self, session):
        from datetime import datetime, timezone
        p = Project(
            name="Deleted",
            created_by=USER_ID,
            status="deleted",
            deleted_at=datetime.now(timezone.utc),
        )
        session.add(p)
        await session.flush()

        result = await export_user_data(user_id=USER_ID, session=session)
        assert all(proj["name"] != "Deleted" for proj in result.projects)

    async def test_export_timestamp_present(self, session):
        result = await export_user_data(user_id=USER_ID, session=session)
        assert result.export_timestamp is not None
        assert result.user_id == USER_ID


# ── delete_user_data ──


class TestDeleteUserData:

    async def test_delete_no_data(self, session):
        uid = uuid.uuid4()
        result = await delete_user_data(user_id=uid, session=session)
        assert result.projects_deleted == 0
        assert result.total_records_deleted == 0

    async def test_delete_soft_deletes(self, session):
        proj = await _seed_project(session, user_id=USER_ID)
        result = await delete_user_data(user_id=USER_ID, session=session)
        assert result.projects_deleted == 1
        assert result.deletion_timestamp is not None

        # Verify project is soft-deleted
        refreshed = await session.get(Project, proj.id)
        assert refreshed.deleted_at is not None
        assert refreshed.status == "deleted"

    async def test_delete_counts_audits_findings(self, session):
        proj = await _seed_project(session, user_id=USER_ID)
        audit = await _seed_audit(session, proj.id)
        await _seed_finding(session, audit.id, proj.id)

        result = await delete_user_data(user_id=USER_ID, session=session)
        assert result.projects_deleted == 1
        assert result.audit_runs_deleted == 1
        assert result.findings_deleted == 1
        assert result.total_records_deleted == 3

    async def test_delete_user_id_returned(self, session):
        result = await delete_user_data(user_id=USER_ID, session=session)
        assert result.user_id == USER_ID


# ── get_retention_policy ──


class TestGetRetentionPolicy:

    async def test_policy_values(self):
        result = await get_retention_policy()
        assert result.project_retention_days == 2555
        assert result.audit_run_retention_days == 1095
        assert result.finding_retention_days == 1095
        assert result.soft_delete_grace_period_days == 30

    async def test_policy_has_timestamp(self):
        result = await get_retention_policy()
        assert result.last_updated is not None
