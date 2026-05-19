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

    data = (resp or {}).get("data") or resp or {}
    project_id = data.get("project_id") or data.get("project_uuid") or ""

    # Persist the SPA-side metadata (greenfield flag + user's free-text
    # description) onto the project row so downstream consumers — the
    # workspace page, the intake role — can read it.
    if project_id:
        try:
            import json as _json
            from shared.api.dependencies import get_db_pool_raw
            pool = get_db_pool_raw()
            if pool is not None:
                patch: dict[str, Any] = {
                    "greenfield": bool(body.greenfield),
                }
                if body.description:
                    patch["description"] = body.description
                async with pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE spine_lifecycle.project SET metadata = "
                        "COALESCE(metadata, '{}'::jsonb) || $1::jsonb "
                        "WHERE project_uuid::text = $2",
                        _json.dumps(patch), project_id,
                    )
        except Exception as exc:  # noqa: BLE001
            logger.warning("project_meta_persist_failed",
                           extra={"project_id": project_id, "error": str(exc)})

    # Seed the intake briefing decision so the queue isn't empty when the
    # user lands. Best-effort — never blocks project creation.
    try:
        import uuid as _uuid

        from shared.api.routes.decisions import DecisionCard, enqueue_decision
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
    # Parse the JSON-string rows server-side so consumers see real objects.
    import json as _json
    items: list[Any] = []
    for r in rows:
        raw = r.get("_row")
        if isinstance(raw, str):
            try:
                items.append(_json.loads(raw))
                continue
            except Exception:  # noqa: BLE001
                pass
        items.append(raw)
    return {"items": items, "limit": limit, "offset": offset}


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


@router.get("/{project_id}/full")
async def get_project_full(project_id: str) -> dict[str, Any]:
    """Direct read of project row + metadata (incl. PRD when present).

    Used by the workspace UI to render the project header + PRD + activity
    feed without going through the MCP indirection. Returns 404 if the
    project doesn't exist; 503 if the DB pool is unavailable.
    """
    from shared.api.dependencies import get_db_pool_raw
    pool = get_db_pool_raw()
    if pool is None:
        raise _err(503, "db_unavailable", "DB pool not initialized (dev mode without vault?)")
    where_clause = "id = $1" if project_id.isdigit() else "project_uuid::text = $1"
    arg: Any = int(project_id) if project_id.isdigit() else project_id
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"SELECT id, project_uuid::text AS project_uuid, name, project_type, "
            f"current_phase, status, owner_user, pipeline_version, "
            f"metadata, created_at, updated_at "
            f"FROM spine_lifecycle.project WHERE {where_clause}",
            arg,
        )
    if row is None:
        raise _err(404, "project_not_found", f"project {project_id!r} not found")
    import json as _json
    metadata = row["metadata"]
    if isinstance(metadata, str):
        try:
            metadata = _json.loads(metadata)
        except Exception:  # noqa: BLE001
            metadata = {}
    return {
        "id": int(row["id"]),
        "project_id": row["project_uuid"],
        "name": row["name"],
        "project_type": row["project_type"],
        "current_phase": row["current_phase"],
        "status": row["status"],
        "owner": row["owner_user"],
        "pipeline_version": row["pipeline_version"],
        "metadata": metadata or {},
        "prd_md": (metadata or {}).get("prd_md"),
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
    }


@router.post("/{project_id}/advance-phase-by-uuid")
async def advance_phase_by_uuid(project_id: str, body: dict[str, Any]) -> dict[str, Any]:
    """Direct phase-advance bypassing MCP indirection.

    Used by the decision-card ack handler when a prd_approval card lands
    so the SPA can flip the workspace into the plan phase immediately.
    Updates project.current_phase + appends to phase_history. No
    HMAC-token check in dev mode (Wave 4 wires the approval token
    pathway through here too).
    """
    target_phase = str(body.get("target_phase", "")).strip()
    if not target_phase:
        raise _err(400, "invalid_input", "target_phase required")
    from shared.api.dependencies import get_db_pool_raw
    pool = get_db_pool_raw()
    if pool is None:
        raise _err(503, "db_unavailable", "DB pool not initialized")
    where_clause = "id = $2" if project_id.isdigit() else "project_uuid::text = $2"
    arg: Any = int(project_id) if project_id.isdigit() else project_id
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                f"UPDATE spine_lifecycle.project SET current_phase = $1, "
                f"updated_at = now() WHERE {where_clause} "
                f"RETURNING id, current_phase",
                target_phase, arg,
            )
            if row is None:
                raise _err(404, "project_not_found", f"project {project_id!r} not found")
            await conn.execute(
                "INSERT INTO spine_lifecycle.phase_history "
                "(project_id, phase, entered_at) VALUES ($1, $2, now())",
                int(row["id"]), target_phase,
            )
    return {"project_id": project_id, "current_phase": row["current_phase"]}


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
