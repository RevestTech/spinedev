"""Orchestrator role dispatch bridge for Hub post-ack hooks.

Maps Decision Queue approval kinds → ``router.sh`` subsystem dispatch → MCP
(``plan_dispatch`` / ``build_dispatch`` / ``verify_audit``). Records
``route_history`` when DB is reachable.

P0 wiring per ``docs/SPINE_MASTER.md`` §4: Hub approval must not call LLM
inline; it routes through the orchestrator chokepoint.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from shared.runtime.mcp_invoke import invoke_mcp_tool

logger = logging.getLogger("spine.api.role_dispatch_bridge")

_SUBSYSTEM_TOOLS = {
    "plan": "plan_dispatch",
    "build": "build_dispatch",
    "verify": "verify_hub_review",
}


@dataclass(frozen=True)
class RoleDispatchSpec:
    subsystem: str
    role: str
    directive: str


@dataclass
class RoleDispatchResult:
    ok: bool
    subsystem: str
    role: str
    directive_id: str
    tool: str
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    used_fallback: bool = False


# Approval-card kind → orchestrator dispatch (after user acks upstream artifact).
KIND_ROLE_DISPATCH: dict[str, RoleDispatchSpec] = {
    "prd_approval": RoleDispatchSpec("plan", "planner", "PRODUCE_ROADMAP"),
    "roadmap_approval": RoleDispatchSpec("plan", "architect", "PRODUCE_TRD"),
    "trd_approval": RoleDispatchSpec("plan", "conductor", "PRODUCE_SPRINT_PLAN"),
    "sprint_plan_approval": RoleDispatchSpec("build", "engineer", "PRODUCE_CODE"),
    "code_approval": RoleDispatchSpec("verify", "auditor", "CODE_REVIEW"),
    "code_review_pass": RoleDispatchSpec("build", "devops", "INSTALL_AND_SMOKE"),
    "code_review_blocked": RoleDispatchSpec("build", "engineer", "REMEDIATE_FROM_REVIEW"),
    "devops_approval": RoleDispatchSpec("plan", "qa", "PRODUCE_TEST_PLAN"),
    "qa_approval": RoleDispatchSpec("plan", "release_manager", "PRODUCE_RELEASE_GATE"),
    "local_deploy_prompt": RoleDispatchSpec("build", "devops_release", "DEPLOY_LOCAL"),
    # Phase-watcher tail rules (verify_approved → acceptance → released → operate).
    "auditor_approval": RoleDispatchSpec("build", "auditor", "PRODUCE_COMPLIANCE_AUDIT"),
    "release_approval": RoleDispatchSpec("plan", "release_manager", "PRODUCE_RELEASE_GATE"),
    "operate_kickoff": RoleDispatchSpec("build", "devops", "OPERATE_KICKOFF"),
}


async def _load_pipeline_version(project_id: str) -> str:
    from shared.api.dependencies import get_db_pool_raw  # noqa: PLC0415

    pool = get_db_pool_raw()
    if pool is None:
        return os.environ.get("SPINE_PIPELINE_VERSION", "1")
    where = "id = $1" if project_id.isdigit() else "project_uuid::text = $1"
    arg: Any = int(project_id) if project_id.isdigit() else project_id
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"SELECT COALESCE(pipeline_version, '1') AS pv FROM spine_lifecycle.project WHERE {where}",
            arg,
        )
    return str(row["pv"]) if row else "1"


async def _record_route_history(
    *,
    project_id: str,
    subsystem: str,
    role: str,
    directive_id: str,
    tool: str,
    pipeline_version: str,
) -> None:
    from shared.api.dependencies import get_db_pool_raw  # noqa: PLC0415

    pool = get_db_pool_raw()
    if pool is None:
        return
    where = "id = $1" if project_id.isdigit() else "project_uuid::text = $1"
    arg: Any = int(project_id) if project_id.isdigit() else project_id
    meta = json.dumps({
        "pipeline_version": pipeline_version,
        "tool": tool,
        "hub_bridge": True,
    })
    try:
        async with pool.acquire() as conn:
            pid_row = await conn.fetchrow(
                f"SELECT id, current_phase FROM spine_lifecycle.project WHERE {where}",
                arg,
            )
            if pid_row is None:
                return
            await conn.execute(
                "INSERT INTO spine_lifecycle.route_history "
                "(project_id, phase, subsystem, role, directive_ref, metadata) "
                "VALUES ($1, $2, $3, $4, $5, $6::jsonb)",
                int(pid_row["id"]),
                pid_row["current_phase"],
                subsystem,
                role,
                directive_id,
                meta,
            )
    except Exception as exc:  # noqa: BLE001
        logger.debug("route_history_insert_failed", extra={"error": str(exc)})


def _build_payload(
    *,
    tool: str,
    project_id: str,
    role: str,
    directive: str,
    pipeline_version: str,
    actor: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    base: dict[str, Any] = {
        "project_id": project_id,
        "role": role,
        "directive": directive,
        "pipeline_version": pipeline_version,
        "actor": actor,
    }
    if tool == "plan_dispatch":
        base["phase"] = extra.get("phase", "plan_in_progress") if extra else "plan_in_progress"
    if extra:
        if "extra_context" in extra:
            base["extra_context"] = extra["extra_context"]
        if "phase" in extra:
            base["phase"] = extra["phase"]
    return base


def _dispatch_sync(
    *,
    tool: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    return invoke_mcp_tool(tool, payload)


async def dispatch_role_for_kind(
    *,
    kind: str,
    project_id: str,
    actor: str,
    extra: dict[str, Any] | None = None,
) -> RoleDispatchResult | None:
    """Dispatch the next role for an approval-card kind via MCP."""
    spec = KIND_ROLE_DISPATCH.get(kind)
    if spec is None:
        return None

    tool = _SUBSYSTEM_TOOLS.get(spec.subsystem)
    if not tool:
        return RoleDispatchResult(
            ok=False,
            subsystem=spec.subsystem,
            role=spec.role,
            directive_id=f"dir_{uuid4().hex[:12]}",
            tool="",
            error=f"no MCP tool for subsystem {spec.subsystem}",
        )

    pipeline_version = await _load_pipeline_version(project_id)

    merged_extra = dict(extra or {})
    try:
        from shared.runtime.kg_role_context import retrieve_kg_context_for_dispatch
        from shared.runtime.project_workspace import repo_slug

        phase = str(merged_extra.get("phase") or "plan_in_progress")
        kg_block = await asyncio.to_thread(
            retrieve_kg_context_for_dispatch,
            project_id=project_id,
            repo=repo_slug(project_id),
            role=spec.role,
            phase=phase,
            directive=spec.directive,
        )
        if kg_block:
            prev = str(merged_extra.get("extra_context") or "")
            merged_extra["extra_context"] = f"{prev}\n\n{kg_block}".strip() if prev else kg_block
    except Exception as exc:  # noqa: BLE001
        logger.debug("kg_retrieve_bridge_skipped", extra={"error": str(exc)})

    payload = _build_payload(
        tool=tool,
        project_id=project_id,
        role=spec.role,
        directive=spec.directive,
        pipeline_version=pipeline_version,
        actor=actor,
        extra=merged_extra or None,
    )

    logger.info(
        "role_dispatch_bridge",
        extra={
            "kind": kind,
            "tool": tool,
            "role": spec.role,
            "project_id": project_id,
        },
    )

    from shared.runtime.role_activity import role_log  # noqa: PLC0415

    role_log(
        project_id,
        spec.role,
        f"Hub dispatch → {tool} ({spec.directive})",
    )

    raw = await asyncio.to_thread(_dispatch_sync, tool=tool, payload=payload)
    status = raw.get("status")
    data = raw.get("data") or {}
    err_obj = raw.get("error") or {}
    err_msg = err_obj.get("message") if isinstance(err_obj, dict) else str(err_obj)

    directive_id = str(data.get("directive_id") or f"dir_{uuid4().hex[:12]}")

    if status == "ok":
        role_log(project_id, spec.role, "Role finished successfully")
        await _record_route_history(
            project_id=project_id,
            subsystem=spec.subsystem,
            role=spec.role,
            directive_id=directive_id,
            tool=tool,
            pipeline_version=pipeline_version,
        )
        try:
            from shared.runtime.smart_spine_bridge import record_role_outcome  # noqa: PLC0415

            record_role_outcome(
                project_id=project_id,
                role=spec.role,
                directive=spec.directive,
                artifact_key=str(data.get("artifact_key") or ""),
                artifact_preview=str(data.get("artifact_md") or ""),
                actor=actor,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("smart_spine_hook_skipped", extra={"error": str(exc)})
        return RoleDispatchResult(
            ok=True,
            subsystem=spec.subsystem,
            role=spec.role,
            directive_id=directive_id,
            tool=tool,
            data=data,
        )

    role_log(
        project_id,
        spec.role,
        f"Role failed: {(err_msg or 'dispatch failed')[:240]}",
        level="error",
    )
    return RoleDispatchResult(
        ok=False,
        subsystem=spec.subsystem,
        role=spec.role,
        directive_id=directive_id,
        tool=tool,
        error=err_msg or "dispatch failed",
        data=data,
    )


__all__ = [
    "KIND_ROLE_DISPATCH",
    "RoleDispatchSpec",
    "RoleDispatchResult",
    "dispatch_role_for_kind",
]
