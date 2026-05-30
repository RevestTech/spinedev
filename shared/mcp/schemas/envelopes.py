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

ToolStatus = Literal["ok", "warning", "error", "refusal", "stub_implementation"]
"""Envelope-level outcome status used by every Spine MCP tool.

V3 #30a extension (2026-05-29). ``warning`` and ``refusal`` join the original
three statuses to align with the ECC-borrowed harness-construction
observation contract (see ``docs/ECC_BORROWS.md`` B2):

  * ``warning``  — tool produced a usable result but the caller should
                   attend to ``summary`` / ``next_actions`` before promoting
                   (e.g. degraded mode, missing optional dep).
  * ``refusal``  — tool deliberately declined to act. Use for policy /
                   Cite-or-Refuse (#12) / gate denials. Distinct from
                   ``error`` (internal failure, possibly retryable).
"""

CitationType = Literal["kg_node", "file_line", "audit_hash"]
"""Categories of supporting evidence recognised by Cite-or-Refuse (V3 #12)."""

ArtifactType = Literal[
    "file_path",
    "kg_node",
    "run_id",
    "audit_hash",
    "url",
    "ledger_entry",
]
"""Categories of artifact references emitted by tools (V3 #30a)."""


class Citation(BaseModel):
    """One unit of supporting evidence for a verify-class tool response.

    Per V3 design decision #12 (Cite-or-Refuse), any tool tagged
    ``requires_citation=True`` MUST attach at least one ``Citation`` to
    its response envelope or explicitly refuse to act. The three types
    listed are the v1.0 surface; future extensions add to the Literal.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: CitationType = Field(
        ..., description="Evidence class: kg_node | file_line | audit_hash.",
    )
    ref: str = Field(
        ..., min_length=1,
        description=(
            "Stable reference. For kg_node: the spine_kg node_id. "
            "For file_line: 'path:line[:col]'. For audit_hash: "
            "spine_audit.event content_hash."
        ),
    )
    excerpt: str | None = Field(
        default=None,
        description="Optional short verbatim excerpt for human review.",
    )


class Artifact(BaseModel):
    """One stable reference to something the tool produced or touched.

    V3 #30a (2026-05-29). Adapted from the ECC ``agent-harness-construction``
    observation contract: every tool response exposes structured artifacts
    so calling roles can chain follow-up work without re-parsing free-text.

    ``ref`` is a stable identifier whose interpretation depends on ``type``:

      * ``file_path``    — repo-relative or absolute path.
      * ``kg_node``      — ``spine_kg.node`` identifier.
      * ``run_id``       — orchestrator run identifier.
      * ``audit_hash``   — ``spine_audit.event.content_hash``.
      * ``url``          — externally resolvable URL.
      * ``ledger_entry`` — ``shared.audit.decision_ledger`` entry id.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: ArtifactType = Field(
        ...,
        description="Artifact class; see ArtifactType literal.",
    )
    ref: str = Field(
        ..., min_length=1,
        description="Stable reference (see class docstring for shape per type).",
    )
    label: str | None = Field(
        default=None,
        description="Optional human-readable label for UI / log surfaces.",
    )


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

    Wave 6 Stream J (#30 heavier API + MCP) extensions:

    * ``feature_flag_required`` — when set the unified MCP server consults
      ``shared.api.middleware.feature_flag.is_feature_enabled`` BEFORE
      dispatching the tool; a disabled flag yields a fail-closed error
      envelope (``error_code='feature_disabled'``) without ever invoking
      the tool. This lets remote-MCP federation Hubs respect customer
      licence boundaries even when the calling client forgot to pre-check.
    * ``actor_token_claims`` — the Keycloak ``TokenClaims`` from the
      bearer/cookie session that produced this call, passed through so a
      tool implementation can make downstream authorisation decisions
      (e.g. "this user has `compliance-officer` role; allow evidence
      export") without re-validating the JWT itself. Spine never persists
      these claims — they are request-scoped only.
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
    feature_flag_required: str | None = Field(
        default=None,
        min_length=1,
        description=(
            "Optional licence-flag gate (V3 #23). When set, the MCP "
            "server rejects the call with a fail-closed error envelope "
            "before invocation if the customer's active licence bundle "
            "does not enable this flag. Must be a member of "
            "shared.api.middleware.feature_flag.KNOWN_FEATURE_FLAGS."
        ),
    )
    actor_token_claims: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Request-scoped Keycloak TokenClaims (V3 #25). Pass-through "
            "auth context for downstream authorisation decisions inside "
            "the tool implementation; never persisted, never logged in "
            "the clear. Equivalent to ``TokenClaims.model_dump()``."
        ),
    )


class ToolResponse(BaseModel):
    """Outbound envelope. Every MCP tool returns this.

    ``audit_id`` is generated server-side and points to the matching row in
    ``spine_audit`` (see REQ-INIT-9 FR-8). ``status='stub_implementation'`` is
    used during scaffolding so callers can detect un-wired tools without
    treating them as errors.

    ``citation`` carries Cite-or-Refuse evidence (V3 #12) and is REQUIRED
    for tools registered with ``requires_citation=True``; the MCP server
    middleware rejects empty citation lists with a 422 refusal.

    V3 #30a (2026-05-29) observation extensions:

      * ``summary``      — one-line, role-readable result. Always present
                           on non-error responses; orchestrator surfaces
                           this in queue UI without parsing ``data``.
      * ``next_actions`` — actionable follow-ups the calling role can
                           dispatch next. Items SHOULD reference tools or
                           commands by name (e.g. ``"retry_engineer"``,
                           ``"approve_decision <id>"``).
      * ``artifacts``    — structured references to things produced or
                           touched. Replaces ad-hoc lists stuffed into
                           ``data``.

    These three fields are additive — existing tools that omit them still
    validate. The ``MCPToolResponseConvention`` validator at the bottom of
    this module emits a ``warning`` for responses that violate the
    convention (status ``ok``/``warning`` without ``summary``); enforcement
    mode is controlled by ``SPINE_HOOK_PROFILE`` (V3 #30a, B7).
    """

    model_config = ConfigDict(extra="forbid")

    status: ToolStatus = Field(
        ...,
        description=(
            "Envelope outcome: 'ok' | 'warning' | 'error' | 'refusal' | "
            "'stub_implementation'."
        ),
    )
    summary: str | None = Field(
        default=None,
        description=(
            "One-line, role-readable result. SHOULD be non-empty when "
            "status is 'ok' or 'warning'. See V3 #30a observation contract."
        ),
    )
    next_actions: list[str] = Field(
        default_factory=list,
        description=(
            "Actionable follow-ups for the calling role (e.g. tool names, "
            "command identifiers). V3 #30a observation contract."
        ),
    )
    artifacts: list[Artifact] = Field(
        default_factory=list,
        description=(
            "Structured references to artifacts produced or touched by "
            "this call. V3 #30a observation contract."
        ),
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
    citation: list[Citation] = Field(
        default_factory=list,
        description=(
            "Supporting evidence for verify-class tool responses "
            "(Cite-or-Refuse, V3 #12). MUST be non-empty for tools with "
            "requires_citation=True; rejected with 422 otherwise."
        ),
    )


def check_envelope_convention(response: "ToolResponse") -> list[str]:
    """Return a list of convention violations for ``response``.

    V3 #30a (2026-05-29). Soft check used by the server middleware:

      * ``ok`` / ``warning`` responses SHOULD set ``summary``.
      * ``refusal`` responses SHOULD populate ``error`` with a
        ``cite_or_refuse_*`` or ``policy_*`` code.
      * ``error`` responses MUST populate ``error`` (already enforced
        elsewhere; included here for symmetry of the violation list).

    Returns an empty list when the response conforms.

    This function never raises. The server middleware decides whether to
    log, warn, or reject based on ``SPINE_HOOK_PROFILE``.
    """
    violations: list[str] = []
    if response.status in ("ok", "warning") and not response.summary:
        violations.append("missing_summary")
    if response.status == "refusal" and response.error is None:
        violations.append("refusal_missing_error")
    if response.status == "error" and response.error is None:
        violations.append("error_missing_error_payload")
    return violations


__all__: list[str] = [
    "Artifact",
    "ArtifactType",
    "Citation",
    "CitationType",
    "ToolError",
    "ToolRequest",
    "ToolResponse",
    "ToolStatus",
    "check_envelope_convention",
]
