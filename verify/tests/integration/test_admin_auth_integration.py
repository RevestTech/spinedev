"""Product admin UI session: POST /api/admin/login, cookie auth on /api/admin/me."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
async def auth_client(test_app, sqlite_db):
    from tron.infra.db.session import get_session

    async def _override_session():
        async with sqlite_db() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    test_app.dependency_overrides[get_session] = _override_session

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    test_app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_admin_login_master_fallback_then_me(auth_client):
    r = await auth_client.post("/api/admin/login", json={"password": "tron_test_key_001"})
    assert r.status_code == 200
    assert r.json().get("ok") is True
    me = await auth_client.get("/api/admin/me")
    assert me.status_code == 200


@pytest.mark.asyncio
async def test_admin_login_invalid_password(auth_client):
    r = await auth_client.post("/api/admin/login", json={"password": "wrong-password"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_admin_login_strips_vault_admin_password_edges(auth_client, monkeypatch):
    """KMac / shell-set secrets often include leading/trailing whitespace."""
    from tron.api.routes import admin_auth

    async def fake_get_secret(key: str, *, field_name: str = "value"):
        assert key == "auth/admin-password"
        return "  ui-secret-value\n"

    monkeypatch.setattr(admin_auth, "get_secret", fake_get_secret)

    r = await auth_client.post("/api/admin/login", json={"password": "ui-secret-value"})
    assert r.status_code == 200
    me = await auth_client.get("/api/admin/me")
    assert me.status_code == 200


@pytest.mark.asyncio
async def test_admin_logout_clears_session(auth_client):
    await auth_client.post("/api/admin/login", json={"password": "tron_test_key_001"})
    lo = await auth_client.post("/api/admin/logout")
    assert lo.status_code == 200
    me = await auth_client.get("/api/admin/me")
    assert me.status_code == 401
