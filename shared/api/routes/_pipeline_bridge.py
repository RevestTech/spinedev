"""Canonical SDLC lifecycle bridge for Hub post-ack hooks.

Routes phase transitions through ``shared.mcp.tools.orchestrator`` (
``approval_grant`` + ``phase_advance`` → ``transition.sh``) instead of
writing ``spine_lifecycle.project.current_phase`` directly.

Phase IDs match ``orchestrator/state/phases.yaml`` and
``plan/artifacts/sdlc-pipeline-default.yaml``.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger("spine.api.pipeline_bridge")

# Canonical phase IDs (orchestrator/state/phases.yaml)
PHASE_INTAKE = "intake"
PHASE_PLAN_IN_PROGRESS = "plan_in_progress"
PHASE_PLAN_APPROVED = "plan_approved"
PHASE_BUILD_IN_PROGRESS = "build_in_progress"
PHASE_BUILD_COMPLETE = "build_complete"
PHASE_VERIFY_IN_PROGRESS = "verify_in_progress"
PHASE_VERIFY_APPROVED = "verify_approved"
PHASE_VERIFY_APPROVED_WARN = "verify_approved_with_warnings"
PHASE_ACCEPTANCE = "acceptance"
PHASE_RELEASED = "released"
PHASE_OPERATE = "operate"
PHASE_RETRO = "retro"

# UI bucket labels (SPA timeline) — not stored in DB.
PHASE_BUCKETS = ("intake", "plan", "build", "verify", "release")

_BUCKET_BY_PHASE: dict[str, str] = {
    PHASE_INTAKE: "intake",
    PHASE_PLAN_IN_PROGRESS: "plan",
    PHASE_PLAN_APPROVED: "plan",
    PHASE_BUILD_IN_PROGRESS: "build",
    PHASE_BUILD_COMPLETE: "build",
    PHASE_VERIFY_IN_PROGRESS: "verify",
    PHASE_VERIFY_APPROVED: "verify",
    PHASE_VERIFY_APPROVED_WARN: "verify",
    PHASE_ACCEPTANCE: "release",
    PHASE_RELEASED: "release",
    PHASE_OPERATE: "release",
    PHASE_RETRO: "release",
    # Legacy shortcut names (migrate in-flight projects)
    "plan": "plan",
    "build": "build",
    "verify": "verify",
    "release": "release",
}


def phase_bucket(phase: str | None) -> str:
    """Map a canonical (or legacy) phase id to a UI bucket."""
    if not phase:
        return "intake"
    return _BUCKET_BY_PHASE.get(phase, "intake")


def default_workspace_root() -> Path:
    """Per-project codegen workspace (#34).

    Resolution order:
    1. ``SPINE_PROJECTS_ROOT`` — explicit override
    2. ``/var/lib/spine/projects`` — Hub container bind-mount (hub-up.sh)
    3. ``<repo>/.spine/work`` — local dev without Docker
    """
    if raw := os.environ.get("SPINE_PROJECTS_ROOT"):
        return Path(raw).expanduser()
    hub_mount = Path("/var/lib/spine/projects")
    if hub_mount.is_dir():
        return hub_mount
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / ".spine" / "work"


def workspace_host_path(project_uuid: str) -> str:
    host = os.environ.get("SPINE_PROJECTS_DIR_HOST", str(default_workspace_root()))
    host = host.rstrip("/")
    if host.startswith("~"):
        host = str(Path(host).expanduser())
    return f"{host}/{project_uuid}"


async def _fallback_advance(project_id: str, target_phase: str) -> bool:
    """Direct SQL advance when transition.sh is unavailable (dev/test)."""
    from shared.api.dependencies import get_db_pool_raw  # noqa: PLC0415

    pool = get_db_pool_raw()
    if pool is None:
        return False
    where_clause = "id = $2" if project_id.isdigit() else "project_uuid::text = $2"
    arg: Any = int(project_id) if project_id.isdigit() else project_id
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    f"UPDATE spine_lifecycle.project SET current_phase = $1, updated_at = now() "
                    f"WHERE {where_clause} RETURNING id",
                    target_phase,
                    arg,
                )
                if row is None:
                    return False
                await conn.execute(
                    "INSERT INTO spine_lifecycle.phase_history "
                    "(project_id, phase, entered_at) VALUES ($1, $2, now())",
                    int(row["id"]),
                    target_phase,
                )
        logger.info(
            "pipeline_fallback_advance",
            extra={"project_id": project_id, "target_phase": target_phase},
        )
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "pipeline_fallback_advance_failed",
            extra={"project_id": project_id, "target_phase": target_phase, "error": str(exc)},
        )
        return False


async def advance_lifecycle_phase(
    project_id: str,
    target_phase: str,
    actor: str,
    *,
    grant_gate: bool = False,
    rationale: str | None = None,
) -> bool:
    """Advance a project via orchestrator ``phase_advance`` (+ ``approval_grant`` if gated).

    Returns True when the transition was accepted or the project is already
    in ``target_phase``. Falls back to direct SQL on orchestrator failure.
    """
    from shared.mcp.tools.orchestrator import (  # noqa: PLC0415
        ApprovalGrantInput,
        PhaseAdvanceInput,
        _phase_requires_gate,
        approval_grant,
        phase_advance,
    )

    needs_gate = grant_gate or _phase_requires_gate(target_phase)
    token: str | None = None

    if needs_gate:
        try:
            grant_resp = await asyncio.to_thread(
                approval_grant,
                ApprovalGrantInput(
                    project_id=project_id,
                    phase=target_phase,
                    approver=actor,
                    notes=rationale,
                ),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "approval_grant_exception",
                extra={"project_id": project_id, "phase": target_phase, "error": str(exc)},
            )
            return await _fallback_advance(project_id, target_phase)

        if grant_resp.status != "ok":
            logger.warning(
                "approval_grant_rejected",
                extra={
                    "project_id": project_id,
                    "phase": target_phase,
                    "error": getattr(grant_resp.error, "message", grant_resp.error),
                },
            )
            return await _fallback_advance(project_id, target_phase)
        token = (grant_resp.data or {}).get("token")

    try:
        adv_resp = await asyncio.to_thread(
            phase_advance,
            PhaseAdvanceInput(
                project_id=project_id,
                target_phase=target_phase,
                actor=actor,
                rationale=rationale,
                approval_token=token,
            ),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "phase_advance_exception",
            extra={"project_id": project_id, "target_phase": target_phase, "error": str(exc)},
        )
        return await _fallback_advance(project_id, target_phase)

    if adv_resp.status == "ok" and (adv_resp.data or {}).get("accepted"):
        return True

    err = getattr(adv_resp.error, "message", None) or adv_resp.error
    if err and "noop" in str(err).lower():
        return True

    logger.warning(
        "phase_advance_rejected",
        extra={"project_id": project_id, "target_phase": target_phase, "error": str(err)},
    )
    return await _fallback_advance(project_id, target_phase)


async def advance_sequence(
    project_id: str,
    phases: list[tuple[str, bool]],
    actor: str,
    *,
    rationale: str | None = None,
) -> bool:
    """Advance through multiple phases in order. Each item is (phase_id, grant_gate)."""
    ok = True
    for phase_id, grant in phases:
        if not await advance_lifecycle_phase(
            project_id, phase_id, actor, grant_gate=grant, rationale=rationale,
        ):
            ok = False
    return ok
