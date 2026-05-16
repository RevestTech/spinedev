"""
GitHub Service - Interface for GitHub API operations.

Handles fetching repositories from organizations and validating access.
"""

import httpx
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

class GitHubService:
    def __init__(self, token: Optional[str] = None):
        self.token = token
        self.base_url = "https://api.github.com"
        self.headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "Tron-Security-Platform"
        }
        if token:
            self.headers["Authorization"] = f"token {token}"

    async def list_org_repos(self, org_name: str) -> List[Dict[str, Any]]:
        """List all repositories for a given organization."""
        url = f"{self.base_url}/orgs/{org_name}/repos"
        params = {"per_page": 100, "sort": "updated"}
        
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(url, headers=self.headers, params=params)
                if response.status_code == 200:
                    return response.json()
                
                logger.error(f"GitHub: Failed to list repos for {org_name}: {response.status_code} {response.text}")
                return []
        except Exception as e:
            logger.error(f"GitHub: Error listing repos for {org_name}: {e}")
            return []

    async def list_user_repos(self) -> List[Dict[str, Any]]:
        """List repositories for the authenticated user."""
        if not self.token:
            return []
            
        url = f"{self.base_url}/user/repos"
        params = {"per_page": 100, "sort": "updated", "affiliation": "owner,collaborator,organization_member"}
        
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(url, headers=self.headers, params=params)
                if response.status_code == 200:
                    return response.json()
                
                logger.error(f"GitHub: Failed to list user repos: {response.status_code} {response.text}")
                return []
        except Exception as e:
            logger.error(f"GitHub: Error listing user repos: {e}")
            return []

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
                response = await client.get(url, headers=self.headers)
                return response.status_code == 200
        except Exception:
            return False
