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
    try:
        # 1. Try primary tron key
        token = await get_secret("github_token")
    except (KeyError, RuntimeError):
        try:
            # 2. Try the shared organization key found in vault
            token = await get_secret("enginsights:github-api-token")
        except (KeyError, RuntimeError):
            token = None
        
    if not token:
        # 3. Fallback to env for local dev if vault not configured
        import os
        token = os.environ.get("TRON_PLAN_GIT_TOKEN")
        
    if not token:
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
