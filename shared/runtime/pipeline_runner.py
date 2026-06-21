"""Hub PipelineRunner — autonomous project SDLC without external walkthrough.

Polls projects with ``metadata.pipeline_mode=autonomous``, runs intake when
needed, and auto-acks decision cards allowed by ``gate_policy``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

from shared.runtime.gate_policy import (
    can_auto_ack,
    resolve_gate_policy,
    resolve_pipeline_mode,
)
from shared.runtime.intake_prompts import next_intake_message

logger = logging.getLogger("spine.runtime.pipeline_runner")

_POLL_SECS = float(os.environ.get("SPINE_PIPELINE_RUNNER_POLL_SECS", "15"))
_ACTOR = "pipeline_runner"

_GLOBAL_DISMISS_KINDS = frozenset(
    k.strip()
    for k in os.environ.get(
        "SPINE_PIPELINE_DISMISS_GLOBAL",
        "master_daily_briefing,host_deploy_instructions",
    ).split(",")
    if k.strip()
)

_STOP_KINDS = frozenset({"orchestrator_gap", "role_failure"})


async def _list_autonomous_projects() -> list[dict[str, Any]]:
    from shared.api.dependencies import get_db_pool_raw  # noqa: PLC0415

    pool = get_db_pool_raw()
    if pool is None:
        return []
    sql = """
    SELECT project_uuid::text AS project_uuid,
           name,
           current_phase,
           project_type::text AS project_type,
           metadata
    FROM spine_lifecycle.project
    WHERE status = 'active'
      AND metadata->>'pipeline_mode' = 'autonomous'
      AND COALESCE(metadata->>'pipeline_paused', 'false') NOT IN ('true', '1')
    ORDER BY updated_at DESC NULLS LAST
    LIMIT 20
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql)
    out: list[dict[str, Any]] = []
    for row in rows:
        md = row["metadata"]
        if isinstance(md, str):
            md = json.loads(md)
        out.append({
            "project_uuid": row["project_uuid"],
            "name": row["name"],
            "current_phase": row["current_phase"],
            "project_type": row["project_type"],
            "metadata": md if isinstance(md, dict) else {},
        })
    return out


async def _persist_pipeline_pause(
    project_uuid: str,
    *,
    reason: str,
    kind: str,
    title: str,
) -> None:
    from shared.api.dependencies import get_db_pool_raw  # noqa: PLC0415

    pool = get_db_pool_raw()
    if pool is None:
        return
    patch = {
        "pipeline_paused": True,
        "pipeline_pause_reason": reason,
        "pipeline_pause_kind": kind,
        "pipeline_pause_title": title[:500],
    }
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE spine_lifecycle.project SET metadata = "
            "COALESCE(metadata, '{}'::jsonb) || $1::jsonb "
            "WHERE project_uuid::text = $2",
            json.dumps(patch),
            project_uuid,
        )


def _card_belongs(card: Any, project_uuid: str) -> bool:
    meta = getattr(card, "metadata", None) or {}
    if meta.get("project_uuid") == project_uuid:
        return True
    pid = getattr(card, "project_id", None)
    return isinstance(pid, str) and pid == project_uuid


async def _dismiss_global_cards(cards: list[Any]) -> int:
    from shared.api.routes.decisions import ack_decision_internal  # noqa: PLC0415

    dismissed = 0
    for card in cards:
        meta = getattr(card, "metadata", None) or {}
        kind = meta.get("kind")
        if kind not in _GLOBAL_DISMISS_KINDS:
            continue
        if getattr(card, "project_id", None) or meta.get("project_uuid"):
            continue
        did = getattr(card, "decision_id", None)
        if not isinstance(did, str) or not did:
            continue
        await ack_decision_internal(did, actor=_ACTOR)
        dismissed += 1
    return dismissed


async def _run_intake_tick(project: dict[str, Any]) -> bool:
    """One intake chat turn when intake is not done. Returns True if work ran."""
    md = project.get("metadata") or {}
    if md.get("intake_done"):
        return False

    from shared.api.routes.intake import (  # noqa: PLC0415
        TranscriptTurn,
        execute_intake_turn,
    )

    transcript_raw = md.get("intake_transcript") or []
    transcript: list[TranscriptTurn] = []
    for turn in transcript_raw:
        if isinstance(turn, dict) and turn.get("role") and turn.get("content"):
            transcript.append(
                TranscriptTurn(role=turn["role"], content=str(turn["content"])),
            )

    turn_index = len([t for t in transcript if t.role == "user"]) + 1
    message = next_intake_message(md, turn_index=turn_index)
    greenfield = bool(md.get("greenfield"))
    try:
        await execute_intake_turn(
            project_id=project["project_uuid"],
            message=message,
            transcript=transcript,
            project_name=project["name"],
            project_type=str(project.get("project_type") or "feature"),
            greenfield=greenfield,
            actor=_ACTOR,
        )
        logger.info(
            "pipeline_runner_intake_turn",
            extra={
                "project_uuid": project["project_uuid"],
                "turn": turn_index,
            },
        )
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "pipeline_runner_intake_failed",
            extra={"project_uuid": project["project_uuid"], "error": str(exc)},
        )
        await _persist_pipeline_pause(
            project["project_uuid"],
            reason=f"intake_failed: {type(exc).__name__}",
            kind="intake",
            title="Intake LLM turn failed",
        )
        return True


async def _maybe_auto_unstick_recovery(
    project: dict[str, Any],
    pending_cards: list[Any],
) -> bool:
    """Break operate-phase security deadlocks without founder intervention."""
    if str(project.get("current_phase") or "") != "operate":
        return False
    md = project.get("metadata") or {}
    if not md.get("code_review_blocked"):
        return False
    if md.get("recovery_dispatch_in_flight"):
        return False
    project_uuid = project["project_uuid"]
    if any(_card_belongs(card, project_uuid) for card in pending_cards):
        return False

    from shared.api.routes._project_recovery import (  # noqa: PLC0415
        code_fix_iteration_count,
        fix_loop_exhausted,
        recovery_dispatch,
    )

    if not fix_loop_exhausted(project) and code_fix_iteration_count(md) == 0:
        return False

    if fix_loop_exhausted(project) or code_fix_iteration_count(md) > 0:
        reset = await recovery_dispatch(
            project_uuid,
            "reset_fix_loop",
            actor=_ACTOR,
            auto_loop=True,
        )
        if not reset.get("ok") and reset.get("error") != "dispatch_in_flight":
            logger.warning(
                "pipeline_runner_unstick_reset_failed",
                extra={"project_uuid": project_uuid, "error": reset.get("error")},
            )

    review = await recovery_dispatch(
        project_uuid,
        "retry_code_review",
        actor=_ACTOR,
        auto_loop=True,
    )
    if review.get("ok"):
        logger.info(
            "pipeline_runner_unstick_code_review",
            extra={"project_uuid": project_uuid},
        )
    return bool(review.get("ok"))


async def _maybe_dispatch_feature_request(
    project: dict[str, Any],
    pending_cards: list[Any],
) -> bool:
    """Auto-start operate-phase engineer work when a feature is queued."""
    if str(project.get("current_phase") or "") != "operate":
        return False
    from shared.api.routes._project_recovery import (  # noqa: PLC0415
        _pending_feature_request,
        recovery_dispatch,
    )

    md = project.get("metadata") or {}
    if not _pending_feature_request(md):
        return False
    if md.get("code_review_blocked"):
        return False
    if md.get("recovery_dispatch_in_flight"):
        return False
    project_uuid = project["project_uuid"]
    if any(_card_belongs(card, project_uuid) for card in pending_cards):
        return False

    result = await recovery_dispatch(
        project_uuid,
        "retry_feature",
        actor=_ACTOR,
        auto_loop=True,
    )
    if result.get("ok"):
        logger.info(
            "pipeline_runner_feature_dispatch",
            extra={"project_uuid": project_uuid},
        )
    return bool(result.get("ok"))


async def _process_project(project: dict[str, Any], pending_cards: list[Any]) -> int:
    """Returns count of cards auto-acked this tick."""
    project_uuid = project["project_uuid"]
    md = project.get("metadata") or {}
    mode = resolve_pipeline_mode(md)
    policy = resolve_gate_policy(md)

    if await _run_intake_tick(project):
        return 0

    if await _maybe_auto_unstick_recovery(project, pending_cards):
        return 0

    if await _maybe_dispatch_feature_request(project, pending_cards):
        return 0

    acked = 0
    for card in pending_cards:
        if not _card_belongs(card, project_uuid):
            continue
        meta = getattr(card, "metadata", None) or {}
        kind = str(meta.get("kind") or "")
        title = str(getattr(card, "title", "") or kind)
        decision_id = getattr(card, "decision_id", None)

        if kind in _STOP_KINDS:
            if kind == "role_failure" and md.get("operate_started_at"):
                if isinstance(decision_id, str) and decision_id:
                    from shared.api.routes.decisions import ack_decision_internal  # noqa: PLC0415

                    await ack_decision_internal(decision_id, actor=_ACTOR)
                    acked += 1
                continue
            await _persist_pipeline_pause(
                project_uuid,
                reason=kind,
                kind=kind,
                title=title,
            )
            logger.warning(
                "pipeline_runner_paused",
                extra={
                    "project_uuid": project_uuid,
                    "kind": kind,
                    "title": title[:120],
                },
            )
            return acked

        if not can_auto_ack(kind, mode=mode, policy=policy):
            continue
        if not isinstance(decision_id, str) or not decision_id:
            continue

        from shared.api.routes.decisions import ack_decision_internal  # noqa: PLC0415

        await ack_decision_internal(decision_id, actor=_ACTOR)
        acked += 1
        logger.info(
            "pipeline_runner_auto_ack",
            extra={
                "project_uuid": project_uuid,
                "kind": kind,
                "decision_id": decision_id[:8],
                "policy": policy.preset,
            },
        )
    return acked


async def pipeline_runner_tick() -> int:
    """One poll cycle. Returns total auto-acks."""
    from shared.api.routes.decisions import get_store  # noqa: PLC0415

    projects = await _list_autonomous_projects()
    if not projects:
        return 0

    store = get_store()
    pending = await store.alist(status_filter="pending")
    await _dismiss_global_cards(pending)

    total = 0
    for project in projects:
        total += await _process_project(project, pending)
    return total


async def run_pipeline_runner(stop: asyncio.Event) -> None:
    """Background loop until ``stop`` is set."""
    logger.info("pipeline_runner_started", extra={"poll_secs": _POLL_SECS})
    while not stop.is_set():
        try:
            count = await pipeline_runner_tick()
            if count:
                logger.info("pipeline_runner_tick", extra={"auto_acked": count})
        except Exception as exc:  # noqa: BLE001
            logger.warning("pipeline_runner_tick_failed", extra={"error": str(exc)})
        try:
            await asyncio.wait_for(stop.wait(), timeout=_POLL_SECS)
        except asyncio.TimeoutError:
            continue
    logger.info("pipeline_runner_stopped")


def pipeline_runner_enabled() -> bool:
    raw = os.environ.get("SPINE_PIPELINE_RUNNER", "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


__all__ = [
    "pipeline_runner_enabled",
    "pipeline_runner_tick",
    "run_pipeline_runner",
]
