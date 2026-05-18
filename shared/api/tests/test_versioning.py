"""Tests for ``shared.api.versioning`` (V3 Wave 6 Stream J, #30)."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shared.api.versioning import (
    API_V1_PREFIX,
    API_V2_PREFIX,
    API_V3_PREFIX,
    CURRENT_PUBLIC_PREFIX,
    SUPPORTED_PREFIXES,
    V1_TO_V2_REDIRECT_STATUS,
    RedirectV1ToV2Middleware,
    is_supported_version,
    redirect_v1_to_v2_middleware,
    versioned_prefix,
)


def test_prefix_constants_are_distinct_strings() -> None:
    assert API_V1_PREFIX == "/api/v1"
    assert API_V2_PREFIX == "/api/v2"
    assert API_V3_PREFIX == "/api/v3"
    assert CURRENT_PUBLIC_PREFIX == API_V2_PREFIX


def test_v1_is_not_in_supported_prefixes() -> None:
    """v1 is redirect-only, never 'supported' for new routes."""
    assert API_V1_PREFIX not in SUPPORTED_PREFIXES
    assert API_V2_PREFIX in SUPPORTED_PREFIXES


def test_versioned_prefix_joins_correctly() -> None:
    assert versioned_prefix("v2", "integrations") == "/api/v2/integrations"
    assert versioned_prefix("v2", "/integrations") == "/api/v2/integrations"
    assert versioned_prefix("v3", "") == "/api/v3"
    assert versioned_prefix("v1", "decisions") == "/api/v1/decisions"


def test_versioned_prefix_unknown_version_raises() -> None:
    with pytest.raises(ValueError):
        versioned_prefix("v99", "integrations")  # type: ignore[arg-type]


def test_is_supported_version_accepts_label_or_prefix() -> None:
    assert is_supported_version("v2") is True
    assert is_supported_version("/api/v2") is True
    assert is_supported_version("v1") is False
    assert is_supported_version("/api/v1") is False
    assert is_supported_version("") is False
    assert is_supported_version("nonsense") is False


# ---------------------------------------------------------------------------
# v1 -> v2 redirect middleware
# ---------------------------------------------------------------------------


@pytest.fixture
def redirect_app() -> TestClient:
    app = FastAPI()
    redirect_v1_to_v2_middleware(app)

    @app.get("/api/v2/decisions")
    async def decisions() -> dict:
        return {"ok": True}

    @app.get("/api/v2/integrations/{name}")
    async def get_integration(name: str) -> dict:
        return {"name": name}

    return TestClient(app, follow_redirects=False)


def test_v1_redirect_uses_307_and_preserves_path(redirect_app: TestClient) -> None:
    r = redirect_app.get("/api/v1/decisions")
    assert r.status_code == V1_TO_V2_REDIRECT_STATUS
    assert r.headers["location"] == "/api/v2/decisions"


def test_v1_redirect_preserves_query_string(redirect_app: TestClient) -> None:
    r = redirect_app.get("/api/v1/decisions?status=open&since=2026-01-01")
    assert r.status_code == V1_TO_V2_REDIRECT_STATUS
    assert r.headers["location"] == "/api/v2/decisions?status=open&since=2026-01-01"


def test_v1_redirect_emits_deprecation_headers(redirect_app: TestClient) -> None:
    r = redirect_app.get("/api/v1/integrations/github")
    assert r.headers.get("Deprecation") == "true"
    assert "2027" in r.headers.get("Sunset", "")
    assert "successor-version" in r.headers.get("Link", "")


def test_v1_redirect_preserves_method_for_post(redirect_app: TestClient) -> None:
    """307 (not 302) preserves the method — client following the redirect
    would still POST. We assert the status + location are correct."""

    @redirect_app.app.post("/api/v2/decisions")  # type: ignore[attr-defined]
    async def post_decision() -> dict:
        return {"ok": True}

    r = redirect_app.post("/api/v1/decisions", json={"x": 1})
    assert r.status_code == V1_TO_V2_REDIRECT_STATUS
    assert r.headers["location"] == "/api/v2/decisions"


def test_v2_request_is_not_redirected(redirect_app: TestClient) -> None:
    r = redirect_app.get("/api/v2/decisions")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_non_api_request_is_not_redirected(redirect_app: TestClient) -> None:
    # A bogus path that doesn't start with /api/v1 should pass through to
    # the app's normal 404 handler, not the redirect.
    r = redirect_app.get("/healthz")
    assert r.status_code == 404
