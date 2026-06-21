"""
Integrations API - GitHub and Third-Party Connectors.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tron.domain.models import SavedGithubOrg
from tron.infra.db.session import get_session
from tron.infra.secrets import get_secret
from tron.services.github_service import GitHubAPIError, GitHubService

logger = logging.getLogger(__name__)
router = APIRouter()

# GitHub login rules: 1-39 chars, alphanumerics or hyphens, no leading/trailing
# hyphen. The point of this regex is to prevent URL-path injection (slashes,
# spaces, ``..``) before we paste the value into ``/orgs/{login}/repos`` — it
# is intentionally not a strict mirror of every GitHub signup rule.
# Length math: 1 first char + up to 37 middle + 1 last char = 39 chars max.
_GITHUB_LOGIN_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")


# ─── GitHub PAT lookup (shared by repo list + saved-org validation) ───

async def _lookup_github_pat() -> Optional[str]:
    """Try the same vault keys the existing repo-list endpoint uses, then env.

    Centralised so the saved-orgs validator and the repo lister stay in sync;
    if a future PR rotates the vault key, both paths get the change for free.
    """
    keys_to_try = ["github_token", "tron:github_token", "enginsights:github-api-token"]
    for k in keys_to_try:
        try:
            is_explicit = ":" in k
            token = await get_secret(k, explicit=is_explicit)
            if token:
                logger.info("Using GitHub token from vault key '%s'", k)
                return token
        except Exception as e:  # vault miss is expected; only log at debug
            logger.debug("Vault key %s not found: %s", k, e)

    import os
    token = os.environ.get("TRON_PLAN_GIT_TOKEN")
    if token:
        logger.info("Using TRON_PLAN_GIT_TOKEN from environment")
        return token
    return None


def _format_github_error(err: GitHubAPIError, *, login: Optional[str]) -> str:
    """Append SSO/PAT-rotation hints to common GitHub failure modes."""
    extra = ""
    if login and err.status_code == 403:
        extra = (
            f" For GitHub organizations with SAML SSO: open the PAT in GitHub → "
            f"Fine-grained or classic token settings → Configure SSO → Authorize "
            f"for {login}. Ensure the token has repo (or org/repository) read "
            f"access to that org."
        )
    elif err.status_code == 401:
        extra = (
            " GitHub rejected the personal access token Tron uses (KMac/vault: "
            "github_token, tron:github_token, or enginsights:github-api-token; "
            "or TRON_PLAN_GIT_TOKEN in the API container). Replace it with a "
            "new PAT in GitHub → Developer settings, store it in vault, redeploy."
        )
    return (err.message or str(err)) + extra


# ─── /integrations/github/repos ───

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
    session: AsyncSession = Depends(get_session),
):
    """Fetch available repositories from GitHub.

    If ``org`` matches a row in ``saved_github_orgs``, we use the saved
    ``kind`` to pick the API path directly. Otherwise we fall back to
    ``list_repos_for_login`` which tries org→user. Both paths converge
    on the same response shape; the saved-org optimisation just skips
    one round-trip when we already know the answer.
    """
    token = await _lookup_github_pat()
    if not token:
        logger.error("No GitHub token found in vault or environment")
        raise HTTPException(
            status_code=400,
            detail="GitHub integration not configured. Please add 'tron/github_token' to vault.",
        )

    github = GitHubService(token=token)

    if org:
        org = org.strip()
    try:
        if org:
            saved = await session.execute(
                select(SavedGithubOrg).where(SavedGithubOrg.login == org.lower())
            )
            saved_row = saved.scalar_one_or_none()
            if saved_row and saved_row.kind == "user":
                # Known to be a user account — go straight to /users/{login}/repos
                # to skip the 404 from /orgs that list_repos_for_login would hit.
                import httpx

                async with httpx.AsyncClient(timeout=15.0) as client:
                    r = await github._get_authenticated(
                        client,
                        f"{github.base_url}/users/{org}/repos",
                        params={"per_page": 100, "sort": "updated"},
                    )
                    if r.status_code == 200:
                        repos = r.json()
                    elif r.status_code in (401, 403):
                        raise GitHubAPIError(r.status_code, r.text[:400])
                    else:
                        repos = []
            else:
                repos = await github.list_repos_for_login(org)
        else:
            repos = await github.list_user_repos()
    except GitHubAPIError as e:
        logger.warning("GitHub repo list failed: %s", e)
        raise HTTPException(
            status_code=502,
            detail=_format_github_error(e, login=org),
        ) from e

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


# ─── /integrations/github/saved-orgs (org switcher) ───

class SavedGithubOrgResponse(BaseModel):
    """A persisted GitHub org/user the operator wants to switch between."""

    id: UUID
    login: str
    display_name: Optional[str]
    kind: str  # "org" or "user"
    pinned: bool
    created_at: datetime


class SavedGithubOrgCreate(BaseModel):
    """Payload for adding a saved org.

    The backend verifies the login resolves on GitHub (using the shared PAT)
    before persisting — that catches typos, SSO-not-authorized PATs, and
    nonexistent orgs at write time so the dropdown can never serve a 404.
    """

    login: str = Field(..., min_length=1, max_length=100)
    display_name: Optional[str] = Field(default=None, max_length=255)
    pinned: bool = False

    @field_validator("login")
    @classmethod
    def _normalise_login(cls, v: str) -> str:
        v = v.strip().strip("/")
        if not _GITHUB_LOGIN_RE.match(v):
            raise ValueError(
                "login must be a valid GitHub login (1-39 chars, alphanumerics or "
                "hyphens, no leading/trailing hyphen)."
            )
        return v.lower()  # case-insensitive on GitHub; normalised for the unique index

    @field_validator("display_name")
    @classmethod
    def _strip_display_name(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v = v.strip()
        return v or None


def _to_response(row: SavedGithubOrg) -> SavedGithubOrgResponse:
    return SavedGithubOrgResponse(
        id=row.id,
        login=row.login,
        display_name=row.display_name,
        kind=row.kind,
        pinned=row.pinned,
        created_at=row.created_at,
    )


@router.get(
    "/integrations/github/saved-orgs",
    response_model=List[SavedGithubOrgResponse],
)
async def list_saved_github_orgs(
    session: AsyncSession = Depends(get_session),
):
    """Return saved GitHub orgs, pinned first, then most recently added."""
    res = await session.execute(
        select(SavedGithubOrg).order_by(
            SavedGithubOrg.pinned.desc(),
            SavedGithubOrg.created_at.desc(),
        )
    )
    return [_to_response(r) for r in res.scalars().all()]


@router.post(
    "/integrations/github/saved-orgs",
    response_model=SavedGithubOrgResponse,
    status_code=201,
)
async def add_saved_github_org(
    body: SavedGithubOrgCreate,
    session: AsyncSession = Depends(get_session),
):
    """Add a saved GitHub org/user after verifying the PAT can see it.

    The verification step is what makes this useful: a saved row whose
    login GitHub returns 404/401 for is dead weight in the dropdown.
    We resolve the kind (org vs user) here too, so the frontend doesn't
    have to guess and the API path is correct on first click.
    """
    token = await _lookup_github_pat()
    if not token:
        raise HTTPException(
            status_code=400,
            detail="GitHub integration not configured. Add 'tron/github_token' to vault first.",
        )

    github = GitHubService(token=token)

    # Resolve kind by trying the org endpoint first, falling back to user
    # exactly the way list_repos_for_login does — this also doubles as
    # an existence/access check.
    import httpx

    kind: str
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            org_url = f"{github.base_url}/orgs/{body.login}"
            r = await github._get_authenticated(client, org_url)
            if r.status_code == 200:
                kind = "org"
            elif r.status_code == 404:
                user_url = f"{github.base_url}/users/{body.login}"
                r2 = await github._get_authenticated(client, user_url)
                if r2.status_code == 200:
                    kind = "user"
                else:
                    raise HTTPException(
                        status_code=404,
                        detail=f"GitHub login '{body.login}' not found.",
                    )
            elif r.status_code in (401, 403):
                raise HTTPException(
                    status_code=502,
                    detail=_format_github_error(
                        GitHubAPIError(r.status_code, r.text[:400] or "auth failed"),
                        login=body.login,
                    ),
                )
            else:
                raise HTTPException(
                    status_code=502,
                    detail=f"GitHub returned {r.status_code} for /orgs/{body.login}.",
                )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("GitHub verification failed for %s: %s", body.login, e)
        raise HTTPException(
            status_code=502,
            detail=f"Could not reach GitHub to verify '{body.login}'.",
        ) from e

    row = SavedGithubOrg(
        login=body.login,
        display_name=body.display_name,
        kind=kind,
        pinned=body.pinned,
    )
    session.add(row)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        # Race or duplicate — return the existing row so the UI can treat
        # add-then-add as idempotent rather than surfacing a 409.
        existing = await session.execute(
            select(SavedGithubOrg).where(SavedGithubOrg.login == body.login)
        )
        existing_row = existing.scalar_one_or_none()
        if existing_row:
            return _to_response(existing_row)
        raise HTTPException(
            status_code=409,
            detail=f"'{body.login}' is already saved.",
        )
    await session.refresh(row)
    return _to_response(row)


@router.delete(
    "/integrations/github/saved-orgs/{org_id}",
    status_code=204,
)
async def delete_saved_github_org(
    org_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> Response:
    row = await session.get(SavedGithubOrg, org_id)
    if not row:
        raise HTTPException(status_code=404, detail="Saved org not found.")
    await session.delete(row)
    await session.commit()
    return Response(status_code=204)


@router.get("/integrations/audit-webhook/schema")
async def audit_webhook_schema() -> dict:
    """JSON Schema for the audit webhook payload.

    Receivers use this to validate incoming events without depending on
    a Tron SDK. Endpoint is intentionally **unauthenticated** — the
    schema is public information about a public integration contract,
    same as a Stripe webhook signature header doc.

    Bumping ``schema_version`` in the payload is a breaking change. The
    schema served here always describes the CURRENT version.
    """
    from tron.services.audit_webhook import AuditWebhookPayload, SCHEMA_VERSION

    schema = AuditWebhookPayload.model_json_schema()
    # Add a top-level discriminator so a receiver caching multiple
    # versions can pick the right one without re-parsing.
    schema["x-tron-schema-version"] = SCHEMA_VERSION
    schema["x-tron-signature-header"] = "X-Tron-Signature"
    schema["x-tron-signature-format"] = (
        "sha256=<hex digest of HMAC-SHA256 over the raw request body>"
    )
    return schema
