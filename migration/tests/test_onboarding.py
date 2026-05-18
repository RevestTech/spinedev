"""Tests for ``migration.onboarding`` (#33 A)."""

from __future__ import annotations

import json

import pytest

from migration.onboarding import (
    GitHubConnector,
    LinearConnector,
    OnboardingDispatcher,
    WorkItemMapping,
)


# ---------------------------------------------------------------------------
# GitHubConnector
# ---------------------------------------------------------------------------


def test_github_connector_imports_repos_and_issues(
    mock_http, stub_token_loader,
) -> None:
    # import_issues() re-fetches repos, so make this persistent.
    mock_http.script_persistent("/orgs/acme/repos", [
        {"name": "spine", "owner": {"login": "acme"}},
        {"name": "demo", "owner": {"login": "acme"}},
    ])
    mock_http.script_persistent("/repos/acme/spine/issues", [
        {"id": 1, "number": 7, "title": "Bug A", "body": "broken",
         "labels": [{"name": "bug"}], "state": "open",
         "created_at": "2026-05-01T00:00:00Z", "updated_at": "2026-05-02T00:00:00Z",
         "assignee": {"login": "alice"}, "html_url": "https://github.com/acme/spine/7"},
        {"id": 2, "number": 8, "title": "Feature B", "body": "request",
         "labels": [{"name": "enhancement"}], "state": "open",
         "created_at": "2026-05-01T00:00:00Z", "updated_at": "2026-05-02T00:00:00Z",
         "assignee": None, "html_url": "https://github.com/acme/spine/8"},
        # PR — must be filtered out.
        {"id": 3, "number": 9, "title": "PR", "pull_request": {}},
    ])
    mock_http.script_persistent("/repos/acme/demo/issues", [])

    c = GitHubConnector(
        http=mock_http, org="acme", token_loader=stub_token_loader,
    )
    repos = c.import_repos()
    assert {r["name"] for r in repos} == {"spine", "demo"}

    issues = c.import_issues()
    assert len(issues) == 2  # PR filtered

    mapped = c.map_to_spine_workitems(issues=issues)
    assert {m.work_item_type for m in mapped} == {"bug", "feature"}
    bug = next(m for m in mapped if m.work_item_type == "bug")
    assert bug.source_id == "acme/spine#7"
    assert bug.external_assignee == "alice"
    assert "bug" in bug.labels


def test_github_label_classifier_covers_all_7_types() -> None:
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


def test_github_repo_filter(mock_http, stub_token_loader) -> None:
    mock_http.script_persistent("/orgs/acme/repos", [
        {"name": "spine", "owner": {"login": "acme"}},
        {"name": "demo", "owner": {"login": "acme"}},
    ])
    mock_http.script_persistent("/repos/acme/spine/issues", [])
    c = GitHubConnector(http=mock_http, org="acme",
                        repo_filter=("spine",), token_loader=stub_token_loader)
    repos = c.import_repos()
    assert {r["name"] for r in repos} == {"spine"}


# ---------------------------------------------------------------------------
# LinearConnector
# ---------------------------------------------------------------------------


def test_linear_connector_paginates_and_maps(mock_http, stub_token_loader) -> None:
    # Page 1: hasNextPage true.
    mock_http.script("graphql", {
        "data": {"issues": {
            "pageInfo": {"hasNextPage": True, "endCursor": "abc"},
            "nodes": [
                {"id": "i1", "identifier": "SPI-1", "title": "Linear bug",
                 "description": "broken", "state": {"name": "Todo", "type": "unstarted"},
                 "url": "https://linear.app/i1",
                 "createdAt": "2026-05-01T00:00:00Z",
                 "updatedAt": "2026-05-02T00:00:00Z",
                 "labels": {"nodes": [{"name": "bug"}]},
                 "assignee": {"name": "Bob", "email": "bob@acme.com"},
                 "team": {"key": "SPI", "name": "Spine"}},
            ],
        }},
    })
    # Page 2: hasNextPage false.
    mock_http.script("graphql", {
        "data": {"issues": {
            "pageInfo": {"hasNextPage": False, "endCursor": None},
            "nodes": [
                {"id": "i2", "identifier": "SPI-2", "title": "Linear infra ask",
                 "description": "ops", "state": {"name": "Backlog", "type": "backlog"},
                 "url": "https://linear.app/i2",
                 "createdAt": "2026-05-03T00:00:00Z",
                 "updatedAt": "2026-05-04T00:00:00Z",
                 "labels": {"nodes": [{"name": "infra"}]},
                 "assignee": None,
                 "team": {"key": "SPI", "name": "Spine"}},
            ],
        }},
    })

    c = LinearConnector(http=mock_http, workspace="acme",
                        token_loader=stub_token_loader)
    issues = c.import_issues()
    assert {i["identifier"] for i in issues} == {"SPI-1", "SPI-2"}

    mapped = c.map_to_spine_workitems(issues=issues)
    types = {m.source_id: m.work_item_type for m in mapped}
    assert types["SPI-1"] == "bug"
    assert types["SPI-2"] == "infra"
    # Linear's HTTP body is GraphQL JSON — verify it was constructed.
    body_calls = [h.get("_spine_body") for (_, h) in mock_http.calls
                  if h.get("_spine_method") == "POST"]
    assert all('"query":' in b for b in body_calls)


def test_linear_team_filter(mock_http, stub_token_loader) -> None:
    mock_http.script("graphql", {
        "data": {"issues": {
            "pageInfo": {"hasNextPage": False, "endCursor": None},
            "nodes": [
                {"id": "i1", "identifier": "AAA-1", "title": "x",
                 "description": "", "state": {"name": "x", "type": "unstarted"},
                 "url": "x", "createdAt": "", "updatedAt": "",
                 "labels": {"nodes": []}, "assignee": None,
                 "team": {"key": "AAA", "name": "Team A"}},
                {"id": "i2", "identifier": "BBB-1", "title": "y",
                 "description": "", "state": {"name": "y", "type": "unstarted"},
                 "url": "y", "createdAt": "", "updatedAt": "",
                 "labels": {"nodes": []}, "assignee": None,
                 "team": {"key": "BBB", "name": "Team B"}},
            ],
        }},
    })
    c = LinearConnector(http=mock_http, workspace="acme",
                        team_keys=("BBB",), token_loader=stub_token_loader)
    issues = c.import_issues()
    assert [i["identifier"] for i in issues] == ["BBB-1"]


# ---------------------------------------------------------------------------
# OnboardingDispatcher
# ---------------------------------------------------------------------------


def test_dispatcher_aggregates_across_connectors(
    mock_http, mock_sink, stub_token_loader,
) -> None:
    mock_http.script_persistent("/orgs/acme/repos", [
        {"name": "spine", "owner": {"login": "acme"}},
    ])
    mock_http.script_persistent("/repos/acme/spine/issues", [
        {"id": 1, "number": 1, "title": "GH issue", "body": "",
         "labels": [], "state": "open", "html_url": "x",
         "created_at": "", "updated_at": "", "assignee": None},
    ])
    mock_http.script("graphql", {
        "data": {"issues": {
            "pageInfo": {"hasNextPage": False, "endCursor": None},
            "nodes": [
                {"id": "i1", "identifier": "LIN-1", "title": "Linear issue",
                 "description": "", "state": {"name": "Todo", "type": "unstarted"},
                 "url": "x", "createdAt": "", "updatedAt": "",
                 "labels": {"nodes": []}, "assignee": None,
                 "team": {"key": "L", "name": "L"}},
            ],
        }},
    })
    gh = GitHubConnector(http=mock_http, org="acme",
                         token_loader=stub_token_loader)
    lin = LinearConnector(http=mock_http, workspace="acme",
                          token_loader=stub_token_loader)
    disp = OnboardingDispatcher(connectors=[gh, lin], sink=mock_sink)
    report = disp.run()
    assert report.total_work_items == 2
    assert report.total_written == 2
    names = {p.connector for p in report.per_connector}
    assert names == {"github", "linear"}
