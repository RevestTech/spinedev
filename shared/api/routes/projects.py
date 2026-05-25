"""``/api/v2/projects`` — Spine project lifecycle REST surface (STORY-9.9.2).

Mutations delegate to the unified MCP server (``project_create``,
``phase_advance``); reads go straight to ``spine_lifecycle`` so list /
detail stay cheap and don't need an MCP round-trip.
"""

from __future__ import annotations

import json as _json
import logging
from datetime import datetime, timezone
from pathlib import Path
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


async def _project_db_pool():
    from shared.api.dependencies import get_db_pool_raw  # noqa: PLC0415

    pool = get_db_pool_raw()
    if pool is None:
        raise _err(503, "db_unavailable", "DB pool not initialized (dev mode without vault?)")
    return pool


def _parse_metadata(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = _json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:  # noqa: BLE001
            return {}
    return {}


async def _fetch_project_row(project_id: str) -> dict[str, Any] | None:
    """Load a project row by numeric PK or UUID string."""
    pool = await _project_db_pool()
    where = "id = $1" if project_id.isdigit() else "project_uuid::text = $1"
    arg: Any = int(project_id) if project_id.isdigit() else project_id
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"SELECT id, project_uuid::text AS project_uuid, name, project_type, "
            f"current_phase, status, owner_user, pipeline_version, metadata, "
            f"created_at, updated_at FROM spine_lifecycle.project WHERE {where}",
            arg,
        )
    if row is None:
        return None
    metadata = _parse_metadata(row["metadata"])
    return {
        "id": int(row["id"]),
        "project_uuid": row["project_uuid"],
        "name": row["name"],
        "project_type": row["project_type"],
        "current_phase": row["current_phase"],
        "status": row["status"],
        "owner": row["owner_user"],
        "pipeline_version": row["pipeline_version"],
        "metadata": metadata,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


async def _patch_project_row(
    project_uuid: str,
    *,
    name: Optional[str] = None,
    status: Optional[str] = None,
    metadata_patch: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Partial update — metadata keys are merged into the existing blob."""
    pool = await _project_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE spine_lifecycle.project
            SET
              name = COALESCE($2, name),
              status = COALESCE($3, status),
              metadata = CASE
                WHEN $4::jsonb IS NOT NULL
                THEN COALESCE(metadata, '{}'::jsonb) || $4::jsonb
                ELSE metadata
              END,
              updated_at = now()
            WHERE project_uuid::text = $1
            RETURNING id, project_uuid::text AS project_uuid, name, project_type,
                      current_phase, status, owner_user, pipeline_version,
                      metadata, created_at, updated_at
            """,
            project_uuid,
            name,
            status,
            _json.dumps(metadata_patch) if metadata_patch is not None else None,
        )
    if row is None:
        raise _err(404, "project_not_found", f"project {project_uuid!r} not found")
    md = _parse_metadata(row["metadata"])
    return {
        "id": int(row["id"]),
        "project_uuid": row["project_uuid"],
        "name": row["name"],
        "project_type": row["project_type"],
        "current_phase": row["current_phase"],
        "status": row["status"],
        "owner": row["owner_user"],
        "pipeline_version": row["pipeline_version"],
        "metadata": md,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


async def _write_project_row(
    project_uuid: str,
    *,
    name: Optional[str] = None,
    status: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Persist project mutations; ``metadata`` replaces the stored JSONB blob."""
    pool = await _project_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE spine_lifecycle.project
            SET
              name = COALESCE($2, name),
              status = COALESCE($3, status),
              metadata = COALESCE($4::jsonb, metadata),
              updated_at = now()
            WHERE project_uuid::text = $1
            RETURNING id, project_uuid::text AS project_uuid, name, project_type,
                      current_phase, status, owner_user, pipeline_version,
                      metadata, created_at, updated_at
            """,
            project_uuid,
            name,
            status,
            _json.dumps(metadata) if metadata is not None else None,
        )
    if row is None:
        raise _err(404, "project_not_found", f"project {project_uuid!r} not found")
    md = _parse_metadata(row["metadata"])
    return {
        "id": int(row["id"]),
        "project_uuid": row["project_uuid"],
        "name": row["name"],
        "project_type": row["project_type"],
        "current_phase": row["current_phase"],
        "status": row["status"],
        "owner": row["owner_user"],
        "pipeline_version": row["pipeline_version"],
        "metadata": md,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _audit_project_mutation(
    *,
    action: str,
    actor: str,
    project_pk: int,
    project_uuid: str,
    rationale: Optional[str] = None,
    extra: Optional[dict[str, Any]] = None,
) -> str:
    from shared.audit.audit_record import AuditRecord, chain_to_previous  # noqa: PLC0415

    rec = AuditRecord(
        role="hub",
        subsystem="hub",
        action=action,
        actor=actor,
        subject_type="project",
        subject_id=project_uuid,
        project_id=project_pk,
        rationale=rationale,
        metadata={"surface": "projects", **(extra or {})},
    )
    rec = chain_to_previous(rec, prev_hash=None)
    return str(rec.event_uuid)


def _project_response(row: dict[str, Any]) -> dict[str, Any]:
    updated = row.get("updated_at")
    return {
        "id": row["id"],
        "project_id": row["project_uuid"],
        "project_uuid": row["project_uuid"],
        "name": row["name"],
        "project_type": row["project_type"],
        "current_phase": row["current_phase"],
        "status": row["status"],
        "owner": row.get("owner"),
        "metadata": row.get("metadata") or {},
        "updated_at": updated.isoformat() if updated is not None else None,
    }


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
    spine_on_spine: Optional[bool] = Field(
        default=None,
        description="Dogfood flag: engineer workspace targets Spine platform repo sandbox.",
    )
    description: Optional[str] = Field(default=None, max_length=2000)


class ProjectUpdate(BaseModel):
    """Body for ``PATCH /api/v2/projects/{id}``."""

    model_config = _FORBID
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=2000)
    status: Optional[ProjectStatus] = None
    metadata: Optional[dict[str, Any]] = None


class ProjectLifecycleNote(BaseModel):
    """Optional audit note for archive / delete / restore."""

    model_config = _FORBID
    note: Optional[str] = Field(default=None, max_length=2000)


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


class ProjectRecoveryDispatch(BaseModel):
    """Body for ``POST /api/v2/projects/{id}/recovery/dispatch``."""

    model_config = _FORBID
    action: str = Field(..., min_length=1)
    note: Optional[str] = Field(default=None, max_length=4000)


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
                if body.spine_on_spine:
                    patch["spine_on_spine"] = True
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

    # Bootstrap per-project git workspace + KG post-commit hook (P1).
    if project_id:
        try:
            from shared.runtime.project_workspace import (
                bootstrap_project_git_repo,
                metadata_patch_from_bootstrap,
            )

            boot = bootstrap_project_git_repo(
                project_id,
                body.name,
                metadata={"spine_on_spine": True} if body.spine_on_spine else None,
            )
            patch = metadata_patch_from_bootstrap(boot)
            if boot.errors:
                logger.warning(
                    "project_workspace_bootstrap_warnings",
                    extra={"project_id": project_id, "errors": boot.errors},
                )
            from shared.api.dependencies import get_db_pool_raw

            pool = get_db_pool_raw()
            if pool is not None and patch:
                import json as _json

                async with pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE spine_lifecycle.project SET metadata = "
                        "COALESCE(metadata, '{}'::jsonb) || $1::jsonb "
                        "WHERE project_uuid::text = $2",
                        _json.dumps(patch),
                        project_id,
                    )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "project_workspace_bootstrap_failed",
                extra={"project_id": project_id, "error": str(exc)},
            )

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
                "project_uuid": project_id,
                "greenfield": bool(body.greenfield),
                "spine_on_spine": bool(body.spine_on_spine),
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
    include_archived: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    """List projects with optional filters + pagination."""
    where = ["status != 'terminated'"]
    if not include_archived and status_filter != "completed":
        where.append("status != 'completed'")
    if phase:
        where.append(f"current_phase = '{_esc(phase)}'")
    if status_filter:
        where.append(f"status = '{_esc(status_filter)}'")
    if owner:
        where.append(f"owner_user = '{_esc(owner)}'")
    sql = (
        "SELECT json_build_object('project_id', project_uuid::text, 'id', id, "
        "'project_uuid', project_uuid::text, "
        "'name', name, 'project_type', project_type, 'current_phase', current_phase, "
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


@router.get("/recovery/summary")
async def list_recovery_summary(
    user: Annotated[User, Depends(current_user)],
    limit: int = Query(default=200, ge=1, le=500),
) -> dict[str, Any]:
    """Batch stuck-project scan for the projects dashboard."""
    from shared.api.routes._project_recovery import recovery_summary  # noqa: PLC0415

    result = await recovery_summary(limit=limit)
    return {"actor": actor_label(user), **result}


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


_MD_ARTIFACT_KEYS = frozenset({
    "prd_md",
    "roadmap_md",
    "trd_md",
    "sprint_plan_md",
    "code_intro_md",
    "code_review_md",
    "qa_md",
    "release_gate_md",
})

# Blobs omitted from GET /summary so first paint stays ~1KB.
_SUMMARY_STRIP_KEYS = frozenset({
    "intake_transcript",
    "code_run_block",
    "recovery_dispatch_in_flight",
})

_BUILD_ARTIFACT_SUMMARY_KEYS = frozenset({
    "status",
    "phase",
    "role",
    "artifact_uuid",
    "directive_id",
    "version",
})


def _parse_project_metadata(raw: Any) -> dict[str, Any]:
    import json as _json

    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str):
        try:
            parsed = _json.loads(raw)
            return dict(parsed) if isinstance(parsed, dict) else {}
        except Exception:  # noqa: BLE001
            return {}
    return {}


def _slim_metadata_for_summary(meta: dict[str, Any]) -> dict[str, Any]:
    out = {
        k: v
        for k, v in meta.items()
        if k not in _MD_ARTIFACT_KEYS and k not in _SUMMARY_STRIP_KEYS
    }
    if "code_files" in out:
        code_files = out.pop("code_files")
        if isinstance(code_files, list):
            out["code_files_count"] = len(code_files)
    build_artifact = out.get("build_artifact")
    if isinstance(build_artifact, dict):
        out["build_artifact"] = {
            k: build_artifact[k]
            for k in _BUILD_ARTIFACT_SUMMARY_KEYS
            if k in build_artifact
        }
    return out


def _project_row_payload(
    row: Any,
    *,
    include_artifacts: bool,
    include_code_list: bool,
    for_summary: bool = False,
) -> dict[str, Any]:
    meta_out = _parse_project_metadata(row["metadata"])
    if for_summary:
        meta_out = _slim_metadata_for_summary(meta_out)
    elif not include_artifacts:
        meta_out = _slim_metadata_for_summary(meta_out)
        meta_out = {k: v for k, v in meta_out.items() if k not in _MD_ARTIFACT_KEYS}
    if not for_summary and not include_code_list and "code_files" in meta_out:
        code_files = meta_out.pop("code_files")
        if isinstance(code_files, list):
            meta_out["code_files_count"] = len(code_files)
    return {
        "id": int(row["id"]),
        "project_id": row["project_uuid"],
        "name": row["name"],
        "project_type": row["project_type"],
        "current_phase": row["current_phase"],
        "status": row["status"],
        "owner": row["owner_user"],
        "pipeline_version": row["pipeline_version"],
        "metadata": meta_out,
        "prd_md": meta_out.get("prd_md") if include_artifacts else None,
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
    }


async def _fetch_project_row(project_id: str) -> Any:
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
    if row["status"] == "terminated":
        raise _err(404, "project_not_found", f"project {project_id!r} was deleted")
    return row


@router.get("/{project_id}/summary")
async def get_project_summary(project_id: str) -> dict[str, Any]:
    """Minimal project header for fast workspace first paint (~1KB)."""
    row = await _fetch_project_row(project_id)
    return _project_row_payload(
        row,
        include_artifacts=False,
        include_code_list=False,
        for_summary=True,
    )


@router.get("/{project_id}/full")
async def get_project_full(
    project_id: str,
    include_artifacts: bool = True,
) -> dict[str, Any]:
    """Direct read of project row + metadata (incl. PRD when present).

    Used by the workspace UI to render the project header + PRD + activity
    feed without going through the MCP indirection. Returns 404 if the
    project doesn't exist; 503 if the DB pool is unavailable.

    Pass ``include_artifacts=false`` for a lightweight snapshot (phase,
    flags, code file list) without multi‑KB markdown blobs in metadata.
    """
    row = await _fetch_project_row(project_id)
    return _project_row_payload(
        row,
        include_artifacts=include_artifacts,
        include_code_list=True,
    )


async def _resolve_workspace_uuid(project_id: str) -> str:
    """Workspace dirs are keyed by project UUID. If the caller passed an
    integer PK (the list endpoint returns id::text), look up the UUID."""
    if not project_id.isdigit():
        return project_id
    from shared.api.dependencies import get_db_pool_raw
    pool = get_db_pool_raw()
    if pool is None:
        return project_id
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT project_uuid::text AS u FROM spine_lifecycle.project WHERE id = $1",
            int(project_id),
        )
    return row["u"] if row else project_id


async def _load_project_metadata(project_uuid: str) -> dict[str, Any]:
    """Load project metadata JSONB for workspace resolution."""
    import json as _json

    from shared.api.dependencies import get_db_pool_raw

    pool = get_db_pool_raw()
    if pool is None:
        return {}
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT metadata FROM spine_lifecycle.project WHERE project_uuid::text = $1",
            project_uuid,
        )
    if not row:
        return {}
    md = row["metadata"] or {}
    if isinstance(md, str):
        try:
            md = _json.loads(md)
        except _json.JSONDecodeError:
            md = {}
    return md if isinstance(md, dict) else {}


async def _resolve_workspace_dir(project_id: str) -> Path:
    """Return engineer workspace path (includes spine_on_spine dogfood sandbox)."""
    from shared.runtime.project_workspace import resolve_code_dir

    uid = await _resolve_workspace_uuid(project_id)
    md = await _load_project_metadata(uid)
    return resolve_code_dir(uid, md)


@router.get("/{project_id}/workspace/files")
async def list_workspace_files(project_id: str) -> dict[str, Any]:
    """Return a tree of files the engineer wrote into the project's workspace."""
    pdir = await _resolve_workspace_dir(project_id)
    if not pdir.exists() or not pdir.is_dir():
        return {"items": [], "root": str(pdir), "missing": True}
    items: list[dict[str, Any]] = []
    for path in sorted(pdir.rglob("*")):
        if path.is_file():
            rel = str(path.relative_to(pdir))
            items.append({"path": rel, "bytes": path.stat().st_size})
    return {"items": items, "root": str(pdir), "missing": False}


@router.get("/{project_id}/workspace/file")
async def read_workspace_file(project_id: str, path: str) -> dict[str, Any]:
    """Return the contents of one file under the project's workspace dir."""
    pdir = await _resolve_workspace_dir(project_id)
    target = (pdir / path).resolve()
    try:
        target.relative_to(pdir)
    except ValueError:
        raise _err(400, "path_escape", "path escapes workspace") from None
    if not target.exists() or not target.is_file():
        raise _err(404, "file_not_found", f"{path} not in workspace")
    content = target.read_text(encoding="utf-8", errors="replace")
    return {"path": path, "bytes": len(content), "content": content}


from fastapi.responses import StreamingResponse
import io
import zipfile


@router.get("/{project_id}/workspace/zip")
async def download_workspace_zip(project_id: str) -> StreamingResponse:
    """Stream the project's workspace dir as a zip."""
    uid = await _resolve_workspace_uuid(project_id)
    pdir = await _resolve_workspace_dir(project_id)
    if not pdir.exists() or not pdir.is_dir():
        raise _err(404, "workspace_missing", f"no workspace for {uid}")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in pdir.rglob("*"):
            if path.is_file():
                zf.write(path, arcname=path.relative_to(pdir))
    buf.seek(0)
    return StreamingResponse(
        buf, media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="spine-{uid[:8]}.zip"'},
    )


@router.get("/{project_id}/deployment")
async def deployment_status(project_id: str) -> dict[str, Any]:
    """Return the live deployment state for a project (in-memory)."""
    from shared.api.routes._post_ack import get_deployment
    project_id = await _resolve_workspace_uuid(project_id)
    info = get_deployment(project_id)
    if info is None:
        return {"running": False}
    proc = info.get("proc")
    cli_mode = bool(info.get("cli_mode"))
    return {
        "running": proc is not None and proc.returncode is None and not cli_mode,
        "cli_mode": cli_mode,
        "port": info.get("port"),
        "url": info.get("url"),
        "pid": info.get("pid"),
        "cmd": info.get("cmd"),
        "started": info.get("started"),
        "log_tail": (info.get("log_tail") or "")[:4000],
        "rc": proc.returncode if proc is not None else None,
        "deploy_ok": proc.returncode == 0 if proc is not None and cli_mode else None,
    }


@router.post("/{project_id}/deployment/stop")
async def deployment_stop(project_id: str) -> dict[str, Any]:
    """Kill the project's running subprocess."""
    from shared.api.routes._post_ack import stop_deployment
    project_id = await _resolve_workspace_uuid(project_id)
    ok = await stop_deployment(project_id)
    return {"ok": ok, "project_id": project_id}


@router.post("/{project_id}/deployment/start")
async def deployment_start(project_id: str) -> dict[str, Any]:
    """Force-start (or restart) the local deployment without waiting for
    the local_deploy_prompt approval card. Useful for the workspace UI's
    "Re-deploy" button."""
    from shared.api.routes._post_ack import _dispatch_local_deploy, _load_project_full
    project = await _load_project_full(project_id)
    if project is None:
        raise _err(404, "project_not_found", project_id)
    import asyncio as _asyncio
    _asyncio.create_task(_dispatch_local_deploy(project=project))
    return {"ok": True, "project_id": project_id, "started": True}


@router.post("/{project_id}/advance-phase-by-uuid")
async def advance_phase_by_uuid(project_id: str, body: dict[str, Any]) -> dict[str, Any]:
    """Advance phase via canonical pipeline bridge (transition.sh when available)."""
    target_phase = str(body.get("target_phase", "")).strip()
    if not target_phase:
        raise _err(400, "invalid_input", "target_phase required")
    actor = str(body.get("actor", "hub-api")).strip() or "hub-api"
    grant_gate = bool(body.get("grant_gate", False))
    from shared.api.routes._pipeline_bridge import advance_lifecycle_phase

    ok = await advance_lifecycle_phase(
        project_id, target_phase, actor, grant_gate=grant_gate,
    )
    if not ok:
        raise _err(409, "transition_rejected", f"could not advance to {target_phase!r}")
    from shared.api.routes._post_ack import _load_project_full

    project = await _load_project_full(project_id)
    if project is None:
        raise _err(404, "project_not_found", f"project {project_id!r} not found")
    return {"project_id": project_id, "current_phase": project["current_phase"]}


@router.patch("/{project_id}")
async def patch_project(
    project_id: str,
    body: ProjectUpdate,
    user: Annotated[User, Depends(current_user)],
) -> dict[str, Any]:
    """Update project name, description (metadata), status, or metadata patch."""
    if (
        body.name is None
        and body.description is None
        and body.status is None
        and body.metadata is None
    ):
        raise _err(400, "invalid_input", "at least one of name, description, status, metadata required")

    row = await _fetch_project_row(project_id)
    if row is None:
        raise _err(404, "project_not_found", f"project {project_id!r} not found")
    if row["status"] == "terminated":
        raise _err(409, "project_terminated", "Cannot update a deleted project")

    meta_patch: dict[str, Any] = dict(body.metadata or {})
    if body.description is not None:
        meta_patch["description"] = body.description

    actor = actor_label(user)
    updated = await _patch_project_row(
        row["project_uuid"],
        name=body.name,
        status=body.status,
        metadata_patch=meta_patch or None,
    )
    audit_id = _audit_project_mutation(
        action="project_updated",
        actor=actor,
        project_pk=updated["id"],
        project_uuid=updated["project_uuid"],
        extra={"fields": body.model_dump(exclude_none=True)},
    )
    return {"ok": True, "actor": actor, "audit_event_uuid": audit_id, **_project_response(updated)}


@router.post("/{project_id}/archive")
async def archive_project(
    project_id: str,
    user: Annotated[User, Depends(current_user)],
    body: ProjectLifecycleNote | None = None,
) -> dict[str, Any]:
    """Archive a project (``status=completed``). Hidden from default lists; restorable."""
    row = await _fetch_project_row(project_id)
    if row is None:
        raise _err(404, "project_not_found", f"project {project_id!r} not found")
    if row["status"] == "terminated":
        raise _err(409, "project_terminated", "Cannot archive a deleted project")
    if row["status"] == "completed":
        return {"ok": True, "already_archived": True, **_project_response(row)}

    actor = actor_label(user)
    now_iso = datetime.now(timezone.utc).isoformat()
    md = dict(row["metadata"])
    md["archived_at"] = now_iso
    md["archived_by"] = actor
    updated = await _write_project_row(row["project_uuid"], status="completed", metadata=md)
    audit_id = _audit_project_mutation(
        action="project_archived",
        actor=actor,
        project_pk=updated["id"],
        project_uuid=updated["project_uuid"],
        rationale=(body.note if body else None),
    )
    return {"ok": True, "actor": actor, "audit_event_uuid": audit_id, **_project_response(updated)}


@router.post("/{project_id}/restore")
async def restore_project(
    project_id: str,
    user: Annotated[User, Depends(current_user)],
    body: ProjectLifecycleNote | None = None,
) -> dict[str, Any]:
    """Restore an archived (``completed``) or paused project to ``active``."""
    row = await _fetch_project_row(project_id)
    if row is None:
        raise _err(404, "project_not_found", f"project {project_id!r} not found")
    if row["status"] == "terminated":
        raise _err(409, "project_terminated", "Cannot restore a deleted project")
    if row["status"] == "active":
        return {"ok": True, "already_active": True, **_project_response(row)}
    if row["status"] not in ("completed", "paused"):
        raise _err(409, "project_not_restorable", f"status {row['status']!r} cannot be restored")

    actor = actor_label(user)
    now_iso = datetime.now(timezone.utc).isoformat()
    md = dict(row["metadata"])
    md.pop("archived_at", None)
    md.pop("archived_by", None)
    md["restored_at"] = now_iso
    md["restored_by"] = actor
    updated = await _write_project_row(row["project_uuid"], status="active", metadata=md)
    audit_id = _audit_project_mutation(
        action="project_restored",
        actor=actor,
        project_pk=updated["id"],
        project_uuid=updated["project_uuid"],
        rationale=(body.note if body else None),
    )
    return {"ok": True, "actor": actor, "audit_event_uuid": audit_id, **_project_response(updated)}


@router.delete("/{project_id}")
async def delete_project(
    project_id: str,
    user: Annotated[User, Depends(current_user)],
    note: Optional[str] = Query(default=None, max_length=2000),
) -> dict[str, Any]:
    """Soft-delete a project (``status=terminated``). Excluded from all Hub lists."""
    row = await _fetch_project_row(project_id)
    if row is None:
        raise _err(404, "project_not_found", f"project {project_id!r} not found")
    if row["status"] == "terminated":
        return {"ok": True, "already_deleted": True, "project_id": row["project_uuid"]}

    actor = actor_label(user)
    now_iso = datetime.now(timezone.utc).isoformat()
    md = dict(row["metadata"])
    md["terminated_at"] = now_iso
    md["terminated_by"] = actor
    updated = await _write_project_row(row["project_uuid"], status="terminated", metadata=md)
    audit_id = _audit_project_mutation(
        action="project_deleted",
        actor=actor,
        project_pk=updated["id"],
        project_uuid=updated["project_uuid"],
        rationale=note,
    )
    return {"ok": True, "actor": actor, "audit_event_uuid": audit_id, "project_id": updated["project_uuid"]}


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


@router.get("/{project_id}/activity/terminal")
async def get_project_terminal_log(
    project_id: str,
    user: Annotated[User, Depends(current_user)],
    limit: int = Query(default=500, ge=1, le=800),
) -> dict[str, Any]:
    """Recent live role output lines for the embedded pipeline terminal."""
    from shared.runtime.role_activity import get_terminal_log  # noqa: PLC0415

    uid = await _resolve_workspace_uuid(project_id)
    lines = await get_terminal_log(uid, limit=limit)
    return {"project_id": uid, "lines": lines, "count": len(lines), "actor": actor_label(user)}


@router.get("/{project_id}/recovery")
async def get_project_recovery(
    project_id: str,
    user: Annotated[User, Depends(current_user)],
) -> dict[str, Any]:
    """Recovery status: stuck reasons + actions the founder can invoke."""
    from shared.api.routes._project_recovery import recovery_status  # noqa: PLC0415

    result = await recovery_status(project_id)
    if not result.get("ok"):
        raise _err(404, "project_not_found", "Project not found")
    return {"actor": actor_label(user), **result}


@router.post("/{project_id}/recovery/dispatch")
async def dispatch_project_recovery(
    project_id: str,
    body: ProjectRecoveryDispatch,
    user: Annotated[User, Depends(current_user)],
) -> dict[str, Any]:
    """Manually dispatch a pipeline role when the SDLC is idle or broken."""
    from shared.api.routes._project_recovery import recovery_dispatch  # noqa: PLC0415

    actor = actor_label(user)
    result = await recovery_dispatch(
        project_id,
        body.action,  # type: ignore[arg-type]
        actor=actor,
        note=body.note,
    )
    if not result.get("ok"):
        code = result.get("error", "dispatch_failed")
        if code == "project_not_found":
            raise _err(404, code, result.get("message", "Project not found"))
        if code == "dispatch_in_flight":
            raise _err(409, str(code), result.get("message", "Dispatch already running"), result)
        raise _err(400, str(code), result.get("message", "Dispatch failed"), result)
    from fastapi.responses import JSONResponse

    status = 202 if result.get("async") else 200
    return JSONResponse(status_code=status, content={"actor": actor, **result})


@router.post("/{project_id}/recovery/cancel-inflight")
async def cancel_project_recovery_inflight(
    project_id: str,
    user: Annotated[User, Depends(current_user)],
) -> dict[str, Any]:
    """Clear orphaned recovery_dispatch_in_flight metadata (UI unblock after Hub restart)."""
    from shared.api.routes._project_recovery import recovery_cancel_inflight  # noqa: PLC0415

    actor = actor_label(user)
    result = await recovery_cancel_inflight(project_id, actor=actor)
    if not result.get("ok"):
        raise _err(404, "project_not_found", "Project not found")
    return {"actor": actor, **result}
