"""Tests for ``shared.api.middleware.feature_flag``."""

from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from shared.api.middleware import feature_flag as ff


@pytest.fixture
def app(monkeypatch) -> FastAPI:
    app = FastAPI()

    @app.get(
        "/needs-fed",
        dependencies=[Depends(ff.require_feature_flag("federation"))],
    )
    def needs_fed() -> dict:
        return {"ok": True}

    return app


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app)


def test_unknown_flag_raises_at_registration_time() -> None:
    """A typo at decoration time fails loudly."""
    with pytest.raises(KeyError):
        ff.require_feature_flag("not-a-real-flag")


def test_enabled_flag_allows_request(client) -> None:
    """When ``is_feature_enabled`` returns True the request goes through."""
    r = client.get("/needs-fed")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_disabled_flag_returns_402_with_upgrade_path(monkeypatch, client) -> None:
    """When the flag is disabled the request gets 402 Payment Required."""
    monkeypatch.setattr(ff, "is_feature_enabled", lambda flag: False, raising=True)
    r = client.get("/needs-fed")
    assert r.status_code == 402
    body = r.json()
    assert body["detail"]["error_code"] == "feature_disabled"
    assert body["detail"]["feature_flag"] == "federation"
    assert body["detail"]["upgrade_path"]


def test_is_feature_enabled_unknown_flag_raises() -> None:
    """Unknown flag at evaluation time also raises (defensive)."""
    with pytest.raises(KeyError):
        ff.is_feature_enabled("totally-unknown")


def test_feature_flag_dependency_returns_a_depends_object() -> None:
    """The wrapper returns a FastAPI ``Depends(...)`` for inline use."""
    dep = ff.feature_flag_dependency("federation")
    # FastAPI ``Depends`` has a ``dependency`` attribute on its inst.
    assert hasattr(dep, "dependency")
