"""Linear adapter (canonical) — GraphQL auth + issue/comment connector.

Per V3 Part 1.1 this is the canonical home for Linear integration
plumbing. The downstream consumer is ``migration/onboarding.py``'s
``LinearConnector`` which re-exports :class:`LinearConnector` from here.

Auth: API key fetched from vault path
``integration/linear/<workspace>/api_key`` (per #9). The Linear API is
GraphQL-only; this connector uses :meth:`HttpClient.get_json` against a
single POST endpoint (the HttpClient interface accepts arbitrary URLs +
headers; tests stub it).

Rationale for picking Linear over Jira in v1.0 (per ADR-F-003):

* Modern GraphQL API with a single endpoint surface (Jira has v2, v3,
  "agile", "service-desk" — four APIs).
* Webhook payloads + REST + GraphQL semantics align; Spine's MCP tool
  surface mirrors that shape.
* Linear's ``state.type`` enum maps 1-to-1 onto Spine work-item
  lifecycle stages without translation tables.
* Linear targets the same segment as Spine (modern software teams);
  Jira will return as a v1.1 connector for the enterprise segment.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Awaitable, Callable, Literal, Optional

from shared.integrations.base import (
    BaseIntegrationAdapter,
    IntegrationKind,
    TestConnectionResult,
    fetch_secret,
    register_adapter,
)
from shared.integrations.github import HttpClient, WorkItemType

logger = logging.getLogger("shared.integrations.linear")

#: Vault path template — per-workspace api_key namespace (per #9).
VAULT_PATH_API_KEY_TMPL = "integration/linear/{workspace}/api_key"
#: Default GraphQL endpoint.
DEFAULT_API_URL = "https://api.linear.app/graphql"


# ---------------------------------------------------------------------------
# Cached GraphQL queries
# ---------------------------------------------------------------------------


_LINEAR_ISSUES_QUERY = """
query Issues($cursor: String) {
  issues(first: 100, after: $cursor) {
    pageInfo { hasNextPage endCursor }
    nodes {
      id identifier title description state { name type }
      url createdAt updatedAt
      labels { nodes { name } }
      assignee { name email }
      team { key name }
    }
  }
}
""".strip()


def _serialize_gql(query: str, variable_value: Optional[str]) -> str:
    """Build a JSON GraphQL request body."""
    return json.dumps(
        {"query": query,
         "variables": ({"cursor": variable_value}
                       if variable_value is not None else {})},
        sort_keys=True,
    )


# ---------------------------------------------------------------------------
# LinearConnector (relocated from migration/onboarding.py)
# ---------------------------------------------------------------------------


class LinearConnector:
    """Read Linear issues + comments and map to Spine work-items."""

    name = "linear"

    def __init__(
        self,
        *,
        http: HttpClient,
        workspace: str,
        team_keys: Optional[tuple[str, ...]] = None,
        token_loader: Optional[Callable[[str], Awaitable[str]]] = None,
        api_url: str = DEFAULT_API_URL,
    ) -> None:
        self._http = http
        self._workspace = workspace
        self._team_keys = team_keys
        self._token_loader = token_loader
        self._api_url = api_url
        self._token_cache: Optional[str] = None

    def _load_token(self) -> str:
        if self._token_cache is not None:
            return self._token_cache

        loader = self._token_loader
        path = VAULT_PATH_API_KEY_TMPL.format(workspace=self._workspace)
        if loader is None:
            from shared.secrets import get_secret as _get  # noqa: PLC0415

            loader = _get  # type: ignore[assignment]
        coro = loader(path)
        try:
            tok = asyncio.run(coro)
        except RuntimeError:
            loop = asyncio.new_event_loop()
            try:
                tok = loop.run_until_complete(coro)
            finally:
                loop.close()
        self._token_cache = tok
        return tok

    def _headers(self) -> dict[str, str]:
        # Linear accepts API keys directly in Authorization header
        # (no "Bearer" prefix, per their docs).
        return {
            "Authorization": self._load_token(),
            "Content-Type": "application/json",
        }

    def import_repos(self) -> list[dict[str, Any]]:
        """Linear has no concept of repos; return an empty list."""
        return []

    def import_issues(self) -> list[dict[str, Any]]:
        # GraphQL pagination loop.
        issues: list[dict[str, Any]] = []
        cursor: Optional[str] = None
        for _ in range(64):  # hard cap: 64 pages * 100 = 6400 issues
            resp = self._http.get_json(
                self._api_url, headers={
                    **self._headers(),
                    "_spine_method": "POST",
                    "_spine_body": _serialize_gql(_LINEAR_ISSUES_QUERY, cursor),
                },
            )
            body = resp.get("body", {}) or {}
            data = (body.get("data") or {}).get("issues") or {}
            for node in data.get("nodes", []) or []:
                if self._team_keys:
                    team_key = (node.get("team") or {}).get("key")
                    if team_key not in self._team_keys:
                        continue
                issues.append(node)
            page = data.get("pageInfo") or {}
            if not page.get("hasNextPage"):
                break
            cursor = page.get("endCursor")
        return issues

    def import_comments(self, *, issue_source_id: str) -> list[dict[str, Any]]:
        query = (
            "query Comments($id: String!) { issue(id: $id) "
            "{ comments { nodes { id body createdAt user { name } } } } }"
        )
        resp = self._http.get_json(
            self._api_url, headers={
                **self._headers(),
                "_spine_method": "POST",
                "_spine_body": _serialize_gql(query, issue_source_id),
            },
        )
        body = resp.get("body", {}) or {}
        return list(
            ((body.get("data") or {}).get("issue") or {})
            .get("comments", {})
            .get("nodes", []) or [],
        )

    @staticmethod
    def _classify(labels: tuple[str, ...], state_type: str) -> WorkItemType:
        # Linear's state.type vocabulary is {backlog, unstarted, started,
        # completed, canceled, triage}; that's pure lifecycle. Use labels
        # for type classification, fall back to feature.
        lowered = {lbl.lower() for lbl in labels}
        if "incident" in lowered or "outage" in lowered:
            return "incident"
        if "bug" in lowered:
            return "bug"
        if "support" in lowered:
            return "support"
        if "refactor" in lowered or "debt" in lowered:
            return "refactor"
        if "infra" in lowered or "ops" in lowered:
            return "infra"
        if "compliance" in lowered or "security" in lowered:
            return "compliance"
        return "feature"

    def map_to_spine_workitems(
        self, *, issues: list[dict[str, Any]],
    ) -> list[Any]:
        """Translate Linear issues into ``WorkItemMapping`` rows."""
        from migration.onboarding import WorkItemMapping  # noqa: PLC0415

        mapped: list[WorkItemMapping] = []
        for it in issues:
            label_nodes = (it.get("labels") or {}).get("nodes") or []
            labels = tuple(
                (n.get("name") or "").strip() for n in label_nodes
                if (n.get("name") or "").strip()
            )
            state = it.get("state") or {}
            mapped.append(WorkItemMapping(
                work_item_type=self._classify(labels, str(state.get("type") or "")),
                title=str(it.get("title", "")),
                body_md=str(it.get("description") or ""),
                source_id=str(it.get("identifier") or it.get("id") or ""),
                source_url=str(it.get("url") or ""),
                connector=self.name,
                labels=labels,
                external_state=str(state.get("name") or ""),
                external_created_at=str(it.get("createdAt") or ""),
                external_updated_at=str(it.get("updatedAt") or ""),
                external_assignee=(
                    (it.get("assignee") or {}).get("name")
                    if it.get("assignee") else None
                ),
                raw=it,
            ))
        return mapped


# ---------------------------------------------------------------------------
# Standard integration-adapter facade (used by MCP + SPA)
# ---------------------------------------------------------------------------


class LinearAdapter(BaseIntegrationAdapter):
    """Canonical integration adapter for Linear."""

    def __init__(self, *, workspace: str = "default") -> None:
        super().__init__(
            name="linear",
            kind=IntegrationKind.ISSUE_TRACKER,
            vault_path=VAULT_PATH_API_KEY_TMPL.format(workspace=workspace),
            stub_v1_1=False,
        )
        self._workspace = workspace


async def _factory() -> LinearAdapter:
    return LinearAdapter()


async def test_connection(*, workspace: str = "default") -> TestConnectionResult:
    """Module-level entry point dispatched by ``integrations_test_connection``."""
    return await LinearAdapter(workspace=workspace).test_connection()


register_adapter("linear", _factory)


__all__ = [
    "DEFAULT_API_URL",
    "LinearAdapter",
    "LinearConnector",
    "VAULT_PATH_API_KEY_TMPL",
    "test_connection",
]
