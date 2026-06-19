"""``/api/v2/role-chat`` — "Talk to a role" surface (#3 Hub feature).

One of the 9 enumerated Hub surfaces. The SPA lets the user pick any
configured role (architect / product / qa / devops / …) and chat with
the role's charter — same prompt the orchestrator uses when that role
acts on the user's behalf, plus the user's typed message.

Routing:

1. Validate the role name exists in ``shared.charters``.
2. Resolve the charter text from ``shared/charters/<role>.md``.
3. Dispatch via MCP ``role_chat`` tool → ``shared.llm``.
4. Audit the call so the conversation is hash-chained in
   ``spine_audit.audit_event``.

In ``SPINE_HUB_DEV=1``, a deterministic stub is returned only when no
LLM API key is configured; otherwise the live charter-backed reply is
used.

Dependencies: ``fastapi``, ``pydantic`` (already required).
"""

from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path
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

_CHARTERS_DIR = Path(__file__).resolve().parents[2] / "charters"


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


def _load_charter(role: str) -> str:
    """Fetch charter markdown for ``role`` from ``shared/charters/``."""
    path = _CHARTERS_DIR / f"{role}.md"
    if not path.exists():
        raise FileNotFoundError(f"charter not found: {path}")
    return path.read_text(encoding="utf-8")


def _is_dev_mode() -> bool:
    return os.environ.get("SPINE_HUB_DEV") == "1"


def _llm_key_available() -> bool:
    """True when an Anthropic or OpenAI key is present (env or vault)."""
    for env_name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        val = os.environ.get(env_name, "").strip()
        if val and not val.lower().startswith("placeholder"):
            return True
    try:
        from shared.secrets import get_default_adapter  # noqa: PLC0415

        adapter = get_default_adapter()
        for path in ("llm/anthropic_api_key", "llm/openai_api_key"):
            try:
                secret = adapter.get_secret(path)
            except Exception:  # noqa: BLE001
                continue
            if secret and str(secret).strip() and not str(secret).lower().startswith("placeholder"):
                return True
    except Exception:  # noqa: BLE001
        pass
    return False


def _stub_reply(role: str, message: str) -> tuple[str, dict[str, Any]]:
    reply = (
        f"[{role} placeholder] received {len(message)} chars. "
        "Set ANTHROPIC_API_KEY (or OPENAI_API_KEY) for live replies in dev mode."
    )
    return reply, {"stub": True}


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

    try:
        charter = _load_charter(body.role)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error_code": "charter_missing", "message": str(exc)},
        ) from exc

    actor = actor_label(user)

    if _is_dev_mode() and not _llm_key_available():
        reply, metadata = _stub_reply(body.role, body.message)
    else:
        try:
            resp = mcp.call(
                "role_chat",
                {"role": body.role, "system": charter, "message": body.message},
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"error_code": "mcp_tool_missing", "message": str(exc)},
            ) from exc

        if resp.get("status") == "error":
            err = resp.get("error") or {}
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={
                    "error_code": err.get("code", "llm_error"),
                    "message": err.get("message", "role_chat tool failed"),
                },
            )

        data = (resp or {}).get("data") or {}
        reply = str(data.get("reply", ""))
        metadata = dict(data.get("metadata") or {})
        if "stub" not in metadata:
            metadata["stub"] = False

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
