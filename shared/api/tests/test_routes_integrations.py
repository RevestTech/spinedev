"""Smoke + auth tests for ``shared.api.routes.integrations``."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shared.api.routes.integrations import router


@pytest.fixture
def client(monkeypatch) -> TestClient:
    # Patch the vault-presence check so "configured" detection is
    # deterministic without needing a real OpenBao.
    async def _fake_get_secret(path: str) -> str:
        return "stub-secret-value" if "github" in path else ""

    import shared.api.routes.integrations as mod

    async def _fake_is_configured(meta):
        return True if "github" in (meta.get("vault_path") or "") else False

    monkeypatch.setattr(mod, "_is_configured", _fake_is_configured, raising=True)

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_list_requires_auth(client) -> None:
    r = client.get("/api/v2/integrations")
    assert r.status_code in (401, 422)
    r2 = client.get("/api/v2/integrations", headers={"Authorization": "Basic abc"})
    assert r2.status_code == 401


def test_list_reports_configured_and_unconfigured(client, oidc_user) -> None:
    """List endpoint reports the status per the configured-probe."""
    r = client.get("/api/v2/integrations", headers={"Authorization": "Bearer t"})
    assert r.status_code == 200
    items = {item["name"]: item for item in r.json()["items"]}
    assert items["github"]["status"] == "configured"
    assert items["linear"]["status"] == "unconfigured"


def test_test_connection_requires_hub_admin(client, oidc_user) -> None:
    """A plain user cannot probe -> 403."""
    r = client.post(
        "/api/v2/integrations/github/test-connection",
        headers={"Authorization": "Bearer t"},
    )
    assert r.status_code == 403


def test_test_connection_smoke_ok_for_admin(client, oidc_hub_admin) -> None:
    """Hub-admin probe returns 200 + healthy flag + audit UUID."""
    r = client.post(
        "/api/v2/integrations/github/test-connection",
        headers={"Authorization": "Bearer t"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["name"] == "github"
    assert body["audit_event_uuid"]


def test_test_connection_unknown_integration_404(client, oidc_hub_admin) -> None:
    r = client.post(
        "/api/v2/integrations/zzz/test-connection",
        headers={"Authorization": "Bearer t"},
    )
    assert r.status_code == 404
