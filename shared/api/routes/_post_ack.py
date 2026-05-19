"""Post-ack side-effect hooks for the SDLC chain.

When a user acks a decision card, this module dispatches the next role
in the SDLC pipeline based on the card's metadata.kind:

  prd_approval     → advance to phase=plan, dispatch architect for TRD
  trd_approval     → advance to phase=build, dispatch engineer for impl
  impl_approval    → advance to phase=verify, dispatch qa for test plan
  qa_approval      → advance to phase=release, mark project complete

Each role call is a real LLM dispatch using the role's charter from
shared/charters/<role>.md. Output gets persisted to project.metadata
and pushed as the next approval card.

All work runs as fire-and-forget asyncio tasks so the ack response
lands fast. Failures are logged but never raise out of this module.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from pathlib import Path
from typing import Any, Optional

from shared.llm import LLMRequest, Message, call_async

logger = logging.getLogger("spine.api.post_ack")

_CHARTERS_DIR = Path(__file__).resolve().parents[1].parent / "charters"

import os as _os
_DEFAULT_MODEL = _os.environ.get("SPINE_INTAKE_MODEL", "claude-sonnet-4-6")


def _load_charter(role: str) -> str:
    path = _CHARTERS_DIR / f"{role}.md"
    if not path.exists():
        return f"# Charter for {role} (not found at {path})"
    return path.read_text(encoding="utf-8")


async def _load_project_full(project_id: str) -> Optional[dict[str, Any]]:
    """Fetch the project row + metadata (incl. prior artifacts)."""
    from shared.api.dependencies import get_db_pool_raw
    pool = get_db_pool_raw()
    if pool is None:
        return None
    where_clause = "id = $1" if project_id.isdigit() else "project_uuid::text = $1"
    arg: Any = int(project_id) if project_id.isdigit() else project_id
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"SELECT id, project_uuid::text AS project_uuid, name, project_type, "
            f"current_phase, metadata FROM spine_lifecycle.project WHERE {where_clause}",
            arg,
        )
    if row is None:
        return None
    metadata = row["metadata"]
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except Exception:  # noqa: BLE001
            metadata = {}
    return {
        "id": int(row["id"]),
        "project_uuid": row["project_uuid"],
        "name": row["name"],
        "project_type": row["project_type"],
        "current_phase": row["current_phase"],
        "metadata": metadata or {},
    }


async def _persist_metadata_patch(project_id: str, patch: dict[str, Any]) -> None:
    """Merge `patch` into project.metadata via JSONB ||."""
    from shared.api.dependencies import get_db_pool_raw
    pool = get_db_pool_raw()
    if pool is None:
        return
    where_clause = "id = $2" if project_id.isdigit() else "project_uuid::text = $2"
    arg: Any = int(project_id) if project_id.isdigit() else project_id
    async with pool.acquire() as conn:
        await conn.execute(
            f"UPDATE spine_lifecycle.project SET metadata = "
            f"COALESCE(metadata, '{{}}'::jsonb) || $1::jsonb, updated_at = now() "
            f"WHERE {where_clause}",
            json.dumps(patch), arg,
        )


async def _advance_phase(project_id: str, target_phase: str) -> None:
    from shared.api.dependencies import get_db_pool_raw
    pool = get_db_pool_raw()
    if pool is None:
        return
    where_clause = "id = $2" if project_id.isdigit() else "project_uuid::text = $2"
    arg: Any = int(project_id) if project_id.isdigit() else project_id
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                f"UPDATE spine_lifecycle.project SET current_phase = $1, updated_at = now() "
                f"WHERE {where_clause} RETURNING id",
                target_phase, arg,
            )
            if row is None:
                return
            await conn.execute(
                "INSERT INTO spine_lifecycle.phase_history "
                "(project_id, phase, entered_at) VALUES ($1, $2, now())",
                int(row["id"]), target_phase,
            )


def _enqueue(card_kwargs: dict[str, Any]) -> None:
    from shared.api.routes.decisions import DecisionCard, enqueue_decision
    card = DecisionCard(decision_id=str(uuid.uuid4()), **card_kwargs)
    enqueue_decision(card)
    logger.info("post_ack_card_enqueued", extra={
        "decision_id": card.decision_id,
        "kind": card_kwargs.get("metadata", {}).get("kind"),
    })


# ---------------------------------------------------------------------------
# Role dispatchers
# ---------------------------------------------------------------------------


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


_ENGINEER_PROMPT = """
You are the Spine **engineer** role. The TRD has just been approved.
Produce an implementation plan in markdown — the concrete code work
that turns the TRD's build sequence into a shippable change set.

IMPL plan structure (start with `# Implementation plan — <Project Name>`):
  1. **Repository layout** — files / directories that need creating
     or modifying. Use a tree diagram.
  2. **Build sequence walkthrough** — for each TRD build item:
     - File-level diff summary (what files change, what functions added)
     - Tests added (test names + what they assert)
     - Estimated lines-of-code delta
  3. **Run instructions** — how the user runs the result locally.
  4. **Out of scope (this pass)** — anything you'd defer to a follow-up.

Clean Code conventions: small functions, intention-revealing names,
no commented-out code. Output ONLY the markdown.
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


async def _dispatch_role(
    *,
    role: str,
    project: dict[str, Any],
    role_prompt: str,
    artifact_key: str,
    next_phase: str,
    approval_card_kind: str,
    extra_context: str = "",
) -> None:
    """Generic dispatcher: load charter, call LLM, persist, push approval."""
    project_id = project["project_uuid"]
    project_name = project["name"]
    prior = project.get("metadata", {})
    try:
        charter = _load_charter(role)
        context_blocks = []
        if prior.get("prd_md"):
            context_blocks.append("## Approved PRD\n\n" + prior["prd_md"])
        if prior.get("trd_md") and role != "architect":
            context_blocks.append("## Approved TRD\n\n" + prior["trd_md"])
        if prior.get("impl_md") and role == "qa":
            context_blocks.append("## Approved implementation plan\n\n" + prior["impl_md"])
        if extra_context:
            context_blocks.append(extra_context)
        system = (
            role_prompt
            + "\n\n---\n\n## Project metadata\n"
            + f"- Name: **{project_name}**\n"
            + f"- Type: **{project['project_type']}**\n\n"
            + "---\n\n## Your charter\n\n"
            + charter
            + ("\n\n---\n\n" + "\n\n---\n\n".join(context_blocks) if context_blocks else "")
        )
        resp = await call_async(LLMRequest(
            model=_DEFAULT_MODEL,
            messages=[Message(role="user", content=f"Produce your output for {project_name} now.")],
            system=system,
            max_tokens=8000,
            temperature=0.3,
        ))
        artifact_md = resp.content.strip()
    except Exception as exc:  # noqa: BLE001
        logger.exception("role_dispatch_failed",
                         extra={"project_id": project_id, "role": role})
        artifact_md = (
            f"# {role.title()} output — {project_name}\n\n"
            f"_Role dispatch failed: {type(exc).__name__}_\n\n"
            f"Check the Hub logs and re-run the dispatcher."
        )

    await _persist_metadata_patch(project_id, {artifact_key: artifact_md})

    _enqueue({
        "decision_class": "approval",
        "project_id": project_id,
        "title": f"Approve {role.upper()} output — {project_name}",
        "body": (
            f"The {role} role produced this artifact. Approve to advance "
            f"to the **{next_phase}** phase and dispatch the next role. "
            f"Reject to send the {role} back for another pass.\n\n"
            f"---\n\n" + artifact_md
        ),
        "severity": "info",
        "actions": ["ack", "reject"],
        "metadata": {
            "kind": approval_card_kind,
            "project_name": project_name,
            "project_uuid": project_id,
            "advances_phase_to": next_phase,
            "produced_by": role,
        },
    })


# ---------------------------------------------------------------------------
# Hook entry point
# ---------------------------------------------------------------------------


async def on_decision_acked(card: Any, *, actor: str) -> None:
    """Top-level hook called from the ack handler. Idempotent in that
    re-acking the same card re-fires the side-effect; the caller is
    expected to gate via the card's status transition first.
    """
    md = getattr(card, "metadata", {}) or {}
    kind = md.get("kind")
    # Card.project_id is a TEXT field on the model but a BIGINT column in
    # spine_lifecycle.decision_card (V36). The DB persistence drops the
    # UUID string. Recover from metadata.project_uuid that the enqueueing
    # site is now responsible for setting.
    project_id = getattr(card, "project_id", None) or md.get("project_uuid")
    if not project_id:
        logger.warning("post_ack_no_project_id",
                       extra={"decision_id": getattr(card, "decision_id", None),
                              "kind": kind, "metadata_keys": list(md.keys())})
        return

    logger.info("post_ack_dispatch", extra={"kind": kind, "project_id": project_id, "actor": actor})

    if kind == "intake_briefing":
        # The seed card from project_create — user confirmed scope; nothing
        # downstream to do here, the intake chat is already running.
        return

    project = await _load_project_full(project_id)
    if project is None:
        logger.warning("post_ack_project_missing", extra={"project_id": project_id})
        return

    if kind == "prd_approval":
        await _advance_phase(project_id, "plan")
        project = (await _load_project_full(project_id)) or project
        await _dispatch_role(
            role="architect",
            project=project,
            role_prompt=_ARCHITECT_PROMPT,
            artifact_key="trd_md",
            next_phase="build",
            approval_card_kind="trd_approval",
        )
        return

    if kind == "trd_approval":
        await _advance_phase(project_id, "build")
        project = (await _load_project_full(project_id)) or project
        await _dispatch_role(
            role="engineer",
            project=project,
            role_prompt=_ENGINEER_PROMPT,
            artifact_key="impl_md",
            next_phase="verify",
            approval_card_kind="impl_approval",
        )
        return

    if kind == "impl_approval":
        await _advance_phase(project_id, "verify")
        project = (await _load_project_full(project_id)) or project
        await _dispatch_role(
            role="qa",
            project=project,
            role_prompt=_QA_PROMPT,
            artifact_key="qa_md",
            next_phase="release",
            approval_card_kind="qa_approval",
        )
        return

    if kind == "qa_approval":
        await _advance_phase(project_id, "release")
        # Final card — celebrate; no further dispatch.
        _enqueue({
            "decision_class": "briefing",
            "project_id": project_id,
            "title": f"Project ready to ship — {project['name']}",
            "body": (
                f"All four roles signed off on **{project['name']}**.\n\n"
                f"- PRD, TRD, implementation plan, and test plan are all "
                f"approved and stored on the project (`metadata.prd_md`, "
                f"`trd_md`, `impl_md`, `qa_md`).\n"
                f"- Next: a human pushes the code to git and runs the "
                f"approved test plan. Real code-generation lands in the "
                f"next iteration (engineer role producing actual file "
                f"diffs rather than the plan).\n"
            ),
            "severity": "info",
            "actions": ["ack", "reject"],
            "metadata": {
                "kind": "project_complete",
                "project_name": project["name"],
                "project_uuid": project_id,
            },
        })
        return

    logger.debug("post_ack_no_handler", extra={"kind": kind, "project_id": project_id})


__all__ = ["on_decision_acked"]
