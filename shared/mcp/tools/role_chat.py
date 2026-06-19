"""Hub role-chat MCP tool (SPINE-010).

Dispatches a single user message to the configured LLM with the role's
charter as the system prompt. Used by ``shared.api.routes.role_chat``.
"""

from __future__ import annotations

import logging
import os

from pydantic import BaseModel, ConfigDict, Field

from shared.llm import LLMRequest, Message, call
from shared.mcp.schemas import ToolError, ToolResponse
from shared.mcp.tools import register_tool

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = os.environ.get("SPINE_ROLE_CHAT_MODEL") or os.environ.get(
    "SPINE_INTAKE_MODEL", "claude-sonnet-4-6"
)


class RoleChatInput(BaseModel):
    """Inputs for ``role_chat``."""

    model_config = ConfigDict(extra="forbid")

    role: str = Field(..., min_length=1, max_length=64)
    system: str = Field(..., min_length=1, description="Charter / system prompt.")
    message: str = Field(..., min_length=1, max_length=8_000)


class RoleChatData(BaseModel):
    """``ToolResponse.data`` payload."""

    model_config = ConfigDict(extra="forbid")

    reply: str
    metadata: dict[str, object] = Field(default_factory=dict)


@register_tool(
    name="role_chat",
    input_model=RoleChatInput,
    story="STORY-3.3.1",
    description="Send a message to a Spine role charter and return the LLM reply.",
    tags=("hub", "role-chat"),
)
def role_chat(payload: RoleChatInput) -> ToolResponse:
    """Call ``shared.llm`` with the role charter as system prompt."""
    logger.info(
        "mcp_tool_call",
        extra={"tool": "role_chat", "role": payload.role, "len_in": len(payload.message)},
    )
    try:
        resp = call(
            LLMRequest(
                model=_DEFAULT_MODEL,
                messages=[Message(role="user", content=payload.message)],
                system=payload.system,
                max_tokens=2048,
                temperature=0.4,
            )
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("role_chat_llm_failed", extra={"role": payload.role})
        return ToolResponse(
            status="error",
            data={},
            error=ToolError(
                code="llm_error",
                message=f"{type(exc).__name__}: {str(exc)[:300]}",
                retryable=False,
            ),
        )

    reply = resp.content.strip()
    return ToolResponse(
        status="ok",
        summary=f"{payload.role} replied ({len(reply)} chars)",
        data=RoleChatData(
            reply=reply,
            metadata={"stub": False, "model": _DEFAULT_MODEL},
        ).model_dump(mode="json"),
    )
