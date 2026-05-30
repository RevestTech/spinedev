"""Hub-facing plan-phase role execution (planner, architect, conductor, qa, release).

Called from ``plan_dispatch`` MCP when the orchestrator routes a directive
through ``router.sh``. Replaces inline LLM dispatch in ``_post_ack.py``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from shared.llm import LLMRequest, Message, call_async

logger = logging.getLogger("spine.plan.hub_role_runner")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CHARTERS_DIR = _REPO_ROOT / "shared" / "charters"
_DEFAULT_MODEL = os.environ.get("SPINE_INTAKE_MODEL", "claude-sonnet-4-6")

_PLANNER_PROMPT = """
You are the Spine **planner** role (PMBOK 7-anchored). The PRD has
just been approved. Produce a project roadmap in markdown.

ROADMAP structure (start with `# Roadmap — <Project Name>`):
  1. **Sprint breakdown** — split the PRD into 1-3 sprints with names
     + clear sprint goals. PMBOK iteration-planning discipline.
  2. **Critical path** — ordered list of milestone artifacts and their
     dependencies. Identify the MVP cut.
  3. **RACI snapshot** — for each PRD FR, name the role responsible
     (architect / engineer / qa / devops) and the consulted/informed roles.
  4. **Risks + mitigations** — top 3 schedule/scope risks with explicit
     mitigations (per PMBOK risk register format).
  5. **Definition of Done (project-level)** — checklist the
     release_manager will reference at ship gate.

Output ONLY the markdown.
""".strip()

_ARCHITECT_PROMPT = """
You are the Spine **architect** role. The PRD has just been approved.
Produce a Technical Requirements Document (TRD) in markdown.

TRD structure (start with `# TRD — <Project Name>`):
  1. **Overview** — one paragraph mapping the PRD's desired outcome to
     a system shape (web app / API / job / etc).
  2. **Architecture** — components + data flow. Use a small ASCII or
     bullet diagram. Identify external dependencies.
  3. **Stack decision** — language, framework, datastore, hosting.
     Justify each in ONE sentence; reference TOGAF / PEAF principles
     where relevant.
  4. **Data model** — key tables / collections, fields, relationships.
  5. **Interfaces** — public API surface (REST endpoints / events).
  6. **Non-functional plan** — how the TRD meets each PRD NFR.
  7. **Build sequence** — ordered list of work items (3-8 items) the
     engineer role will implement. Each item: name, scope (1-2 lines),
     acceptance criteria.
  8. **Open architectural risks** — top 3, with mitigation.

Output ONLY the TRD markdown. No preamble. Mark inferred assumptions
with `[INFERRED]`.
""".strip()

_CONDUCTOR_PROMPT = """
You are the Spine **conductor** role (Scrum master + SAFe anchored).
The TRD has just been approved. Produce a sprint plan that the
engineer role can execute against.

SPRINT PLAN structure (start with `# Sprint plan — <Project Name>`):
  1. **Sprint goal** — one sentence: what shipped at the end of this
     sprint proves the PRD's desired outcome.
  2. **Task breakdown** — for each TRD build-sequence item, define
     story-card-sized tasks (1-2 day chunks). Format:
       - **T-1** Title — description (1-2 lines).
         Acceptance: <testable criteria>
         Files touched: <path>, <path>
         Estimate: <S/M/L>
  3. **Definition of Done (sprint-level)** — concrete pass/fail.
  4. **Standups + ceremonies** — propose cadence: daily standup
     summary format, sprint review, retro.
  5. **Impediment log** — placeholders the scrum master will fill in
     during execution.

Output ONLY the markdown.
""".strip()

_QA_PROMPT = """
You are the Spine **qa** role. The implementation plan has been
approved. Produce a test plan in markdown.

QA plan structure (start with `# Test plan — <Project Name>`):
  1. **Test pyramid** — unit / integration / e2e counts + rationale.
  2. **Per-FR coverage** — for each PRD FR, name the tests that cover
     it (cite by name). ISTQB traceability.
  3. **Risk-based testing** — top risks from PRD + TRD, how each is
     mitigated in the test plan.
  4. **Acceptance gates** — what passing means; coverage thresholds;
     who signs off.
  5. **Out of scope (this pass)** — accessibility / load / etc to
     defer.

Output ONLY the markdown.
""".strip()

_RELEASE_MANAGER_PROMPT = """
You are the Spine **release_manager** role (ITIL change-management
anchored). QA signed off. Produce a ship gate + concrete cloud-deploy
options. The user picks one target post-approval.

SHIP GATE structure (start with `# Ship gate — <Project Name>`):
  1. **Release scope** — one-paragraph summary of what's shipping.
  2. **Go / no-go checklist** — explicit boxes:
     - [ ] PRD signed off
     - [ ] TRD signed off
     - [ ] Code review complete
     - [ ] Test plan executed; coverage threshold met
     - [ ] No P0/P1 defects open
     - [ ] Rollback plan documented
     - [ ] Monitoring + alerting in place
     - [ ] Runbook for ops linked
  3. **Rollback plan** — concrete steps if launch fails.
  4. **Comms plan** — who gets notified pre/post launch, in what
     order, via what channel.
  5. **Cloud deploy options** — for the stack the architect chose,
     give the user 3-4 viable targets with the **exact shell commands**
     they'd run from the project workspace.
  6. **Post-launch retro framing** — 3 questions the team should
     answer 1 week post-launch.

Output ONLY the markdown.
""".strip()

_ROLE_CONFIG: dict[str, tuple[str, str]] = {
    "planner": (_PLANNER_PROMPT, "roadmap_md"),
    "architect": (_ARCHITECT_PROMPT, "trd_md"),
    "conductor": (_CONDUCTOR_PROMPT, "sprint_plan_md"),
    "qa": (_QA_PROMPT, "qa_md"),
    "release_manager": (_RELEASE_MANAGER_PROMPT, "release_gate_md"),
}


@dataclass
class HubPlanRoleResult:
    ok: bool
    role: str
    directive_id: str
    artifact_key: str = ""
    artifact_md: str = ""
    error_class: str | None = None
    error_message: str | None = None
    project_uuid: str = ""
    project_name: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


def _load_charter(role: str) -> str:
    path = _CHARTERS_DIR / f"{role}.md"
    if not path.exists():
        return f"# Charter for {role} (not found at {path})"
    return path.read_text(encoding="utf-8")


def _load_project_sync(project_id: str) -> dict[str, Any] | None:
    from build.runtime.build_dispatcher import _load_project  # noqa: PLC0415

    try:
        row = _load_project(project_id)
    except RuntimeError:
        return None
    metadata = row.get("metadata") or {}
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except json.JSONDecodeError:
            metadata = {}
    return {
        "id": row["id"],
        "project_uuid": row["project_uuid"],
        "name": row["name"],
        "project_type": row.get("work_item_type") or row.get("project_type") or "feature",
        "current_phase": row["current_phase"],
        "metadata": metadata,
    }


def _persist_metadata_sync(
    project_id: str,
    patch: dict[str, Any],
    *,
    role: str | None = None,
    directive_id: str | None = None,
) -> None:
    from build.runtime.build_dispatcher import _load_project, _merge_metadata  # noqa: PLC0415
    from shared.runtime.project_workspace import promote_plan_artifacts  # noqa: PLC0415

    row = _load_project(project_id)
    metadata = row.get("metadata") or {}
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except json.JSONDecodeError:
            metadata = {}

    commit_patch = promote_plan_artifacts(
        project_id,
        patch,
        metadata=metadata,
        role=role or "plan",
        directive_id=directive_id or "",
        project_name=str(row.get("name") or ""),
    )
    merged = {**patch, **commit_patch} if commit_patch else patch
    _merge_metadata(int(row["id"]), merged)


async def _run_text_role(
    *,
    role: str,
    project: dict[str, Any],
    extra_context: str = "",
    directive: str = "",
    actor: str = "orchestrator",
) -> HubPlanRoleResult:
    from shared.runtime.kg_role_context import retrieve_kg_context_for_dispatch
    from shared.runtime.project_workspace import repo_slug
    from shared.runtime.role_runtime import (
        append_directive_context,
        begin_directive,
        complete_directive,
        fail_directive,
    )

    project_uuid_pre = project["project_uuid"]

    # V3 #34 hygiene gate — Conductor refuses to mark a project done
    # while uncleaned workspace state exists (D2 slate #7, 2026-05-30).
    # Applies to ``conductor`` only; other plan roles bypass.
    if role == "conductor":
        unclean = _hygiene_blockers(project_uuid_pre)
        if unclean:
            return HubPlanRoleResult(
                ok=False,
                role=role,
                directive_id=f"dir_{uuid4().hex[:12]}",
                artifact_key=_ROLE_CONFIG[role][1],
                error_class="workspace_unclean",
                error_message=(
                    "conductor refused per V3 #34 — uncleaned workspace: "
                    + ", ".join(unclean[:5])
                ),
                project_uuid=project_uuid_pre,
                project_name=project["name"],
            )

    handle = begin_directive(
        project["project_uuid"],
        role,
        directive or f"PLAN_{role.upper()}",
        actor,
    )
    directive_id = handle.directive_id
    prompt, artifact_key = _ROLE_CONFIG[role]
    project_uuid = project["project_uuid"]
    project_name = project["name"]
    prior = project.get("metadata") or {}

    kg_block = retrieve_kg_context_for_dispatch(
        project_id=project_uuid,
        repo=str(prior.get("repo") or repo_slug(project_uuid)),
        role=role,
        phase=str(project.get("current_phase") or "plan_in_progress"),
        directive=directive or f"PLAN_{role.upper()}",
        project_name=project_name,
        commit_sha=prior.get("last_commit_sha"),
    )
    if kg_block:
        append_directive_context(handle, kg_block)
        extra_context = f"{extra_context}\n\n{kg_block}".strip() if extra_context else kg_block

    context_blocks: list[str] = []
    if prior.get("prd_md"):
        context_blocks.append("## Approved PRD\n\n" + prior["prd_md"])
    if prior.get("trd_md") and role != "architect":
        context_blocks.append("## Approved TRD\n\n" + prior["trd_md"])
    if prior.get("impl_md") and role == "qa":
        context_blocks.append("## Approved implementation plan\n\n" + prior["impl_md"])
    if extra_context:
        context_blocks.append(extra_context)

    system = (
        prompt
        + "\n\n---\n\n## Project metadata\n"
        + f"- Name: **{project_name}**\n"
        + f"- Type: **{project['project_type']}**\n\n"
        + "---\n\n## Your charter\n\n"
        + _load_charter(role)
        + ("\n\n---\n\n" + "\n\n---\n\n".join(context_blocks) if context_blocks else "")
    )
    try:
        resp = await call_async(LLMRequest(
            model=_DEFAULT_MODEL,
            messages=[Message(role="user", content=f"Produce your output for {project_name} now.")],
            system=system,
            max_tokens=8000,
            temperature=0.3,
        ))
        artifact_md = resp.content.strip()
    except Exception as exc:  # noqa: BLE001
        fail_directive(handle, str(exc))
        return HubPlanRoleResult(
            ok=False,
            role=role,
            directive_id=directive_id,
            artifact_key=artifact_key,
            error_class=type(exc).__name__,
            error_message=str(exc)[:500],
            project_uuid=project_uuid,
            project_name=project_name,
        )

    _persist_metadata_sync(
        project_uuid,
        {artifact_key: artifact_md},
        role=role,
        directive_id=directive_id,
    )
    complete_directive(handle, artifact_md, ok=True, extra={"artifact_key": artifact_key})

    # V3 #12a decision-ledger write for promotion-gating roles
    # (Conductor + QA; D2 slate #2, 2026-05-30). Auditor writes through
    # its own runtime. Fail-soft inside _record_ledger_outcome.
    if role in ("conductor", "qa"):
        _record_ledger_outcome(
            project_uuid=project_uuid,
            run_id=directive_id,
            role=role,
            artifact_key=artifact_key,
            artifact_md=artifact_md,
        )

    return HubPlanRoleResult(
        ok=True,
        role=role,
        directive_id=directive_id,
        artifact_key=artifact_key,
        artifact_md=artifact_md,
        project_uuid=project_uuid,
        project_name=project_name,
    )


def run_plan_hub_role(
    *,
    project_id: str,
    role: str,
    directive: str,
    actor: str = "orchestrator",
    extra_context: str = "",
) -> HubPlanRoleResult:
    """Sync entry for MCP ``plan_dispatch`` (runs asyncio internally)."""
    if role not in _ROLE_CONFIG:
        return HubPlanRoleResult(
            ok=False,
            role=role,
            directive_id=f"dir_{uuid4().hex[:12]}",
            error_class="unsupported_role",
            error_message=f"plan hub runner does not support role={role!r}",
        )
    project = _load_project_sync(project_id)
    if project is None:
        return HubPlanRoleResult(
            ok=False,
            role=role,
            directive_id=f"dir_{uuid4().hex[:12]}",
            error_class="project_not_found",
            error_message=f"project {project_id!r} not found",
        )

    if role == "architect":
        return asyncio.run(_run_architect(
            project=project,
            extra_context=extra_context,
            directive=directive,
            actor=actor,
        ))

    return asyncio.run(_run_text_role(
        role=role,
        project=project,
        extra_context=extra_context,
        directive=directive,
        actor=actor,
    ))


async def _run_architect(
    *,
    project: dict[str, Any],
    extra_context: str = "",
    directive: str = "",
    actor: str = "orchestrator",
) -> HubPlanRoleResult:
    from plan.runtime.architect_swarm_runner import run_architect_swarm, swarm_enabled
    from shared.runtime.role_runtime import begin_directive, complete_directive, fail_directive

    handle = begin_directive(
        project["project_uuid"],
        "architect",
        directive or "PRODUCE_TRD",
        actor,
    )
    project_uuid = project["project_uuid"]
    project_name = project["name"]

    if swarm_enabled():
        swarm = run_architect_swarm(project)
        if swarm.ok and swarm.trd_md:
            _persist_metadata_sync(
                project_uuid,
                {
                    "trd_md": swarm.trd_md,
                    "trd_swarm_run_id": swarm.swarm_run_id,
                    "trd_swarm_scouts": swarm.scouts_run,
                    "trd_swarm_unrun": swarm.scouts_unrun,
                },
                role="architect",
                directive_id=handle.directive_id,
            )
            complete_directive(
                handle,
                swarm.trd_md,
                ok=True,
                extra={"swarm_run_id": swarm.swarm_run_id},
            )
            return HubPlanRoleResult(
                ok=True,
                role="architect",
                directive_id=handle.directive_id,
                artifact_key="trd_md",
                artifact_md=swarm.trd_md,
                project_uuid=project_uuid,
                project_name=project_name,
                extra={"swarm": True, "scouts": swarm.scouts_run},
            )
        if swarm.error_message:
            fail_directive(handle, swarm.error_message)

    return await _run_text_role(
        role="architect",
        project=project,
        extra_context=extra_context,
        directive=directive or "PRODUCE_TRD",
        actor=actor,
    )


# ─── V3 #34 + #12a wiring helpers (D2 slate #2 + #7) ────────────────


def _hygiene_blockers(project_uuid: str) -> list[str]:
    """Return any uncleaned-workspace reasons; empty list = OK.

    Fail-soft: if the hygiene module is unavailable or raises, we
    treat the project as clean rather than blocking dispatch on a
    broken hygiene check.
    """
    try:
        from shared.runtime.hygiene import project_is_clean

        ok, reasons = project_is_clean(project_uuid)
        if ok:
            return []
        return list(reasons)
    except Exception:  # noqa: BLE001
        logger.warning(
            "hygiene_check_unavailable",
            extra={"project_uuid": project_uuid},
        )
        return []


def _record_ledger_outcome(
    *,
    project_uuid: str,
    run_id: str,
    role: str,
    artifact_key: str,
    artifact_md: str,
) -> None:
    """Append a V3 #12a decision-ledger entry for Conductor / QA.

    Fail-soft: any error swallowed so the directive's report.md and
    audit chain remain the source of truth.
    """
    try:
        from shared.audit.decision_ledger_io import (
            SafePromotionInputs,
            append_promotion_decision,
            make_candidate,
        )

        # Both roles default to internal tier here. The orchestrator
        # promotes to production-class after gate checks downstream.
        append_promotion_decision(
            SafePromotionInputs(
                project_id=project_uuid,
                run_id=run_id,
                role=role,
                rollout_index=0,
                tier="internal",
                freshness_passed=True,  # artifact produced fresh in this run
                replay_passed=False,    # caller decides; default-deny live promotion
                candidates=(
                    make_candidate(
                        f"{role}:{artifact_key}",
                        mark="accept",
                        rationale=f"{role} produced {artifact_key}",
                    ),
                ),
                fresh_evidence=(f"artifact:{artifact_key}:{len(artifact_md)}chars",),
            )
        )
    except Exception:  # noqa: BLE001
        logger.exception(
            "ledger_write_failed",
            extra={"project_uuid": project_uuid, "role": role},
        )


__all__ = ["HubPlanRoleResult", "run_plan_hub_role"]
