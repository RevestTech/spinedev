"""POST /api/audits/reconcile-stale-queued (master-only)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import update

from tron.domain.models import AuditRun, Project


@pytest.fixture
async def reconcile_db(sqlite_db):
    async with sqlite_db() as session:
        session.add(
            Project(
                id=uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc"),
                name="Reconcile Project",
                repo_url="https://example.com/r.git",
            )
        )
        await session.commit()
    return sqlite_db


@pytest.fixture
async def reconcile_client_master(test_app, reconcile_db, auth_headers):
    from tron.infra.db.session import get_session

    async def _override_session():
        async with reconcile_db() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    test_app.dependency_overrides[get_session] = _override_session

    transport = ASGITransport(app=test_app)
    async with AsyncClient(
        transport=transport, base_url="http://test", headers=auth_headers,
    ) as client:
        yield client

    test_app.dependency_overrides.clear()


@pytest.fixture
async def reconcile_client_scoped(test_app, reconcile_db):
    """Scoped key (audits only) — must not call master-only reconcile."""
    from httpx import ASGITransport, AsyncClient
    from tron.domain.models import ApiKey
    from tron.infra.db.session import get_session
    import hashlib

    plain = "scoped-reconcile-test-key-zzzzzzzz"
    kh = hashlib.sha256(plain.encode()).hexdigest()
    async with reconcile_db() as session:
        session.add(
            ApiKey(
                id=uuid.uuid4(),
                label="reconcile-test",
                key_hash=kh,
                active=True,
                scopes=["audits"],
            )
        )
        await session.commit()

    async def _override_session():
        async with reconcile_db() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    test_app.dependency_overrides[get_session] = _override_session

    transport = ASGITransport(app=test_app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-API-Key": plain},
    ) as client:
        yield client

    test_app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_reconcile_stale_queued_marks_failed(reconcile_client_master, reconcile_db):
    aid = uuid.uuid4()
    pid = uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
    async with reconcile_db() as session:
        session.add(
            AuditRun(
                id=aid,
                project_id=pid,
                workflow_id="audit-test",
                workflow_run_id="run-1",
                status="queued",
                progress=0,
            )
        )
        await session.commit()
        old = datetime.now(timezone.utc) - timedelta(hours=4)
        await session.execute(
            update(AuditRun).where(AuditRun.id == aid).values(created_at=old)
        )
        await session.commit()

    r = await reconcile_client_master.post(
        "/api/audits/reconcile-stale-queued",
        json={"older_than_minutes": 60, "dry_run": False},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["older_than_minutes"] == 60
    assert str(aid) in data["audit_run_ids"]
    assert data["updated"] >= 1

    r2 = await reconcile_client_master.get(f"/api/audits/{aid}")
    assert r2.status_code == 200
    assert r2.json()["status"] == "failed"


@pytest.mark.asyncio
async def test_reconcile_stale_queued_dry_run(reconcile_client_master, reconcile_db):
    aid = uuid.uuid4()
    pid = uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
    async with reconcile_db() as session:
        session.add(
            AuditRun(
                id=aid,
                project_id=pid,
                workflow_id="audit-dry",
                workflow_run_id="run-d",
                status="queued",
                progress=0,
            )
        )
        await session.commit()
        old = datetime.now(timezone.utc) - timedelta(hours=2)
        await session.execute(
            update(AuditRun).where(AuditRun.id == aid).values(created_at=old)
        )
        await session.commit()

    r = await reconcile_client_master.post(
        "/api/audits/reconcile-stale-queued",
        json={"older_than_minutes": 30, "dry_run": True},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["dry_run"] is True
    assert data["updated"] == 0
    assert str(aid) in data["audit_run_ids"]

    r2 = await reconcile_client_master.get(f"/api/audits/{aid}")
    assert r2.json()["status"] == "queued"


@pytest.mark.asyncio
async def test_reconcile_stale_queued_forbidden_for_scoped_key(reconcile_client_scoped):
    r = await reconcile_client_scoped.post(
        "/api/audits/reconcile-stale-queued",
        json={"dry_run": True},
    )
    assert r.status_code == 403
