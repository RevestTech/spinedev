"""Tests for ``shared.api.middleware.oidc`` — login redirect, cookie set, logout."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shared.api.middleware.oidc import (
    SESSION_COOKIE_NAME,
    OidcSessionConfig,
    build_login_redirect_url,
    get_session_store,
    install_oidc_routes,
    set_session_config,
)


def _cfg() -> OidcSessionConfig:
    return OidcSessionConfig(
        hmac_key=b"k" * 32,
        keycloak_login_url="http://kc/realms/spine/protocol/openid-connect/auth",
        keycloak_logout_url="http://kc/realms/spine/protocol/openid-connect/logout",
        redirect_uri="http://localhost:8088/api/v2/auth/callback",
        cookie_secure=False,
    )


@pytest.fixture
def app() -> FastAPI:
    set_session_config(_cfg())
    app = FastAPI()

    async def _exchanger(code: str) -> dict:
        return {
            "access_token": f"access-for-{code}",
            "id_token_claims": {"sub": "u-mock"},
        }

    install_oidc_routes(app, token_exchanger=_exchanger)
    try:
        yield app
    finally:
        set_session_config(None)


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def test_build_login_redirect_url_includes_params() -> None:
    """Helper composes a Keycloak auth URL with required OIDC params."""
    cfg = _cfg()
    url = build_login_redirect_url(cfg, state="abc", nonce="xyz")
    assert "response_type=code" in url
    assert "client_id=spine-hub" in url
    assert "redirect_uri=" in url
    assert "state=abc" in url and "nonce=xyz" in url


# ---------------------------------------------------------------------------
# Login redirect
# ---------------------------------------------------------------------------


def test_login_returns_302_to_keycloak(client) -> None:
    """``GET /auth/login`` returns a 302 to the Keycloak auth URL."""
    r = client.get("/api/v2/auth/login", follow_redirects=False)
    assert r.status_code == 302
    assert "/protocol/openid-connect/auth" in r.headers["location"]


def test_login_dev_mode_without_oidc_redirects_to_spa(monkeypatch: pytest.MonkeyPatch) -> None:
    """SPINE_HUB_DEV=1 without OIDC config sends users to the SPA, not JSON 500."""
    monkeypatch.setenv("SPINE_HUB_DEV", "1")
    set_session_config(None)
    app = FastAPI()
    install_oidc_routes(app)
    try:
        with TestClient(app) as c:
            r = c.get("/api/v2/auth/login", follow_redirects=False)
            assert r.status_code == 302
            assert r.headers["location"] == "/spa/"
    finally:
        set_session_config(_cfg())


# ---------------------------------------------------------------------------
# Callback sets a signed cookie + stores the session
# ---------------------------------------------------------------------------


def test_callback_sets_session_cookie_and_stores_token(client) -> None:
    """``GET /auth/callback`` exchanges the code + sets ``spine_sid`` cookie."""
    r = client.get(
        "/api/v2/auth/callback",
        params={"code": "xyz123", "state": "s"},
        follow_redirects=False,
    )
    assert r.status_code == 302
    set_cookie = r.headers.get("set-cookie", "")
    assert SESSION_COOKIE_NAME in set_cookie
    # Verify the store actually has a session with the swapped token
    store = get_session_store()
    # Internal: we expect exactly one session with our access token text.
    found = [
        s for s in store._sessions.values()  # noqa: SLF001 — test peeks
        if s.access_token == "access-for-xyz123"
    ]
    assert len(found) == 1


def test_callback_400_when_no_code(client) -> None:
    r = client.get("/api/v2/auth/callback", follow_redirects=False)
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# Logout clears the cookie + invalidates the session
# ---------------------------------------------------------------------------


def test_logout_clears_cookie_and_invalidates_session(client) -> None:
    """Logout deletes the cookie + drops the session from the store."""
    r1 = client.get(
        "/api/v2/auth/callback",
        params={"code": "logout-test", "state": "s"},
        follow_redirects=False,
    )
    assert r1.status_code == 302
    # TestClient persists cookies across requests by default.
    r2 = client.post("/api/v2/auth/logout", follow_redirects=False)
    assert r2.status_code == 302
    cookie_header = r2.headers.get("set-cookie", "")
    assert SESSION_COOKIE_NAME in cookie_header
    # The store should have no remaining "access-for-logout-test" session.
    store = get_session_store()
    assert not any(
        s.access_token == "access-for-logout-test"
        for s in store._sessions.values()  # noqa: SLF001
    )


def test_whoami_returns_authenticated_user(client, oidc_user, monkeypatch) -> None:
    """``GET /auth/whoami`` mirrors registry/me for SPA session probes."""
    monkeypatch.setenv("SPINE_HUB_ID", "hub-auth-probe")
    r = client.get("/api/v2/auth/whoami", headers={"Authorization": "Bearer t"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["user"]["sub"] == "u-1"
    assert body["user"]["hub_id"] == "hub-auth-probe"
