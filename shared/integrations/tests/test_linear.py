"""Tests for ``shared.integrations.linear`` — canonical Linear adapter.

Covers:

* LinearConnector public API matches what ``migration/onboarding.py``
  used to expose inline (GraphQL pagination, comment fetch, team-key
  filtering, label-driven classification).
* Vault path template includes the per-workspace namespace.
* LinearAdapter.test_connection returns the documented probe envelope.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import pytest

from shared.integrations.linear import (
    DEFAULT_API_URL,
    LinearAdapter,
    LinearConnector,
    VAULT_PATH_API_KEY_TMPL,
)
from shared.integrations.linear import test_connection as probe_connection


# ---------------------------------------------------------------------------
# Local scripted HTTP client — single-use, FIFO (mirrors onboarding tests)
# ---------------------------------------------------------------------------


@dataclass
class _ScriptedHttp:
    calls: list[tuple[str, dict[str, str]]] = field(default_factory=list)
    scripts: list[tuple[str, Any]] = field(default_factory=list)

    def script(self, sub: str, body: Any) -> None:
        self.scripts.append((sub, body))

    def get_json(self, url: str, *, headers: dict[str, str]) -> dict[str, Any]:
        self.calls.append((url, dict(headers)))
        for i, (sub, body) in enumerate(self.scripts):
            if sub in url:
                self.scripts.pop(i)
                return {"status_code": 200, "body": body}
        return {"status_code": 404, "body": {}}


@pytest.fixture
def mock_http() -> _ScriptedHttp:
    return _ScriptedHttp()


@pytest.fixture
def stub_loader():
    async def _loader(path: str) -> str:
        return f"token-for-{path}"

    return _loader


# ---------------------------------------------------------------------------
# Vault path scheme
# ---------------------------------------------------------------------------


def test_vault_path_includes_workspace() -> None:
    assert VAULT_PATH_API_KEY_TMPL.format(workspace="acme") == (
        "integration/linear/acme/api_key"
    )


def test_default_api_url_is_linear_graphql() -> None:
    assert DEFAULT_API_URL == "https://api.linear.app/graphql"


# ---------------------------------------------------------------------------
# LinearConnector — GraphQL pagination + mapping
# ---------------------------------------------------------------------------


def test_connector_paginates_through_graphql(mock_http, stub_loader) -> None:
    mock_http.script("graphql", {
        "data": {"issues": {
            "pageInfo": {"hasNextPage": True, "endCursor": "abc"},
            "nodes": [
                {"id": "i1", "identifier": "SPI-1", "title": "Linear bug",
                 "description": "broken",
                 "state": {"name": "Todo", "type": "unstarted"},
                 "url": "https://linear.app/i1",
                 "createdAt": "2026-05-01T00:00:00Z",
                 "updatedAt": "2026-05-02T00:00:00Z",
                 "labels": {"nodes": [{"name": "bug"}]},
                 "assignee": {"name": "Bob", "email": "bob@acme.com"},
                 "team": {"key": "SPI", "name": "Spine"}},
            ],
        }},
    })
    mock_http.script("graphql", {
        "data": {"issues": {
            "pageInfo": {"hasNextPage": False, "endCursor": None},
            "nodes": [
                {"id": "i2", "identifier": "SPI-2", "title": "Linear infra ask",
                 "description": "ops",
                 "state": {"name": "Backlog", "type": "backlog"},
                 "url": "https://linear.app/i2",
                 "createdAt": "", "updatedAt": "",
                 "labels": {"nodes": [{"name": "infra"}]},
                 "assignee": None,
                 "team": {"key": "SPI", "name": "Spine"}},
            ],
        }},
    })

    c = LinearConnector(
        http=mock_http, workspace="acme", token_loader=stub_loader,
    )
    issues = c.import_issues()
    assert {i["identifier"] for i in issues} == {"SPI-1", "SPI-2"}

    mapped = c.map_to_spine_workitems(issues=issues)
    types = {m.source_id: m.work_item_type for m in mapped}
    assert types["SPI-1"] == "bug"
    assert types["SPI-2"] == "infra"


def test_connector_team_filter_applies(mock_http, stub_loader) -> None:
    mock_http.script("graphql", {
        "data": {"issues": {
            "pageInfo": {"hasNextPage": False, "endCursor": None},
            "nodes": [
                {"id": "i1", "identifier": "AAA-1", "title": "x",
                 "description": "",
                 "state": {"name": "x", "type": "unstarted"},
                 "url": "x", "createdAt": "", "updatedAt": "",
                 "labels": {"nodes": []}, "assignee": None,
                 "team": {"key": "AAA", "name": "Team A"}},
                {"id": "i2", "identifier": "BBB-1", "title": "y",
                 "description": "",
                 "state": {"name": "y", "type": "unstarted"},
                 "url": "y", "createdAt": "", "updatedAt": "",
                 "labels": {"nodes": []}, "assignee": None,
                 "team": {"key": "BBB", "name": "Team B"}},
            ],
        }},
    })
    c = LinearConnector(
        http=mock_http, workspace="acme",
        team_keys=("BBB",), token_loader=stub_loader,
    )
    issues = c.import_issues()
    assert [i["identifier"] for i in issues] == ["BBB-1"]


def test_connector_import_repos_returns_empty(mock_http, stub_loader) -> None:
    """Linear has no concept of repos; return [] without hitting the network."""
    c = LinearConnector(
        http=mock_http, workspace="acme", token_loader=stub_loader,
    )
    assert c.import_repos() == []
    assert mock_http.calls == []  # no HTTP call made


def test_connector_classifier_label_dispatch() -> None:
    cls = LinearConnector._classify
    assert cls(("incident",), "started") == "incident"
    assert cls(("bug",), "unstarted") == "bug"
    assert cls(("support",), "unstarted") == "support"
    assert cls(("debt",), "unstarted") == "refactor"
    assert cls(("ops",), "unstarted") == "infra"
    assert cls(("security",), "unstarted") == "compliance"
    assert cls((), "unstarted") == "feature"


def test_connector_emits_graphql_post_body(mock_http, stub_loader) -> None:
    """Every Linear request is a POST with a GraphQL body in headers."""
    mock_http.script("graphql", {
        "data": {"issues": {
            "pageInfo": {"hasNextPage": False, "endCursor": None},
            "nodes": [],
        }},
    })
    c = LinearConnector(
        http=mock_http, workspace="acme", token_loader=stub_loader,
    )
    c.import_issues()
    posted = [h for (_, h) in mock_http.calls if h.get("_spine_method") == "POST"]
    assert posted
    assert all('"query":' in h["_spine_body"] for h in posted)


# ---------------------------------------------------------------------------
# LinearAdapter (registry facade)
# ---------------------------------------------------------------------------


def test_adapter_name_and_kind() -> None:
    adapter = LinearAdapter(workspace="acme")
    assert adapter.name == "linear"
    assert adapter.kind.value == "issue_tracker"
    assert adapter.vault_path == "integration/linear/acme/api_key"


def test_test_connection_healthy_when_vault_has_key(monkeypatch) -> None:
    import shared.integrations.base as base_mod

    async def _fake(path: str) -> str:
        return "lin_api_xxx"

    monkeypatch.setattr(base_mod, "fetch_secret", _fake, raising=True)
    result = asyncio.run(probe_connection(workspace="acme"))
    assert result.name == "linear"
    assert result.healthy is True


def test_test_connection_unhealthy_when_vault_missing(monkeypatch) -> None:
    import shared.integrations.base as base_mod

    async def _fake(path: str) -> None:
        return None

    monkeypatch.setattr(base_mod, "fetch_secret", _fake, raising=True)
    result = asyncio.run(probe_connection(workspace="acme"))
    assert result.healthy is False
    assert result.error == "vault_secret_missing"
