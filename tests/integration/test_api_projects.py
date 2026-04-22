"""
Integration tests for Projects API.

Tests:
  - POST /api/projects (create)
  - GET /api/projects (list)
  - GET /api/projects/{id} (get)
  - PUT /api/projects/{id} (update)
  - DELETE /api/projects/{id} (soft-delete)
  - Auth required (401/403)

Uses SQLite in-memory for fast testing.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Test Database Setup ───────────────────────────────────────────────


@pytest.fixture
async def project_client(test_app, sqlite_db, auth_headers):
    """API client with DB session overridden to use test SQLite."""
    from httpx import ASGITransport, AsyncClient
    from tron.infra.db.session import get_session

    async def _override_session():
        async with sqlite_db() as session:
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
        headers=auth_headers,
    ) as client:
        yield client

    test_app.dependency_overrides.clear()


# ── Tests ─────────────────────────────────────────────────────────────


class TestCreateProject:

    async def test_create_project(self, project_client):
        """POST /api/projects → 201 with project data."""
        response = await project_client.post("/api/projects", json={
            "name": "Test Project",
            "description": "A test project",
            "repo_url": "https://github.com/test/repo",
            "default_branch": "main",
        })

        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Test Project"
        assert data["repo_url"] == "https://github.com/test/repo"
        assert "id" in data

    async def test_create_project_minimal(self, project_client):
        """POST with only name → 201."""
        response = await project_client.post("/api/projects", json={
            "name": "Minimal Project",
        })

        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Minimal Project"
        assert data["default_branch"] == "main"

    async def test_create_project_no_name_fails(self, project_client):
        """POST without name → 422."""
        response = await project_client.post("/api/projects", json={
            "description": "No name",
        })

        assert response.status_code == 422


class TestListProjects:

    async def test_list_empty(self, project_client):
        """GET /api/projects → empty list when no projects."""
        response = await project_client.get("/api/projects")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["items"] == []

    async def test_list_after_create(self, project_client):
        """Create then list → contains the project."""
        await project_client.post("/api/projects", json={"name": "P1"})
        await project_client.post("/api/projects", json={"name": "P2"})

        response = await project_client.get("/api/projects")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert len(data["items"]) == 2


class TestGetProject:

    async def test_get_existing_project(self, project_client):
        """GET /api/projects/{id} → returns project."""
        create_resp = await project_client.post("/api/projects", json={
            "name": "Get Test",
        })
        project_id = create_resp.json()["id"]

        response = await project_client.get(f"/api/projects/{project_id}")

        assert response.status_code == 200
        assert response.json()["name"] == "Get Test"

    async def test_get_nonexistent_project(self, project_client):
        """GET with random UUID → 404."""
        fake_id = str(uuid.uuid4())
        response = await project_client.get(f"/api/projects/{fake_id}")
        assert response.status_code == 404


class TestUpdateProject:

    async def test_update_project_name(self, project_client):
        """PUT /api/projects/{id} → updates fields."""
        create_resp = await project_client.post("/api/projects", json={
            "name": "Original",
        })
        project_id = create_resp.json()["id"]

        response = await project_client.put(f"/api/projects/{project_id}", json={
            "name": "Updated",
        })

        assert response.status_code == 200
        assert response.json()["name"] == "Updated"


class TestDeleteProject:

    async def test_soft_delete(self, project_client):
        """DELETE /api/projects/{id} → soft-deletes (still in DB but filtered)."""
        create_resp = await project_client.post("/api/projects", json={
            "name": "To Delete",
        })
        project_id = create_resp.json()["id"]

        response = await project_client.delete(f"/api/projects/{project_id}")
        assert response.status_code == 204

        # Should not appear in list
        list_resp = await project_client.get("/api/projects")
        assert list_resp.json()["total"] == 0


class TestAuthRequired:

    async def test_no_api_key_returns_401(self, test_app):
        """Request without X-API-Key → 401."""
        from httpx import ASGITransport, AsyncClient

        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/projects")

        assert response.status_code == 401

    async def test_wrong_api_key_returns_403(self, test_app):
        """Request with wrong key → 403."""
        from httpx import ASGITransport, AsyncClient

        transport = ASGITransport(app=test_app)
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
            headers={"X-API-Key": "wrong-key"},
        ) as client:
            response = await client.get("/api/projects")

        assert response.status_code == 403
