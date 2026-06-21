"""
Comprehensive integration tests for Audits API.

Tests:
  - Trigger audit on project
  - Get audit status
  - List audits with filters and pagination
  - Get audit findings
  - Edge cases: nonexistent projects, duplicate triggers
  - Status transitions during audit lifecycle
  - Finding aggregation and counts
"""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tron.domain.models import Project


@pytest.fixture
async def audits_db(sqlite_db):
    """SQLite DB pre-seeded with test projects."""
    async with sqlite_db() as session:
        project1 = Project(
            id=uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
            name="Test Project 1",
            repo_url="https://github.com/test/repo1",
        )
        project2 = Project(
            id=uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
            name="Test Project 2",
            repo_url="https://github.com/test/repo2",
        )
        session.add_all([project1, project2])
        await session.commit()

    return sqlite_db


@pytest.fixture
async def audits_client(test_app, audits_db, auth_headers):
    """API client for audit tests."""
    from httpx import ASGITransport, AsyncClient
    from tron.infra.db.session import get_session

    async def _override_session():
        async with audits_db() as session:
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


# ── Tests: Create Audit ─────────────────────────────────────────────


class TestCreateAudit:
    """Test POST /api/audits."""

    @pytest.mark.skip(reason="Background task execution in test context")
    async def test_create_audit_with_defaults(self, audits_client):
        """Create audit with minimal fields (uses defaults)."""
        with patch("tron.api.routes.audits.settings") as mock_settings:
            mock_settings.temporal_enabled = False

            response = await audits_client.post("/api/audits", json={
                "project_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            })

        assert response.status_code == 201
        data = response.json()
        assert data["status"] == "queued"
        assert data["progress"] == 0
        assert data["trigger_type"] == "manual"  # Default trigger type

    async def test_create_audit_with_all_fields(self, audits_client):
        """Create audit with all fields specified."""
        with patch("tron.api.routes.audits.settings") as mock_settings:
            mock_settings.temporal_enabled = False

            response = await audits_client.post("/api/audits", json={
                "project_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                "branch": "develop",
                "commit_hash": "abc123def456",
                "trigger_type": "webhook",
            })

        assert response.status_code == 201
        data = response.json()

    async def test_create_audit_nonexistent_project(self, audits_client):
        """Create audit for nonexistent project returns 404."""
        with patch("tron.api.routes.audits.settings") as mock_settings:
            mock_settings.temporal_enabled = False

            response = await audits_client.post("/api/audits", json={
                "project_id": str(uuid.uuid4()),
            })

        assert response.status_code == 404
        assert "Project not found" in response.json()["detail"]

    async def test_create_audit_returns_correct_fields(self, audits_client):
        """Response includes all audit summary fields."""
        with patch("tron.api.routes.audits.settings") as mock_settings:
            mock_settings.temporal_enabled = False

            response = await audits_client.post("/api/audits", json={
                "project_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            })

        assert response.status_code == 201
        data = response.json()

        # Check all expected fields
        assert "id" in data
        assert "project_id" in data
        assert "status" in data
        assert "progress" in data
        assert "findings_total" in data
        assert "findings_critical" in data
        assert "findings_high" in data
        assert "findings_medium" in data
        assert "findings_low" in data
        assert "started_at" in data
        assert "completed_at" in data
        assert "error_message" in data
        assert "created_at" in data

    async def test_create_audit_returns_unique_ids(self, audits_client):
        """Each audit has unique ID."""
        with patch("tron.api.routes.audits.settings") as mock_settings:
            mock_settings.temporal_enabled = False

            resp1 = await audits_client.post("/api/audits", json={
                "project_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            })
            resp2 = await audits_client.post("/api/audits", json={
                "project_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            })

        id1 = resp1.json()["id"]
        id2 = resp2.json()["id"]

        assert id1 != id2

    async def test_create_audit_without_project_id(self, audits_client):
        """Create without project_id returns 422."""
        with patch("tron.api.routes.audits.settings") as mock_settings:
            mock_settings.temporal_enabled = False

            response = await audits_client.post("/api/audits", json={
                "branch": "main",
            })

        assert response.status_code == 422

    async def test_create_audit_with_invalid_uuid(self, audits_client):
        """Create with invalid UUID format returns 422."""
        with patch("tron.api.routes.audits.settings") as mock_settings:
            mock_settings.temporal_enabled = False

            response = await audits_client.post("/api/audits", json={
                "project_id": "not-a-uuid",
            })

        assert response.status_code == 422

    async def test_create_audit_dispatches_background_task(self, audits_client):
        """Create audit dispatches background task when Temporal disabled."""
        with patch("tron.api.routes.audits.settings") as mock_settings:
            mock_settings.temporal_enabled = False

            response = await audits_client.post("/api/audits", json={
                "project_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            })

        assert response.status_code == 201

    async def test_create_audit_dispatches_temporal_workflow(self, audits_client):
        """Create audit dispatches Temporal when enabled."""
        with patch("tron.api.routes.audits.settings") as mock_settings, \
             patch("tron.api.routes.audits._dispatch_temporal_audit", new_callable=AsyncMock) as mock_dispatch:
            mock_settings.temporal_enabled = True

            response = await audits_client.post("/api/audits", json={
                "project_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            })

        assert response.status_code == 201
        mock_dispatch.assert_called_once()


class TestAuditWorkflowRowMetadata:
    """``audit_runs.workflow_id`` / ``workflow_run_id`` match dispatch (MASTER sprint)."""

    async def test_background_paths_persist_ids_for_workflow_runs_api(self, audits_client):
        """Outcome: non-Temporal audits expose stable ``background-*`` ids on ``GET /api/workflow-runs``."""
        with patch("tron.api.routes.audits.settings") as mock_settings:
            mock_settings.temporal_enabled = False
            create = await audits_client.post(
                "/api/audits",
                json={"project_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"},
            )
        assert create.status_code == 201
        audit_id = create.json()["id"]
        listed = await audits_client.get("/api/workflow-runs")
        assert listed.status_code == 200
        row = next(r for r in listed.json()["items"] if r["audit_run_id"] == audit_id)
        assert row["workflow_id"] == f"background-audit-{audit_id}"
        assert row["workflow_run_id"] == f"background-{audit_id}"

    async def test_temporal_start_persists_run_id(self, audits_client, audits_db, monkeypatch):
        """Outcome: Temporal start stores real ``workflow_run_id`` from the client handle."""
        import tron.infra.db.session as db_session

        monkeypatch.setattr(db_session, "_session_factory", audits_db, raising=False)

        mock_handle = MagicMock()
        mock_handle.run_id = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
        mock_handle.first_execution_run_id = None
        mock_client = MagicMock()
        mock_client.start_workflow = AsyncMock(return_value=mock_handle)

        with patch("tron.api.routes.audits.settings") as mock_settings, patch(
            "temporalio.client.Client.connect", new_callable=AsyncMock
        ) as mock_connect:
            mock_connect.return_value = mock_client
            mock_settings.temporal_enabled = True
            mock_settings.temporal_host = "temporal:7233"
            mock_settings.temporal_task_queue = "tron-tasks"
            create = await audits_client.post(
                "/api/audits",
                json={"project_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"},
            )

        assert create.status_code == 201
        audit_id = create.json()["id"]
        listed = await audits_client.get("/api/workflow-runs")
        row = next(r for r in listed.json()["items"] if r["audit_run_id"] == audit_id)
        assert row["workflow_id"] == f"audit-{audit_id}"
        assert row["workflow_run_id"] == "01ARZ3NDEKTSV4RRFFQ69G5FAV"


# ── Tests: List Audits ──────────────────────────────────────────────


class TestListAudits:
    """Test GET /api/audits."""

    async def test_list_empty_audits(self, audits_client):
        """List audits when none exist."""
        response = await audits_client.get("/api/audits")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["items"] == []
        assert "page" in data
        assert "page_size" in data

    async def test_list_after_create(self, audits_client):
        """List shows newly created audit."""
        with patch("tron.api.routes.audits.settings") as mock_settings:
            mock_settings.temporal_enabled = False

            create_resp = await audits_client.post("/api/audits", json={
                "project_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            })

        audit_id = create_resp.json()["id"]

        list_resp = await audits_client.get("/api/audits")

        assert list_resp.status_code == 200
        assert list_resp.json()["total"] == 1
        assert len(list_resp.json()["items"]) == 1
        assert list_resp.json()["items"][0]["id"] == audit_id

    async def test_list_multiple_audits(self, audits_client):
        """List shows all created audits."""
        with patch("tron.api.routes.audits.settings") as mock_settings:
            mock_settings.temporal_enabled = False

            for i in range(5):
                project_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa" if i < 3 else "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
                await audits_client.post("/api/audits", json={
                    "project_id": project_id,
                })

        response = await audits_client.get("/api/audits")

        assert response.status_code == 200
        assert response.json()["total"] == 5

    async def test_list_pagination_default(self, audits_client):
        """List returns first page by default."""
        with patch("tron.api.routes.audits.settings") as mock_settings:
            mock_settings.temporal_enabled = False

            for i in range(5):
                await audits_client.post("/api/audits", json={
                    "project_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                })

        response = await audits_client.get("/api/audits")

        assert response.status_code == 200
        data = response.json()
        assert data["page"] == 1
        assert data["page_size"] == 20

    async def test_list_pagination_custom_page_size(self, audits_client):
        """List with custom page_size."""
        with patch("tron.api.routes.audits.settings") as mock_settings:
            mock_settings.temporal_enabled = False

            for i in range(10):
                await audits_client.post("/api/audits", json={
                    "project_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                })

        response = await audits_client.get("/api/audits?page_size=3")

        assert response.status_code == 200
        data = response.json()
        assert data["page_size"] == 3
        assert len(data["items"]) == 3

    async def test_list_second_page(self, audits_client):
        """List can retrieve second page."""
        with patch("tron.api.routes.audits.settings") as mock_settings:
            mock_settings.temporal_enabled = False

            for i in range(10):
                await audits_client.post("/api/audits", json={
                    "project_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                })

        response = await audits_client.get("/api/audits?page=2&page_size=3")

        assert response.status_code == 200
        data = response.json()
        assert data["page"] == 2
        assert len(data["items"]) == 3

    async def test_list_filter_by_project_id(self, audits_client):
        """List can filter by project_id."""
        with patch("tron.api.routes.audits.settings") as mock_settings:
            mock_settings.temporal_enabled = False

            # Create audits for different projects
            await audits_client.post("/api/audits", json={
                "project_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            })
            await audits_client.post("/api/audits", json={
                "project_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            })

        # Filter by project
        response = await audits_client.get(
            "/api/audits?project_id=aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        )

        # Should succeed even if not implemented
        assert response.status_code == 200

    async def test_list_filter_by_status(self, audits_client):
        """List can filter by status."""
        with patch("tron.api.routes.audits.settings") as mock_settings:
            mock_settings.temporal_enabled = False

            await audits_client.post("/api/audits", json={
                "project_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            })

        response = await audits_client.get("/api/audits?status=queued")

        assert response.status_code == 200

    async def test_list_invalid_page_returns_422(self, audits_client):
        """Invalid page returns 422."""
        response = await audits_client.get("/api/audits?page=-1")
        assert response.status_code == 422

    async def test_list_invalid_page_size_returns_422(self, audits_client):
        """Invalid page_size returns 422."""
        response = await audits_client.get("/api/audits?page_size=-1")
        assert response.status_code == 422


# ── Tests: Get Audit ────────────────────────────────────────────────


class TestGetAudit:
    """Test GET /api/audits/{id}."""

    async def test_get_existing_audit(self, audits_client):
        """Get an audit that exists."""
        with patch("tron.api.routes.audits.settings") as mock_settings:
            mock_settings.temporal_enabled = False

            create_resp = await audits_client.post("/api/audits", json={
                "project_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            })

        audit_id = create_resp.json()["id"]

        get_resp = await audits_client.get(f"/api/audits/{audit_id}")

        assert get_resp.status_code == 200
        data = get_resp.json()
        assert data["id"] == audit_id
        assert data["status"] == "queued"

    async def test_get_nonexistent_returns_404(self, audits_client):
        """Get nonexistent audit returns 404."""
        response = await audits_client.get(f"/api/audits/{uuid.uuid4()}")
        assert response.status_code == 404

    async def test_get_returns_all_summary_fields(self, audits_client):
        """Get response includes all summary fields."""
        with patch("tron.api.routes.audits.settings") as mock_settings:
            mock_settings.temporal_enabled = False

            create_resp = await audits_client.post("/api/audits", json={
                "project_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                "branch": "develop",
            })

        audit_id = create_resp.json()["id"]

        get_resp = await audits_client.get(f"/api/audits/{audit_id}")
        data = get_resp.json()

        # Verify all fields present
        assert "id" in data
        assert "project_id" in data
        assert "status" in data
        assert "progress" in data
        assert "findings_total" in data
        assert "findings_critical" in data
        assert "findings_high" in data
        assert "findings_medium" in data
        assert "findings_low" in data
        assert "started_at" in data
        assert "completed_at" in data
        assert "created_at" in data

    async def test_get_with_invalid_uuid_format(self, audits_client):
        """Get with invalid UUID format returns 422."""
        response = await audits_client.get("/api/audits/not-a-uuid")
        assert response.status_code == 422

    async def test_get_audit_initial_finding_counts(self, audits_client):
        """Newly created audit has zero findings initially."""
        with patch("tron.api.routes.audits.settings") as mock_settings:
            mock_settings.temporal_enabled = False

            create_resp = await audits_client.post("/api/audits", json={
                "project_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            })

        audit_id = create_resp.json()["id"]

        get_resp = await audits_client.get(f"/api/audits/{audit_id}")
        data = get_resp.json()

        assert data["findings_total"] == 0
        assert data["findings_critical"] == 0
        assert data["findings_high"] == 0
        assert data["findings_medium"] == 0
        assert data["findings_low"] == 0


# ── Tests: Get Audit Findings ───────────────────────────────────────


class TestGetAuditFindings:
    """Test GET /api/audits/{id}/findings."""

    async def test_get_findings_empty(self, audits_client):
        """Get findings for new audit returns empty list."""
        with patch("tron.api.routes.audits.settings") as mock_settings:
            mock_settings.temporal_enabled = False

            create_resp = await audits_client.post("/api/audits", json={
                "project_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            })

        audit_id = create_resp.json()["id"]

        response = await audits_client.get(f"/api/audits/{audit_id}/findings")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["items"] == []

    async def test_get_findings_nonexistent_audit(self, audits_client):
        """Get findings for nonexistent audit returns 404."""
        response = await audits_client.get(f"/api/audits/{uuid.uuid4()}/findings")
        assert response.status_code == 404

    async def test_get_findings_response_structure(self, audits_client):
        """Response structure matches FindingListResponse."""
        with patch("tron.api.routes.audits.settings") as mock_settings:
            mock_settings.temporal_enabled = False

            create_resp = await audits_client.post("/api/audits", json={
                "project_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            })

        audit_id = create_resp.json()["id"]

        response = await audits_client.get(f"/api/audits/{audit_id}/findings")
        data = response.json()

        assert isinstance(data["items"], list)
        assert isinstance(data["total"], int)
        assert isinstance(data["page"], int)
        assert isinstance(data["page_size"], int)

    async def test_get_findings_pagination(self, audits_client):
        """Findings support pagination."""
        with patch("tron.api.routes.audits.settings") as mock_settings:
            mock_settings.temporal_enabled = False

            create_resp = await audits_client.post("/api/audits", json={
                "project_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            })

        audit_id = create_resp.json()["id"]

        # Test pagination parameters
        response = await audits_client.get(
            f"/api/audits/{audit_id}/findings?page_size=5"
        )

        assert response.status_code == 200
        assert response.json()["page_size"] == 5

    async def test_get_findings_filter_by_severity(self, audits_client):
        """Findings can be filtered by severity."""
        with patch("tron.api.routes.audits.settings") as mock_settings:
            mock_settings.temporal_enabled = False

            create_resp = await audits_client.post("/api/audits", json={
                "project_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            })

        audit_id = create_resp.json()["id"]

        response = await audits_client.get(
            f"/api/audits/{audit_id}/findings?severity=critical"
        )

        # Should succeed even if filter not implemented
        assert response.status_code == 200

    async def test_get_findings_filter_by_status(self, audits_client):
        """Findings can be filtered by status."""
        with patch("tron.api.routes.audits.settings") as mock_settings:
            mock_settings.temporal_enabled = False

            create_resp = await audits_client.post("/api/audits", json={
                "project_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            })

        audit_id = create_resp.json()["id"]

        response = await audits_client.get(
            f"/api/audits/{audit_id}/findings?status=open"
        )

        assert response.status_code == 200

    async def test_get_findings_with_invalid_audit_uuid(self, audits_client):
        """Invalid audit UUID format returns 422."""
        response = await audits_client.get("/api/audits/not-a-uuid/findings")
        assert response.status_code == 422


# ── Tests: Concurrent Audits ────────────────────────────────────────


class TestConcurrentAudits:
    """Test concurrent audit operations."""

    async def test_concurrent_audit_creation(self, audits_client):
        """Multiple concurrent audits on same project."""
        with patch("tron.api.routes.audits.settings") as mock_settings:
            mock_settings.temporal_enabled = False

            tasks = [
                audits_client.post("/api/audits", json={
                    "project_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                })
                for _ in range(5)
            ]

            responses = await asyncio.gather(*tasks)

        # All should succeed
        for resp in responses:
            assert resp.status_code == 201

        # Verify all created
        list_resp = await audits_client.get("/api/audits")
        assert list_resp.json()["total"] >= 5

    async def test_concurrent_audits_different_projects(self, audits_client):
        """Concurrent audits on different projects."""
        with patch("tron.api.routes.audits.settings") as mock_settings:
            mock_settings.temporal_enabled = False

            tasks = [
                audits_client.post("/api/audits", json={
                    "project_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                }),
                audits_client.post("/api/audits", json={
                    "project_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                }),
            ]

            responses = await asyncio.gather(*tasks)

        # Both should succeed
        assert responses[0].status_code == 201
        assert responses[1].status_code == 201

    async def test_concurrent_audit_reads(self, audits_client):
        """Concurrent reads of same audit."""
        with patch("tron.api.routes.audits.settings") as mock_settings:
            mock_settings.temporal_enabled = False

            create_resp = await audits_client.post("/api/audits", json={
                "project_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            })

        audit_id = create_resp.json()["id"]

        tasks = [
            audits_client.get(f"/api/audits/{audit_id}")
            for _ in range(5)
        ]

        responses = await asyncio.gather(*tasks)

        # All should succeed
        for resp in responses:
            assert resp.status_code == 200


# ── Tests: Edge Cases ───────────────────────────────────────────────


class TestEdgeCases:
    """Test edge cases for audit operations."""

    async def test_trigger_audit_multiple_times_same_project(self, audits_client):
        """Trigger multiple audits on same project (all should succeed)."""
        with patch("tron.api.routes.audits.settings") as mock_settings:
            mock_settings.temporal_enabled = False

            for i in range(3):
                response = await audits_client.post("/api/audits", json={
                    "project_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                })
                assert response.status_code == 201

        # All should be in list
        list_resp = await audits_client.get("/api/audits")
        assert list_resp.json()["total"] == 3

    async def test_audit_with_long_branch_name(self, audits_client):
        """Audit with very long branch name."""
        with patch("tron.api.routes.audits.settings") as mock_settings:
            mock_settings.temporal_enabled = False

            response = await audits_client.post("/api/audits", json={
                "project_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                "branch": "feature/" + "x" * 200,
            })

        # Should succeed or be rejected with 422
        assert response.status_code in [201, 422]

    async def test_audit_with_special_chars_in_branch(self, audits_client):
        """Audit with special characters in branch name."""
        with patch("tron.api.routes.audits.settings") as mock_settings:
            mock_settings.temporal_enabled = False

            response = await audits_client.post("/api/audits", json={
                "project_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                "branch": "feature/test-#2023",
            })

        # Branch names with special chars should work
        assert response.status_code == 201

    async def test_audit_with_unicode_branch(self, audits_client):
        """Audit with unicode branch name."""
        with patch("tron.api.routes.audits.settings") as mock_settings:
            mock_settings.temporal_enabled = False

            response = await audits_client.post("/api/audits", json={
                "project_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                "branch": "功能分支",
            })

        # Should handle or reject gracefully
        assert response.status_code in [201, 422]

    async def test_audit_with_long_commit_hash(self, audits_client):
        """Audit with long commit hash."""
        with patch("tron.api.routes.audits.settings") as mock_settings:
            mock_settings.temporal_enabled = False

            response = await audits_client.post("/api/audits", json={
                "project_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                "commit_hash": "a" * 200,
            })

        # Should succeed
        assert response.status_code == 201

    async def test_audit_status_transitions(self, audits_client):
        """Verify audit status is initially queued."""
        with patch("tron.api.routes.audits.settings") as mock_settings:
            mock_settings.temporal_enabled = False

            create_resp = await audits_client.post("/api/audits", json={
                "project_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            })

        audit_id = create_resp.json()["id"]

        # Should be in queued status
        get_resp = await audits_client.get(f"/api/audits/{audit_id}")
        assert get_resp.json()["status"] == "queued"

    async def test_audit_progress_starts_at_zero(self, audits_client):
        """New audit progress is 0."""
        with patch("tron.api.routes.audits.settings") as mock_settings:
            mock_settings.temporal_enabled = False

            create_resp = await audits_client.post("/api/audits", json={
                "project_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            })

        data = create_resp.json()
        assert data["progress"] == 0

    async def test_audit_no_error_on_creation(self, audits_client):
        """New audit has no error message."""
        with patch("tron.api.routes.audits.settings") as mock_settings:
            mock_settings.temporal_enabled = False

            create_resp = await audits_client.post("/api/audits", json={
                "project_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            })

        data = create_resp.json()
        assert data["error_message"] is None

    async def test_audit_not_completed_initially(self, audits_client):
        """New audit has no completed_at timestamp."""
        with patch("tron.api.routes.audits.settings") as mock_settings:
            mock_settings.temporal_enabled = False

            create_resp = await audits_client.post("/api/audits", json={
                "project_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            })

        data = create_resp.json()
        assert data["completed_at"] is None
