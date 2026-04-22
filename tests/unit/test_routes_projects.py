"""
Unit tests for Project route schemas and validation logic.

Pure Pydantic schema tests — no FastAPI TestClient or DB needed.
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone
from uuid import uuid4
from pydantic import ValidationError

from tron.api.routes.projects import (
    ProjectCreate,
    ProjectUpdate,
    ProjectResponse,
    ProjectListResponse,
)


# ============================================================================
# ProjectCreate Schema Validation
# ============================================================================

class TestProjectCreateSchema:

    def test_valid_create(self):
        req = ProjectCreate(name="My Project")
        assert req.name == "My Project"
        assert req.default_branch == "main"

    def test_name_required(self):
        with pytest.raises(ValidationError):
            ProjectCreate()

    def test_empty_name_rejected(self):
        with pytest.raises(ValidationError):
            ProjectCreate(name="")

    def test_name_min_length_1(self):
        req = ProjectCreate(name="X")
        assert req.name == "X"

    def test_name_max_length_255(self):
        req = ProjectCreate(name="A" * 255)
        assert len(req.name) == 255

    def test_name_too_long_rejected(self):
        with pytest.raises(ValidationError):
            ProjectCreate(name="A" * 256)

    def test_description_default_none(self):
        req = ProjectCreate(name="P")
        assert req.description is None

    def test_description_set(self):
        req = ProjectCreate(name="P", description="My desc")
        assert req.description == "My desc"

    def test_repo_url_default_none(self):
        req = ProjectCreate(name="P")
        assert req.repo_url is None

    def test_repo_url_set(self):
        req = ProjectCreate(name="P", repo_url="https://github.com/org/repo")
        assert "github.com" in req.repo_url

    def test_default_branch_main(self):
        req = ProjectCreate(name="P")
        assert req.default_branch == "main"

    def test_custom_branch(self):
        req = ProjectCreate(name="P", default_branch="develop")
        assert req.default_branch == "develop"

    def test_full_create(self):
        req = ProjectCreate(
            name="Tron", description="QA platform",
            repo_url="https://github.com/org/tron",
            default_branch="develop",
        )
        assert req.name == "Tron"
        assert req.description == "QA platform"

    def test_serialization_roundtrip(self):
        req = ProjectCreate(name="Test", description="Desc")
        data = req.model_dump()
        req2 = ProjectCreate(**data)
        assert req2.name == "Test"

    def test_whitespace_name(self):
        """Name with only spaces — Pydantic may or may not strip."""
        req = ProjectCreate(name="   Valid   ")
        assert len(req.name.strip()) > 0


# ============================================================================
# ProjectUpdate Schema Validation
# ============================================================================

class TestProjectUpdateSchema:

    def test_all_fields_optional(self):
        update = ProjectUpdate()
        assert update.name is None
        assert update.description is None
        assert update.repo_url is None

    def test_partial_update_name(self):
        update = ProjectUpdate(name="New Name")
        assert update.name == "New Name"
        assert update.description is None

    def test_partial_update_description(self):
        update = ProjectUpdate(description="New desc")
        assert update.description == "New desc"

    def test_name_min_length(self):
        update = ProjectUpdate(name="X")
        assert update.name == "X"

    def test_empty_name_rejected(self):
        with pytest.raises(ValidationError):
            ProjectUpdate(name="")

    def test_name_max_length(self):
        update = ProjectUpdate(name="A" * 255)
        assert len(update.name) == 255

    def test_name_too_long_rejected(self):
        with pytest.raises(ValidationError):
            ProjectUpdate(name="A" * 256)

    def test_status_update(self):
        update = ProjectUpdate(status="archived")
        assert update.status == "archived"

    def test_default_branch_update(self):
        update = ProjectUpdate(default_branch="release")
        assert update.default_branch == "release"

    def test_serialization(self):
        update = ProjectUpdate(name="Updated")
        data = update.model_dump(exclude_none=True)
        assert data == {"name": "Updated"}


# ============================================================================
# ProjectResponse Schema Tests
# ============================================================================

class TestProjectResponseSchema:

    def test_valid_response(self):
        now = datetime.now(timezone.utc)
        resp = ProjectResponse(
            id=uuid4(), name="Tron", description="QA",
            repo_url="https://github.com/org/tron",
            default_branch="main", status="active",
            created_at=now, updated_at=now,
        )
        assert resp.name == "Tron"
        assert resp.status == "active"

    def test_optional_fields_none(self):
        now = datetime.now(timezone.utc)
        resp = ProjectResponse(
            id=uuid4(), name="P", description=None,
            repo_url=None, default_branch="main",
            status="active", created_at=now, updated_at=now,
        )
        assert resp.description is None
        assert resp.repo_url is None

    def test_from_attributes(self):
        assert ProjectResponse.model_config.get("from_attributes") is True

    def test_serialization(self):
        now = datetime.now(timezone.utc)
        resp = ProjectResponse(
            id=uuid4(), name="P", description=None,
            repo_url=None, default_branch="main",
            status="active", created_at=now, updated_at=now,
        )
        data = resp.model_dump()
        assert "id" in data
        assert data["status"] == "active"


# ============================================================================
# ProjectListResponse Schema Tests
# ============================================================================

class TestProjectListResponseSchema:

    def test_empty_list(self):
        resp = ProjectListResponse(items=[], total=0, page=1, page_size=20)
        assert resp.total == 0

    def test_with_items(self):
        now = datetime.now(timezone.utc)
        item = ProjectResponse(
            id=uuid4(), name="P", description=None,
            repo_url=None, default_branch="main",
            status="active", created_at=now, updated_at=now,
        )
        resp = ProjectListResponse(items=[item], total=1, page=1, page_size=20)
        assert len(resp.items) == 1

    def test_pagination(self):
        resp = ProjectListResponse(items=[], total=100, page=5, page_size=20)
        assert resp.page == 5
        assert resp.page_size == 20
        assert resp.total == 100
