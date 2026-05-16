"""Unit tests for API path → scope mapping."""

from __future__ import annotations

import pytest

from tron.api.middleware.scopes import required_scopes_for_path, scopes_satisfy


@pytest.mark.parametrize(
    "path,expected",
    [
        ("/api/projects", frozenset({"projects"})),
        ("/api/projects/550e8400-e29b-41d4-a716-446655440000/graph", frozenset({"graph", "projects"})),
        ("/api/projects/x/graph/transitive", frozenset({"graph", "projects"})),
        ("/api/audits", frozenset({"audits"})),
        ("/api/standards/defaults", frozenset({"standards"})),
        ("/api/plan/pid", frozenset({"modes"})),
        ("/api/build/pid", frozenset({"modes"})),
        ("/api/costs", frozenset({"costs"})),
        ("/api/workflow-runs", frozenset({"workflows"})),
        ("/api/gdpr/export", frozenset({"gdpr"})),
        ("/api/openapi.json", None),
    ],
)
def test_required_scopes_for_path(path: str, expected):
    assert required_scopes_for_path(path) == expected


def test_scopes_satisfy_any_of_required():
    req = frozenset({"graph", "projects"})
    assert scopes_satisfy(req, frozenset({"graph"}))
    assert scopes_satisfy(req, frozenset({"projects"}))
    assert not scopes_satisfy(req, frozenset({"audits"}))


def test_wildcard_scope_grants_all_routes():
    assert scopes_satisfy(frozenset({"projects"}), frozenset({"*"}))
