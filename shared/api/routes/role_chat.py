"""``/api/v2/role-chat`` — "Talk to a role" surface (#3 Hub feature).

One of the 9 enumerated Hub surfaces. The SPA lets the user pick any
configured role (architect / product / qa / devops / …) and chat with
the role's charter — same prompt the orchestrator uses when that role
acts on the user's behalf, plus the user's typed message.

Routing:

1. Validate the role name exists in ``shared.charters``.
2. Resolve the charter text (Wave 2 substrate).
3. Dispatch via MCP (in-process for Wave 3 part 1; remote-MCP federation
   in Wave 3 part 2) to the role's underlying LLM tool.
4. Audit the call so the conversation is hash-chained in
   ``spine_audit.audit_event``.

Wave 3 part 1 returns a synchronous reply; streaming variant lands in
Wave 3 part 2 with the SPA chat panel.

Dependencies: ``fastapi``, ``pydantic`` (already required).
"""

from __future__ import annotations

import logging
import uuid
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from shared.api.dependencies import McpClient, actor_label, current_user, get_mcp_client
from shared.audit.audit_record import AuditRecord, chain_to_previous
from shared.identity.models import User

logger = logging.getLogger("spine.api.role_chat")
router = APIRouter(prefix="/api/v2/role-chat", tags=["role-chat"])

# Min/max input lengths — tight enough to bound LLM cost, loose enough
# that "draft the standup summary" fits.
_MAX_MESSAGE_LEN = 8_000


class RoleChatRequest(BaseModel):
    """``POST /api/v2/role-chat`` request body."""

    model_config = ConfigDict(extra="forbid")
    role: str = Field(..., min_length=1, max_length=64)
    message: str = Field(..., min_length=1, max_length=_MAX_MESSAGE_LEN)
    project_id: Optional[str] = None
    correlation_id: Optional[str] = None


class RoleChatResponse(BaseModel):
    """``POST /api/v2/role-chat`` response."""

    model_config = ConfigDict(extra="forbid")
    ok: bool = True
    role: str
    reply: str
    actor: str
    audit_event_uuid: str
    metadata: dict[str, Any] = Field(default_factory=dict)


# Set of role names accepted today. Wave 2's `shared.charters` package
# will replace this static list with a charter-driven lookup. We keep
# the list inline so a typo at the call site fails fast.
_KNOWN_ROLES: frozenset[str] = frozenset(
    {
        "architect", "product", "qa", "operator", "devops", "datawright",
        "ux", "engineer", "planner", "conductor", "release_manager",
        "tech_writer", "security_engineer", "compliance_officer",
        "customer_support",
    }
)


def _resolve_charter(role: str) -> str:
    """Fetch the charter text for ``role``.

    Wave 3 part 1: stub returns a fixed system prompt referencing the
    role name. Wave 2's ``shared.charters`` package will swap this for
    a real lookup. The stub keeps the call path testable end-to-end
    without depending on filesystem layout.
    """
    return (
        f"You are the Spine `{role}` role. Respond in the charter's voice, "
        "citing standards when claims are made (per cite-or-refuse, #12)."
    )


@router.post("", response_model=RoleChatResponse, status_code=status.HTTP_200_OK)
async def role_chat(
    body: RoleChatRequest,
    user: Annotated[User, Depends(current_user)],
    mcp: Annotated[McpClient, Depends(get_mcp_client)],
) -> RoleChatResponse:
    """Send ``message`` to ``role`` and return the LLM reply."""
    if body.role not in _KNOWN_ROLES:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error_code": "role_unknown",
                "message": f"role {body.role!r} not in registry",
                "known": sorted(_KNOWN_ROLES),
            },
        )
    charter = _resolve_charter(body.role)
    actor = actor_label(user)

    # Dispatch via MCP. The tool name is conventional ("role_chat"); the
    # underlying tool wires to ``shared.llm`` and will be registered in
    # Wave 3 part 2's ``shared/mcp/tools/role_chat.py``. Until then we
    # return a deterministic stub so the SPA panel can be built end-to-end.
    try:
        resp = mcp.call(
            "role_chat",
            {"role": body.role, "system": charter, "message": body.message},
        )
        reply = str(resp.get("reply", ""))
        metadata = dict(resp.get("metadata") or {})
    except KeyError:
        # Tool not yet registered — return a deterministic placeholder so
        # the panel renders + can be E2E-tested without an LLM bill.
        reply = (
            f"[{body.role} placeholder] received {len(body.message)} chars. "
            "Wave 3 part 2 wires the live LLM tool."
        )
        metadata = {"stub": True}

    correlation = uuid.UUID(body.correlation_id) if body.correlation_id else uuid.uuid4()
    rec = AuditRecord(
        role=body.role,
        subsystem="hub",
        action="role_chat",
        actor=actor,
        subject_type="message",
        subject_id=str(correlation),
        project_id=int(body.project_id) if body.project_id and body.project_id.isdigit() else None,
        correlation_id=correlation,
        metadata={"len_in": len(body.message), "len_out": len(reply), **metadata},
    )
    rec = chain_to_previous(rec, prev_hash=None)
    return RoleChatResponse(
        role=body.role,
        reply=reply,
        actor=actor,
        audit_event_uuid=str(rec.event_uuid),
        metadata=metadata,
    )


__all__ = ["router", "RoleChatRequest", "RoleChatResponse"]
