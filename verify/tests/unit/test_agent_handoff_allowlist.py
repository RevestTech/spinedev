"""
Regression tests for the agent-handoff path allowlist (P1 M2).

Three attack surfaces to cover:

  1. Pydantic validator on ProjectCreate/ProjectUpdate — the request edge.
     A malicious PUT body asking to write ``/etc/passwd`` or
     ``../../../../root/.ssh/`` must die here with a 422-shaped ValueError
     before anything hits the DB.

  2. Worker's ``_maybe_write_agent_handoff_inner`` — the write-time edge.
     Even if a row with a bad path exists in the DB (written before the
     allowlist was tightened), the worker must refuse to write through it.

  3. Fail-closed defaults — with no allowlist configured, ALL non-empty
     paths are refused. This is the safe default.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from types import SimpleNamespace

from tron.api.routes import projects as projects_mod
from tron.api.routes.projects import ProjectCreate, ProjectUpdate
from tron.services import agent_handoff as handoff_mod


def _patch_allowlist(monkeypatch, raw: str) -> None:
    """Helper: swap the module-level ``settings`` reference with a stand-in.

    ``Settings`` is a frozen pydantic/dataclass instance, so we can't mutate
    it in place. Both consumer modules import ``settings`` at import time;
    we monkeypatch each local reference to a SimpleNamespace carrying just
    the field this feature actually reads.
    """
    stand_in = SimpleNamespace(
        tron_agent_handoff_allowed_roots=raw,
        tron_agent_handoff=True,
        tron_ui_base="http://localhost:13080",
        tron_handoff_append_tron_md=True,
    )
    monkeypatch.setattr(projects_mod, "settings", stand_in)
    monkeypatch.setattr(handoff_mod, "settings", stand_in)


# ── Pydantic validator: ProjectCreate / ProjectUpdate ─────────────────────


class TestProjectCreateValidator:
    def test_empty_handoff_path_is_accepted_as_unset(self, monkeypatch):
        _patch_allowlist(monkeypatch, "/tmp")
        # None and empty string should both succeed (they mean "clear it")
        assert ProjectCreate(name="x", agent_handoff_path=None).agent_handoff_path is None
        assert ProjectCreate(name="x", agent_handoff_path="").agent_handoff_path is None
        # Whitespace-only also treated as clear.
        assert ProjectCreate(name="x", agent_handoff_path="   ").agent_handoff_path is None

    def test_path_under_allowlist_is_accepted_and_canonicalised(self, tmp_path, monkeypatch):
        _patch_allowlist(monkeypatch, str(tmp_path))
        sub = tmp_path / "handoffs" / "proj-a"
        sub.mkdir(parents=True)

        body = ProjectCreate(name="x", agent_handoff_path=str(sub))
        # Canonical form is what the API stores.
        assert body.agent_handoff_path == str(sub.resolve())

    def test_path_outside_allowlist_rejected(self, tmp_path, monkeypatch):
        _patch_allowlist(monkeypatch, str(tmp_path / "allowed"))
        (tmp_path / "allowed").mkdir()
        outside = tmp_path / "not-allowed" / "file"

        with pytest.raises(ValidationError) as exc_info:
            ProjectCreate(name="x", agent_handoff_path=str(outside))
        assert "not under any configured" in str(exc_info.value)

    def test_parent_dot_dot_escape_rejected(self, tmp_path, monkeypatch):
        allowed = tmp_path / "allowed"
        allowed.mkdir()
        _patch_allowlist(monkeypatch, str(allowed))

        escape = allowed / ".." / ".." / "etc" / "passwd"
        with pytest.raises(ValidationError, match="not under any configured"):
            ProjectCreate(name="x", agent_handoff_path=str(escape))

    def test_symlink_into_allowlist_pointing_out_rejected(self, tmp_path, monkeypatch):
        allowed = tmp_path / "allowed"
        allowed.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        link = allowed / "trick"
        link.symlink_to(outside)

        _patch_allowlist(monkeypatch, str(allowed))

        with pytest.raises(ValidationError, match="not under any configured"):
            ProjectCreate(name="x", agent_handoff_path=str(link))

    def test_relative_path_rejected(self, tmp_path, monkeypatch):
        _patch_allowlist(monkeypatch, str(tmp_path))
        with pytest.raises(ValidationError, match="not absolute"):
            ProjectCreate(name="x", agent_handoff_path="./some/thing")

    def test_empty_allowlist_refuses_any_non_empty_path(self, tmp_path, monkeypatch):
        # Fail-closed default: operator didn't opt in → nothing is accepted.
        _patch_allowlist(monkeypatch, "")
        with pytest.raises(ValidationError, match="no allowlist roots"):
            ProjectCreate(name="x", agent_handoff_path=str(tmp_path))


class TestProjectUpdateValidator:
    # Mirror the create-side suite: PUT must be just as strict.

    def test_update_accepts_none(self, monkeypatch):
        _patch_allowlist(monkeypatch, "/tmp")
        body = ProjectUpdate(agent_handoff_path=None)
        assert body.agent_handoff_path is None

    def test_update_rejects_escape(self, tmp_path, monkeypatch):
        allowed = tmp_path / "allowed"
        allowed.mkdir()
        _patch_allowlist(monkeypatch, str(allowed))
        with pytest.raises(ValidationError, match="not under any configured"):
            ProjectUpdate(agent_handoff_path="/etc/passwd")

    def test_update_accepts_canonical_path(self, tmp_path, monkeypatch):
        _patch_allowlist(monkeypatch, str(tmp_path))
        sub = tmp_path / "project-x"
        sub.mkdir()
        body = ProjectUpdate(agent_handoff_path=str(sub))
        assert body.agent_handoff_path == str(sub.resolve())


# ── Worker re-validation at write time ────────────────────────────────────


class _FakeProject:
    """Minimal shape for ``_maybe_write_agent_handoff_inner`` to inspect."""

    def __init__(self, handoff: str):
        self.agent_handoff_path = handoff
        self.name = "fake"


class _FakeSession:
    """AsyncMock-based session that returns the project we configure."""

    def __init__(self, project):
        self._project = project
        self.get = AsyncMock(return_value=project)


@pytest.mark.asyncio
async def test_worker_refuses_row_outside_current_allowlist(tmp_path, monkeypatch, caplog):
    """A stale DB row pointing at /etc must still be refused.

    This covers the "allowlist was narrowed after the row was written" case
    and the "attacker won the race at the API" case simultaneously — we
    don't trust the DB value on its own.
    """
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    _patch_allowlist(monkeypatch, str(allowed))

    project = _FakeProject(handoff="/etc")
    session = _FakeSession(project)

    # No bundle writer should get called. If it does, it'll AttributeError
    # because we don't stub it — that's a test failure signal on its own,
    # but we also assert nothing was written.
    bundle_writer = MagicMock()
    monkeypatch.setattr(handoff_mod, "write_audit_handoff_bundle", bundle_writer)

    await handoff_mod._maybe_write_agent_handoff_inner(
        session,
        audit_run_id=uuid4(),
        project_id=uuid4(),
        preloaded_findings=None,
    )

    bundle_writer.assert_not_called()


@pytest.mark.asyncio
async def test_worker_happy_path_inside_allowlist(tmp_path, monkeypatch):
    """Positive control: a valid path does reach the bundle writer."""
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    dest = allowed / "proj"
    dest.mkdir()
    _patch_allowlist(monkeypatch, str(allowed))

    project = _FakeProject(handoff=str(dest))
    audit = MagicMock()
    audit.status = "completed"
    audit.progress = 100
    audit.findings_total = 0
    audit.findings_critical = 0
    audit.findings_high = 0
    audit.findings_medium = 0
    audit.findings_low = 0
    audit.started_at = None
    audit.completed_at = None

    # _maybe_write_agent_handoff_inner calls session.get twice:
    # first for Project, then for AuditRun. Use a counter instead of
    # hasattr() on a MagicMock (whose attributes are always truthy).
    call_count = {"n": 0}

    async def get(model, _id):
        call_count["n"] += 1
        return project if call_count["n"] == 1 else audit

    session = MagicMock()
    session.get = AsyncMock(side_effect=get)

    async def no_find(_session, _audit_id):
        return []

    monkeypatch.setattr(handoff_mod, "_load_findings_from_db", no_find)
    bundle_writer = MagicMock(return_value=["a.md", "b.md"])
    monkeypatch.setattr(handoff_mod, "write_audit_handoff_bundle", bundle_writer)

    await handoff_mod._maybe_write_agent_handoff_inner(
        session,
        audit_run_id=uuid4(),
        project_id=uuid4(),
        preloaded_findings=None,
    )

    bundle_writer.assert_called_once()
