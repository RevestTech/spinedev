"""Smoke + auth tests for ``shared.api.routes.role_chat``."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shared.api.routes.role_chat import router


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_role_chat_requires_auth(client) -> None:
    """Unauthenticated POST is rejected (422 missing header / 401 malformed)."""
    r = client.post("/api/v2/role-chat", json={"role": "architect", "message": "hi"})
    assert r.status_code in (401, 422)
    r2 = client.post(
        "/api/v2/role-chat",
        json={"role": "architect", "message": "hi"},
        headers={"Authorization": "Basic abc"},
    )
    assert r2.status_code == 401


def test_role_chat_unknown_role_404(client, oidc_user) -> None:
    """Unknown role yields a 404 with the registry list for the SPA to show."""
    r = client.post(
        "/api/v2/role-chat",
        json={"role": "not-a-role", "message": "hi"},
        headers={"Authorization": "Bearer t"},
    )
    assert r.status_code == 404
    body = r.json()
    assert body["detail"]["error_code"] == "role_unknown"
    assert "architect" in body["detail"]["known"]


def test_role_chat_known_role_returns_stub_reply(client, oidc_user) -> None:
    """Known role yields a deterministic stub reply (Wave 3 part 1 behaviour)."""
    r = client.post(
        "/api/v2/role-chat",
        json={"role": "architect", "message": "diagram the auth flow"},
        headers={"Authorization": "Bearer t"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["role"] == "architect"
    assert body["actor"] == "u-1"
    assert "placeholder" in body["reply"].lower()
    assert body["audit_event_uuid"]


def test_role_chat_validates_message_max_length(client, oidc_user) -> None:
    """Message length above the cap is rejected with 422."""
    r = client.post(
        "/api/v2/role-chat",
        json={"role": "architect", "message": "x" * 50_000},
        headers={"Authorization": "Bearer t"},
    )
    assert r.status_code == 422
