"""Smoke + auth tests for ``shared.api.routes.registry``."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shared.api.routes.registry import router


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_roles_requires_auth(client) -> None:
    r = client.get("/api/v2/registry/roles")
    assert r.status_code in (401, 422)
    r2 = client.get("/api/v2/registry/roles", headers={"Authorization": "Basic abc"})
    assert r2.status_code == 401


def test_integrations_requires_auth(client) -> None:
    r = client.get("/api/v2/registry/integrations")
    assert r.status_code in (401, 422)
    r2 = client.get("/api/v2/registry/integrations", headers={"Authorization": "Basic abc"})
    assert r2.status_code == 401


def test_roles_contains_both_master_and_project_tiers(client, oidc_user) -> None:
    """Catalog should include at least one master + one project role."""
    r = client.get("/api/v2/registry/roles", headers={"Authorization": "Bearer t"})
    assert r.status_code == 200
    items = r.json()["items"]
    tiers = {item["tier"] for item in items}
    assert "master" in tiers and "project" in tiers
    names = {item["name"] for item in items}
    # Spot-check a few known roles required by #19
    assert "devops" in names and "release_manager" in names


def test_integrations_lists_known_connectors(client, oidc_user) -> None:
    """Integration catalog contains GitHub + Vanta + Slack (per #24/#6/#3)."""
    r = client.get("/api/v2/registry/integrations", headers={"Authorization": "Bearer t"})
    assert r.status_code == 200
    names = {item["name"] for item in r.json()["items"]}
    assert {"github", "slack", "vanta"}.issubset(names)
