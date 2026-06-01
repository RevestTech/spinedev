"""CSRF middleware — cookie session mutating requests require matching header."""

from __future__ import annotations

import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shared.api.middleware.csrf import CSRF_COOKIE_NAME, CSRF_HEADER_NAME, install_csrf_middleware
from shared.api.middleware.oidc import SESSION_COOKIE_NAME


@pytest.fixture(autouse=True)
def _skip_csrf_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SPINE_HUB_SKIP_CSRF", raising=False)


def _app() -> FastAPI:
    app = FastAPI()
    install_csrf_middleware(app)

    @app.post("/api/v2/decisions/d-1/ack")
    async def ack() -> dict[str, bool]:
        return {"ok": True}

    return app


def test_cookie_mutating_without_csrf_header_rejected() -> None:
    client = TestClient(_app())
    r = client.post(
        "/api/v2/decisions/d-1/ack",
        cookies={SESSION_COOKIE_NAME: "signed-session"},
    )
    assert r.status_code == 403
    assert r.json()["error_code"] == "csrf_failed"


def test_cookie_mutating_with_matching_csrf_passes() -> None:
    client = TestClient(_app())
    token = "test-csrf-token-value"
    r = client.post(
        "/api/v2/decisions/d-1/ack",
        cookies={SESSION_COOKIE_NAME: "signed-session", CSRF_COOKIE_NAME: token},
        headers={CSRF_HEADER_NAME: token},
    )
    assert r.status_code == 200


def test_bearer_mutating_skips_csrf() -> None:
    client = TestClient(_app())
    r = client.post(
        "/api/v2/decisions/d-1/ack",
        headers={"Authorization": "Bearer test-token"},
    )
    assert r.status_code == 200


def test_skip_env_disables_csrf(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPINE_HUB_SKIP_CSRF", "1")
    client = TestClient(_app())
    r = client.post(
        "/api/v2/decisions/d-1/ack",
        cookies={SESSION_COOKIE_NAME: "signed-session"},
    )
    assert r.status_code == 200
