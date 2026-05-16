"""Integration tests for GET /api/workflow-runs."""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from tron.domain.models import AuditRun, Project


@pytest.fixture
async def wf_db(sqlite_db):
    async with sqlite_db() as session:
        pid = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
        session.add(
            Project(
                id=pid,
                name="WF Project",
                repo_url="https://github.com/test/wf",
            )
        )
        session.add(
            AuditRun(
                project_id=pid,
                workflow_id="background-audit-11111111-1111-1111-1111-111111111111",
                workflow_run_id="background-11111111-1111-1111-1111-111111111111",
                branch="main",
                trigger_type="manual",
                status="completed",
                progress=100,
                findings_total=0,
                findings_critical=0,
                findings_high=0,
                findings_medium=0,
                findings_low=0,
            )
        )
        await session.commit()
    return sqlite_db


@pytest.fixture
async def wf_client(test_app, wf_db, auth_headers):
    from tron.infra.db.session import get_session

    async def _override_session():
        async with wf_db() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    test_app.dependency_overrides[get_session] = _override_session
    transport = ASGITransport(app=test_app)
    async with AsyncClient(
        transport=transport, base_url="http://test", headers=auth_headers
    ) as client:
        yield client
    test_app.dependency_overrides.clear()


@pytest.fixture
async def wf_client_no_auth(test_app, wf_db):
    from tron.infra.db.session import get_session

    async def _override_session():
        async with wf_db() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    test_app.dependency_overrides[get_session] = _override_session
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    test_app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_workflow_runs_lists_audit_metadata(wf_client):
    r = await wf_client.get("/api/workflow-runs")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] >= 1
    assert len(data["items"]) >= 1
    row = data["items"][0]
    assert row["project_name"] == "WF Project"
    assert row["workflow_id"].startswith("background-audit-")
    assert row["workflow_run_id"].startswith("background-")


@pytest.mark.asyncio
async def test_workflow_runs_requires_api_key(wf_client_no_auth):
    r = await wf_client_no_auth.get("/api/workflow-runs")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_workflow_runs_status_filter(wf_client):
    r = await wf_client.get("/api/workflow-runs", params={"status": "completed"})
    assert r.status_code == 200
    for item in r.json()["items"]:
        assert item["status"] == "completed"


@pytest.mark.asyncio
async def test_workflow_runs_wrong_scope_forbidden(test_app, wf_db, fake_secrets):
    """Scoped key without ``workflows`` cannot list workflow runs."""
    import hashlib
    from httpx import ASGITransport, AsyncClient
    from tron.domain.models import ApiKey
    from tron.infra.db.session import get_session

    plain = "tron_test_scope_projects_only"
    h = hashlib.sha256(plain.encode()).hexdigest()
    async with wf_db() as session:
        session.add(
            ApiKey(
                label="test",
                key_hash=h,
                scopes=["projects"],
                active=True,
            )
        )
        await session.commit()

    async def _override_session():
        async with wf_db() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    test_app.dependency_overrides[get_session] = _override_session
    test_app.state.secrets = fake_secrets
    transport = ASGITransport(app=test_app)
    try:
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
            headers={"X-API-Key": plain},
        ) as client:
            r = await client.get("/api/workflow-runs")
        assert r.status_code == 403
    finally:
        test_app.dependency_overrides.clear()
