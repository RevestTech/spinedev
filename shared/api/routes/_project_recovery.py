"""Manual pipeline recovery — direct the Hub when the SDLC is idle or broken.

When decision cards are all acked and a role failed, users had no surface to
tell Spine what to run next. This module exposes phase-aware recovery actions
via ``GET/POST /api/v2/projects/{id}/recovery``.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from shared.api.routes._post_ack import (
    _load_project_full,
    _orchestrate_hub_role,
    _persist_metadata_patch,
)
from shared.api.routes._pipeline_bridge import (
    PHASE_PLAN_IN_PROGRESS,
    PHASE_VERIFY_IN_PROGRESS,
    phase_bucket,
)

logger = logging.getLogger("spine.api.project_recovery")

RecoveryAction = Literal[
    "retry_planner",
    "retry_architect",
    "retry_conductor",
    "retry_engineer",
    "retry_engineer_remediate",
    "retry_code_review",
    "retry_devops",
    "retry_qa",
    "reset_fix_loop",
    "resume",
]

_TERMINAL_PHASES = frozenset({"retro", "completed", "terminated"})
# Background dispatches that outlive this window are treated as orphaned (Hub
# restart, worker crash, hung MCP call). Must stay below the SPA stale threshold.
_INFLIGHT_STALE_SECONDS = 5 * 60
MAX_CODE_FIX_ITERATIONS = 3


def code_fix_iteration_count(metadata: dict[str, Any] | None) -> int:
    """Engineer remediate passes completed (``code_review_blocked`` dispatches)."""
    try:
        return max(0, int((metadata or {}).get("code_fix_iteration", 0)))
    except (TypeError, ValueError):
        return 0


def fix_loop_exhausted(project: dict[str, Any]) -> bool:
    """True when security review still blocks after max remediate attempts."""
    md = project.get("metadata") or {}
    if not md.get("code_review_blocked"):
        return False
    return code_fix_iteration_count(md) >= MAX_CODE_FIX_ITERATIONS


async def increment_code_fix_iteration(project_uuid: str) -> int:
    """Bump remediate counter once after engineer ``code_review_blocked`` completes."""
    project = await _load_project_full(project_uuid)
    if project is None:
        return 0
    next_iter = code_fix_iteration_count(project.get("metadata")) + 1
    await _persist_metadata_patch(project_uuid, {"code_fix_iteration": next_iter})
    return next_iter


async def fix_loop_guard(
    project: dict[str, Any],
    *,
    block_on_pending: bool,
) -> dict[str, Any] | None:
    """Return an error payload when a fix-loop dispatch must not start."""
    if fix_loop_exhausted(project):
        n = code_fix_iteration_count(project.get("metadata"))
        return {
            "ok": False,
            "error": "fix_loop_exhausted",
            "message": (
                f"Automated remediation already ran {n} time(s) and security review "
                f"is still blocked (maximum {MAX_CODE_FIX_ITERATIONS} auto attempts). "
                "Use **Run engineer remediation again** on the Pipeline tab to dispatch "
                "another AI fix pass, or **Run security review** after remediation completes."
            ),
            "code_fix_iteration": n,
            "max_code_fix_iterations": MAX_CODE_FIX_ITERATIONS,
        }
    if block_on_pending:
        pending = await count_pending_for_project(
            project["project_uuid"],
            project.get("id"),
        )
        if pending > 0:
            return {
                "ok": False,
                "error": "pending_decisions",
                "message": (
                    f"{pending} approval(s) still require your decision. "
                    "Approve or reject them before starting another remediation run — "
                    "approving a blocked security review already dispatches the engineer."
                ),
                "pending_decisions": pending,
            }
    return None


def _dispatch_in_flight_stale(inflight: Any) -> bool:
    """True when a prior recovery dispatch likely died without clearing metadata."""
    if not isinstance(inflight, dict):
        return True
    started = inflight.get("started_at")
    if not started:
        return True
    try:
        started_dt = datetime.fromisoformat(str(started).replace("Z", "+00:00"))
        if started_dt.tzinfo is None:
            started_dt = started_dt.replace(tzinfo=UTC)
        age = (datetime.now(UTC) - started_dt).total_seconds()
        return age > _INFLIGHT_STALE_SECONDS
    except Exception:  # noqa: BLE001
        return True


async def _reap_stale_dispatch_inflight(
    project: dict[str, Any],
    *,
    emit_pulse: bool = False,
) -> bool:
    """Clear orphaned ``recovery_dispatch_in_flight`` when past the stale window."""
    md = project.get("metadata") or {}
    inflight = md.get("recovery_dispatch_in_flight")
    if not inflight or not _dispatch_in_flight_stale(inflight):
        return False
    project_uuid = project["project_uuid"]
    await _persist_metadata_patch(project_uuid, {"recovery_dispatch_in_flight": None})
    if emit_pulse:
        try:
            from shared.api.routes.decisions import publish_project_pulse  # noqa: PLC0415

            publish_project_pulse(
                project_uuid=project_uuid,
                dispatch_in_flight=False,
                refresh_artifacts=False,
            )
        except Exception:  # noqa: BLE001
            pass
        await publish_recovery_pulse(project_uuid, dispatch_in_flight=None)
    return True


class RecoveryActionSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: RecoveryAction
    label: str
    description: str


class RecoveryDispatchBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: RecoveryAction
    note: str | None = Field(default=None, max_length=4000)


async def count_pending_for_project(
    project_uuid: str,
    project_db_id: str | int | None = None,
) -> int:
    """Pending project-scoped decision cards (uuid and/or numeric id, deduped)."""
    project: dict[str, Any] = {"project_uuid": project_uuid}
    if project_db_id is not None:
        project["id"] = project_db_id
    index = await _build_pending_decision_index()
    return pending_count_for_project(project, index)


def _project_card_keys(project: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    if project.get("project_uuid"):
        keys.add(str(project["project_uuid"]))
    if project.get("id") is not None:
        keys.add(str(project["id"]))
    return keys


async def _build_pending_decision_index() -> dict[str, set[str]]:
    """Map project key → decision_ids for pending project-scoped cards."""
    try:
        from shared.api.routes.decisions import get_store  # noqa: PLC0415
        from shared.api.routes.hub_scope import is_project_decision_card  # noqa: PLC0415
    except Exception:
        return {}

    store = get_store()
    items = await store.alist(status_filter="pending")
    index: dict[str, set[str]] = {}
    for card in items:
        if not is_project_decision_card(card):
            continue
        card_keys: set[str] = set()
        if card.project_id:
            card_keys.add(str(card.project_id))
        md = card.metadata or {}
        if md.get("project_uuid") is not None:
            card_keys.add(str(md["project_uuid"]))
        for key in card_keys:
            index.setdefault(key, set()).add(card.decision_id)
    return index


def pending_count_for_project(
    project: dict[str, Any],
    index: dict[str, set[str]],
) -> int:
    """Distinct pending cards for one project (no double-count when card has uuid + id)."""
    match = _project_card_keys(project)
    if not match:
        return 0
    ids: set[str] = set()
    for key in match:
        ids |= index.get(key, set())
    return len(ids)


async def pending_counts_by_project() -> dict[str, int]:
    """Map project key → pending card count (legacy; prefer ``pending_count_for_project``)."""
    index = await _build_pending_decision_index()
    counts: dict[str, int] = {}
    for key, ids in index.items():
        counts[key] = len(ids)
    return counts


def _stuck_reasons(project: dict[str, Any], pending: int) -> list[str]:
    phase = str(project.get("current_phase") or "")
    md = project.get("metadata") or {}
    reasons: list[str] = []
    if pending == 0 and phase not in _TERMINAL_PHASES and phase != "released":
        reasons.append("no_pending_decisions")
    if md.get("code_review_blocked"):
        if fix_loop_exhausted(project):
            reasons.append("fix_loop_exhausted")
        else:
            reasons.append("code_review_blocked")
    if md.get("last_role_failure"):
        reasons.append("last_role_failed")
    from shared.runtime.project_workspace import count_workspace_files  # noqa: PLC0415

    meta_files = md.get("code_files") or []
    on_disk = count_workspace_files(project["project_uuid"], md)
    if meta_files and on_disk == 0:
        reasons.append("workspace_empty_stale_metadata")
    elif not meta_files and on_disk == 0 and phase.startswith("build"):
        reasons.append("workspace_empty_no_code")
    return reasons


def _is_stuck(project: dict[str, Any], pending: int) -> bool:
    phase = str(project.get("current_phase") or "")
    if phase in _TERMINAL_PHASES or phase == "released":
        return False
    reasons = _stuck_reasons(project, pending)
    return bool(reasons) and pending == 0


async def recovery_summary(*, limit: int = 200) -> dict[str, Any]:
    """Batch stuck scan for the projects dashboard (one round-trip)."""
    from shared.api.dependencies import get_db_pool_raw  # noqa: PLC0415

    pool = get_db_pool_raw()
    if pool is None:
        return {"items": [], "stuck_count": 0, "by_project_id": {}}

    pending_index = await _build_pending_decision_index()
    items: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, project_uuid::text AS project_uuid, name, current_phase,
                   COALESCE(metadata, '{}'::jsonb) AS metadata
            FROM spine_lifecycle.project
            WHERE status = 'active'
              AND current_phase NOT IN ('retro', 'released', 'terminated')
            ORDER BY updated_at DESC
            LIMIT $1
            """,
            limit,
        )

    import json as _json

    for row in rows:
        md = row["metadata"]
        if isinstance(md, str):
            try:
                md = _json.loads(md or "{}")
            except Exception:  # noqa: BLE001
                md = {}
        project = {
            "id": int(row["id"]),
            "project_uuid": row["project_uuid"],
            "name": row["name"],
            "current_phase": row["current_phase"],
            "metadata": dict(md or {}),
        }
        pid = str(row["id"])
        uuid = row["project_uuid"]
        pend = pending_count_for_project(project, pending_index)
        if not _is_stuck(project, pend):
            continue
        entry = {
            "project_id": pid,
            "project_uuid": uuid,
            "name": project["name"],
            "current_phase": project["current_phase"],
            "stuck": True,
            "reasons": _stuck_reasons(project, pend),
            "pending_decisions": pend,
            "recommended_action": _pick_resume_action(project),
            "last_role_failure": project["metadata"].get("last_role_failure"),
        }
        items.append(entry)
        by_id[pid] = entry
        by_id[uuid] = entry

    return {"items": items, "stuck_count": len(items), "by_project_id": by_id}


def _action_specs(project: dict[str, Any]) -> list[RecoveryActionSpec]:
    """Phase + metadata aware catalog of actions the founder can invoke."""
    phase = str(project.get("current_phase") or "")
    md = project.get("metadata") or {}
    specs: list[RecoveryActionSpec] = []

    if phase.startswith("plan") or phase == "intake":
        if md.get("prd_md"):
            specs.append(RecoveryActionSpec(
                action="retry_planner",
                label="Regenerate roadmap",
                description="Regenerate the delivery roadmap from the approved product requirements.",
            ))
        if md.get("roadmap_md"):
            specs.append(RecoveryActionSpec(
                action="retry_architect",
                label="Regenerate technical design",
                description="Regenerate the technical requirements document from the approved roadmap.",
            ))
        if md.get("trd_md"):
            specs.append(RecoveryActionSpec(
                action="retry_conductor",
                label="Regenerate sprint plan",
                description="Regenerate the sprint plan from the approved technical design.",
            ))

    if phase.startswith("build") or phase.startswith("verify") or phase == "acceptance":
        if md.get("sprint_plan_md"):
            specs.append(RecoveryActionSpec(
                action="retry_engineer",
                label="Regenerate application code",
                description="Generate application code from the approved sprint plan (fresh pass).",
            ))
        if md.get("code_intro_md") or md.get("code_files"):
            specs.append(RecoveryActionSpec(
                action="retry_code_review",
                label="Run security review",
                description="Run the security engineer review against the current workspace.",
            ))
        if (md.get("code_review_blocked") or md.get("code_review_md")) and (
            md.get("code_intro_md") or md.get("code_files")
        ):
            n = code_fix_iteration_count(md)
            exhausted = fix_loop_exhausted(project)
            iter_note = (
                f" (attempt {n + 1} of {MAX_CODE_FIX_ITERATIONS})"
                if md.get("code_review_blocked") and not exhausted
                else ""
            )
            label = (
                "Fix security findings (auto re-review)"
                if exhausted
                else "Apply security remediation"
            )
            desc = (
                "Run targeted engineer remediation from the latest security findings, "
                "then automatically re-run security review — no full regen."
                if exhausted
                else (
                    "Send the engineer role the latest security findings"
                    f"{iter_note}. Security review re-runs automatically after remediation."
                )
            )
            specs.append(RecoveryActionSpec(
                action="retry_engineer_remediate",
                label=label,
                description=desc,
            ))
        if fix_loop_exhausted(project) or (
            md.get("code_review_blocked") and code_fix_iteration_count(md) > 0
        ):
            specs.append(RecoveryActionSpec(
                action="reset_fix_loop",
                label="Reset fix loop",
                description=(
                    "Clear the remediation attempt counter and security block flag so "
                    "automated fix passes can run again from zero."
                ),
            ))
        if md.get("code_review_md") and not md.get("code_review_blocked"):
            specs.append(RecoveryActionSpec(
                action="retry_devops",
                label="Run environment setup",
                description="Install dependencies and run smoke validation in the project workspace.",
            ))

    if phase.startswith("verify") or phase == "acceptance" or phase == "released":
        if md.get("devops_install_ok") is not False:
            specs.append(RecoveryActionSpec(
                action="retry_qa",
                label="Generate test plan",
                description="Regenerate the test plan after environment setup completes.",
            ))

    if specs:
        specs.append(RecoveryActionSpec(
            action="resume",
            label="Resume pipeline",
            description="Select and run the most appropriate next step for the current phase.",
        ))

    seen: set[str] = set()
    out: list[RecoveryActionSpec] = []
    for spec in specs:
        if spec.action in seen:
            continue
        seen.add(spec.action)
        out.append(spec)
    return out


def _pick_resume_action(project: dict[str, Any]) -> RecoveryAction | None:
    md = project.get("metadata") or {}
    phase = str(project.get("current_phase") or "")
    from shared.runtime.project_workspace import count_workspace_files  # noqa: PLC0415

    on_disk = count_workspace_files(project["project_uuid"], md)
    meta_files = md.get("code_files") or []
    if on_disk == 0 and (meta_files or phase.startswith("build")):
        if md.get("code_review_blocked") and md.get("code_review_md"):
            if fix_loop_exhausted(project):
                if md.get("code_intro_md") or md.get("code_files"):
                    return "retry_engineer_remediate"
                return None
            return "retry_engineer_remediate"
        if md.get("sprint_plan_md"):
            return "retry_engineer"

    if md.get("code_review_blocked"):
        if fix_loop_exhausted(project):
            if md.get("code_intro_md") or md.get("code_files"):
                return "retry_engineer_remediate"
            return None
        return "retry_engineer_remediate"
    if phase.startswith("build"):
        if md.get("code_intro_md") and not md.get("code_review_md"):
            return "retry_code_review"
        if md.get("code_review_md") and not md.get("devops_install_ok"):
            return "retry_devops"
        if md.get("sprint_plan_md") and not md.get("code_intro_md"):
            return "retry_engineer"
    if phase.startswith("verify"):
        if not md.get("qa_md"):
            return "retry_qa"
    if phase.startswith("plan") or phase == "intake":
        if md.get("trd_md") and not md.get("sprint_plan_md"):
            return "retry_conductor"
        if md.get("roadmap_md") and not md.get("trd_md"):
            return "retry_architect"
        if md.get("prd_md") and not md.get("roadmap_md"):
            return "retry_planner"
    specs = _action_specs(project)
    if not specs:
        return None
    for preferred in (
        "retry_engineer_remediate",
        "retry_engineer",
        "retry_code_review",
        "retry_devops",
        "retry_qa",
        "retry_conductor",
        "retry_architect",
        "retry_planner",
    ):
        if any(s.action == preferred for s in specs):
            return preferred  # type: ignore[return-value]
    return specs[0].action


def _dispatch_params(
    action: RecoveryAction,
    project: dict[str, Any],
    note: str | None,
) -> dict[str, Any]:
    """Map a recovery action to ``_orchestrate_hub_role`` kwargs."""
    md = project.get("metadata") or {}
    extra: dict[str, Any] | None = None

    if action == "retry_planner":
        return {
            "kind": "prd_approval",
            "approval_card_kind": "roadmap_approval",
            "next_phase": phase_bucket(PHASE_PLAN_IN_PROGRESS),
        }
    if action == "retry_architect":
        return {
            "kind": "roadmap_approval",
            "approval_card_kind": "trd_approval",
            "next_phase": phase_bucket(PHASE_PLAN_IN_PROGRESS),
        }
    if action == "retry_conductor":
        return {
            "kind": "trd_approval",
            "approval_card_kind": "sprint_plan_approval",
            "next_phase": phase_bucket(PHASE_PLAN_IN_PROGRESS),
        }
    if action == "retry_engineer":
        return {
            "kind": "sprint_plan_approval",
            "approval_card_kind": "code_approval",
        }
    if action == "retry_engineer_remediate":
        review_md = md.get("code_review_md") or ""
        feedback = "## Code review findings (manual recovery)\n\n" + review_md
        if note:
            feedback += f"\n\n## Founder note\n\n{note.strip()}"
        return {
            "kind": "code_review_blocked",
            "approval_card_kind": "code_approval",
            "next_phase": phase_bucket(PHASE_VERIFY_IN_PROGRESS),
            "extra": {"extra_context": feedback[:12000]},
        }
    if action == "retry_code_review":
        return {
            "kind": "code_approval",
            "approval_card_kind": None,
            "next_phase": phase_bucket(PHASE_VERIFY_IN_PROGRESS),
            "expected_role": "verify",
        }
    if action == "retry_devops":
        return {
            "kind": "code_review_pass",
            "approval_card_kind": "devops_approval",
            "next_phase": PHASE_VERIFY_IN_PROGRESS,
        }
    if action == "retry_qa":
        return {
            "kind": "devops_approval",
            "approval_card_kind": "qa_approval",
            "next_phase": phase_bucket(PHASE_VERIFY_IN_PROGRESS),
        }
    raise ValueError(f"unknown recovery action: {action}")


def _workspace_files_on_disk(project: dict[str, Any]) -> int:
    from shared.runtime.project_workspace import count_workspace_files  # noqa: PLC0415

    return count_workspace_files(project["project_uuid"], project.get("metadata") or {})


async def clear_orphaned_recovery_dispatches_on_startup() -> int:
    """Hub restart kills in-flight asyncio tasks — drop stale metadata flags."""
    from shared.api.dependencies import get_db_pool_raw

    pool = get_db_pool_raw()
    if pool is None:
        return 0
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT project_uuid::text AS project_uuid "
            "FROM spine_lifecycle.project "
            "WHERE metadata ? 'recovery_dispatch_in_flight' "
            "AND status NOT IN ('terminated', 'completed')",
        )
        tag = await conn.execute(
            "UPDATE spine_lifecycle.project "
            "SET metadata = metadata - 'recovery_dispatch_in_flight', "
            "updated_at = now() "
            "WHERE metadata ? 'recovery_dispatch_in_flight' "
            "AND status NOT IN ('terminated', 'completed')",
        )
    for row in rows:
        try:
            from shared.api.routes.decisions import publish_project_pulse  # noqa: PLC0415

            publish_project_pulse(
                project_uuid=row["project_uuid"],
                dispatch_in_flight=False,
                refresh_artifacts=False,
            )
            await publish_recovery_pulse(row["project_uuid"], dispatch_in_flight=None)
        except Exception:  # noqa: BLE001
            pass
    try:
        return int(str(tag).split()[-1])
    except (ValueError, IndexError):
        return 0


async def recovery_status(project_id: str) -> dict[str, Any]:
    project = await _load_project_full(project_id)
    if project is None:
        return {"ok": False, "error": "project_not_found"}

    pending_index = await _build_pending_decision_index()
    pending = pending_count_for_project(project, pending_index)
    phase = str(project.get("current_phase") or "")
    md = project.get("metadata") or {}
    if await _reap_stale_dispatch_inflight(project, emit_pulse=True):
        inflight = None
    else:
        inflight = md.get("recovery_dispatch_in_flight")
    actions = _action_specs(project)
    reasons = _stuck_reasons(project, pending)
    stuck = _is_stuck(project, pending)

    return {
        "ok": True,
        "project_uuid": project["project_uuid"],
        "current_phase": phase,
        "pending_decisions": pending,
        "stuck": stuck,
        "reasons": reasons,
        "last_role_failure": md.get("last_role_failure"),
        "dispatch_in_flight": inflight,
        "workspace_files_on_disk": _workspace_files_on_disk(project),
        "actions": [a.model_dump() for a in actions],
        "recommended_action": _pick_resume_action(project),
        "code_fix_iteration": code_fix_iteration_count(md),
        "max_code_fix_iterations": MAX_CODE_FIX_ITERATIONS,
        "fix_loop_exhausted": fix_loop_exhausted(project),
        "code_review_blocked": bool(md.get("code_review_blocked")),
        "code_files_count": (
            md.get("code_files_count")
            if isinstance(md.get("code_files_count"), int)
            else len(md.get("code_files") or [])
            if isinstance(md.get("code_files"), list)
            else 0
        ),
    }


_RECOVERY_PULSE_KEYS = (
    "stuck",
    "reasons",
    "pending_decisions",
    "recommended_action",
    "last_role_failure",
    "dispatch_in_flight",
    "actions",
    "code_fix_iteration",
    "max_code_fix_iterations",
    "fix_loop_exhausted",
    "current_phase",
    "workspace_files_on_disk",
    "code_review_blocked",
    "code_files_count",
)


async def publish_recovery_pulse(project_id: str, **extra: Any) -> None:
    """Push recovery snapshot over the decisions SSE stream (SPA-first updates)."""
    try:
        status = await recovery_status(project_id)
        if not status.get("ok"):
            return
        from shared.api.routes.decisions import publish_event  # noqa: PLC0415

        publish_event({
            "type": "recovery_pulse",
            "project_uuid": project_id,
            "ts": time.time(),
            **{k: status[k] for k in _RECOVERY_PULSE_KEYS if k in status},
            **extra,
        })
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "recovery_pulse_publish_failed",
            extra={"project_id": project_id, "error": str(exc)},
        )


def schedule_recovery_pulse(project_id: str, **extra: Any) -> None:
    """Fire-and-forget recovery pulse for sync callers (post-ack emit path)."""
    try:
        asyncio.get_running_loop().create_task(
            publish_recovery_pulse(project_id, **extra),
        )
    except RuntimeError:
        pass


async def _run_recovery_orchestration(
    *,
    project: dict[str, Any],
    params: dict[str, Any],
    expected_role: str | None,
    actor: str,
) -> None:
    """Background worker — engineer/verify roles can run many minutes."""
    project_uuid = project["project_uuid"]
    dispatch_params = dict(params)
    try:
        if dispatch_params.get("kind") == "code_review_blocked":
            md = project.get("metadata") or {}
            if not str(md.get("code_review_md") or "").strip():
                scanned = await _orchestrate_hub_role(
                    kind="code_approval",
                    project=project,
                    actor=actor,
                )
                if scanned:
                    project = (await _load_project_full(project_uuid)) or project
                    md = project.get("metadata") or {}
                    if not md.get("code_review_blocked"):
                        return
                    review_md = md.get("code_review_md") or ""
                    extra = dict(dispatch_params.get("extra") or {})
                    extra["extra_context"] = (
                        "## Code review findings (recovery scan)\n\n"
                        + str(review_md)[:12000]
                    )
                    dispatch_params["extra"] = extra

        handled = await _orchestrate_hub_role(
            kind=dispatch_params["kind"],
            project=project,
            actor=actor,
            approval_card_kind=dispatch_params.get("approval_card_kind"),
            next_phase=dispatch_params.get("next_phase"),
            extra=dispatch_params.get("extra"),
        )
        if not handled:
            from shared.api.routes._post_ack import _enqueue_orchestrator_gap  # noqa: PLC0415

            await _enqueue_orchestrator_gap(
                kind=dispatch_params["kind"],
                project=project,
                expected_role=expected_role,
            )
    finally:
        await _persist_metadata_patch(project_uuid, {"recovery_dispatch_in_flight": None})
        try:
            from shared.api.routes.decisions import publish_project_pulse  # noqa: PLC0415

            publish_project_pulse(
                project_uuid=project_uuid,
                dispatch_in_flight=False,
                refresh_artifacts=False,
            )
        except Exception:  # noqa: BLE001
            pass
        await publish_recovery_pulse(project_uuid)


async def recovery_cancel_inflight(project_id: str, *, actor: str) -> dict[str, Any]:
    """Clear a stuck recovery dispatch flag (Hub restart / orphaned asyncio task)."""
    project = await _load_project_full(project_id)
    if project is None:
        return {"ok": False, "error": "project_not_found"}
    md = project.get("metadata") or {}
    inflight = md.get("recovery_dispatch_in_flight")
    if not inflight:
        await publish_recovery_pulse(project["project_uuid"])
        return {"ok": True, "cleared": False, "message": "No dispatch was marked in flight."}
    await _persist_metadata_patch(project["project_uuid"], {"recovery_dispatch_in_flight": None})
    from shared.api.routes.decisions import publish_project_pulse  # noqa: PLC0415
    from shared.runtime.role_activity import role_log  # noqa: PLC0415

    publish_project_pulse(
        project_uuid=project["project_uuid"],
        dispatch_in_flight=False,
        refresh_artifacts=False,
    )
    role_log(
        project["project_uuid"],
        str(inflight.get("dispatch_kind") or "recovery"),
        f"Recovery dispatch cleared by {actor} (was `{inflight.get('action', 'unknown')}`)",
    )
    await publish_recovery_pulse(project["project_uuid"], dispatch_in_flight=None)
    return {"ok": True, "cleared": True}


async def recovery_dispatch(
    project_id: str,
    action: RecoveryAction,
    *,
    actor: str,
    note: str | None = None,
    auto_loop: bool = False,
) -> dict[str, Any]:
    project = await _load_project_full(project_id)
    if project is None:
        return {"ok": False, "error": "project_not_found"}

    resolved = action
    if action == "resume":
        picked = _pick_resume_action(project)
        if picked is None:
            return {"ok": False, "error": "no_resume_action", "message": "Nothing to resume for this phase."}
        resolved = picked

    md = project.get("metadata") or {}
    if await _reap_stale_dispatch_inflight(project, emit_pulse=True):
        md = {**md, "recovery_dispatch_in_flight": None}
        project = {**project, "metadata": md}
    inflight = md.get("recovery_dispatch_in_flight")
    if inflight and not _dispatch_in_flight_stale(inflight):
        return {
            "ok": False,
            "error": "dispatch_in_flight",
            "message": (
                f"A recovery dispatch is already running "
                f"({inflight.get('dispatch_kind', 'role')}). "
                "Watch Live activity or refresh in a few minutes."
            ),
            "dispatch_in_flight": inflight,
        }

    if resolved == "reset_fix_loop":
        if not fix_loop_exhausted(project) and not (
            md.get("code_review_blocked") and code_fix_iteration_count(md) > 0
        ):
            return {
                "ok": False,
                "error": "action_not_allowed",
                "message": "Fix loop reset is only available when remediation is blocked or exhausted.",
            }
        project_uuid = project["project_uuid"]
        await _persist_metadata_patch(project_uuid, {
            "code_review_blocked": False,
            "code_fix_iteration": 0,
        })
        from shared.runtime.role_activity import role_log  # noqa: PLC0415

        role_log(
            project_uuid,
            "recovery",
            f"Fix loop reset by {actor} (counter cleared, security block lifted)",
        )
        await publish_recovery_pulse(project_uuid)
        return {
            "ok": True,
            "action": "reset_fix_loop",
            "message": "Fix loop counter reset — automated remediation can run again.",
        }

    if resolved == "retry_engineer_remediate":
        if auto_loop:
            if fix_loop_exhausted(project):
                guard = await fix_loop_guard(project, block_on_pending=False)
                if guard is not None:
                    return guard
        else:
            # Manual remediate: never blocked by fix_loop_exhausted; only pending cards.
            guard = await fix_loop_guard(project, block_on_pending=True)
            if guard is not None and guard.get("error") == "pending_decisions":
                return guard

    allowed = {s.action for s in _action_specs(project)}
    if resolved not in allowed:
        return {
            "ok": False,
            "error": "action_not_allowed",
            "message": f"Action `{resolved}` is not valid for phase `{project.get('current_phase')}`.",
            "allowed": sorted(allowed),
        }

    params = _dispatch_params(resolved, project, note)
    expected_role = params.pop("expected_role", None)
    project_uuid = project["project_uuid"]

    logger.info(
        "recovery_dispatch",
        extra={
            "project_uuid": project_uuid,
            "action": resolved,
            "dispatch_kind": params["kind"],
            "actor": actor,
        },
    )

    await _persist_metadata_patch(project_uuid, {
        "recovery_dispatch_in_flight": {
            "action": resolved,
            "dispatch_kind": params["kind"],
            "actor": actor,
            "started_at": datetime.now(UTC).isoformat(),
        },
    })

    from shared.api.routes.decisions import publish_project_pulse  # noqa: PLC0415

    publish_project_pulse(
        project_uuid=project_uuid,
        current_phase=project.get("current_phase"),
        dispatch_in_flight=True,
        dispatch_kind=params["kind"],
    )
    schedule_recovery_pulse(project_uuid)

    from shared.runtime.role_activity import role_log  # noqa: PLC0415

    role_log(
        project_uuid,
        expected_role or params["kind"],
        f"Recovery action `{resolved}` started ({params['kind']})",
    )

    asyncio.create_task(_run_recovery_orchestration(
        project=project,
        params=params,
        expected_role=expected_role,
        actor=actor,
    ))

    return {
        "ok": True,
        "async": True,
        "action": resolved,
        "dispatch_kind": params["kind"],
        "message": "Role started — watch Live activity below. A decision card appears when it finishes.",
    }


def schedule_auto_engineer_remediate(project_id: str, *, actor: str = "hub") -> None:
    """Auto-dispatch engineer remediate after security review FAIL (under max iterations).

    Skips pending-decision guard so the loop is not blocked by the review card we
    just enqueued — iteration is counted only when remediate completes.
    """
    async def _run() -> None:
        await recovery_dispatch(
            project_id,
            "retry_engineer_remediate",
            actor=actor,
            auto_loop=True,
        )

    try:
        asyncio.get_running_loop().create_task(_run())
    except RuntimeError:
        pass


def retry_action_for_dispatch_kind(kind: str) -> RecoveryAction | None:
    """Map a failed orchestrator ack kind → recovery action for role_failure cards."""
    return {
        "sprint_plan_approval": "retry_engineer",
        "code_approval": "retry_code_review",
        "code_review_blocked": "retry_engineer_remediate",
        "code_review_pass": "retry_devops",
        "devops_approval": "retry_qa",
        "prd_approval": "retry_planner",
        "roadmap_approval": "retry_architect",
        "trd_approval": "retry_conductor",
    }.get(kind)


__all__ = [
    "MAX_CODE_FIX_ITERATIONS",
    "RecoveryAction",
    "RecoveryDispatchBody",
    "code_fix_iteration_count",
    "count_pending_for_project",
    "fix_loop_exhausted",
    "fix_loop_guard",
    "increment_code_fix_iteration",
    "pending_count_for_project",
    "pending_counts_by_project",
    "recovery_dispatch",
    "recovery_cancel_inflight",
    "recovery_status",
    "recovery_summary",
    "retry_action_for_dispatch_kind",
    "clear_orphaned_recovery_dispatches_on_startup",
    "publish_recovery_pulse",
    "schedule_auto_engineer_remediate",
    "schedule_recovery_pulse",
]
