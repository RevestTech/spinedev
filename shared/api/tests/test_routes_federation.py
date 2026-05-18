"""Smoke + auth tests for ``shared.api.routes.federation``."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shared.api.routes.federation import router


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_hubs_requires_auth(client) -> None:
    r = client.get("/api/v2/federation/hubs")
    # Federation routes also have a feature-flag dep (always returns OK in
    # Wave 3 stub), so a missing auth header surfaces as 422 (missing required
    # Authorization Header) or 401 (malformed Bearer).
    assert r.status_code in (401, 422)
    r2 = client.get("/api/v2/federation/hubs", headers={"Authorization": "Basic abc"})
    assert r2.status_code == 401


def test_register_child_requires_hub_admin(client, oidc_user) -> None:
    """Plain user cannot register a child Hub -> 403."""
    r = client.post(
        "/api/v2/federation/register-child",
        json={
            "hub_id": "child-1",
            "name": "Child Hub",
            "url": "https://child.example/",
            "rationale": "test",
        },
        headers={"Authorization": "Bearer t"},
    )
    assert r.status_code == 403


def test_register_child_succeeds_for_admin_and_shows_up_in_status(
    client, oidc_hub_admin
) -> None:
    """Hub-admin registers a child; status reflects children_count."""
    r = client.post(
        "/api/v2/federation/register-child",
        json={
            "hub_id": "child-2",
            "name": "Child Two",
            "url": "https://child2.example/",
            "rationale": "test",
        },
        headers={"Authorization": "Bearer t"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["ok"] is True
    assert body["audit_event_uuid"]

    r2 = client.get("/api/v2/federation/status", headers={"Authorization": "Bearer t"})
    assert r2.status_code == 200
    assert r2.json()["children_count"] >= 1


def test_consent_decision_persists(client, oidc_hub_admin) -> None:
    """Recorded consent flips the hub's consent field on the next list."""
    client.post(
        "/api/v2/federation/consent",
        json={"hub_id": "peer-3", "decision": "accepted", "rationale": "trust"},
        headers={"Authorization": "Bearer t"},
    )
    r = client.get("/api/v2/federation/hubs", headers={"Authorization": "Bearer t"})
    assert r.status_code == 200
    found = [h for h in r.json()["items"] if h["hub_id"] == "peer-3"]
    assert found and found[0]["consent"] == "accepted"
