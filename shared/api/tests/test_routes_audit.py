"""Tests for ``shared.api.routes.audit`` — filter + cursor pagination.

Wave 3.5 FIX3: ``GET /api/v2/audit`` learned new filters
(``subsystem`` / ``role`` / ``action`` / ``from_ts`` / ``to_ts``) and a
BIGINT ``after_event_id`` cursor with ``next_cursor`` in the response.
"""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shared.api.routes.audit import router


@pytest.fixture
def client(mock_db_pool) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_requires_project_or_correlation(client) -> None:
    """Hard requirement: at least one filter must be present."""
    r = client.get("/api/v2/audit")
    assert r.status_code == 400
    assert r.json()["detail"]["error_code"] == "invalid_input"


def test_uuid_project_id_resolves(client, mock_db_pool) -> None:
    """UUID project_id from the Hub SPA resolves to numeric PK rows."""
    uid = "0b7061be-c5c7-465c-a250-1298a0fb1acd"
    r = client.get("/api/v2/audit", params={"project_id": uid, "limit": "5"})
    assert r.status_code == 200
    sql = mock_db_pool.queries[-1]
    assert "spine_lifecycle.project" in sql
    assert uid in sql
    assert "subject_id" in sql


def test_filter_query_includes_all_axes(client, mock_db_pool) -> None:
    """All optional filters appear in the generated WHERE clause."""
    r = client.get(
        "/api/v2/audit",
        params={
            "project_id": "42",
            "subsystem": "shared",
            "role": "qa",
            "action": "directive_dispatched",
            "from_ts": "2026-01-01T00:00:00Z",
            "to_ts":   "2026-12-31T23:59:59Z",
            "after_event_id": "1234",
            "limit": "10",
        },
    )
    assert r.status_code == 200
    sql = mock_db_pool.queries[-1]
    assert "project_id::text = '42'" in sql
    assert "subsystem = 'shared'" in sql
    assert "role = 'qa'" in sql
    assert "action = 'directive_dispatched'" in sql
    assert "ts >=" in sql and "ts <=" in sql
    assert "event_id > 1234" in sql
    assert "LIMIT 10" in sql


def test_next_cursor_when_page_is_full(client, mock_db_pool) -> None:
    """A full page produces a ``next_cursor`` from the last row's event_id."""
    # Script `limit` rows so the response thinks the page is full.
    page_size = 3
    mock_db_pool.script([
        {"_row": json.dumps({"event_id": i, "action": "x", "ts": "2026-01-01T00:00:00Z"})}
        for i in range(1, page_size + 1)
    ])
    r = client.get("/api/v2/audit", params={"project_id": "1", "limit": str(page_size)})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["next_cursor"] == page_size  # last row event_id


def test_next_cursor_null_when_page_short(client, mock_db_pool) -> None:
    """A short page signals end-of-stream with ``next_cursor=None``."""
    mock_db_pool.script([
        {"_row": json.dumps({"event_id": 1, "action": "x", "ts": "2026-01-01T00:00:00Z"})},
    ])
    r = client.get("/api/v2/audit", params={"project_id": "1", "limit": "100"})
    assert r.status_code == 200
    assert r.json()["next_cursor"] is None
