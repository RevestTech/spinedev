"""Smoke + auth tests for ``shared.api.routes.kg`` (Wave 3 part 2 Squad SPA3).

The KG MCP tools require ``SPINE_DB_URL`` + a live Postgres; we don't have
either in unit tests. So every test here either:

  1. Exercises the auth gate (no DB call), or
  2. Monkey-patches the underlying tool callable to return a canned
     ``ToolResponse`` envelope and asserts our HTTP adapter shapes it
     correctly + emits citations per #12.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shared.api.routes.kg import router
from shared.mcp.schemas.envelopes import ToolError, ToolResponse


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


# ---------------------------------------------------------------------------
# Auth gate
# ---------------------------------------------------------------------------


def test_search_requires_auth(client) -> None:
    r = client.get("/api/v2/kg/search?q=hi&project_id=p&repo=r")
    assert r.status_code in (401, 422)
    r2 = client.get(
        "/api/v2/kg/search?q=hi&project_id=p&repo=r",
        headers={"Authorization": "Basic abc"},
    )
    assert r2.status_code == 401


def test_node_requires_auth(client) -> None:
    r = client.get("/api/v2/kg/node/some-node?project_id=p&repo=r")
    assert r.status_code in (401, 422)


# ---------------------------------------------------------------------------
# kg_unavailable mapping — RuntimeError → 503
# ---------------------------------------------------------------------------


def test_search_503_when_db_unavailable(client, oidc_user, monkeypatch) -> None:
    """Without SPINE_DB_URL the MCP tool raises RuntimeError → adapter 503."""
    from shared.mcp.tools import kg as _kg

    def _boom(_payload):
        raise RuntimeError("SPINE_DB_URL not set; KG tools require an explicit DB URL")

    monkeypatch.setattr(_kg, "hybrid_search", _boom)
    r = client.get(
        "/api/v2/kg/search?q=hello&project_id=demo&repo=spine",
        headers={"Authorization": "Bearer t"},
    )
    assert r.status_code == 503
    assert r.json()["detail"]["error_code"] == "kg_unavailable"


# ---------------------------------------------------------------------------
# Happy paths via monkey-patched tools
# ---------------------------------------------------------------------------


def test_search_shapes_results_and_emits_citations(client, oidc_user, monkeypatch) -> None:
    from shared.mcp.tools import kg as _kg

    canned = ToolResponse(
        status="ok",
        data={
            "results": [
                {
                    "node_id": "node-1",
                    "name": "executor.run",
                    "type": "Function",
                    "path": "lib/executor.sh:42",
                    "combined_score": 0.91,
                    "rationale": "name match",
                    "semantic_score": 0.8,
                    "structural_score": 0.95,
                },
                {
                    "node_id": "node-2",
                    "name": "Executor",
                    "type": "Class",
                    "path": "lib/executor.sh:1",
                    "combined_score": 0.55,
                    "rationale": "neighbour",
                    "semantic_score": 0.3,
                    "structural_score": 0.7,
                },
            ],
        },
    )
    monkeypatch.setattr(_kg, "hybrid_search", lambda _p: canned)
    r = client.get(
        "/api/v2/kg/search?q=executor&project_id=demo&repo=spine",
        headers={"Authorization": "Bearer t"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    assert body["results"][0]["node_id"] == "node-1"
    # Per #12 — citations array contains one kg_node ref per result.
    assert len(body["citations"]) == 2
    assert body["citations"][0]["type"] == "kg_node"
    assert {c["ref"] for c in body["citations"]} == {"node-1", "node-2"}


def test_callers_endpoint_shapes_response(client, oidc_user, monkeypatch) -> None:
    from shared.mcp.tools import kg as _kg

    canned = ToolResponse(
        status="ok",
        data={
            "callers": [
                {"node_id": "n-99", "name": "caller_a", "type": "Function",
                 "path": "lib/foo.py:10", "depth": 1},
                {"node_id": "n-100", "name": "caller_b", "type": "Function",
                 "path": "lib/bar.py:5", "depth": 2},
            ],
        },
    )
    monkeypatch.setattr(_kg, "find_callers", lambda _p: canned)
    r = client.get(
        "/api/v2/kg/callers/mod.func?project_id=demo&repo=spine",
        headers={"Authorization": "Bearer t"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["symbol"] == "mod.func"
    assert body["total"] == 2
    assert body["citations"][0]["type"] == "kg_node"


def test_impact_endpoint_passes_target_type(client, oidc_user, monkeypatch) -> None:
    from shared.mcp.tools import kg as _kg

    received: dict = {}

    def _capture(payload):
        received["target"] = payload.target
        received["target_type"] = payload.target_type
        return ToolResponse(status="ok", data={
            "impacted": [{"node_id": "n-1", "type": "TestCase", "path": "t.py",
                          "impact_distance": 1, "impact_kind": "test"}],
            "direct_caller_count": 0, "direct_test_count": 1,
            "importer_count": 0, "total_impact": 1,
        })

    monkeypatch.setattr(_kg, "impact_radius", _capture)
    r = client.get(
        "/api/v2/kg/impact/lib/executor.sh?project_id=demo&repo=spine&target_type=file",
        headers={"Authorization": "Bearer t"},
    )
    assert r.status_code == 200
    assert received["target_type"] == "file"
    body = r.json()
    assert body["direct_test_count"] == 1
    assert body["citations"][0]["ref"] == "n-1"


def test_owners_endpoint_emits_path_citation(client, oidc_user, monkeypatch) -> None:
    from shared.mcp.tools import kg as _kg

    canned = ToolResponse(status="ok", data={"owners": [
        {"owner_type": "Role", "owner_id": "engineer", "confidence": 0.9, "via": "OWNED_BY"},
    ]})
    monkeypatch.setattr(_kg, "who_owns", lambda _p: canned)
    r = client.get(
        "/api/v2/kg/owners/lib/foo.py?project_id=demo&repo=spine",
        headers={"Authorization": "Bearer t"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["owners"][0]["owner_id"] == "engineer"
    # Owners aren't necessarily KG nodes; we cite the queried path itself.
    assert body["citations"] and body["citations"][0]["ref"] == "lib/foo.py"


def test_tool_error_becomes_422(client, oidc_user, monkeypatch) -> None:
    from shared.mcp.tools import kg as _kg

    def _err(_p):
        return ToolResponse(
            status="error",
            error=ToolError(code="no_filter", message="needs node_type", retryable=False),
        )

    monkeypatch.setattr(_kg, "hybrid_search", _err)
    r = client.get(
        "/api/v2/kg/search?q=x&project_id=demo&repo=spine",
        headers={"Authorization": "Bearer t"},
    )
    assert r.status_code == 422
    assert r.json()["detail"]["error_code"] == "no_filter"
