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
