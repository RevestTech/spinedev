"""Tests for project lifecycle REST mutations."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from shared.api.routes import projects as projects_routes
from shared.identity.models import TokenClaims, User


def _user() -> User:
    claims = TokenClaims(sub="dev-user", exp=9_999_999_999, iat=1)
    return User(id="dev-user", username="dev-user", roles=["hub-user"], raw_claims=claims)


def _row(**overrides):
    base = {
        "id": 10,
        "project_uuid": "00000000-0000-0000-0000-00000000abcd",
        "name": "Old",
        "project_type": "feature",
        "current_phase": "intake",
        "status": "active",
        "owner_user": "dev-user",
        "pipeline_version": "1.0.0",
        "metadata": {"description": "before"},
        "created_at": None,
        "updated_at": None,
    }
    base.update(overrides)
    return base


def test_patch_project_updates_name_and_description() -> None:
    row = _row()
    updated = _row(name="New", metadata={"description": "after"})

    async def _run():
        with patch.object(projects_routes, "_fetch_project_row", AsyncMock(return_value=row)), patch.object(
            projects_routes, "_patch_project_row", AsyncMock(return_value=updated)
        ), patch.object(projects_routes, "_audit_project_mutation", return_value="audit-1"):
            return await projects_routes.patch_project(
                row["project_uuid"],
                projects_routes.ProjectUpdate(name="New", description="after"),
                user=_user(),
            )

    resp = asyncio.run(_run())
    assert resp["ok"] is True
    assert resp["name"] == "New"


def test_archive_project_sets_completed() -> None:
    row = _row(status="active", metadata={})
    updated = _row(status="completed", metadata={"archived_at": "t", "archived_by": "dev-user"})

    async def _run():
        with patch.object(projects_routes, "_fetch_project_row", AsyncMock(return_value=row)), patch.object(
            projects_routes, "_write_project_row", AsyncMock(return_value=updated)
        ), patch.object(projects_routes, "_audit_project_mutation", return_value="audit-2"):
            return await projects_routes.archive_project(row["project_uuid"], user=_user())

    resp = asyncio.run(_run())
    assert resp["ok"] is True
    assert resp["status"] == "completed"


def test_delete_project_sets_terminated() -> None:
    row = _row(status="active", metadata={})
    updated = _row(status="terminated")

    async def _run():
        with patch.object(projects_routes, "_direct_fetch_project_row", AsyncMock(return_value=row)), patch.object(
            projects_routes, "_write_project_row", AsyncMock(return_value=updated)
        ), patch.object(projects_routes, "_audit_project_mutation", return_value="audit-3"):
            return await projects_routes.delete_project(row["project_uuid"], user=_user())

    resp = asyncio.run(_run())
    assert resp["ok"] is True
    assert resp["project_id"] == row["project_uuid"]


def test_get_project_summary_strips_artifacts_and_code_list() -> None:
    row = _row(
        metadata={
            "description": "brief",
            "prd_md": "x" * 5000,
            "code_files": [{"path": "a.ts", "bytes": 1}, {"path": "b.ts", "bytes": 2}],
            "intake_transcript": [{"role": "user", "content": "hi"}],
            "build_artifact": {
                "status": "sealed",
                "phase": "build_in_progress",
                "role": "engineer",
                "kg_impact": [{"node_id": "file:a.ts"}] * 50,
                "code_changes": [{"path": "a.ts", "lines_added": 100}] * 50,
            },
        }
    )

    async def _run():
        with patch.object(projects_routes, "_direct_fetch_project_row", AsyncMock(return_value=row)):
            return await projects_routes.get_project_summary(row["project_uuid"])

    resp = asyncio.run(_run())
    assert resp["name"] == row["name"]
    assert "prd_md" not in resp["metadata"]
    assert "code_files" not in resp["metadata"]
    assert "intake_transcript" not in resp["metadata"]
    assert resp["metadata"]["code_files_count"] == 2
    assert resp["prd_md"] is None
    ba = resp["metadata"]["build_artifact"]
    assert ba["status"] == "sealed"
    assert "kg_impact" not in ba
    assert "code_changes" not in ba
