"""Phase watcher — dispatch roles when gates clear without Hub ack.

Polls for active projects that have evidence work is due (metadata +
phase) but no recent ``route_history`` dispatch, then routes through
``_orchestrate_hub_role``.

Enabled when ``SPINE_PHASE_WATCHER=1`` (default on when DB pool is up).
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

logger = logging.getLogger("spine.runtime.phase_watcher")

_POLL_SECS = float(os.environ.get("SPINE_PHASE_WATCHER_POLL_SECS", "30"))

# (current_phase, metadata predicate SQL fragment, dispatch kind)
_WATCH_RULES: list[tuple[str, str, str]] = [
    (
        "plan_in_progress",
        "metadata ? 'prd_md' AND NOT (metadata ? 'roadmap_md')",
        "prd_approval",
    ),
    (
        "plan_in_progress",
        "metadata ? 'roadmap_md' AND NOT (metadata ? 'trd_md')",
        "roadmap_approval",
    ),
    (
        "plan_in_progress",
        "metadata ? 'trd_md' AND NOT (metadata ? 'sprint_plan_md')",
        "trd_approval",
    ),
    (
        "build_in_progress",
        "metadata ? 'sprint_plan_md' AND NOT (metadata ? 'code_intro_md')",
        "sprint_plan_approval",
    ),
    (
        "build_in_progress",
        "metadata ? 'code_intro_md' AND NOT (metadata ? 'code_review_md')",
        "code_approval",
    ),
    (
        "verify_in_progress",
        "metadata ? 'devops_install_ok' AND NOT (metadata ? 'qa_md')",
        "devops_approval",
    ),
    # D2 slate #4 — verify_approved → acceptance → released → operate.
    # Without these the loop dead-ends at QA. Each rule fires when the
    # phase's required artifact is in metadata and the next-phase's
    # marker is not. router.sh maps the dispatch_kind to the appropriate
    # role runtime; the actual phase transition is the orchestrator's
    # call (gate_check etc. live in orchestrator/lib).
    (
        "verify_approved",
        "metadata ? 'qa_md' AND NOT (metadata ? 'audit_md')",
        "auditor_approval",
    ),
    (
        "acceptance",
        "metadata ? 'audit_md' AND NOT (metadata ? 'release_gate_md')",
        "release_approval",
    ),
    (
        "released",
        (
            "metadata ? 'deploy_result' "
            "AND NOT (metadata ? 'operate_started_at')"
        ),
        "operate_kickoff",
    ),
]


async def _find_pending_work() -> list[dict[str, Any]]:
    from shared.api.dependencies import get_db_pool_raw  # noqa: PLC0415

    pool = get_db_pool_raw()
    if pool is None:
        return []
    found: list[dict[str, Any]] = []
    async with pool.acquire() as conn:
        for phase, meta_pred, kind in _WATCH_RULES:
            sql = f"""
            SELECT p.project_uuid::text AS project_uuid,
                   p.name,
                   p.current_phase,
                   $2::text AS dispatch_kind
            FROM spine_lifecycle.project p
            WHERE p.status = 'active'
              AND p.current_phase = $1
              AND ({meta_pred})
              AND NOT EXISTS (
                SELECT 1 FROM spine_lifecycle.route_history r
                 WHERE r.project_id = p.id
                   AND r.dispatched_at > now() - interval '15 minutes'
              )
            LIMIT 3
            """
            rows = await conn.fetch(sql, phase, kind)
            found.extend(dict(r) for r in rows)
    return found


async def phase_watcher_tick() -> int:
    """One poll cycle. Returns count of dispatches attempted."""
    from shared.api.routes._post_ack import (  # noqa: PLC0415
        _load_project_full,
        _require_orchestrate_hub_role,
    )
    from shared.api.routes._project_recovery import (  # noqa: PLC0415
        _build_pending_decision_index,
        pending_count_for_project,
    )

    rows = await _find_pending_work()
    if not rows:
        return 0
    pending_index = await _build_pending_decision_index()
    dispatched = 0
    for row in rows:
        kind = row["dispatch_kind"]
        project_uuid = row["project_uuid"]
        project = await _load_project_full(project_uuid)
        if project is None:
            continue
        if pending_count_for_project(project, pending_index) > 0:
            continue
        logger.info(
            "phase_watcher_dispatch",
            extra={
                "project_uuid": project_uuid,
                "phase": row["current_phase"],
                "kind": kind,
            },
        )
        if await _require_orchestrate_hub_role(
            kind=kind,
            project=project,
            actor="phase_watcher",
        ):
            dispatched += 1
    return dispatched


async def run_phase_watcher(stop: asyncio.Event) -> None:
    """Background loop until ``stop`` is set."""
    logger.info("phase_watcher_started", extra={"poll_secs": _POLL_SECS})
    while not stop.is_set():
        try:
            count = await phase_watcher_tick()
            if count:
                logger.info("phase_watcher_tick", extra={"dispatched": count})
        except Exception as exc:  # noqa: BLE001
            logger.warning("phase_watcher_tick_failed", extra={"error": str(exc)})
        try:
            await asyncio.wait_for(stop.wait(), timeout=_POLL_SECS)
        except asyncio.TimeoutError:
            continue
    logger.info("phase_watcher_stopped")


def watcher_enabled() -> bool:
    raw = os.environ.get("SPINE_PHASE_WATCHER", "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


__all__ = ["phase_watcher_tick", "run_phase_watcher", "watcher_enabled"]
