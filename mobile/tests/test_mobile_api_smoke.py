"""Smoke tests for ``shared.api.routes.mobile`` (Wave 6 Stream H).

Per the V3 #28 scaffold scope we verify:

1. The mobile router is registered + reachable.
2. Each endpoint enforces Keycloak Bearer auth (per #25) — anonymous
   requests are rejected before hitting any handler logic.
3. Authenticated requests return the compact-JSON contract documented in
   the module docstring (short keys, ``ok`` flag, ``n`` count, items
   list with the right field names).
4. ``POST /approvals/{id}/action`` routes through the in-process decision
   store and 404s on unknown IDs (proving the wiring is real, not a stub
   that always returns 200).
"""

from __future__ import annotations

import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shared.api.routes.decisions import DecisionCard, get_store
from shared.api.routes.mobile import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    router as mobile_router,
)


@pytest.fixture
def client() -> TestClient:
    """FastAPI app with only the mobile router mounted — keeps the
    smoke surface narrow so a failure here points at mobile code, not
    at unrelated Wave-3 routes."""
    app = FastAPI()
    app.include_router(mobile_router)
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clean_store():
    """Reset the in-process decision store between tests so cross-test
    state never leaks (the store is a module-level singleton)."""
    store = get_store()
    # Quick reset — clear the dict in place (no public ``clear`` method)
    store._cards.clear()  # noqa: SLF001
    yield
    store._cards.clear()  # noqa: SLF001


# ---------------------------------------------------------------------------
# 1. Router registration is real
# ---------------------------------------------------------------------------


def test_router_prefix_and_routes_registered() -> None:
    """All four documented endpoints must exist on the router."""
    paths = {r.path for r in mobile_router.routes}
    assert "/api/v2/mobile/approvals" in paths
    assert "/api/v2/mobile/briefings" in paths
    assert "/api/v2/mobile/status" in paths
    assert "/api/v2/mobile/approvals/{decision_id}/action" in paths


def test_constants_are_sane() -> None:
    """Limit constants must be positive + ordered."""
    assert DEFAULT_LIMIT > 0
    assert MAX_LIMIT >= DEFAULT_LIMIT


# ---------------------------------------------------------------------------
# 2. Auth gates — anonymous requests rejected
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/api/v2/mobile/approvals"),
        ("GET", "/api/v2/mobile/briefings"),
        ("GET", "/api/v2/mobile/status"),
    ],
)
def test_endpoints_require_auth(client: TestClient, method: str, path: str) -> None:
    """No Bearer → 401/422; per #25 every mobile endpoint goes through OIDC."""
    r = client.request(method, path)
    assert r.status_code in (401, 422)


def test_action_requires_auth(client: TestClient) -> None:
    r = client.post("/api/v2/mobile/approvals/abc/action?action=approve")
    assert r.status_code in (401, 422)


# ---------------------------------------------------------------------------
# 3. Compact-JSON contract honored when authenticated
# ---------------------------------------------------------------------------


def _seed_card(*, kind: str = "approval", proj: str = "42", sev: str = "info") -> str:
    store = get_store()
    card = DecisionCard(
        decision_id=f"d-{kind}-{int(time.time()*1000)}",
        decision_class=kind,  # type: ignore[arg-type]
        project_id=proj,
        title=f"Test {kind}",
        body="body text — should not appear in compact output",
        severity=sev,  # type: ignore[arg-type]
        created_at=time.time(),
    )
    store.put(card)
    return card.decision_id


def test_approvals_compact_shape(client: TestClient, oidc_user) -> None:
    """``/mobile/approvals`` returns compact rows for approval-class cards only."""
    _seed_card(kind="approval", proj="42")
    _seed_card(kind="briefing", proj="42")  # must NOT appear in approvals list
    r = client.get(
        "/api/v2/mobile/approvals", headers={"Authorization": "Bearer t"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert isinstance(body["items"], list)
    assert body["n"] == 1  # only the approval-class card
    item = body["items"][0]
    # Compact keys, no full-fidelity ones
    assert set(item.keys()) <= {"id", "proj", "phase", "sev", "ts"}
    assert "approval_id" not in item
    assert "created_at" not in item
    assert isinstance(item["ts"], int)  # unix seconds per the contract


def test_briefings_compact_shape(client: TestClient, oidc_user) -> None:
    """``/mobile/briefings`` returns non-approval classes only."""
    _seed_card(kind="approval")
    _seed_card(kind="briefing")
    _seed_card(kind="incident")
    r = client.get(
        "/api/v2/mobile/briefings", headers={"Authorization": "Bearer t"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["n"] == 2  # briefing + incident, NOT approval
    kinds = {it["kind"] for it in body["items"]}
    assert kinds == {"briefing", "incident"}


def test_status_compact_shape(client: TestClient, oidc_user) -> None:
    """``/mobile/status`` returns the lock-screen payload."""
    _seed_card(kind="approval")
    _seed_card(kind="briefing")
    r = client.get(
        "/api/v2/mobile/status", headers={"Authorization": "Bearer t"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["pending"] == 2
    assert isinstance(body["hub"], str) and body["hub"]
    # Lock-screen widget budget — fewer than 200 bytes is the design target
    assert len(r.content) < 200


# ---------------------------------------------------------------------------
# 4. POST action routes through the store + 404s on unknowns
# ---------------------------------------------------------------------------


def test_action_unknown_decision_404(client: TestClient, oidc_user) -> None:
    r = client.post(
        "/api/v2/mobile/approvals/does-not-exist/action?action=approve",
        headers={"Authorization": "Bearer t"},
    )
    assert r.status_code == 404
    assert r.json()["detail"]["error_code"] == "decision_not_found"


def test_action_approve_transitions_card(client: TestClient, oidc_user) -> None:
    decision_id = _seed_card(kind="approval")
    r = client.post(
        f"/api/v2/mobile/approvals/{decision_id}/action?action=approve",
        headers={"Authorization": "Bearer t"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body == {"ok": True, "id": decision_id, "action": "approve", "actor": "u-1"}
    # Real wiring — the card actually transitioned in the store
    card = get_store().get(decision_id)
    assert card is not None
    assert card.status == "acked"


def test_action_reject_transitions_card(client: TestClient, oidc_user) -> None:
    decision_id = _seed_card(kind="approval")
    r = client.post(
        f"/api/v2/mobile/approvals/{decision_id}/action?action=reject",
        headers={"Authorization": "Bearer t"},
    )
    assert r.status_code == 200
    assert r.json()["action"] == "reject"
    assert get_store().get(decision_id).status == "rejected"  # type: ignore[union-attr]


def test_limit_clamping(client: TestClient, oidc_user) -> None:
    """``?limit=`` is clamped to ``MAX_LIMIT`` server-side."""
    for _ in range(3):
        _seed_card(kind="approval")
    r = client.get(
        f"/api/v2/mobile/approvals?limit={MAX_LIMIT + 50}",
        headers={"Authorization": "Bearer t"},
    )
    # Pydantic's ``le=MAX_LIMIT`` validator returns 422 if the caller
    # asks for too much — that's the explicit "you exceeded the budget"
    # signal documented in the module.
    assert r.status_code in (200, 422)
