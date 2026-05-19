"""``/api/v2/projects`` — Spine project lifecycle REST surface (STORY-9.9.2).

Mutations delegate to the unified MCP server (``project_create``,
``phase_advance``); reads go straight to ``spine_lifecycle`` so list /
detail stay cheap and don't need an MCP round-trip.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field

from shared.api.dependencies import (
    DbHandle,
    McpClient,
    actor_label,
    current_user,
    get_db_pool,
    get_mcp_client,
)
from shared.identity.models import User

logger = logging.getLogger("spine.api.projects")
router = APIRouter(prefix="/api/v2/projects", tags=["projects"])

# Wave-2 (Design Decision #19): 7 canonical work-item types Day 1.
# Order matches V28 ENUM seed in ``db/flyway/sql/V28__work_item_types.sql``.
ProjectType = Literal[
    "feature", "bug", "incident", "support", "refactor", "infra", "compliance",
]
ProjectStatus = Literal["active", "paused", "terminated", "completed"]


def _err(code: int, ec: str, msg: str, details: dict[str, Any] | None = None) -> HTTPException:
    """Standard structured ``HTTPException`` — ``{error_code, message, details?}``."""
    body: dict[str, Any] = {"error_code": ec, "message": msg}
    if details is not None:
        body["details"] = details
    return HTTPException(status_code=code, detail=body)


def _esc(s: str) -> str:
    """Single-quote escape for inline SQL literals."""
    return s.replace("'", "''")


_FORBID = ConfigDict(extra="forbid")


class ProjectCreate(BaseModel):
    """Body for ``POST /api/v2/projects``."""

    model_config = _FORBID
    name: str = Field(..., min_length=1, max_length=200)
    project_type: ProjectType
    owner: Optional[str] = None
    # SPA "Kind" dropdown maps `greenfield` → project_type='feature' + this
    # flag so the intake role skips the "read existing code first" preamble.
    # Optional + ignored if not set; backend-only metadata, not stored as a
    # separate column for #19 (the 7 work-item types stay canonical).
    greenfield: Optional[bool] = None
    description: Optional[str] = Field(default=None, max_length=2000)


class ProjectUpdate(BaseModel):
    """Body for ``PATCH /api/v2/projects/{id}``."""

    model_config = _FORBID
    status: Optional[ProjectStatus] = None
    metadata: Optional[dict[str, Any]] = None


class PhaseAdvanceBody(BaseModel):
    """Body for ``POST /api/v2/projects/{id}/phase-advance``."""

    model_config = _FORBID
    target_phase: str = Field(..., min_length=1)
    approval_token: Optional[str] = None


class RollbackBody(BaseModel):
    """Body for ``POST /api/v2/projects/{id}/rollback``."""

    model_config = _FORBID
    target_phase: str = Field(..., min_length=1)
    reason: str = Field(..., min_length=1, max_length=2000)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_project(
    body: ProjectCreate,
    mcp: Annotated[McpClient, Depends(get_mcp_client)],
    user: Annotated[User, Depends(current_user)],
) -> dict[str, Any]:
    """Create a project in ``intake`` via MCP ``project_create``.

    Also seeds an initial "intake briefing" decision card so the SPA's
    decision queue is non-empty immediately after submit — the user has
    something to act on while the intake role (which lands in a future
    wave with real LLM-backed PRD drafting) ramps up.
    """
    actor = actor_label(user)
    try:
        resp = mcp.call("project_create", {
            "name": body.name, "project_type": body.project_type, "owner": body.owner or actor,
        })
    except KeyError as exc:
        raise _err(503, "mcp_tool_missing", str(exc)) from exc
    except ValueError as exc:
        raise _err(400, "invalid_input", str(exc)) from exc

    # Seed the intake briefing decision so the queue isn't empty when the
    # user lands. Best-effort — never blocks project creation.
    try:
        import uuid as _uuid

        from shared.api.routes.decisions import DecisionCard, enqueue_decision

        data = (resp or {}).get("data") or resp or {}
        project_id = data.get("project_id") or data.get("project_uuid") or ""
        kind_label = "greenfield project" if body.greenfield else f"{body.project_type} work"
        desc_block = (
            f"\n\nYour brief:\n> {body.description.strip()}\n"
            if body.description else ""
        )
        card_body = (
            f"You started a new {kind_label}: **{body.name}**.{desc_block}\n"
            f"Before I dispatch the intake role I want to confirm:\n"
            f"  1. Scope is captured above (edit by replying).\n"
            f"  2. Default stack + workspace conventions are OK for v1.\n"
            f"  3. You want the intake role to draft a PRD now and bring "
            f"back a follow-up card with the open questions.\n\n"
            f"Approve to begin, or Reject to take a different direction."
        )
        card = DecisionCard(
            decision_id=str(_uuid.uuid4()),
            decision_class="briefing",
            project_id=str(project_id) if project_id else None,
            title=f"Intake — {body.name}",
            body=card_body,
            severity="info",
            actions=["ack", "reject"],
            metadata={
                "kind": "intake_briefing",
                "project_type": body.project_type,
                "greenfield": bool(body.greenfield),
            },
        )
        enqueue_decision(card)
    except Exception as exc:  # noqa: BLE001
        # Card seeding is non-critical; log + carry on.
        logger.warning("intake_card_seed_failed", extra={"error": str(exc)})

    return {"actor": actor, **resp}


@router.get("")
async def list_projects(
    db: Annotated[DbHandle, Depends(get_db_pool)],
    phase: Optional[str] = Query(default=None),
    status_filter: Optional[ProjectStatus] = Query(default=None, alias="status"),
    owner: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    """List projects with optional filters + pagination."""
    where = ["1=1"]
    if phase:
        where.append(f"current_phase = '{_esc(phase)}'")
    if status_filter:
        where.append(f"status = '{status_filter}'")
    if owner:
        where.append(f"owner_user = '{_esc(owner)}'")
    sql = (
        "SELECT json_build_object('project_id', id::text, 'name', name, "
        "'project_type', project_type, 'current_phase', current_phase, "
        "'status', status, 'owner', owner_user, 'pipeline_version', pipeline_version, "
        "'created_at', created_at, 'updated_at', updated_at)::text "
        f"FROM spine_lifecycle.project WHERE {' AND '.join(where)} "
        f"ORDER BY updated_at DESC LIMIT {limit} OFFSET {offset};"
    )
    try:
        rows = await db.fetch(sql)
    except RuntimeError as exc:
        # Pool absent (dev mode without vault-wired DB password) — return
        # empty list rather than 502 so the SPA dashboard renders cleanly.
        if "pool is not initialized" in str(exc):
            return {"items": [], "limit": limit, "offset": offset, "db_unavailable": True}
        raise _err(502, "db_error", str(exc)) from exc
    return {"items": [r["_row"] for r in rows], "limit": limit, "offset": offset}


@router.get("/{project_id}")
async def get_project(
    project_id: str,
    db: Annotated[DbHandle, Depends(get_db_pool)],
    mcp: Annotated[McpClient, Depends(get_mcp_client)],
) -> dict[str, Any]:
    """Status snapshot via MCP + total audit cost via direct read."""
    try:
        snap = mcp.call("project_status", {"project_id": project_id})
    except KeyError as exc:
        raise _err(503, "mcp_tool_missing", str(exc)) from exc
    except ValueError as exc:
        raise _err(404, "project_not_found", str(exc)) from exc
    try:
        rows = await db.fetch("SELECT COALESCE(SUM(cost_usd),0)::text FROM spine_audit.audit_event"
                              f" WHERE project_id::text = '{_esc(project_id)}';")
    except RuntimeError:
        rows = []
    cost = float(rows[0]["_row"]) if rows else 0.0
    return {"project_id": project_id, "status_snapshot": snap, "total_cost_usd": cost}


@router.patch("/{project_id}")
async def patch_project(project_id: str, body: ProjectUpdate,
                        user: Annotated[User, Depends(current_user)]) -> dict[str, Any]:
    """Update project ``status`` (paused/terminated) or ``metadata`` (stub)."""
    if body.status is None and body.metadata is None:
        raise _err(400, "invalid_input", "at least one of status, metadata required")
    return {"project_id": project_id, "applied": body.model_dump(exclude_none=True),
            "actor": actor_label(user), "note": "stub: wire to transition.sh"}


@router.post("/{project_id}/phase-advance")
async def phase_advance(
    project_id: str, body: PhaseAdvanceBody,
    mcp: Annotated[McpClient, Depends(get_mcp_client)],
    user: Annotated[User, Depends(current_user)],
) -> dict[str, Any]:
    """Advance phase via MCP ``phase_advance``."""
    try:
        return mcp.call("phase_advance", {
            "project_id": project_id, "target_phase": body.target_phase,
            "approval_token": body.approval_token,
        }) | {"actor": actor_label(user)}
    except KeyError as exc:
        raise _err(503, "mcp_tool_missing", str(exc)) from exc
    except ValueError as exc:
        raise _err(400, "invalid_input", str(exc)) from exc


@router.post("/{project_id}/rollback")
async def rollback_project(project_id: str, body: RollbackBody,
                           user: Annotated[User, Depends(current_user)]) -> dict[str, Any]:
    """Roll back to ``target_phase`` (stub — wire to transition.sh rollback)."""
    return {"project_id": project_id, "target_phase": body.target_phase,
            "reason": body.reason, "actor": actor_label(user), "note": "stub"}
