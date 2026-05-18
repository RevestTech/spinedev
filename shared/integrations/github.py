"""GitHub adapter (canonical) — auth + REST plumbing + repo/issue connector.

Per V3 Part 1.1 this is the canonical home for GitHub integration
plumbing. The downstream consumer is ``migration/onboarding.py``'s
``GitHubConnector`` which re-exports :class:`GitHubConnector` from here.

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

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, Literal, Optional, Protocol

from shared.integrations.base import (
    BaseIntegrationAdapter,
    IntegrationKind,
    TestConnectionResult,
    fetch_secret,
    register_adapter,
)

logger = logging.getLogger("shared.integrations.github")

#: Vault path template — per-org token namespace (per #9).
VAULT_PATH_TOKEN_TMPL = "integration/github/{org}/token"
#: Default GitHub REST API base URL.
DEFAULT_API_BASE = "https://api.github.com"

# Mirror migration.onboarding's WorkItemType for backward compat with
# the existing connector tests that import the dataclass from there.
WorkItemType = Literal[
    "feature", "bug", "incident", "support", "refactor", "infra", "compliance",
]


# ---------------------------------------------------------------------------
# HTTP client protocol — injectable for tests
# ---------------------------------------------------------------------------


class HttpClient(Protocol):
    """Tiny façade over an HTTP client — only what the connectors use."""

    def get_json(self, url: str, *, headers: dict[str, str]) -> dict[str, Any]:
        ...


# ---------------------------------------------------------------------------
# GitHubConnector  (relocated from migration/onboarding.py)
# ---------------------------------------------------------------------------


class GitHubConnector:
    """Read GitHub repos + issues + comments and map to Spine work-items.

    The connector is **side-effect-free at the network layer for tests**:
    the HTTP client is injectable so unit tests stub the whole external
    surface. Production wires :mod:`httpx` (lazy-imported by the caller).

    Public API — guaranteed-stable for downstream callers:

    * ``name``                                     class attribute
    * ``import_repos() -> list[dict]``             discover repositories
    * ``import_issues() -> list[dict]``            discover issues (PRs filtered)
    * ``import_comments(*, issue_source_id) -> list[dict]``  per-issue comments
    * ``map_to_spine_workitems(*, issues) -> list[WorkItemMapping]``
    """

    name = "github"

    def __init__(
        self,
        *,
        http: HttpClient,
        org: str,
        repo_filter: Optional[tuple[str, ...]] = None,
        token_loader: Optional[Callable[[str], Awaitable[str]]] = None,
        api_base: str = DEFAULT_API_BASE,
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

        loader = self._token_loader
        path = VAULT_PATH_TOKEN_TMPL.format(org=self._org)
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
    ) -> list[Any]:
        """Translate GitHub issues into ``WorkItemMapping`` rows.

        The return type is ``list[Any]`` here (not the concrete
        ``WorkItemMapping``) so this module can be imported without
        pulling in ``migration.onboarding`` (which would create a cycle).
        The actual class is imported lazily.
        """
        from migration.onboarding import WorkItemMapping  # noqa: PLC0415

        mapped: list[WorkItemMapping] = []
        for it in issues:
            labels = tuple(
                (lbl.get("name") or "").strip()
                for lbl in (it.get("labels") or [])
                if (lbl.get("name") or "").strip()
            )
            repo = it.get("_spine_repo_full_name", "")
            number = it.get("number")
            source_id = (
                f"{repo}#{number}" if repo and number
                else str(it.get("id", ""))
            )
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
                    (it.get("assignee") or {}).get("login")
                    if it.get("assignee") else None
                ),
                raw=it,
            ))
        return mapped


# ---------------------------------------------------------------------------
# Standard integration-adapter facade (used by MCP + SPA)
# ---------------------------------------------------------------------------


class GitHubAdapter(BaseIntegrationAdapter):
    """Canonical integration adapter for GitHub.

    Real ``test_connection`` probe is a vault-presence check for the
    default ``integration/github/acme/token`` path. Per-org adapters
    can be constructed via :class:`GitHubConnector` directly with a
    specific org name.
    """

    def __init__(self, *, org: str = "default") -> None:
        super().__init__(
            name="github",
            kind=IntegrationKind.SCM,
            vault_path=VAULT_PATH_TOKEN_TMPL.format(org=org),
            stub_v1_1=False,
        )
        self._org = org


async def _factory() -> GitHubAdapter:
    return GitHubAdapter()


async def test_connection(*, org: str = "default") -> TestConnectionResult:
    """Module-level entry point dispatched by ``integrations_test_connection``."""
    return await GitHubAdapter(org=org).test_connection()


register_adapter("github", _factory)


__all__ = [
    "DEFAULT_API_BASE",
    "GitHubAdapter",
    "GitHubConnector",
    "HttpClient",
    "VAULT_PATH_TOKEN_TMPL",
    "WorkItemType",
    "test_connection",
]
