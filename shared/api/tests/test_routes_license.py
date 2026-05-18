"""Smoke + auth tests for ``shared.api.routes.license``."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shared.api.routes.license import router


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_license_requires_auth(client) -> None:
    r = client.get("/api/v2/license")
    assert r.status_code in (401, 422)
    r2 = client.get("/api/v2/license", headers={"Authorization": "Basic abc"})
    assert r2.status_code == 401


def test_license_returns_tier_flags_citation(client, oidc_user) -> None:
    """``/license`` returns the tier + a flags array + a citation (per #12)."""
    r = client.get("/api/v2/license", headers={"Authorization": "Bearer t"})
    assert r.status_code == 200
    body = r.json()
    assert body["tier"] in {"free", "founder", "team", "enterprise", "airgapped"}
    assert isinstance(body["flags"], list) and len(body["flags"]) > 5
    # Per #12 — citation field must be present and non-empty on verify-class.
    assert body["citation"]


def test_license_usage_returns_zero_counters_and_citation(client, oidc_user) -> None:
    """Wave 3 part 1 stubs counters at 0; the contract is the shape."""
    r = client.get("/api/v2/license/usage", headers={"Authorization": "Bearer t"})
    assert r.status_code == 200
    body = r.json()
    assert all(item["count"] == 0 for item in body["items"])
    assert body["citation"]
