"""Tests for ``shared.mcp.tools.integrations`` (V3 Wave 6 Stream J, #30).

Covers all three tools — list, test_connection, configure — and the
Cite-or-Refuse contract on ``integrations_configure``.
"""

from __future__ import annotations

import pytest

from shared.mcp.tools import TOOL_REGISTRY, discover_tools
from shared.mcp.tools.integrations import (
    IntegrationsConfigureInput,
    IntegrationsListInput,
    IntegrationsTestConnectionInput,
    integrations_configure,
    integrations_list,
    integrations_test_connection,
)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


@pytest.fixture
def registry() -> dict:
    if not TOOL_REGISTRY:
        discover_tools("shared.mcp.tools")
    return TOOL_REGISTRY


def test_three_tools_registered(registry: dict) -> None:
    for name in ("integrations_list", "integrations_test_connection",
                 "integrations_configure"):
        assert name in registry


def test_configure_requires_citation_per_design_12(registry: dict) -> None:
    """Mutating tool must opt into Cite-or-Refuse (#12)."""
    assert registry["integrations_configure"].requires_citation is True
    # Non-mutating tools don't have to.
    assert registry["integrations_list"].requires_citation is False
    assert registry["integrations_test_connection"].requires_citation is False


def test_configure_tagged_mutating(registry: dict) -> None:
    assert "mutating" in registry["integrations_configure"].tags


# ---------------------------------------------------------------------------
# integrations_list
# ---------------------------------------------------------------------------


def test_list_returns_all_catalog_rows(monkeypatch) -> None:
    """List enumerates the full catalog with feature_enabled defaults."""
    # Fail-open feature flag eval (no licence subsystem present in tests).
    resp = integrations_list(
        IntegrationsListInput(project_id="p1", actor="op"),
    )
    assert resp.status == "ok"
    items = resp.data["items"]
    names = {i["name"] for i in items}
    # The 10-integration v1.0 surface.
    assert {"github", "linear", "jira", "slack", "pagerduty",
            "twilio", "teams", "vanta", "drata", "secureframe"} <= names


def test_list_filters_by_kind() -> None:
    resp = integrations_list(
        IntegrationsListInput(project_id="p1", actor="op", kind="grc"),
    )
    assert resp.status == "ok"
    items = resp.data["items"]
    assert all(i["kind"] == "grc" for i in items)
    names = {i["name"] for i in items}
    assert names == {"vanta", "drata", "secureframe"}


# ---------------------------------------------------------------------------
# integrations_test_connection
# ---------------------------------------------------------------------------


def test_test_connection_unknown_returns_error() -> None:
    resp = integrations_test_connection(
        IntegrationsTestConnectionInput(
            project_id="p1", actor="hub_admin", name="github",
        ),
    )
    # Real adapter doesn't exist on disk for v1.0 -> fell back to stub envelope.
    assert resp.status in ("ok", "stub_implementation")


def test_test_connection_stub_for_v1_1_integrations() -> None:
    """vanta/drata/secureframe/twilio/teams are stub-mode in v1.0."""
    for name in ("vanta", "drata", "secureframe", "twilio", "teams"):
        resp = integrations_test_connection(
            IntegrationsTestConnectionInput(
                project_id="p1", actor="hub_admin", name=name,
            ),
        )
        assert resp.status == "stub_implementation"
        assert resp.data["probe_mode"] == "stub"
        assert resp.data["name"] == name


def test_test_connection_rejects_invalid_name() -> None:
    """Pydantic Literal rejects non-catalog names at parse time."""
    with pytest.raises(Exception):
        IntegrationsTestConnectionInput(
            project_id="p1", actor="hub_admin", name="bogus",  # type: ignore[arg-type]
        )


# ---------------------------------------------------------------------------
# integrations_configure  —  Cite-or-Refuse
# ---------------------------------------------------------------------------


def _stub_secret(monkeypatch, *, present: bool) -> None:
    """Patch ``shared.secrets.get_secret`` to control vault presence."""
    import shared.secrets as _sec

    async def _fake_get(path: str) -> str:
        return "stub-value" if present else ""

    monkeypatch.setattr(_sec, "get_secret", _fake_get, raising=True)


def test_configure_ok_path_attaches_citations(monkeypatch) -> None:
    _stub_secret(monkeypatch, present=True)
    resp = integrations_configure(
        IntegrationsConfigureInput(
            project_id="p1", actor="hub_admin", name="github",
            vault_path="spine/integrations/github/token",
            options={"org": "my-org"},
        ),
    )
    assert resp.status == "ok"
    assert resp.data["configured"] is True
    assert resp.data["name"] == "github"
    assert len(resp.citation) >= 1
    types = {c.type for c in resp.citation}
    assert "audit_hash" in types


def test_configure_refuses_when_vault_empty(monkeypatch) -> None:
    """Mutating tool refuses + still carries Cite-or-Refuse citation."""
    _stub_secret(monkeypatch, present=False)
    resp = integrations_configure(
        IntegrationsConfigureInput(
            project_id="p1", actor="hub_admin", name="github",
            vault_path="spine/integrations/github/token",
        ),
    )
    assert resp.status == "error"
    assert resp.error is not None
    assert resp.error.code == "vault_secret_missing"
    # Refusal MUST still cite the audit row per #12.
    assert len(resp.citation) >= 1
    assert resp.citation[0].type == "audit_hash"


def test_configure_unknown_integration_errors(monkeypatch) -> None:
    """Validation happens at the pydantic boundary, not inside the tool."""
    with pytest.raises(Exception):
        IntegrationsConfigureInput(
            project_id="p1", actor="hub_admin", name="not-an-integration",  # type: ignore[arg-type]
            vault_path="spine/integrations/x/y",
        )


def test_configure_rejects_empty_actor() -> None:
    with pytest.raises(Exception):
        IntegrationsConfigureInput(
            project_id="p1", actor="", name="github",
            vault_path="spine/integrations/github/token",
        )


def test_configure_persists_option_keys_in_audit(monkeypatch) -> None:
    """The audit metadata captures the option key names (not values)."""
    _stub_secret(monkeypatch, present=True)
    captured: dict = {}

    def _spy(*, action, project_id, actor, integration_name, metadata):
        captured.update(metadata)
        from uuid import uuid4
        return uuid4()

    import shared.mcp.tools.integrations as mod
    monkeypatch.setattr(mod, "_audit_write", _spy, raising=True)

    integrations_configure(
        IntegrationsConfigureInput(
            project_id="p1", actor="hub_admin", name="linear",
            vault_path="spine/integrations/linear/api_key",
            options={"workspace_id": "ws-1", "default_team": "core"},
        ),
    )
    assert captured["ok"] is True
    assert captured["option_keys"] == ["default_team", "workspace_id"]
