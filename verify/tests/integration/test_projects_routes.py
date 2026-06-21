"""
Integration tests for Projects CRUD API routes.

Tests all five endpoint handler functions directly (bypassing ASGI transport
which prevents coverage tracking due to thread-pool execution):
  create_project, list_projects, get_project, update_project, delete_project

Uses in-memory SQLite via the sqlite_db fixture.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from tron.api.routes.projects import (
    ProjectCreate,
    ProjectUpdate,
    create_project,
    delete_project,
    get_project,
    list_projects,
    update_project,
)


@pytest.fixture
async def session(sqlite_db):
    """Yield a single async session for direct handler calls."""
    async with sqlite_db() as s:
        yield s


# ── Helper ──────────────────────────────────────────────────────────


async def _create(session, name="Test", **kw):
    """Shortcut to create a project via the handler."""
    body = ProjectCreate(name=name, **kw)
    return await create_project(body=body, session=session)


# ── create_project ──────────────────────────────────────────────────


class TestCreateProject:

    async def test_create_success(self, session):
        result = await _create(session, name="My Project", description="Desc",
                               repo_url="https://github.com/x/y", default_branch="develop")
        assert result.name == "My Project"
        assert result.description == "Desc"
        assert result.default_branch == "develop"
        assert result.status == "active"
        assert result.id is not None

    async def test_create_minimal(self, session):
        result = await _create(session, name="Minimal")
        assert result.name == "Minimal"
        assert result.default_branch == "main"


# ── list_projects ───────────────────────────────────────────────────


class TestListProjects:

    async def test_list_empty(self, session):
        result = await list_projects(page=1, page_size=20, status=None, session=session)
        assert result.items == []
        assert result.total == 0

    async def test_list_with_projects(self, session):
        await _create(session, name="A")
        await _create(session, name="B")
        await session.flush()
        result = await list_projects(page=1, page_size=20, status=None, session=session)
        assert result.total == 2
        assert len(result.items) == 2

    async def test_list_pagination(self, session):
        for i in range(5):
            await _create(session, name=f"P{i}")
        await session.flush()
        result = await list_projects(page=1, page_size=2, status=None, session=session)
        assert result.total == 5
        assert len(result.items) == 2
        assert result.page == 1

    async def test_list_filter_by_status(self, session):
        await _create(session, name="Active")
        await session.flush()
        result = await list_projects(page=1, page_size=20, status="active", session=session)
        assert result.total >= 1

        result2 = await list_projects(page=1, page_size=20, status="archived", session=session)
        assert result2.total == 0


# ── get_project ─────────────────────────────────────────────────────


class TestGetProject:

    async def test_get_success(self, session):
        project = await _create(session, name="Get Me")
        await session.flush()
        result = await get_project(project_id=project.id, session=session)
        assert result.name == "Get Me"

    async def test_get_not_found(self, session):
        with pytest.raises(HTTPException) as exc_info:
            await get_project(project_id=uuid.uuid4(), session=session)
        assert exc_info.value.status_code == 404


# ── update_project ──────────────────────────────────────────────────


class TestUpdateProject:

    async def test_update_name(self, session):
        project = await _create(session, name="Old")
        await session.flush()
        body = ProjectUpdate(name="New")
        result = await update_project(project_id=project.id, body=body, session=session)
        assert result.name == "New"

    async def test_update_multiple_fields(self, session):
        project = await _create(session, name="Multi")
        await session.flush()
        body = ProjectUpdate(description="Desc", default_branch="dev", repo_url="https://new")
        result = await update_project(project_id=project.id, body=body, session=session)
        assert result.description == "Desc"
        assert result.default_branch == "dev"

    async def test_update_not_found(self, session):
        body = ProjectUpdate(name="X")
        with pytest.raises(HTTPException) as exc_info:
            await update_project(project_id=uuid.uuid4(), body=body, session=session)
        assert exc_info.value.status_code == 404

    async def test_update_no_fields(self, session):
        project = await _create(session, name="NoOp")
        await session.flush()
        body = ProjectUpdate()
        result = await update_project(project_id=project.id, body=body, session=session)
        assert result.name == "NoOp"


# ── delete_project ──────────────────────────────────────────────────


class TestDeleteProject:

    async def test_delete_success(self, session):
        project = await _create(session, name="Del Me")
        await session.flush()
        result = await delete_project(project_id=project.id, session=session)
        assert result is None  # 204 = no body

    async def test_delete_not_found(self, session):
        with pytest.raises(HTTPException) as exc_info:
            await delete_project(project_id=uuid.uuid4(), session=session)
        assert exc_info.value.status_code == 404

    async def test_delete_is_soft(self, session):
        project = await _create(session, name="Soft")
        await session.flush()
        await delete_project(project_id=project.id, session=session)
        await session.flush()
        # Should be gone from list
        result = await list_projects(page=1, page_size=100, status=None, session=session)
        ids = [item.id for item in result.items]
        assert project.id not in ids

    async def test_delete_twice_raises(self, session):
        project = await _create(session, name="Twice")
        await session.flush()
        await delete_project(project_id=project.id, session=session)
        await session.flush()
        with pytest.raises(HTTPException) as exc_info:
            await delete_project(project_id=project.id, session=session)
        assert exc_info.value.status_code == 404
