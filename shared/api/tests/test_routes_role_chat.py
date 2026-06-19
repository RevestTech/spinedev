"""Smoke + auth tests for ``shared.api.routes.role_chat``."""

from __future__ import annotations

from unittest.mock import patch

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


def test_role_chat_dev_stub_when_no_api_key(client, oidc_user, monkeypatch) -> None:
    """SPINE_HUB_DEV=1 without an LLM key yields a deterministic stub reply."""
    monkeypatch.setenv("SPINE_HUB_DEV", "1")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

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
    assert body["metadata"]["stub"] is True
    assert body["audit_event_uuid"]


def test_role_chat_live_reply_when_key_available(client, oidc_user, monkeypatch) -> None:
    """SPINE_HUB_DEV=1 with a key uses the MCP tool and marks metadata.stub false."""
    monkeypatch.setenv("SPINE_HUB_DEV", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    fake_resp = {
        "status": "ok",
        "data": {
            "reply": "Use OIDC with PKCE for browser clients.",
            "metadata": {"stub": False, "model": "claude-sonnet-4-6"},
        },
    }

    with patch("shared.api.dependencies.McpClient.call", return_value=fake_resp):
        r = client.post(
            "/api/v2/role-chat",
            json={"role": "architect", "message": "diagram the auth flow"},
            headers={"Authorization": "Bearer t"},
        )

    assert r.status_code == 200
    body = r.json()
    assert body["reply"] == "Use OIDC with PKCE for browser clients."
    assert body["metadata"]["stub"] is False
    assert "placeholder" not in body["reply"].lower()


def test_role_chat_validates_message_max_length(client, oidc_user) -> None:
    """Message length above the cap is rejected with 422."""
    r = client.post(
        "/api/v2/role-chat",
        json={"role": "architect", "message": "x" * 50_000},
        headers={"Authorization": "Bearer t"},
    )
    assert r.status_code == 422
