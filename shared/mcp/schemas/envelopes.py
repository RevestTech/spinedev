"""Shared Pydantic envelopes for every MCP tool request and response.

Each tool wraps its tool-specific payload inside a :class:`ToolRequest` (input)
or :class:`ToolResponse` (output) envelope so the orchestrator, audit log, and
cost ledger always see the same shape regardless of which subsystem the tool
belongs to.

These envelopes are deliberately permissive in ``params``/``data``: each
concrete tool module defines its own Pydantic input/output model and embeds it
in the envelope at call time.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

ToolStatus = Literal["ok", "error", "stub_implementation"]
"""Envelope-level outcome status used by every Spine MCP tool."""


def _utcnow() -> datetime:
    """Return a timezone-aware UTC ``datetime``; used as a default factory."""
    return datetime.now(timezone.utc)


class ToolError(BaseModel):
    """Structured error returned inside :class:`ToolResponse` when ``status='error'``.

    ``retryable`` lets the orchestrator distinguish transient failures (network,
    queue contention) from terminal ones (bad input, capability denial).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str = Field(
        ...,
        description="Stable machine-readable error code, e.g. 'kg_index_missing'.",
        min_length=1,
    )
    message: str = Field(
        ...,
        description="Human-readable error message; safe to surface in logs/UI.",
        min_length=1,
    )
    retryable: bool = Field(
        ...,
        description="True if the orchestrator may retry the same call verbatim.",
    )


class ToolRequest(BaseModel):
    """Inbound envelope. Every MCP tool call carries this on the wire.

    The orchestrator (or any caller) MUST set ``project_id`` and ``actor`` so
    the audit log can attribute the call. ``params`` is the tool-specific input
    model serialized to a ``dict``.
    """

    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(
        ...,
        description="Spine project this call belongs to (FK -> spine_lifecycle.project).",
        min_length=1,
    )
    actor: str = Field(
        ...,
        description="Role / user / subsystem invoking the tool (e.g. 'engineer', 'orchestrator').",
        min_length=1,
    )
    timestamp: datetime = Field(
        default_factory=_utcnow,
        description="Wall-clock UTC time at which the caller emitted the request.",
    )
    params: dict[str, Any] = Field(
        default_factory=dict,
        description="Tool-specific input payload (validated by the tool's own input model).",
    )


class ToolResponse(BaseModel):
    """Outbound envelope. Every MCP tool returns this.

    ``audit_id`` is generated server-side and points to the matching row in
    ``spine_audit`` (see REQ-INIT-9 FR-8). ``status='stub_implementation'`` is
    used during scaffolding so callers can detect un-wired tools without
    treating them as errors.
    """

    model_config = ConfigDict(extra="forbid")

    status: ToolStatus = Field(
        ...,
        description="Envelope outcome: 'ok' | 'error' | 'stub_implementation'.",
    )
    data: dict[str, Any] = Field(
        default_factory=dict,
        description="Tool-specific output payload (validated by the tool's own output model).",
    )
    error: ToolError | None = Field(
        default=None,
        description="Populated iff status == 'error'; None otherwise.",
    )
    audit_id: UUID = Field(
        default_factory=uuid4,
        description="Server-generated correlation ID; matches spine_audit row.",
    )
    timestamp: datetime = Field(
        default_factory=_utcnow,
        description="Wall-clock UTC time at which the server emitted the response.",
    )


__all__: list[str] = [
    "ToolError",
    "ToolRequest",
    "ToolResponse",
    "ToolStatus",
]
