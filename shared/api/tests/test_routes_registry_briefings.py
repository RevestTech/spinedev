"""Tests for master briefing preview API."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from shared.api.routes.registry import router


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    return app


def test_preview_master_briefing(oidc_user) -> None:
    client = TestClient(_app())
    r = client.get(
        "/api/v2/registry/master-briefings/preview",
        params={"director": "director_engineering"},
        headers={"Authorization": "Bearer t"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["director"] == "director_engineering"
    assert "Active projects" in body["body"]
