"""Smoke + auth tests for ``shared.api.routes.vault_config``."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shared.api.routes.vault_config import router


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_status_requires_auth(client) -> None:
    r = client.get("/api/v2/vault/status")
    assert r.status_code in (401, 422)
    r2 = client.get("/api/v2/vault/status", headers={"Authorization": "Basic abc"})
    assert r2.status_code == 401


def test_secrets_requires_hub_admin_role(client, oidc_user) -> None:
    """A plain user must NOT be able to enumerate vault paths -> 403."""
    r = client.get("/api/v2/vault/secrets", headers={"Authorization": "Bearer t"})
    assert r.status_code == 403


def test_rotate_requires_hub_admin_role(client, oidc_user) -> None:
    """A plain user must NOT be able to rotate -> 403."""
    r = client.post(
        "/api/v2/vault/rotate",
        json={"path": "spine/integrations/github/token", "reason": "expired"},
        headers={"Authorization": "Bearer t"},
    )
    assert r.status_code == 403


def test_status_returns_adapter_kind_when_admin(client, oidc_hub_admin, monkeypatch) -> None:
    """A hub-admin sees adapter kind + healthy flag."""
    class _Adapter:
        endpoint = "https://vault.example/v1"

        async def ping(self) -> bool:  # noqa: D401
            return True

    import shared.secrets as secrets_mod

    def _fake_default():
        return _Adapter()

    monkeypatch.setattr(secrets_mod, "get_default_adapter", _fake_default, raising=True)
    r = client.get("/api/v2/vault/status", headers={"Authorization": "Bearer t"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["adapter_kind"] == "_Adapter"
    assert body["healthy"] is True
