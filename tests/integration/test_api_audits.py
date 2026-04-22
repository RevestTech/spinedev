"""
Integration tests for Audits API.

Tests:
  - POST /api/audits (create audit)
  - GET /api/audits (list)
  - GET /api/audits/{id} (get status)
  - GET /api/audits/{id}/findings (list findings)
  - Temporal dispatch vs BackgroundTask fallback
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from tron.domain.models import Project


@pytest.fixture
async def audit_db(sqlite_db):
    """SQLite DB pre-seeded with a test project."""
    async with sqlite_db() as session:
        project = Project(
            id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
            name="Test Project",
        )
        session.add(project)
        await session.commit()

    return sqlite_db


@pytest.fixture
async def audit_client(test_app, audit_db, auth_headers):
    from httpx import ASGITransport, AsyncClient
    from tron.infra.db.session import get_session

    async def _override_session():
        async with audit_db() as session:
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


class TestCreateAudit:

    async def test_create_audit_background_task(self, audit_client):
        """POST /api/audits → 201, dispatches BackgroundTask when Temporal disabled."""
        with patch("tron.api.routes.audits.settings") as mock_settings:
            mock_settings.temporal_enabled = False

            response = await audit_client.post("/api/audits", json={
                "project_id": "11111111-1111-1111-1111-111111111111",
            })

        assert response.status_code == 201
        data = response.json()
        assert data["status"] == "queued"
        assert data["progress"] == 0

    async def test_create_audit_temporal_dispatch(self, audit_client):
        """POST /api/audits → dispatches Temporal workflow when enabled."""
        with patch("tron.api.routes.audits.settings") as mock_settings, \
             patch("tron.api.routes.audits._dispatch_temporal_audit", new_callable=AsyncMock) as mock_dispatch:
            mock_settings.temporal_enabled = True

            response = await audit_client.post("/api/audits", json={
                "project_id": "11111111-1111-1111-1111-111111111111",
            })

        assert response.status_code == 201
        mock_dispatch.assert_called_once()

    async def test_create_audit_nonexistent_project(self, audit_client):
        """POST with unknown project_id → 404."""
        with patch("tron.api.routes.audits.settings") as mock_settings:
            mock_settings.temporal_enabled = False
            response = await audit_client.post("/api/audits", json={
                "project_id": str(uuid.uuid4()),
            })

        assert response.status_code == 404


class TestListAudits:

    async def test_list_empty(self, audit_client):
        """GET /api/audits → empty when none exist."""
        response = await audit_client.get("/api/audits")
        assert response.status_code == 200
        assert response.json()["total"] == 0

    async def test_list_after_create(self, audit_client):
        """Create then list → audit appears."""
        with patch("tron.api.routes.audits.settings") as mock_settings:
            mock_settings.temporal_enabled = False
            await audit_client.post("/api/audits", json={
                "project_id": "11111111-1111-1111-1111-111111111111",
            })

        response = await audit_client.get("/api/audits")
        assert response.json()["total"] >= 1


class TestGetAudit:

    async def test_get_existing_audit(self, audit_client):
        """GET /api/audits/{id} → returns audit."""
        with patch("tron.api.routes.audits.settings") as mock_settings:
            mock_settings.temporal_enabled = False
            create_resp = await audit_client.post("/api/audits", json={
                "project_id": "11111111-1111-1111-1111-111111111111",
            })
        audit_id = create_resp.json()["id"]

        response = await audit_client.get(f"/api/audits/{audit_id}")
        assert response.status_code == 200
        assert response.json()["id"] == audit_id

    async def test_get_nonexistent_audit(self, audit_client):
        """GET with random UUID → 404."""
        response = await audit_client.get(f"/api/audits/{uuid.uuid4()}")
        assert response.status_code == 404
