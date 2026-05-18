"""Tests for ``shared.api.rate_limit`` (V3 Wave 6 Stream J, #30).

Exercises:

* Token-bucket consume + refill math.
* Per-(org, flag) bucket isolation.
* Route -> flag longest-prefix mapping.
* Middleware end-to-end via TestClient: 429 + Retry-After header on
  exhausted bucket, headers on allowed responses.
* Fail-open behaviour when no provider is configured / pool is missing.
"""

from __future__ import annotations

from typing import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shared.api.rate_limit import (
    DEFAULT_ORG_ID,
    ORG_ID_HEADER,
    QUOTA_UNIT_WINDOWS_SECONDS,
    RateLimitMiddleware,
    _STORE,
    get_bucket_store,
    install_rate_limit_middleware,
    map_route_to_flag,
    reset_bucket_store,
    set_quota_provider,
)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_quota_unit_windows_cover_rate_units() -> None:
    """rate-shaped units must map to a wall-clock window."""
    for unit in ("runs_per_day", "tokens_per_day", "agents_per_month"):
        assert unit in QUOTA_UNIT_WINDOWS_SECONDS
        assert QUOTA_UNIT_WINDOWS_SECONDS[unit] > 0
    # Non-rate units must NOT have a window (semantic caps).
    assert "projects" not in QUOTA_UNIT_WINDOWS_SECONDS
    assert "seats" not in QUOTA_UNIT_WINDOWS_SECONDS


def test_route_to_flag_longest_prefix() -> None:
    assert map_route_to_flag("/api/v2/integrations/github") == "integration_github"
    assert map_route_to_flag("/api/v2/integrations/github/test-connection") == "integration_github"
    assert map_route_to_flag("/api/v2/federation/hubs") == "federation"
    assert map_route_to_flag("/api/v2/projects/p1") == "quota_max_concurrent_runs"
    assert map_route_to_flag("/api/v2/decisions/x") == "hub_admin"
    assert map_route_to_flag("/api/v1/anything") is None
    assert map_route_to_flag("/healthz") is None


# ---------------------------------------------------------------------------
# Bucket math
# ---------------------------------------------------------------------------


@pytest.fixture
def store_reset() -> Iterator[None]:
    reset_bucket_store()
    try:
        yield
    finally:
        set_quota_provider(None)
        reset_bucket_store()


def test_bucket_allows_then_blocks(store_reset: None) -> None:
    """A 3-token bucket allows 3 calls then blocks the 4th."""
    import asyncio

    async def provider(_org: str, _flag: str):
        return (3, "runs_per_day")

    store = get_bucket_store()

    now = [1000.0]

    def now_fn() -> float:
        return now[0]

    async def _run() -> None:
        for _ in range(3):
            allowed, bucket, retry = await store.consume(
                org_id="acme", flag_name="integration_github",
                provider=provider, now_fn=now_fn,
            )
            assert allowed is True
            assert bucket is not None
            assert retry == 0.0

        allowed, bucket, retry = await store.consume(
            org_id="acme", flag_name="integration_github",
            provider=provider, now_fn=now_fn,
        )
        assert allowed is False
        assert bucket is not None
        # 3 tokens / 86400s = 3.47e-5 tok/s -> ~28800s per token.
        assert retry > 0

    asyncio.run(_run())


def test_bucket_unlimited_when_quota_none(store_reset: None) -> None:
    """quota_value=None -> bucket is None, always allowed."""
    import asyncio

    async def provider(_org: str, _flag: str):
        return (None, None)

    store = get_bucket_store()

    async def _run() -> None:
        for _ in range(50):
            allowed, bucket, retry = await store.consume(
                org_id="acme", flag_name="integration_github",
                provider=provider,
            )
            assert allowed is True
            assert bucket is None
            assert retry == 0.0

    asyncio.run(_run())


def test_bucket_isolation_per_org(store_reset: None) -> None:
    """Two orgs share a flag but not a bucket."""
    import asyncio

    async def provider(_org: str, _flag: str):
        return (1, "runs_per_day")

    store = get_bucket_store()

    async def _run() -> None:
        a1, _, _ = await store.consume(
            org_id="org-a", flag_name="federation", provider=provider,
        )
        b1, _, _ = await store.consume(
            org_id="org-b", flag_name="federation", provider=provider,
        )
        assert a1 is True
        assert b1 is True  # b's bucket is independent of a's.

        a2, _, _ = await store.consume(
            org_id="org-a", flag_name="federation", provider=provider,
        )
        assert a2 is False  # a is now empty.

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Middleware end-to-end
# ---------------------------------------------------------------------------


@pytest.fixture
def app_with_quota(monkeypatch) -> TestClient:
    """A FastAPI app with the rate-limit middleware + a single test route."""
    reset_bucket_store()

    async def fake_provider(_org: str, _flag: str):
        # Tiny bucket -> easy to exhaust in a test.
        return (2, "runs_per_day")

    set_quota_provider(fake_provider)

    app = FastAPI()
    install_rate_limit_middleware(app)

    @app.get("/api/v2/integrations/github/{name}")
    async def _route(name: str) -> dict:
        return {"name": name}

    @app.get("/healthz")
    async def _hz() -> dict:
        return {"ok": True}

    client = TestClient(app, raise_server_exceptions=True)
    yield client
    set_quota_provider(None)
    reset_bucket_store()


def test_middleware_skips_health(app_with_quota: TestClient) -> None:
    """/healthz is not in ROUTE_FLAG_MAP, so it passes through untouched."""
    for _ in range(5):
        r = app_with_quota.get("/healthz")
        assert r.status_code == 200
        assert "X-Spine-Rate-Limit-Flag" not in r.headers


def test_middleware_allows_then_429s(app_with_quota: TestClient) -> None:
    headers = {ORG_ID_HEADER: "acme"}
    r1 = app_with_quota.get("/api/v2/integrations/github/repo", headers=headers)
    assert r1.status_code == 200
    assert r1.headers.get("X-Spine-Rate-Limit-Flag") == "integration_github"

    r2 = app_with_quota.get("/api/v2/integrations/github/repo", headers=headers)
    assert r2.status_code == 200

    r3 = app_with_quota.get("/api/v2/integrations/github/repo", headers=headers)
    assert r3.status_code == 429
    assert int(r3.headers["Retry-After"]) >= 1
    body = r3.json()
    assert body["error_code"] == "rate_limited"
    assert body["feature_flag"] == "integration_github"
    assert body["quota_value"] == 2
    assert body["quota_unit"] == "runs_per_day"


def test_middleware_options_is_not_billed(app_with_quota: TestClient) -> None:
    """OPTIONS preflight is skipped — does not consume tokens."""
    for _ in range(10):
        r = app_with_quota.options("/api/v2/integrations/github/repo")
        # No route handler => 405 or 200; either way no 429.
        assert r.status_code != 429


def test_middleware_uses_default_org_when_header_missing(
    app_with_quota: TestClient,
) -> None:
    """No X-Spine-Org-ID header -> falls back to DEFAULT_ORG_ID bucket."""
    r1 = app_with_quota.get("/api/v2/integrations/github/repo")
    assert r1.status_code == 200
    r2 = app_with_quota.get("/api/v2/integrations/github/repo")
    assert r2.status_code == 200
    r3 = app_with_quota.get("/api/v2/integrations/github/repo")
    # 2-token bucket exhausted under DEFAULT_ORG_ID.
    assert r3.status_code == 429


def test_middleware_fail_open_when_provider_none(monkeypatch) -> None:
    """Provider returning (None, None) -> no rate limit applied."""
    reset_bucket_store()

    async def open_provider(_org: str, _flag: str):
        return (None, None)

    set_quota_provider(open_provider)
    try:
        app = FastAPI()
        install_rate_limit_middleware(app)

        @app.get("/api/v2/integrations/github/x")
        async def _r() -> dict:
            return {"ok": True}

        client = TestClient(app)
        for _ in range(20):
            r = client.get("/api/v2/integrations/github/x")
            assert r.status_code == 200
        # No quota -> no rate-limit headers either.
        assert "X-Spine-Rate-Limit-Flag" not in r.headers
    finally:
        set_quota_provider(None)
        reset_bucket_store()
