"""
Map HTTP paths to API key scope names for scoped (non-master) keys.

WebSocket ``/ws/audits/...`` requires scope ``audits`` (see ``WS_AUDIT_PROGRESS_SCOPES``), matching REST audit routes.

Scopes are lowercase strings stored on ``api_keys.scopes`` (JSON array).
``*`` means full API access (handled before this module runs).

Documented scopes:
  projects, graph, audits, standards, modes, fixes, costs, workflows, gdpr
"""

from __future__ import annotations

import re

from fastapi import HTTPException, Request

# WebSocket audit progress stream — align with REST ``/api/audits`` (scope ``audits``).
WS_AUDIT_PROGRESS_SCOPES: frozenset[str] = frozenset({"audits"})

# OpenAPI / docs: any authenticated key may read (still requires X-API-Key).
_OPENAPI_PATH_PREFIXES = (
    "/api/openapi.json",
    "/api/docs",
    "/api/redoc",
)

_GRAPH_PATH = re.compile(r"^/api/projects/[^/]+/graph(?:/|$)")


def required_scopes_for_path(path: str) -> frozenset[str] | None:
    """
    Return the scope(s) that authorize ``path`` (any one scope is sufficient).

    ``None`` means any non-empty scoped key is allowed (OpenAPI only).
    ``frozenset()`` would deny — not used here.
    """
    if path.startswith(_OPENAPI_PATH_PREFIXES):
        return None

    if path.startswith("/api/api-keys"):
        return frozenset()  # master-only routes add stricter deps; never satisfied by scopes

    if path.startswith("/api/gdpr"):
        return frozenset({"gdpr"})
    if path.startswith("/api/workflow-runs"):
        return frozenset({"workflows"})
    if path.startswith("/api/costs"):
        return frozenset({"costs"})
    if path.startswith("/api/findings"):
        return frozenset({"fixes"})
    if path.startswith("/api/plan/") or path.startswith("/api/build/") or path.startswith("/api/evolve/"):
        return frozenset({"modes"})
    if path.startswith("/api/standards"):
        return frozenset({"standards"})
    if path.startswith("/api/audits"):
        return frozenset({"audits"})

    if _GRAPH_PATH.match(path):
        return frozenset({"graph", "projects"})

    if path.startswith("/api/projects"):
        return frozenset({"projects"})

    return frozenset()


def scopes_satisfy(required: frozenset[str] | None, granted: frozenset[str]) -> bool:
    if required is None:
        return True
    if not required:
        return False
    if "*" in granted:
        return True
    return bool(required & granted)


async def enforce_api_key_route_scope(request: Request) -> None:
    """FastAPI dependency: run after ``require_api_key``."""
    if getattr(request.state, "api_key_is_master", False):
        return
    scopes = getattr(request.state, "api_key_scopes", frozenset())
    if "*" in scopes:
        return

    path = request.url.path
    required = required_scopes_for_path(path)
    if scopes_satisfy(required, scopes):
        return

    raise HTTPException(
        status_code=403,
        detail=(
            "API key is missing a required scope for this route. "
            "See docs/project/TRD.md / docs/reference/API_REFERENCE.md (API key scopes)."
        ),
    )
