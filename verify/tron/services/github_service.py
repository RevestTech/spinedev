"""
GitHub Service - Interface for GitHub API operations.

Handles fetching repositories from organizations and validating access.
"""

import httpx
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


class GitHubAPIError(Exception):
    """Raised when the GitHub REST API returns an error (auth, SSO, scope, etc.)."""

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        self.message = message
        super().__init__(f"GitHub API {status_code}: {message}")


def _github_error_message(response: httpx.Response) -> str:
    try:
        data = response.json()
        if isinstance(data, dict) and data.get("message"):
            return str(data["message"])
    except Exception:
        pass
    return (response.text[:400] or response.reason_phrase or "Unknown error").strip()


def normalize_github_pat(raw: Optional[str]) -> Optional[str]:
    """Strip whitespace and accidental ``Bearer `` prefix from vault/env pastes."""
    if raw is None:
        return None
    t = str(raw).strip().strip('"').strip("'")
    if t.lower().startswith("bearer "):
        t = t[7:].strip()
    return t if t else None


class GitHubService:
    def __init__(self, token: Optional[str] = None):
        self._pat = normalize_github_pat(token)
        self.token = self._pat
        self.base_url = "https://api.github.com"
        self.headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "Tron-Security-Platform",
        }
        if self._pat:
            self.headers["Authorization"] = f"Bearer {self._pat}"

    async def _get_authenticated(
        self,
        client: httpx.AsyncClient,
        url: str,
        *,
        params: Optional[Dict[str, Any]] = None,
    ) -> httpx.Response:
        """GET with Bearer; on 401 retry once with legacy ``token`` scheme (classic PAT edge cases)."""
        params = params or {}
        r = await client.get(url, headers=self.headers, params=params)
        if r.status_code == 401 and self._pat:
            legacy = dict(self.headers)
            legacy["Authorization"] = f"token {self._pat}"
            r2 = await client.get(url, headers=legacy, params=params)
            if r2.status_code == 200:
                logger.info("GitHub API accepted Authorization: token after Bearer 401")
            return r2
        return r

    async def list_org_repos(self, org_name: str) -> List[Dict[str, Any]]:
        """List repositories for a GitHub **organization** (``/orgs/{org}/repos``)."""
        url = f"{self.base_url}/orgs/{org_name}/repos"
        params = {"per_page": 100, "sort": "updated"}

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await self._get_authenticated(client, url, params=params)
                if response.status_code == 200:
                    return response.json()

                logger.error(
                    "GitHub: Failed to list org repos for %s: %s %s",
                    org_name,
                    response.status_code,
                    response.text[:500],
                )
                return []
        except Exception as e:
            logger.error(f"GitHub: Error listing org repos for {org_name}: {e}")
            return []

    async def list_repos_for_login(self, login: str) -> List[Dict[str, Any]]:
        """List repos for an owner name that may be an **organization** or a **user** account.

        Real orgs use ``/orgs/{login}/repos``. That returns **404** when ``login`` is a
        **user** (not an org); we then fall back to ``/users/{login}/repos``.

        **401/403** on an org usually means PAT scope, expiry, or **missing SSO authorization**
        for SAML-enabled orgs — we surface that as :class:`GitHubAPIError` instead of an empty list.
        """
        login = login.strip().removeprefix("/")
        if not login:
            return []

        params = {"per_page": 100, "sort": "updated"}
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                org_url = f"{self.base_url}/orgs/{login}/repos"
                r = await self._get_authenticated(client, org_url, params=params)
                if r.status_code == 200:
                    return r.json()

                if r.status_code in (401, 403):
                    msg = _github_error_message(r)
                    logger.error(
                        "GitHub: org repo list denied for %s: %s %s",
                        login,
                        r.status_code,
                        msg,
                    )
                    raise GitHubAPIError(r.status_code, msg)

                if r.status_code == 404:
                    user_url = f"{self.base_url}/users/{login}/repos"
                    r2 = await self._get_authenticated(client, user_url, params=params)
                    if r2.status_code == 200:
                        return r2.json()
                    if r2.status_code in (401, 403):
                        raise GitHubAPIError(r2.status_code, _github_error_message(r2))
                    logger.error(
                        "GitHub: org 404 and user listing failed for %s: %s %s",
                        login,
                        r2.status_code,
                        r2.text[:500],
                    )
                    return []

                logger.error(
                    "GitHub: Failed to list repos for owner %s: %s %s",
                    login,
                    r.status_code,
                    r.text[:500],
                )
                raise GitHubAPIError(r.status_code, _github_error_message(r))
        except GitHubAPIError:
            raise
        except Exception as e:
            logger.error("GitHub: Error listing repos for owner %s: %s", login, e)
            raise GitHubAPIError(0, str(e)) from e

    async def list_user_repos(self) -> List[Dict[str, Any]]:
        """List repositories for the authenticated user."""
        if not self.token:
            return []

        url = f"{self.base_url}/user/repos"
        params = {"per_page": 100, "sort": "updated", "affiliation": "owner,collaborator,organization_member"}

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await self._get_authenticated(client, url, params=params)
                if response.status_code == 200:
                    return response.json()

                msg = _github_error_message(response)
                logger.error("GitHub: Failed to list user repos: %s %s", response.status_code, msg)
                raise GitHubAPIError(response.status_code, msg)
        except GitHubAPIError:
            raise
        except Exception as e:
            logger.error("GitHub: Error listing user repos: %s", e)
            raise GitHubAPIError(0, str(e)) from e

    async def validate_repo_access(self, repo_url: str) -> bool:
        """Check if the configured token has access to a specific repo URL."""
        # Extract org/repo from URL
        parts = repo_url.replace("https://github.com/", "").replace(".git", "").split("/")
        if len(parts) < 2:
            return False
            
        owner, repo = parts[0], parts[1]
        url = f"{self.base_url}/repos/{owner}/{repo}"
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await self._get_authenticated(client, url)
                return response.status_code == 200
        except Exception:
            return False
