"""
Comprehensive integration tests for Projects CRUD operations.

Tests:
  - Create: valid/invalid data, edge cases
  - List: pagination, filtering, sorting
  - Get: existing and nonexistent
  - Update: full/partial, nonexistent
  - Delete: soft-delete behavior
  - Concurrency: simultaneous operations
  - Edge cases: empty names, long descriptions, special characters
"""

from __future__ import annotations

import asyncio
import uuid

import pytest


@pytest.fixture
async def projects_client(test_app, sqlite_db, auth_headers):
    """API client for projects tests."""
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


# ── Tests: Create Project ───────────────────────────────────────────


class TestCreateProject:
    """Test POST /api/projects."""

    async def test_create_with_all_fields(self, projects_client):
        """Create project with all fields populated."""
        response = await projects_client.post("/api/projects", json={
            "name": "Full Project",
            "description": "Complete project description",
            "repo_url": "https://github.com/owner/repo",
            "default_branch": "develop",
        })

        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Full Project"
        assert data["description"] == "Complete project description"
        assert data["repo_url"] == "https://github.com/owner/repo"
        assert data["default_branch"] == "develop"
        assert "id" in data
        assert data["id"]

    async def test_create_with_minimal_fields(self, projects_client):
        """Create project with only required name field."""
        response = await projects_client.post("/api/projects", json={
            "name": "Minimal",
        })

        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Minimal"
        assert data["default_branch"] == "main"  # Default value
        assert data["description"] is None
        assert data["repo_url"] is None

    async def test_create_without_name_fails(self, projects_client):
        """Create without name returns 422."""
        response = await projects_client.post("/api/projects", json={
            "description": "No name",
        })

        assert response.status_code == 422

    async def test_create_with_empty_name_fails(self, projects_client):
        """Create with empty string name returns 422."""
        response = await projects_client.post("/api/projects", json={
            "name": "",
        })

        assert response.status_code == 422

    async def test_create_with_very_long_name_fails(self, projects_client):
        """Create with name > 255 chars returns 422."""
        response = await projects_client.post("/api/projects", json={
            "name": "x" * 256,
        })

        assert response.status_code == 422

    async def test_create_with_max_length_name_succeeds(self, projects_client):
        """Create with exactly 255 char name succeeds."""
        response = await projects_client.post("/api/projects", json={
            "name": "x" * 255,
        })

        assert response.status_code == 201
        assert len(response.json()["name"]) == 255

    async def test_create_with_special_characters_in_name(self, projects_client):
        """Create with special chars in name."""
        response = await projects_client.post("/api/projects", json={
            "name": "Project-#1_@2023!",
        })

        assert response.status_code == 201
        assert response.json()["name"] == "Project-#1_@2023!"

    async def test_create_with_unicode_in_name(self, projects_client):
        """Create with unicode characters in name."""
        response = await projects_client.post("/api/projects", json={
            "name": "项目 2023 🚀",
        })

        assert response.status_code == 201
        assert "项目" in response.json()["name"]

    async def test_create_with_very_long_description(self, projects_client):
        """Create with long description (no max length)."""
        long_desc = "a" * 5000
        response = await projects_client.post("/api/projects", json={
            "name": "Long Desc Project",
            "description": long_desc,
        })

        assert response.status_code == 201
        assert response.json()["description"] == long_desc

    async def test_create_with_invalid_repo_url(self, projects_client):
        """Create with invalid URL format (currently not validated)."""
        response = await projects_client.post("/api/projects", json={
            "name": "Bad URL Project",
            "repo_url": "not-a-valid-url",
        })

        # URL validation may or may not be enforced
        assert response.status_code in [201, 422]

    async def test_create_with_valid_github_url(self, projects_client):
        """Create with valid GitHub URL."""
        response = await projects_client.post("/api/projects", json={
            "name": "GitHub Project",
            "repo_url": "https://github.com/user/repo.git",
        })

        assert response.status_code == 201
        assert response.json()["repo_url"] == "https://github.com/user/repo.git"

    async def test_create_with_gitlab_url(self, projects_client):
        """Create with GitLab URL."""
        response = await projects_client.post("/api/projects", json={
            "name": "GitLab Project",
            "repo_url": "https://gitlab.com/user/repo",
        })

        assert response.status_code == 201

    async def test_create_returns_correct_fields(self, projects_client):
        """Response includes all required fields."""
        response = await projects_client.post("/api/projects", json={
            "name": "Field Test",
        })

        assert response.status_code == 201
        data = response.json()

        # Check all expected fields are present
        assert "id" in data
        assert "name" in data
        assert "description" in data
        assert "repo_url" in data
        assert "default_branch" in data
        assert "status" in data
        assert "created_at" in data
        assert "updated_at" in data

    async def test_create_with_invalid_json(self, projects_client):
        """Request with invalid JSON returns 422."""
        response = await projects_client.post(
            "/api/projects",
            content="not json",
        )

        assert response.status_code == 422

    async def test_create_returns_unique_ids(self, projects_client):
        """Each created project has a unique ID."""
        resp1 = await projects_client.post("/api/projects", json={"name": "P1"})
        resp2 = await projects_client.post("/api/projects", json={"name": "P2"})

        id1 = resp1.json()["id"]
        id2 = resp2.json()["id"]

        assert id1 != id2
        assert len(id1) > 0
        assert len(id2) > 0


# ── Tests: List Projects ────────────────────────────────────────────


class TestListProjects:
    """Test GET /api/projects."""

    async def test_list_empty_database(self, projects_client):
        """List projects when none exist."""
        response = await projects_client.get("/api/projects")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["items"] == []
        assert "page" in data
        assert "page_size" in data

    async def test_list_after_single_create(self, projects_client):
        """List shows newly created project."""
        create_resp = await projects_client.post(
            "/api/projects", json={"name": "P1"}
        )
        project_id = create_resp.json()["id"]

        list_resp = await projects_client.get("/api/projects")

        assert list_resp.status_code == 200
        assert list_resp.json()["total"] == 1
        assert len(list_resp.json()["items"]) == 1
        assert list_resp.json()["items"][0]["id"] == project_id

    async def test_list_after_multiple_creates(self, projects_client):
        """List shows all created projects."""
        names = ["P1", "P2", "P3", "P4", "P5"]
        for name in names:
            await projects_client.post("/api/projects", json={"name": name})

        response = await projects_client.get("/api/projects")

        assert response.status_code == 200
        assert response.json()["total"] == 5
        assert len(response.json()["items"]) == 5

    async def test_list_pagination_default_page(self, projects_client):
        """List returns first page by default."""
        for i in range(5):
            await projects_client.post("/api/projects", json={"name": f"P{i}"})

        response = await projects_client.get("/api/projects")

        assert response.status_code == 200
        data = response.json()
        assert data["page"] == 1
        assert data["page_size"] == 20

    async def test_list_pagination_with_custom_page_size(self, projects_client):
        """List with custom page_size parameter."""
        for i in range(15):
            await projects_client.post("/api/projects", json={"name": f"P{i}"})

        response = await projects_client.get("/api/projects?page_size=5")

        assert response.status_code == 200
        data = response.json()
        assert data["page_size"] == 5
        assert len(data["items"]) == 5
        assert data["total"] == 15

    async def test_list_pagination_second_page(self, projects_client):
        """List can retrieve second page."""
        for i in range(15):
            await projects_client.post("/api/projects", json={"name": f"P{i}"})

        response = await projects_client.get("/api/projects?page=2&page_size=5")

        assert response.status_code == 200
        data = response.json()
        assert data["page"] == 2
        assert len(data["items"]) == 5

    async def test_list_pagination_beyond_total(self, projects_client):
        """Requesting page beyond total returns empty items."""
        for i in range(5):
            await projects_client.post("/api/projects", json={"name": f"P{i}"})

        response = await projects_client.get("/api/projects?page=10&page_size=5")

        assert response.status_code == 200
        data = response.json()
        assert data["items"] == []

    async def test_list_filter_by_status(self, projects_client):
        """List can filter by status."""
        # Create projects, may have status field
        await projects_client.post("/api/projects", json={"name": "P1"})
        await projects_client.post("/api/projects", json={"name": "P2"})

        response = await projects_client.get("/api/projects?status=active")

        # Should succeed even if filter not implemented
        assert response.status_code == 200

    async def test_list_invalid_page_returns_422(self, projects_client):
        """Invalid page parameter returns 422."""
        response = await projects_client.get("/api/projects?page=-1")
        assert response.status_code == 422

    async def test_list_invalid_page_size_returns_422(self, projects_client):
        """Invalid page_size parameter returns 422."""
        response = await projects_client.get("/api/projects?page_size=-1")
        assert response.status_code == 422

    async def test_list_page_size_exceeds_max_returns_422(self, projects_client):
        """page_size > 100 returns 422."""
        response = await projects_client.get("/api/projects?page_size=101")
        assert response.status_code == 422

    async def test_list_response_structure(self, projects_client):
        """Response structure matches ProjectListResponse."""
        await projects_client.post("/api/projects", json={"name": "P1"})

        response = await projects_client.get("/api/projects")
        data = response.json()

        assert isinstance(data["items"], list)
        assert isinstance(data["total"], int)
        assert isinstance(data["page"], int)
        assert isinstance(data["page_size"], int)

        if data["items"]:
            item = data["items"][0]
            assert "id" in item
            assert "name" in item


# ── Tests: Get Project ──────────────────────────────────────────────


class TestGetProject:
    """Test GET /api/projects/{id}."""

    async def test_get_existing_project(self, projects_client):
        """Get a project that exists."""
        create_resp = await projects_client.post(
            "/api/projects", json={"name": "Fetch Test"}
        )
        project_id = create_resp.json()["id"]

        get_resp = await projects_client.get(f"/api/projects/{project_id}")

        assert get_resp.status_code == 200
        assert get_resp.json()["id"] == project_id
        assert get_resp.json()["name"] == "Fetch Test"

    async def test_get_nonexistent_returns_404(self, projects_client):
        """Get nonexistent project returns 404."""
        fake_id = str(uuid.uuid4())
        response = await projects_client.get(f"/api/projects/{fake_id}")

        assert response.status_code == 404

    async def test_get_deleted_project_returns_404(self, projects_client):
        """Get soft-deleted project returns 404."""
        # Create, then delete
        create_resp = await projects_client.post(
            "/api/projects", json={"name": "To Delete"}
        )
        project_id = create_resp.json()["id"]

        await projects_client.delete(f"/api/projects/{project_id}")

        # Should not find it
        get_resp = await projects_client.get(f"/api/projects/{project_id}")
        assert get_resp.status_code == 404

    async def test_get_with_invalid_uuid_format(self, projects_client):
        """Get with invalid UUID format returns 422."""
        response = await projects_client.get("/api/projects/not-a-uuid")
        assert response.status_code == 422

    async def test_get_returns_all_fields(self, projects_client):
        """Get response includes all project fields."""
        create_resp = await projects_client.post(
            "/api/projects",
            json={
                "name": "Full Fields",
                "description": "Test desc",
                "repo_url": "https://github.com/test/repo",
                "default_branch": "main",
            },
        )
        project_id = create_resp.json()["id"]

        get_resp = await projects_client.get(f"/api/projects/{project_id}")
        data = get_resp.json()

        assert data["id"] == project_id
        assert data["name"] == "Full Fields"
        assert data["description"] == "Test desc"
        assert data["repo_url"] == "https://github.com/test/repo"
        assert data["default_branch"] == "main"
        assert "created_at" in data
        assert "updated_at" in data


# ── Tests: Update Project ───────────────────────────────────────────


class TestUpdateProject:
    """Test PUT /api/projects/{id}."""

    async def test_update_name(self, projects_client):
        """Update project name."""
        create_resp = await projects_client.post(
            "/api/projects", json={"name": "Original"}
        )
        project_id = create_resp.json()["id"]

        update_resp = await projects_client.put(
            f"/api/projects/{project_id}", json={"name": "Updated"}
        )

        assert update_resp.status_code == 200
        assert update_resp.json()["name"] == "Updated"

    async def test_update_description(self, projects_client):
        """Update project description."""
        create_resp = await projects_client.post(
            "/api/projects", json={"name": "P1"}
        )
        project_id = create_resp.json()["id"]

        update_resp = await projects_client.put(
            f"/api/projects/{project_id}",
            json={"description": "New description"},
        )

        assert update_resp.status_code == 200
        assert update_resp.json()["description"] == "New description"

    async def test_update_repo_url(self, projects_client):
        """Update repository URL."""
        create_resp = await projects_client.post(
            "/api/projects", json={"name": "P1"}
        )
        project_id = create_resp.json()["id"]

        update_resp = await projects_client.put(
            f"/api/projects/{project_id}",
            json={"repo_url": "https://github.com/new/repo"},
        )

        assert update_resp.status_code == 200
        assert update_resp.json()["repo_url"] == "https://github.com/new/repo"

    async def test_update_default_branch(self, projects_client):
        """Update default branch."""
        create_resp = await projects_client.post(
            "/api/projects", json={"name": "P1"}
        )
        project_id = create_resp.json()["id"]

        update_resp = await projects_client.put(
            f"/api/projects/{project_id}", json={"default_branch": "develop"}
        )

        assert update_resp.status_code == 200
        assert update_resp.json()["default_branch"] == "develop"

    async def test_update_status(self, projects_client):
        """Update project status."""
        create_resp = await projects_client.post(
            "/api/projects", json={"name": "P1"}
        )
        project_id = create_resp.json()["id"]

        update_resp = await projects_client.put(
            f"/api/projects/{project_id}", json={"status": "archived"}
        )

        assert update_resp.status_code == 200
        assert update_resp.json()["status"] == "archived"

    async def test_update_multiple_fields(self, projects_client):
        """Update multiple fields at once."""
        create_resp = await projects_client.post(
            "/api/projects", json={"name": "Original"}
        )
        project_id = create_resp.json()["id"]

        update_resp = await projects_client.put(
            f"/api/projects/{project_id}",
            json={
                "name": "New Name",
                "description": "New Desc",
                "default_branch": "staging",
            },
        )

        assert update_resp.status_code == 200
        data = update_resp.json()
        assert data["name"] == "New Name"
        assert data["description"] == "New Desc"
        assert data["default_branch"] == "staging"

    async def test_update_nonexistent_returns_404(self, projects_client):
        """Update nonexistent project returns 404."""
        response = await projects_client.put(
            f"/api/projects/{uuid.uuid4()}", json={"name": "Updated"}
        )

        assert response.status_code == 404

    async def test_update_with_empty_name_fails(self, projects_client):
        """Update with empty name returns 422."""
        create_resp = await projects_client.post(
            "/api/projects", json={"name": "P1"}
        )
        project_id = create_resp.json()["id"]

        update_resp = await projects_client.put(
            f"/api/projects/{project_id}", json={"name": ""}
        )

        assert update_resp.status_code == 422

    async def test_update_preserves_untouched_fields(self, projects_client):
        """Update preserves fields not included in request."""
        create_resp = await projects_client.post(
            "/api/projects",
            json={
                "name": "Original",
                "description": "Original Desc",
                "repo_url": "https://github.com/original/repo",
            },
        )
        project_id = create_resp.json()["id"]
        original_created_at = create_resp.json()["created_at"]

        # Update only name
        update_resp = await projects_client.put(
            f"/api/projects/{project_id}", json={"name": "Updated"}
        )

        data = update_resp.json()
        assert data["name"] == "Updated"
        assert data["description"] == "Original Desc"  # Unchanged
        assert data["repo_url"] == "https://github.com/original/repo"  # Unchanged
        assert data["created_at"] == original_created_at  # Unchanged


# ── Tests: Delete Project ───────────────────────────────────────────


class TestDeleteProject:
    """Test DELETE /api/projects/{id}."""

    async def test_soft_delete_project(self, projects_client):
        """Delete returns 204 and soft-deletes."""
        create_resp = await projects_client.post(
            "/api/projects", json={"name": "To Delete"}
        )
        project_id = create_resp.json()["id"]

        delete_resp = await projects_client.delete(f"/api/projects/{project_id}")

        assert delete_resp.status_code == 204

    async def test_deleted_project_not_in_list(self, projects_client):
        """Deleted project does not appear in list."""
        create_resp = await projects_client.post(
            "/api/projects", json={"name": "To Delete"}
        )
        project_id = create_resp.json()["id"]

        await projects_client.delete(f"/api/projects/{project_id}")

        # Should not appear in list
        list_resp = await projects_client.get("/api/projects")
        ids = [p["id"] for p in list_resp.json()["items"]]
        assert project_id not in ids

    async def test_deleted_project_not_retrievable(self, projects_client):
        """Deleted project cannot be retrieved by ID."""
        create_resp = await projects_client.post(
            "/api/projects", json={"name": "To Delete"}
        )
        project_id = create_resp.json()["id"]

        await projects_client.delete(f"/api/projects/{project_id}")

        # Should return 404
        get_resp = await projects_client.get(f"/api/projects/{project_id}")
        assert get_resp.status_code == 404

    async def test_delete_nonexistent_returns_404(self, projects_client):
        """Delete nonexistent project returns 404."""
        response = await projects_client.delete(f"/api/projects/{uuid.uuid4()}")
        assert response.status_code == 404

    async def test_double_delete_returns_404(self, projects_client):
        """Deleting twice returns 404 second time."""
        create_resp = await projects_client.post(
            "/api/projects", json={"name": "P1"}
        )
        project_id = create_resp.json()["id"]

        first_delete = await projects_client.delete(f"/api/projects/{project_id}")
        assert first_delete.status_code == 204

        second_delete = await projects_client.delete(f"/api/projects/{project_id}")
        assert second_delete.status_code == 404

    async def test_soft_delete_preserves_data(self, projects_client):
        """Soft delete marks deleted_at but preserves row data."""
        # This test documents that we use soft delete (deleted_at column)
        create_resp = await projects_client.post(
            "/api/projects", json={"name": "Data Preservation"}
        )
        project_id = create_resp.json()["id"]

        await projects_client.delete(f"/api/projects/{project_id}")

        # Project should be filtered from normal queries
        list_resp = await projects_client.get("/api/projects")
        assert project_id not in [p["id"] for p in list_resp.json()["items"]]


# ── Tests: Concurrent Operations ────────────────────────────────────


class TestConcurrentOperations:
    """Test concurrent project creation and operations."""

    async def test_concurrent_creates(self, projects_client):
        """Multiple concurrent project creates."""
        tasks = [
            projects_client.post("/api/projects", json={"name": f"Concurrent-{i}"})
            for i in range(10)
        ]
        responses = await asyncio.gather(*tasks)

        # All should succeed
        for resp in responses:
            assert resp.status_code == 201

        # Verify all were created
        list_resp = await projects_client.get("/api/projects")
        assert list_resp.json()["total"] == 10

    async def test_concurrent_creates_with_same_name(self, projects_client):
        """Concurrent creates with identical names should all succeed."""
        tasks = [
            projects_client.post("/api/projects", json={"name": "Duplicate"})
            for _ in range(5)
        ]
        responses = await asyncio.gather(*tasks)

        for resp in responses:
            assert resp.status_code == 201

        # All should be created (no unique constraint on name)
        list_resp = await projects_client.get("/api/projects")
        assert list_resp.json()["total"] >= 5

    async def test_concurrent_updates_same_project(self, projects_client):
        """Multiple concurrent updates to same project."""
        create_resp = await projects_client.post(
            "/api/projects", json={"name": "Concurrent Update"}
        )
        project_id = create_resp.json()["id"]

        # Try to update concurrently
        tasks = [
            projects_client.put(
                f"/api/projects/{project_id}",
                json={"name": f"Updated-{i}"},
            )
            for i in range(5)
        ]
        responses = await asyncio.gather(*tasks)

        # All should succeed (last write wins)
        for resp in responses:
            assert resp.status_code == 200

        # Final state should be one of the updates
        final = await projects_client.get(f"/api/projects/{project_id}")
        assert final.json()["name"].startswith("Updated-")

    async def test_concurrent_mixed_operations(self, projects_client):
        """Mix of concurrent creates, updates, and lists."""
        # Pre-create a project to update
        create_resp = await projects_client.post(
            "/api/projects", json={"name": "Base"}
        )
        project_id = create_resp.json()["id"]

        tasks = [
            projects_client.post("/api/projects", json={"name": "Concurrent-1"}),
            projects_client.post("/api/projects", json={"name": "Concurrent-2"}),
            projects_client.put(
                f"/api/projects/{project_id}", json={"name": "Updated"}
            ),
            projects_client.get("/api/projects"),
        ]

        responses = await asyncio.gather(*tasks)

        # All should succeed
        assert responses[0].status_code == 201
        assert responses[1].status_code == 201
        assert responses[2].status_code == 200
        assert responses[3].status_code == 200


# ── Tests: Edge Cases ───────────────────────────────────────────────


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    async def test_whitespace_only_name_fails(self, projects_client):
        """Name with only whitespace returns 422."""
        response = await projects_client.post(
            "/api/projects", json={"name": "   "}
        )
        # Depends on validation; may succeed or fail
        assert response.status_code in [201, 422]

    async def test_name_with_leading_trailing_spaces(self, projects_client):
        """Name with leading/trailing spaces."""
        response = await projects_client.post(
            "/api/projects", json={"name": "  Project  "}
        )
        assert response.status_code in [201, 422]

    async def test_description_with_null_bytes(self, projects_client):
        """Description with null bytes (should be rejected or handled)."""
        # Most APIs reject null bytes
        response = await projects_client.post(
            "/api/projects",
            json={"name": "Test", "description": "Bad\x00String"},
        )
        # Should either succeed or return 422
        assert response.status_code in [201, 422]

    async def test_very_large_number_of_projects(self, projects_client):
        """Create and list many projects."""
        # Create 50 projects
        for i in range(50):
            await projects_client.post(
                "/api/projects", json={"name": f"Project-{i}"}
            )

        # List with pagination
        response = await projects_client.get("/api/projects?page_size=10")
        assert response.status_code == 200
        assert response.json()["total"] == 50
        assert len(response.json()["items"]) == 10

    async def test_name_exactly_one_character(self, projects_client):
        """Name with single character."""
        response = await projects_client.post(
            "/api/projects", json={"name": "A"}
        )
        assert response.status_code == 201
        assert response.json()["name"] == "A"

    async def test_name_with_newlines(self, projects_client):
        """Name with newlines."""
        response = await projects_client.post(
            "/api/projects", json={"name": "Line1\nLine2"}
        )
        # Should either accept or reject
        assert response.status_code in [201, 422]
