"""Onboarding migration — design decision #33 A.

Scaffold the connector interface + ship Day 1 connectors for **GitHub**
and **Linear** (the "Linear OR Jira" choice in #33; rationale in
``ADR-F-003``: Linear's API is the more modern issue-tracker surface and
maps more cleanly onto Spine's work-item types). Confluence / Notion /
Asana / Jira / GitLab connectors are deferred to v1.1+ per the design
doc's deferred-items table.

Each connector exposes four pure operations:

* ``import_repos`` — discover source-code repositories.
* ``import_issues`` — discover issue records.
* ``import_comments`` — discover issue comments / discussion threads.
* ``map_to_spine_workitems`` — translate connector-native records into
  Spine ``spine_workitem.work_item`` rows.

Connectors are **side-effect-free at the network layer for tests**: the
HTTP client is injectable so unit tests stub the whole external surface.
Production wires :mod:`httpx` clients with auth headers fetched from
:mod:`shared.secrets` (per #9 — never read tokens from env vars).

The :class:`OnboardingDispatcher` walks a connector matrix and writes
every produced work-item into the destination via a writer protocol that
mirrors :class:`migration.import_.DestWriter` (subset).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Literal, Optional, Protocol

logger = logging.getLogger("spine.migration.onboarding")

WorkItemType = Literal[
    "feature", "bug", "incident", "support", "refactor", "infra", "compliance",
]
"""The 7 work-item types Spine v1.0 supports (per #19)."""


@dataclass(frozen=True)
class WorkItemMapping:
    """A connector-native record translated to a Spine work-item shape.

    The mapping is intentionally **dumb** — connectors don't try to be
    clever about decomposition / prioritisation. The mapping captures
    enough provenance (``source_url``, ``source_id``, ``connector``) that
    the conductor role can revisit decisions during the intake phase.
    """

    work_item_type: WorkItemType
    title: str
    body_md: str
    source_id: str
    source_url: str
    connector: str
    labels: tuple[str, ...] = ()
    external_state: Optional[str] = None
    external_created_at: Optional[str] = None
    external_updated_at: Optional[str] = None
    external_assignee: Optional[str] = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class ConnectorRunReport:
    """Per-connector outcome of an onboarding run."""

    connector: str
    repos: int = 0
    issues: int = 0
    comments: int = 0
    work_items_mapped: int = 0
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# HTTP client protocol — injectable for tests
# ---------------------------------------------------------------------------


class HttpClient(Protocol):
    """Tiny façade over an HTTP client — only what the connectors use.

    Implementations must:

    * Authenticate via headers (the connector hands them in per call).
    * Return ``{"status_code": int, "body": Any}`` where ``body`` is the
      parsed JSON dict / list.
    * Raise nothing for non-2xx — the connector decides how to react.
    """

    def get_json(self, url: str, *, headers: dict[str, str]) -> dict[str, Any]:
        ...


# ---------------------------------------------------------------------------
# Connector base
# ---------------------------------------------------------------------------


class Connector(Protocol):
    """The contract every onboarding connector implements.

    Concrete connectors (``GitHubConnector``, ``LinearConnector``) take
    an ``http`` client + a secret loader at construction so tests can
    inject mocks. Production wiring uses :func:`shared.secrets.get_secret`
    + an :mod:`httpx` ``AsyncClient`` driven through a sync facade.
    """

    name: str

    def import_repos(self) -> list[dict[str, Any]]:
        ...

    def import_issues(self) -> list[dict[str, Any]]:
        ...

    def import_comments(self, *, issue_source_id: str) -> list[dict[str, Any]]:
        ...

    def map_to_spine_workitems(
        self, *, issues: list[dict[str, Any]],
    ) -> list[WorkItemMapping]:
        ...


# ---------------------------------------------------------------------------
# GitHubConnector
# ---------------------------------------------------------------------------


class GitHubConnector:
    """Read GitHub repos + issues + comments and map to Spine work-items.

    Auth: PAT or GitHub App token fetched from vault path
    ``integration/github/<org>/token`` (per #9). The token MUST scope
    only ``repo:read`` + ``issues:read`` + ``contents:read``.

    Issue → work-item type heuristic (cheap; conductor refines later):

    * label ``bug`` → ``bug``
    * label ``incident`` / ``outage`` → ``incident``
    * label ``support`` / ``question`` → ``support``
    * label ``refactor`` / ``tech-debt`` → ``refactor``
    * label ``infra`` / ``ops`` → ``infra``
    * label ``compliance`` / ``security`` → ``compliance``
    * otherwise → ``feature``
    """

    name = "github"

    def __init__(
        self,
        *,
        http: HttpClient,
        org: str,
        repo_filter: Optional[tuple[str, ...]] = None,
        token_loader: Optional[Callable[[str], Awaitable[str]]] = None,
        api_base: str = "https://api.github.com",
    ) -> None:
        self._http = http
        self._org = org
        self._repo_filter = repo_filter
        self._token_loader = token_loader
        self._api_base = api_base.rstrip("/")
        self._token_cache: Optional[str] = None

    # ---- auth helpers ----
    def _load_token(self) -> str:
        if self._token_cache is not None:
            return self._token_cache
        import asyncio

        loader = self._token_loader
        path = f"integration/github/{self._org}/token"
        if loader is None:
            from shared.secrets import get_secret as _get

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
        return {
            "Authorization": f"Bearer {self._load_token()}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    # ---- public API ----
    def import_repos(self) -> list[dict[str, Any]]:
        resp = self._http.get_json(
            f"{self._api_base}/orgs/{self._org}/repos?per_page=100",
            headers=self._headers(),
        )
        body = resp.get("body", []) or []
        if self._repo_filter:
            body = [r for r in body if r.get("name") in self._repo_filter]
        return list(body)

    def import_issues(self) -> list[dict[str, Any]]:
        all_issues: list[dict[str, Any]] = []
        for repo in self.import_repos():
            owner = repo.get("owner", {}).get("login", self._org)
            name = repo.get("name", "")
            if not name:
                continue
            resp = self._http.get_json(
                f"{self._api_base}/repos/{owner}/{name}/issues"
                f"?state=all&per_page=100",
                headers=self._headers(),
            )
            for it in resp.get("body", []) or []:
                # Filter out pull-request entries (GitHub returns PRs here too).
                if "pull_request" in it:
                    continue
                it["_spine_repo_full_name"] = f"{owner}/{name}"
                all_issues.append(it)
        return all_issues

    def import_comments(self, *, issue_source_id: str) -> list[dict[str, Any]]:
        # issue_source_id is "<owner>/<repo>#<number>"
        try:
            repo_part, num = issue_source_id.split("#", 1)
            owner, name = repo_part.split("/", 1)
        except ValueError:
            return []
        resp = self._http.get_json(
            f"{self._api_base}/repos/{owner}/{name}/issues/{num}/comments?per_page=100",
            headers=self._headers(),
        )
        return list(resp.get("body", []) or [])

    @staticmethod
    def _classify(labels: tuple[str, ...]) -> WorkItemType:
        lowered = {lbl.lower() for lbl in labels}
        if "incident" in lowered or "outage" in lowered:
            return "incident"
        if "bug" in lowered:
            return "bug"
        if "support" in lowered or "question" in lowered:
            return "support"
        if "refactor" in lowered or "tech-debt" in lowered:
            return "refactor"
        if "infra" in lowered or "ops" in lowered:
            return "infra"
        if "compliance" in lowered or "security" in lowered:
            return "compliance"
        return "feature"

    def map_to_spine_workitems(
        self, *, issues: list[dict[str, Any]],
    ) -> list[WorkItemMapping]:
        mapped: list[WorkItemMapping] = []
        for it in issues:
            labels = tuple(
                (lbl.get("name") or "").strip()
                for lbl in (it.get("labels") or [])
                if (lbl.get("name") or "").strip()
            )
            repo = it.get("_spine_repo_full_name", "")
            number = it.get("number")
            source_id = f"{repo}#{number}" if repo and number else str(it.get("id", ""))
            mapped.append(WorkItemMapping(
                work_item_type=self._classify(labels),
                title=str(it.get("title", "")),
                body_md=str(it.get("body") or ""),
                source_id=source_id,
                source_url=str(it.get("html_url", "")),
                connector=self.name,
                labels=labels,
                external_state=str(it.get("state") or ""),
                external_created_at=str(it.get("created_at") or ""),
                external_updated_at=str(it.get("updated_at") or ""),
                external_assignee=(
                    (it.get("assignee") or {}).get("login") if it.get("assignee") else None
                ),
                raw=it,
            ))
        return mapped


# ---------------------------------------------------------------------------
# LinearConnector
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


class LinearConnector:
    """Read Linear issues + comments and map to Spine work-items.

    Auth: API key fetched from vault path
    ``integration/linear/<workspace>/api_key`` (per #9). The Linear API
    is GraphQL-only; this connector uses :meth:`HttpClient.get_json`
    against a single POST endpoint (the HttpClient interface accepts
    arbitrary URLs + headers; tests stub it).

    Rationale for picking Linear over Jira in v1.0 (per ADR-F-003):

    * Modern GraphQL API with a single endpoint surface (Jira has v2,
      v3, "agile", "service-desk" — four APIs).
    * Webhook payloads + REST + GraphQL semantics align; Spine's MCP
      tool surface mirrors that shape.
    * Linear's ``state.type`` enum maps 1-to-1 onto Spine work-item
      lifecycle stages without translation tables.
    * Linear targets the same segment as Spine (modern software teams);
      Jira will return as a v1.1 connector for the enterprise segment.
    """

    name = "linear"

    def __init__(
        self,
        *,
        http: HttpClient,
        workspace: str,
        team_keys: Optional[tuple[str, ...]] = None,
        token_loader: Optional[Callable[[str], Awaitable[str]]] = None,
        api_url: str = "https://api.linear.app/graphql",
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
        import asyncio

        loader = self._token_loader
        path = f"integration/linear/{self._workspace}/api_key"
        if loader is None:
            from shared.secrets import get_secret as _get

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
        """Linear has no concept of repos; return an empty list.

        The connector contract requires the method; conductors must not
        infer repo presence from non-empty returns.
        """
        return []

    def import_issues(self) -> list[dict[str, Any]]:
        # GraphQL pagination loop.
        issues: list[dict[str, Any]] = []
        cursor: Optional[str] = None
        for _ in range(64):  # hard cap: 64 pages * 100 = 6400 issues per onboarding
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
                    if (node.get("team") or {}).get("key") not in self._team_keys:
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
    ) -> list[WorkItemMapping]:
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
                    (it.get("assignee") or {}).get("name") if it.get("assignee") else None
                ),
                raw=it,
            ))
        return mapped


def _serialize_gql(query: str, variable_value: Optional[str]) -> str:
    """Build a JSON GraphQL request body — kept as a helper so the
    ``HttpClient`` mock can re-parse it in tests without depending on
    a real GraphQL serializer."""
    import json as _json

    return _json.dumps({"query": query, "variables": {"cursor": variable_value}
                        if variable_value is not None else {}}, sort_keys=True)


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


class WorkItemSink(Protocol):
    """Destination for produced Spine work-items.

    Production wires this to the spine_workitem schema writer. Tests
    capture calls in a list.
    """

    def upsert_work_items(
        self, items: list[WorkItemMapping],
    ) -> int:
        """UPSERT ``items``; return rows written. Idempotent."""
        ...


@dataclass
class OnboardingDispatchReport:
    """Aggregate outcome across all connectors."""

    started_at: str
    finished_at: str = ""
    per_connector: list[ConnectorRunReport] = field(default_factory=list)
    total_work_items: int = 0
    total_written: int = 0
    errors: list[str] = field(default_factory=list)


class OnboardingDispatcher:
    """Drive a configured matrix of connectors and persist their output.

    Per #33 A: "Wizard step in first-time-setup". The Hub wizard hands
    this dispatcher its connector list (one or many of GitHub / Linear in
    v1.0); the dispatcher runs each, hands the produced work-items to the
    sink, and returns an aggregate report.

    The dispatcher is **synchronous + simple** by design — connector
    parallelism is out of scope. v1.0 onboarding is a one-shot wizard
    flow, not a streaming consumer.
    """

    def __init__(self, *, connectors: list[Connector], sink: WorkItemSink) -> None:
        self._connectors = connectors
        self._sink = sink

    def run(self) -> OnboardingDispatchReport:
        report = OnboardingDispatchReport(
            started_at=datetime.now(timezone.utc).isoformat(),
        )
        for c in self._connectors:
            sub = ConnectorRunReport(connector=c.name)
            try:
                repos = c.import_repos()
                sub.repos = len(repos)
                issues = c.import_issues()
                sub.issues = len(issues)
                # Comment counting is best-effort + bounded; we don't
                # actually persist them as work-items, but the count is
                # a useful signal for the wizard UI.
                comment_count = 0
                for issue in issues[:25]:  # cap; full pass on demand later
                    source_id = (
                        issue.get("identifier")
                        or issue.get("id")
                        or f"{issue.get('_spine_repo_full_name', '')}#"
                           f"{issue.get('number', '')}"
                    )
                    if not source_id:
                        continue
                    try:
                        comment_count += len(c.import_comments(
                            issue_source_id=str(source_id),
                        ))
                    except Exception as exc:  # noqa: BLE001
                        sub.errors.append(f"comments({source_id}): {exc}")
                sub.comments = comment_count
                items = c.map_to_spine_workitems(issues=issues)
                sub.work_items_mapped = len(items)
                written = self._sink.upsert_work_items(items)
                report.total_work_items += len(items)
                report.total_written += written
            except Exception as exc:  # noqa: BLE001
                sub.errors.append(str(exc))
                report.errors.append(f"{c.name}: {exc}")
            report.per_connector.append(sub)
        report.finished_at = datetime.now(timezone.utc).isoformat()
        return report


__all__ = [
    "Connector",
    "ConnectorRunReport",
    "GitHubConnector",
    "HttpClient",
    "LinearConnector",
    "OnboardingDispatcher",
    "OnboardingDispatchReport",
    "WorkItemMapping",
    "WorkItemSink",
    "WorkItemType",
]
