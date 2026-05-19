"""``/api/v2/projects/{project_id}/intake`` — conversational intake loop.

The intake role (product charter, anchored on Inspired + Continuous
Discovery + JTBD) asks the user clarifying questions until it has
enough to draft a PRD. This route is the chat surface.

Wire shape:
  POST /api/v2/projects/{project_id}/intake/chat
    body: { message: str, transcript: list[{role, content}] }
    resp: { reply: str, transcript: [...updated...], done: bool, prd?: str }

Server is stateless for v1 — the client owns the transcript and sends
the full history each turn. The Hub does NOT store the transcript yet
(Wave 4 lands an intake_transcript table). The audit ledger captures
every LLM call.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from shared.api.dependencies import actor_label, current_user
from shared.identity.models import User
from shared.llm import LLMRequest, Message, call_async

logger = logging.getLogger("spine.api.intake")
router = APIRouter(prefix="/api/v2/projects", tags=["intake"])

# Default model — Anthropic Sonnet, balanced cost/quality for intake.
# Operators can override per-Hub via SPINE_INTAKE_MODEL env.
import os as _os
_DEFAULT_MODEL = _os.environ.get("SPINE_INTAKE_MODEL", "claude-sonnet-4-6")

# Charter path resolution. Container layout: /app/shared/charters/product.md.
_CHARTERS_DIR = Path(__file__).resolve().parents[1].parent / "charters"


def _load_charter(role: str) -> str:
    path = _CHARTERS_DIR / f"{role}.md"
    if not path.exists():
        raise FileNotFoundError(f"charter not found: {path}")
    return path.read_text(encoding="utf-8")


_INTAKE_PROTOCOL = """
You are running the Spine **intake** loop for a brand-new project.

Your job is to extract clear, testable product requirements from the
user via a short conversation, then signal completion so the system
can draft a PRD.

Operating rules:
  1. Ask AT MOST ONE focused question per turn. Never bullet-list 5
     questions; the user can only answer one at a time.
  2. Cover (in this rough order): the user / use-case, the desired
     outcome, success criteria, constraints (deadline / stack / budget),
     known risks. Skip what's already stated.
  3. When you have ENOUGH to draft a PRD (typically 3-7 turns), end
     your reply with the literal sentinel `[INTAKE_COMPLETE]` on its
     own line. The system reads this to advance to PRD-draft phase.
     Do NOT use this sentinel until you actually have enough info.
  4. Be concise. One short paragraph + one question. No preamble. No
     "Great question!" filler.
  5. If the user is vague, push back with a more specific question
     rather than accepting vagueness.

You will receive the user's project NAME and TYPE up front. Your first
turn should reference the name and ask the most important open
question for that type.
""".strip()


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


_FORBID = ConfigDict(extra="forbid")
_ChatRole = Literal["user", "assistant"]


class TranscriptTurn(BaseModel):
    model_config = _FORBID
    role: _ChatRole
    content: str = Field(..., min_length=1, max_length=16_000)


class IntakeChatRequest(BaseModel):
    model_config = _FORBID
    message: str = Field(..., min_length=1, max_length=8_000)
    transcript: list[TranscriptTurn] = Field(default_factory=list)
    project_name: str = Field(..., min_length=1, max_length=200)
    project_type: str = Field(..., min_length=1, max_length=40)
    greenfield: bool = False


class IntakeChatResponse(BaseModel):
    model_config = _FORBID
    reply: str
    transcript: list[TranscriptTurn]
    done: bool
    model: str
    actor: str


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


_INTAKE_COMPLETE_SENTINEL = "[INTAKE_COMPLETE]"


_PRD_SYNTHESIS_PROMPT = """
You are the Spine **product** role. The intake conversation just
completed. Synthesize a Product Requirements Document from the
transcript.

PRD structure (markdown — start with `# <Project Name>` heading):
  1. **Problem** — one paragraph describing the user need + the
     opportunity in JTBD terms (when X happens, the user wants to Y so
     they can Z).
  2. **Users** — who this is for; primary + secondary segments.
  3. **Desired outcome** — what "done" looks like from the user's POV.
  4. **Functional requirements** — bullet list, numbered FR-1, FR-2…
  5. **Non-functional requirements** — perf, security, accessibility,
     scale targets. Numbered NFR-1, NFR-2…
  6. **Out of scope** — explicit non-goals; what we are NOT building.
  7. **Constraints** — deadlines / budget / stack / regulatory.
  8. **Open risks** — top 3-5; for each note value/usability/feasibility/
     viability framing per Cagan.
  9. **Success metrics** — leading + lagging indicators.
 10. **Next decisions** — what the next role (architect) needs to pick.

Tight prose. No filler. Use the user's own words where useful. Mark
anything you had to infer with `[INFERRED]`.

Do NOT include the intake transcript in the PRD. Do NOT include this
prompt. Output ONLY the PRD markdown, starting with `# `.
""".strip()


async def _synthesize_prd_and_seed_approval(
    *,
    project_id: str,
    project_name: str,
    project_type: str,
    greenfield: bool,
    transcript: list[TranscriptTurn],
    actor: str,
) -> None:
    """Background task fired when intake completes.

    Calls the LLM again to draft a full PRD from the transcript, then
    enqueues an approval DecisionCard so the user can ack/reject the
    PRD. Best-effort — failures are logged and do not surface to the
    user (the chat-turn reply has already returned).
    """
    import uuid as _uuid

    try:
        product_charter = _load_charter("product")
        transcript_text = "\n\n".join(
            f"**{t.role.upper()}:** {t.content}" for t in transcript
        )
        system = (
            _PRD_SYNTHESIS_PROMPT
            + "\n\n---\n\n## Project metadata\n"
            + f"- Name: **{project_name}**\n"
            + f"- Type: **{project_type}**\n"
            + f"- Greenfield: **{greenfield}**\n\n"
            + "---\n\n## Your charter (product role)\n\n"
            + product_charter
            + "\n\n---\n\n## Intake transcript\n\n"
            + transcript_text
        )
        resp = await call_async(LLMRequest(
            model=_DEFAULT_MODEL,
            messages=[Message(role="user", content="Draft the PRD now.")],
            system=system,
            max_tokens=8000,
            temperature=0.3,
        ))
        prd_md = resp.content.strip()
    except Exception as exc:  # noqa: BLE001
        logger.exception("prd_synthesis_failed", extra={"project_id": project_id})
        # Seed a stub approval card so the user sees SOMETHING about the
        # failure rather than silently sitting on intake.
        prd_md = (
            f"# {project_name}\n\n"
            f"_PRD generation failed: {type(exc).__name__}_\n\n"
            f"The intake transcript is preserved on the workspace page; "
            f"re-run intake or contact support."
        )

    # Persist PRD into project.metadata.
    try:
        import json as _json
        from shared.api.dependencies import get_db_pool_raw
        pool = get_db_pool_raw()
        if pool is not None:
            project_pk: Optional[int] = None
            if project_id.isdigit():
                project_pk = int(project_id)
            else:
                async with pool.acquire() as conn:
                    row = await conn.fetchrow(
                        "SELECT id FROM spine_lifecycle.project WHERE project_uuid::text = $1",
                        project_id,
                    )
                    if row:
                        project_pk = int(row["id"])
            if project_pk is not None:
                async with pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE spine_lifecycle.project SET metadata = "
                        "COALESCE(metadata, '{}'::jsonb) || $1::jsonb WHERE id = $2",
                        _json.dumps({"prd_md": prd_md}),
                        project_pk,
                    )
    except Exception as exc:  # noqa: BLE001
        logger.warning("prd_persist_failed", extra={"project_id": project_id, "error": str(exc)})

    # Push approval card.
    try:
        from shared.api.routes.decisions import DecisionCard, enqueue_decision
        card = DecisionCard(
            decision_id=str(_uuid.uuid4()),
            decision_class="approval",
            project_id=project_id,
            title=f"Approve PRD — {project_name}",
            body=(
                "The product role drafted this PRD from the intake "
                "conversation. Approve to advance the project to the "
                "**plan** phase and dispatch the architect role for a "
                "TRD. Reject to send the product role back for another "
                "intake pass.\n\n---\n\n" + prd_md
            ),
            severity="info",
            actions=["ack", "reject"],
            metadata={
                "kind": "prd_approval",
                "project_name": project_name,
                "project_type": project_type,
                "greenfield": bool(greenfield),
                "advances_phase_to": "plan",
            },
        )
        enqueue_decision(card)
        logger.info("prd_approval_card_enqueued", extra={
            "project_id": project_id, "decision_id": card.decision_id,
            "prd_chars": len(prd_md),
        })
    except Exception as exc:  # noqa: BLE001
        logger.exception("prd_approval_card_enqueue_failed",
                         extra={"project_id": project_id})


@router.post(
    "/{project_id}/intake/chat",
    response_model=IntakeChatResponse,
    status_code=status.HTTP_200_OK,
)
async def intake_chat(
    project_id: str,
    body: IntakeChatRequest,
    user: Annotated[User, Depends(current_user)],
) -> IntakeChatResponse:
    """One turn of the intake conversation. Calls the product role via
    the configured LLM. The client maintains transcript state.
    """
    actor = actor_label(user)

    try:
        product_charter = _load_charter("product")
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=500,
            detail={"error_code": "charter_missing", "message": str(exc)},
        ) from exc

    system_prompt = "\n\n---\n\n".join([
        _INTAKE_PROTOCOL,
        f"## Project under intake\n\nName: **{body.project_name}**\n"
        f"Type: **{body.project_type}**\n"
        f"Greenfield: **{body.greenfield}**\n",
        "## Your charter (product role)\n\n" + product_charter,
    ])

    # Build the LLM messages from transcript + new user turn.
    messages = [
        Message(role=turn.role, content=turn.content) for turn in body.transcript
    ]
    messages.append(Message(role="user", content=body.message))

    try:
        resp = await call_async(LLMRequest(
            model=_DEFAULT_MODEL,
            messages=messages,
            system=system_prompt,
            max_tokens=2048,
            temperature=0.4,
        ))
    except Exception as exc:  # noqa: BLE001
        logger.exception("intake_llm_call_failed", extra={"project_id": project_id})
        raise HTTPException(
            status_code=502,
            detail={
                "error_code": "llm_error",
                "message": f"{type(exc).__name__}: {str(exc)[:300]}",
                "hint": "Check ANTHROPIC_API_KEY is set in the host shell and rebuild via "
                        "tools/hub-up.sh --rebuild.",
            },
        ) from exc

    reply = resp.content.strip()
    done = _INTAKE_COMPLETE_SENTINEL in reply
    if done:
        # Strip the sentinel from the user-visible reply.
        reply = reply.replace(_INTAKE_COMPLETE_SENTINEL, "").strip()
        # If the role returned ONLY the sentinel (no prose) the strip
        # leaves an empty string — Pydantic min_length=1 then rejects
        # TranscriptTurn(content=""). Substitute a sensible closing line.
        if not reply:
            reply = ("Got it. I have enough to draft the PRD now — "
                     "you'll see an approval card in the decision queue "
                     "shortly.")
        # Fire-and-forget PRD synthesis + approval card; non-blocking so
        # the chat reply lands fast even when PRD generation is slow.
        import asyncio as _asyncio
        _asyncio.create_task(_synthesize_prd_and_seed_approval(
            project_id=project_id,
            project_name=body.project_name,
            project_type=body.project_type,
            greenfield=body.greenfield,
            transcript=list(body.transcript) + [
                TranscriptTurn(role="user", content=body.message),
                TranscriptTurn(role="assistant", content=reply),
            ],
            actor=actor,
        ))

    # Updated transcript = previous + user turn + assistant reply.
    new_transcript = list(body.transcript) + [
        TranscriptTurn(role="user", content=body.message),
        TranscriptTurn(role="assistant", content=reply),
    ]

    return IntakeChatResponse(
        reply=reply,
        transcript=new_transcript,
        done=done,
        model=_DEFAULT_MODEL,
        actor=actor,
    )


__all__ = ["router"]
