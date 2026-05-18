"""Tests for ``shared.api.routes.decisions`` — auth, ack/reject, SSE."""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shared.api.routes.decisions import (
    DecisionCard,
    enqueue_decision,
    get_store,
    router,
)


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture
def app() -> FastAPI:
    return _build_app()


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app)


def _seed(decision_id: str = "d-1") -> DecisionCard:
    card = DecisionCard(
        decision_id=decision_id,
        decision_class="approval",
        title="Approve release v1.4.5",
        body="release manager requests sign-off",
    )
    enqueue_decision(card)
    return card


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def test_list_decisions_requires_auth(client) -> None:
    """Missing Bearer token rejected (422 when header absent, 401 when malformed)."""
    r = client.get("/api/v2/decisions")
    assert r.status_code in (401, 422)
    r2 = client.get("/api/v2/decisions", headers={"Authorization": "Basic abc"})
    assert r2.status_code == 401


def test_ack_requires_auth(client) -> None:
    """Missing Bearer token rejected on POST too."""
    r = client.post("/api/v2/decisions/d-1/ack")
    assert r.status_code in (401, 422)
    r2 = client.post("/api/v2/decisions/d-1/ack", headers={"Authorization": "Basic abc"})
    assert r2.status_code == 401


# ---------------------------------------------------------------------------
# List + fetch + ack + reject
# ---------------------------------------------------------------------------


def test_list_decisions_returns_seeded_card(client, oidc_user) -> None:
    """A seeded card shows up in the pending list."""
    _seed("d-list")
    r = client.get("/api/v2/decisions", headers={"Authorization": "Bearer t"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert any(item["decision_id"] == "d-list" for item in body["items"])


def test_get_decision_404_when_missing(client, oidc_user) -> None:
    """Unknown decision_id -> 404 with structured error envelope."""
    r = client.get("/api/v2/decisions/nope", headers={"Authorization": "Bearer t"})
    assert r.status_code == 404
    assert r.json()["detail"]["error_code"] == "decision_not_found"


def test_ack_transitions_to_acked_and_audits(client, oidc_user) -> None:
    """ACK transitions the card status to ``acked``."""
    _seed("d-ack")
    r = client.post("/api/v2/decisions/d-ack/ack", headers={"Authorization": "Bearer t"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "acked"
    assert body["actor"] == "u-1"
    assert body["audit_event_uuid"]
    # Confirm store state transitioned
    assert get_store().get("d-ack").status == "acked"


def test_reject_transitions_to_rejected_and_audits(client, oidc_user) -> None:
    """REJECT transitions the card status to ``rejected``."""
    _seed("d-rej")
    r = client.post("/api/v2/decisions/d-rej/reject", headers={"Authorization": "Bearer t"})
    assert r.status_code == 200
    assert r.json()["status"] == "rejected"


def test_ack_404_when_missing(client, oidc_user) -> None:
    """ACK on missing decision -> 404."""
    r = client.post("/api/v2/decisions/missing/ack", headers={"Authorization": "Bearer t"})
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# SSE subscribe — stream a single event and verify framing
# ---------------------------------------------------------------------------


def test_sse_subscribe_unit_streams_card_created_event(oidc_user) -> None:
    """Unit-test the SSE generator directly (Starlette's TestClient blocks on
    streaming generators with no terminal sentinel, so we exercise the
    store's pub/sub contract here without spinning the HTTP layer)."""
    import asyncio

    store = get_store()
    q = store.subscribe()
    try:
        enqueue_decision(
            DecisionCard(
                decision_id="d-sse",
                decision_class="briefing",
                title="hello-from-sse",
            )
        )

        async def _drain() -> dict:
            return await asyncio.wait_for(q.get(), timeout=1.0)

        evt = asyncio.run(_drain())
        assert evt["type"] == "card_created"
        assert evt["card"]["decision_id"] == "d-sse"
    finally:
        store.unsubscribe(q)


def test_sse_endpoint_route_registered(client) -> None:
    """The SSE subscribe route is registered on the app (URL routing test).

    A full streaming-response integration test would block on the
    long-lived generator under Starlette's sync TestClient. The unit
    test above covers the store-side pub/sub contract — here we just
    confirm the route exists by hitting it without auth and asserting
    we don't get a 404.
    """
    r = client.post("/api/v2/decisions/subscribe")
    # No auth -> 422 (header missing) or 401, not 404 -> route is wired.
    assert r.status_code != 404
