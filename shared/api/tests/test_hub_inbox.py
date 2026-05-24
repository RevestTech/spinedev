"""Tests for ``/api/v2/hub/inbox`` and decision scope filtering."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shared.api.routes.decisions import DecisionCard, enqueue_decision, router as decisions_router
from shared.api.routes.hub_inbox import router as hub_inbox_router


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(decisions_router)
    app.include_router(hub_inbox_router)
    return app


@pytest.fixture
def client() -> TestClient:
    return TestClient(_build_app())


def _seed(card: DecisionCard) -> DecisionCard:
    enqueue_decision(card)
    return card


def test_hub_inbox_requires_auth(client: TestClient) -> None:
    r = client.get("/api/v2/hub/inbox")
    assert r.status_code in (401, 422)


def test_hub_inbox_lists_master_briefings_only(client: TestClient, oidc_user) -> None:
    _seed(
        DecisionCard(
            decision_id="hub-brief-1",
            decision_class="briefing",
            title="Security daily briefing",
            body="Portfolio rollup.",
            metadata={"kind": "master_daily_briefing", "director": "director_security"},
        )
    )
    _seed(
        DecisionCard(
            decision_id="proj-approval-1",
            decision_class="approval",
            project_id="9",
            title="Approve CODE output",
            body="Engineer proposes refactor.",
            metadata={"project_uuid": "uuid-9"},
        )
    )

    r = client.get("/api/v2/hub/inbox", headers={"Authorization": "Bearer t"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    ids = {item["decision_id"] for item in body["items"]}
    assert "hub-brief-1" in ids
    assert "proj-approval-1" not in ids


def test_decisions_default_scope_excludes_hub_inbox(client: TestClient, oidc_user) -> None:
    _seed(
        DecisionCard(
            decision_id="hub-brief-2",
            decision_class="briefing",
            title="DevOps daily briefing",
            metadata={"kind": "master_daily_briefing"},
        )
    )
    _seed(
        DecisionCard(
            decision_id="proj-approval-2",
            decision_class="approval",
            project_id="42",
            title="Approve TRD",
            metadata={"project_uuid": "uuid-42"},
        )
    )

    r = client.get("/api/v2/decisions", headers={"Authorization": "Bearer t"})
    assert r.status_code == 200
    ids = {item["decision_id"] for item in r.json()["items"]}
    assert "proj-approval-2" in ids
    assert "hub-brief-2" not in ids


def test_decisions_scope_all_includes_both(client: TestClient, oidc_user) -> None:
    _seed(
        DecisionCard(
            decision_id="hub-brief-3",
            decision_class="briefing",
            title="Product daily briefing",
            metadata={"kind": "master_daily_briefing"},
        )
    )
    _seed(
        DecisionCard(
            decision_id="proj-approval-3",
            decision_class="release",
            title="Cut v1.0",
        )
    )

    r = client.get(
        "/api/v2/decisions?scope=all",
        headers={"Authorization": "Bearer t"},
    )
    assert r.status_code == 200
    ids = {item["decision_id"] for item in r.json()["items"]}
    assert "hub-brief-3" in ids
    assert "proj-approval-3" in ids
