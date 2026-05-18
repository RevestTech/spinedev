"""Tests for ``shared.integrations.github`` — canonical GitHub adapter.

Covers:

* GitHubConnector public API matches what ``migration/onboarding.py``
  used to expose inline (repo discovery, issue import, comment fetch,
  work-item mapping, label-driven classification).
* Vault path template includes the per-org namespace.
* GitHubAdapter.test_connection returns a real probe envelope when the
  vault entry resolves.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import pytest

from shared.integrations.github import (
    DEFAULT_API_BASE,
    GitHubAdapter,
    GitHubConnector,
    VAULT_PATH_TOKEN_TMPL,
)
from shared.integrations.github import test_connection as probe_connection


# ---------------------------------------------------------------------------
# Local scripted HTTP client (mirrors migration/tests/conftest's flavour)
# ---------------------------------------------------------------------------


@dataclass
class _ScriptedHttp:
    persistent: list[tuple[str, Any]] = field(default_factory=list)

    def script_persistent(self, sub: str, body: Any) -> None:
        self.persistent.append((sub, body))

    def get_json(self, url: str, *, headers: dict[str, str]) -> dict[str, Any]:
        for sub, body in self.persistent:
            if sub in url:
                return {"status_code": 200, "body": body}
        return {"status_code": 404, "body": []}


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


def test_vault_path_template_includes_org() -> None:
    assert VAULT_PATH_TOKEN_TMPL.format(org="acme") == "integration/github/acme/token"


def test_default_api_base_is_dotcom() -> None:
    assert DEFAULT_API_BASE == "https://api.github.com"


# ---------------------------------------------------------------------------
# GitHubConnector
# ---------------------------------------------------------------------------


def test_connector_imports_repos_and_filters_prs(
    mock_http, stub_loader,
) -> None:
    mock_http.script_persistent("/orgs/acme/repos", [
        {"name": "spine", "owner": {"login": "acme"}},
    ])
    mock_http.script_persistent("/repos/acme/spine/issues", [
        {"id": 1, "number": 7, "title": "Bug A", "body": "broken",
         "labels": [{"name": "bug"}], "state": "open",
         "created_at": "2026-05-01T00:00:00Z",
         "updated_at": "2026-05-02T00:00:00Z",
         "assignee": {"login": "alice"},
         "html_url": "https://github.com/acme/spine/7"},
        {"id": 9, "number": 99, "pull_request": {}},  # PR — must filter
    ])

    c = GitHubConnector(http=mock_http, org="acme", token_loader=stub_loader)
    assert {r["name"] for r in c.import_repos()} == {"spine"}

    issues = c.import_issues()
    assert len(issues) == 1
    assert issues[0]["number"] == 7
    assert issues[0]["_spine_repo_full_name"] == "acme/spine"


def test_connector_label_classifier_covers_seven_types() -> None:
    cls = GitHubConnector._classify
    assert cls(("incident",)) == "incident"
    assert cls(("outage",)) == "incident"
    assert cls(("bug",)) == "bug"
    assert cls(("support",)) == "support"
    assert cls(("question",)) == "support"
    assert cls(("refactor",)) == "refactor"
    assert cls(("tech-debt",)) == "refactor"
    assert cls(("infra",)) == "infra"
    assert cls(("ops",)) == "infra"
    assert cls(("compliance",)) == "compliance"
    assert cls(("security",)) == "compliance"
    assert cls(()) == "feature"


def test_connector_map_to_workitems_returns_workitemmapping(
    mock_http, stub_loader,
) -> None:
    """Mapping returns the canonical migration.onboarding.WorkItemMapping shape."""
    from migration.onboarding import WorkItemMapping

    mock_http.script_persistent("/orgs/acme/repos", [
        {"name": "spine", "owner": {"login": "acme"}},
    ])
    mock_http.script_persistent("/repos/acme/spine/issues", [
        {"id": 1, "number": 7, "title": "Bug", "body": "broken",
         "labels": [{"name": "bug"}], "state": "open",
         "created_at": "", "updated_at": "", "assignee": None,
         "html_url": "https://github.com/acme/spine/7"},
    ])
    c = GitHubConnector(http=mock_http, org="acme", token_loader=stub_loader)
    mapped = c.map_to_spine_workitems(issues=c.import_issues())
    assert len(mapped) == 1
    assert isinstance(mapped[0], WorkItemMapping)
    assert mapped[0].source_id == "acme/spine#7"
    assert mapped[0].work_item_type == "bug"
    assert mapped[0].connector == "github"


def test_connector_repo_filter_applies(mock_http, stub_loader) -> None:
    mock_http.script_persistent("/orgs/acme/repos", [
        {"name": "spine", "owner": {"login": "acme"}},
        {"name": "demo", "owner": {"login": "acme"}},
    ])
    mock_http.script_persistent("/repos/acme/spine/issues", [])
    c = GitHubConnector(
        http=mock_http, org="acme",
        repo_filter=("spine",), token_loader=stub_loader,
    )
    assert {r["name"] for r in c.import_repos()} == {"spine"}


def test_connector_import_comments_parses_source_id(
    mock_http, stub_loader,
) -> None:
    mock_http.script_persistent(
        "/repos/acme/spine/issues/7/comments",
        [{"id": 1, "body": "hi"}],
    )
    c = GitHubConnector(http=mock_http, org="acme", token_loader=stub_loader)
    comments = c.import_comments(issue_source_id="acme/spine#7")
    assert len(comments) == 1


def test_connector_import_comments_malformed_returns_empty(
    mock_http, stub_loader,
) -> None:
    c = GitHubConnector(http=mock_http, org="acme", token_loader=stub_loader)
    assert c.import_comments(issue_source_id="not-formatted") == []


# ---------------------------------------------------------------------------
# GitHubAdapter (registry facade)
# ---------------------------------------------------------------------------


def test_adapter_name_and_kind() -> None:
    adapter = GitHubAdapter(org="acme")
    assert adapter.name == "github"
    assert adapter.kind.value == "scm"
    assert adapter.vault_path == "integration/github/acme/token"


def test_test_connection_healthy_when_vault_has_token(monkeypatch) -> None:
    import shared.integrations.base as base_mod

    async def _fake(path: str) -> str:
        return "ghp_xxxx"

    monkeypatch.setattr(base_mod, "fetch_secret", _fake, raising=True)
    result = asyncio.run(probe_connection(org="acme"))
    assert result.name == "github"
    assert result.healthy is True


def test_test_connection_unhealthy_when_vault_missing(monkeypatch) -> None:
    import shared.integrations.base as base_mod

    async def _fake(path: str) -> None:
        return None

    monkeypatch.setattr(base_mod, "fetch_secret", _fake, raising=True)
    result = asyncio.run(probe_connection(org="acme"))
    assert result.healthy is False
    assert result.error == "vault_secret_missing"
