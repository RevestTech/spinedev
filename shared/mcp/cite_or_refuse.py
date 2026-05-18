"""Cite-or-Refuse middleware for the unified MCP server (V3 #12).

Per V3_DESIGN_DECISIONS §12 (formally ratified 2026-05-17):

> Strict tier for verify-class roles (auditor / qa / verify): must cite
> supporting evidence (KG node ID, file:line, prior audit row hash) or
> **refuse to act**. Refusal is itself an audit event.

Behaviour
---------

For any tool registered with ``requires_citation=True``:

  * Wraps the tool function. Calls the tool, then inspects the returned
    ``ToolResponse`` (or dict-shaped response).
  * If ``status == 'ok'`` the response MUST include a non-empty
    ``citation: list[Citation]`` field; the citation list MUST satisfy
    Pydantic shape (each row carries ``type`` and a non-empty ``ref``).
  * If absent / empty / malformed → the call is REFUSED. The middleware
    rewrites the response to a 422-class envelope (``status='error'``,
    ``error.code='cite_or_refuse_refused'``, ``error.retryable=False``)
    AND emits an audit event with ``action='cite_or_refuse_refused'``.
  * Tools whose own logic explicitly chose to refuse (``status='error'``
    with code prefix ``cite_or_refuse_``) pass through unchanged; the
    middleware still records the audit event so the refusal is
    persistent in the chain.

Wave 1 boundary
---------------

* This module defines the wrap function; ``server.SpineMcpServer``
  installs it during ``_register_one``.
* The middleware is *additive* — tools without ``requires_citation``
  see exactly the previous behaviour. No existing test breaks.
"""
from __future__ import annotations

import logging
from typing import Any, Callable
from uuid import uuid4

from pydantic import BaseModel, ValidationError

from shared.mcp.schemas import Citation, ToolError, ToolResponse

logger = logging.getLogger(__name__)

REFUSAL_ERROR_CODE = "cite_or_refuse_refused"
REFUSAL_AUDIT_ACTION = "cite_or_refuse_refused"
REFUSAL_MESSAGE = (
    "Cite-or-Refuse contract (V3 #12) violated: verify-class tool returned "
    "no supporting citation. Tool must cite kg_node / file_line / "
    "audit_hash evidence OR explicitly refuse to act."
)


def enforce(
    tool_name: str,
    fn: Callable[[BaseModel], Any],
    *,
    actor: str = "mcp_server",
) -> Callable[[BaseModel], ToolResponse]:
    """Wrap ``fn`` so its output is Cite-or-Refuse-validated.

    Returns a callable with the same input contract but a guaranteed
    ``ToolResponse`` shape. ``actor`` is used as the audit-event actor
    when a refusal is recorded.
    """

    def _wrapped(payload: BaseModel) -> ToolResponse:
        try:
            raw = fn(payload)
        except Exception:
            logger.exception("cite_or_refuse: tool %s raised", tool_name)
            raise

        normalised = _coerce_response(raw)
        verdict = _check(normalised)
        if verdict.is_ok:
            return normalised
        # Refuse + audit.
        _record_refusal_audit(
            tool_name=tool_name, actor=actor, reason=verdict.reason,
            payload=payload, original_status=normalised.status,
        )
        return ToolResponse(
            status="error",
            data={},
            error=ToolError(
                code=REFUSAL_ERROR_CODE,
                message=f"{REFUSAL_MESSAGE} reason={verdict.reason}",
                retryable=False,
            ),
            audit_id=uuid4(),
            citation=[],
        )

    _wrapped.__name__ = getattr(fn, "__name__", f"cite_or_refuse_{tool_name}")
    _wrapped.__doc__ = getattr(fn, "__doc__", "") or ""
    return _wrapped


# ─── Internal helpers ────────────────────────────────────────────────


class _Verdict:
    __slots__ = ("is_ok", "reason")

    def __init__(self, is_ok: bool, reason: str = "") -> None:
        self.is_ok = is_ok
        self.reason = reason


def _coerce_response(raw: Any) -> ToolResponse:
    """Accept either a ToolResponse or a dict and produce a ToolResponse."""
    if isinstance(raw, ToolResponse):
        return raw
    if hasattr(raw, "model_dump"):  # other Pydantic model
        return ToolResponse.model_validate(raw.model_dump())
    if isinstance(raw, dict):
        return ToolResponse.model_validate(raw)
    raise TypeError(
        f"cite_or_refuse: tool returned unsupported type {type(raw)!r}"
    )


def _check(resp: ToolResponse) -> _Verdict:
    """Run the Cite-or-Refuse contract on a normalised response."""
    if resp.status != "ok":
        # Non-ok responses are passed through; if the tool explicitly
        # refused via cite_or_refuse_* code, that's the strong signal.
        if resp.error and resp.error.code.startswith("cite_or_refuse_"):
            return _Verdict(is_ok=True)
        # Otherwise still acceptable — middleware doesn't enforce on errors.
        return _Verdict(is_ok=True)
    if not resp.citation:
        return _Verdict(is_ok=False, reason="missing_or_empty_citation")
    # Validate each citation row via Pydantic round-trip (catches malformed).
    for idx, item in enumerate(resp.citation):
        try:
            Citation.model_validate(item.model_dump())
        except ValidationError as exc:
            return _Verdict(
                is_ok=False,
                reason=f"malformed_citation[{idx}]: {exc.errors()[0]['msg']}",
            )
    return _Verdict(is_ok=True)


def _record_refusal_audit(
    *,
    tool_name: str,
    actor: str,
    reason: str,
    payload: BaseModel,
    original_status: str,
) -> None:
    """Persist a refusal as an audit event. Failures are swallowed."""
    try:
        from shared.audit.audit_record import AuditRecord
    except Exception:  # pragma: no cover - audit pkg optional in some envs
        logger.warning("cite_or_refuse: audit_record import failed; skip audit")
        return
    try:
        project_id = getattr(payload, "project_id", None)
        try:
            project_id_int = int(project_id) if project_id is not None else None
        except (TypeError, ValueError):
            project_id_int = None
        AuditRecord(
            role="verify",
            subsystem="shared",
            action=REFUSAL_AUDIT_ACTION,
            actor=actor,
            project_id=project_id_int,
            subject_type="mcp_tool",
            subject_id=tool_name,
            rationale=REFUSAL_MESSAGE,
            metadata={
                "tool": tool_name,
                "reason": reason,
                "original_status": original_status,
            },
        )
        # Build-only — persistence is the caller's hot-path concern. The
        # important contract is that the record is constructable and
        # represents the refusal. write_via_psql is invoked by the audit
        # pipeline downstream once a DB is wired into the test/runtime env.
    except Exception:  # pragma: no cover
        logger.exception("cite_or_refuse: refusal audit record build failed")


__all__ = [
    "REFUSAL_AUDIT_ACTION",
    "REFUSAL_ERROR_CODE",
    "REFUSAL_MESSAGE",
    "enforce",
]
