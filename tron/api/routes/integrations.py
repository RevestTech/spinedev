"""
Integrations API - GitHub and Third-Party Connectors.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from tron.api.routes.admin_auth import require_api_key
from tron.infra.db.session import get_session
from tron.infra.secrets import get_secret
from tron.services.github_service import GitHubService

logger = logging.getLogger(__name__)
router = APIRouter()

class GithubRepoResponse(BaseModel):
    name: str
    full_name: str
    html_url: str
    description: Optional[str]
    stargazers_count: int
    language: Optional[str]
    updated_at: str

@router.get("/integrations/github/repos", response_model=List[GithubRepoResponse])
async def list_github_repos(
    org: Optional[str] = Query(None, description="GitHub Organization name"),
):
    """Fetch available repositories from GitHub."""
    token = None
    logger.info("Attempting to retrieve GitHub token from vault...")
    
    # 1. Try different possible keys in the vault
    keys_to_try = ["github_token", "tron:github_token", "enginsights:github-api-token"]
    
    for k in keys_to_try:
        try:
            # Use explicit=True for keys that already have a prefix or are from other projects
            is_explicit = ":" in k
            token = await get_secret(k, explicit=is_explicit)
            if token: 
                logger.info(f"Successfully found GitHub token using key: {k}")
                break
        except Exception as e:
            logger.debug(f"Key {k} not found in vault: {e}")

    if not token:
        # 2. Fallback to env for local dev if vault not configured
        import os
        token = os.environ.get("TRON_PLAN_GIT_TOKEN")
        if token: logger.info("Using TRON_PLAN_GIT_TOKEN from environment")
        
    if not token:
        logger.error("No GitHub token found in vault or environment")
        raise HTTPException(
            status_code=400, 
            detail="GitHub integration not configured. Please add 'tron/github_token' to vault."
        )
        
    github = GitHubService(token=token)
    
    if org:
        repos = await github.list_org_repos(org)
    else:
        repos = await github.list_user_repos()
        
    return [
        GithubRepoResponse(
            name=r["name"],
            full_name=r["full_name"],
            html_url=r["html_url"],
            description=r.get("description"),
            stargazers_count=r.get("stargazers_count", 0),
            language=r.get("language"),
            updated_at=r.get("updated_at", ""),
        )
        for r in repos
    ]
