"""Auditor role runtime (Operating-loop slate #1 — D2 gap analysis).

Closes the ``not_implemented_in_runner`` branch in
``build/runtime/hub_role_runner.py`` for ``auditor`` (and
``security_engineer`` code review, which routes through the same
contract). Replaces the inline-LLM fallback in
``shared/api/routes/_post_ack.py`` so V3 #21 (all-AI-all-the-time with
audit chain) holds for code review.

Cite-or-Refuse contract (V3 #12)
--------------------------------

The auditor MUST either:

  * **Verdict** — return a ``status='ok'`` envelope with a non-empty
    ``citation`` list (``kg_node``, ``file_line``, or ``audit_hash``
    references that support the verdict), OR
  * **Refuse** — return a ``status='refusal'`` envelope with
    ``error.code = 'cite_or_refuse_refused'`` and a ``summary`` naming
    why the audit could not proceed.

Naked verdicts without citations are rejected by the
``shared.mcp.cite_or_refuse`` middleware when the response leaves the
MCP layer; this runtime emits the right envelope shape directly so the
contract is satisfied in-process too.

Design boundary
---------------

This runtime does NOT call an LLM directly. It composes an
``AuditorBriefing`` (charter + project context + evidence pointers)
and hands it to a caller-supplied ``audit_callable``. Production wires
``audit_callable`` to either the existing TRON verify pipeline or a
charter-grounded LLM driver; tests inject a stub. Provider-agnostic
matches the pattern in B6 / verify.charter_evals.harness.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from shared.mcp.schemas import Artifact, Citation, ToolError, ToolResponse

logger = logging.getLogger("spine.runtime.auditor_runner")


CHARTER_PATH = Path(__file__).resolve().parents[2] / "shared" / "charters" / "auditor.md"


@dataclass(frozen=True)
class AuditorBriefing:
    """Payload assembled for the auditor's decision pass."""

    project_uuid: str
    project_name: str
    role: str  # 'auditor' | 'security_engineer'
    artifact_subject: str  # what's being audited (file path / brief id / PR id)
    charter: str
    evidence_pointers: tuple[str, ...]  # kg_node ids / file:line / audit hashes


@dataclass(frozen=True)
class AuditorOutcome:
    """What an audit callable returns to the runtime."""

    verdict: str  # 'passed' | 'failed' | 'refused'
    summary: str  # one-line, role-readable
    citations: tuple[Citation, ...] = field(default_factory=tuple)
    findings_markdown: str = ""  # full report body
    refusal_reason: str | None = None


# Shape every audit_callable must satisfy.
AuditCallable = Callable[[AuditorBriefing], AuditorOutcome]


def _load_charter() -> str:
    """Read the auditor charter; fall back to a stub if absent."""
    try:
        return CHARTER_PATH.read_text(encoding="utf-8")
    except OSError:
        return "# auditor charter unavailable\n"


def _refusal_envelope(
    *,
    project_uuid: str,
    role: str,
    summary: str,
    reason: str,
    audit_id: str,
) -> ToolResponse:
    """V3 #30a refusal envelope shape."""
    return ToolResponse(
        status="refusal",
        summary=summary,
        next_actions=[
            "review evidence_pointers and re-dispatch with more context",
            "or escalate to a human auditor per #8 hybrid authority",
        ],
        artifacts=[
            Artifact(
                type="run_id",
                ref=audit_id,
                label=f"{role} refusal trace",
            ),
        ],
        data={
            "project_uuid": project_uuid,
            "role": role,
            "refusal_reason": reason,
        },
        error=ToolError(
            code="cite_or_refuse_refused",
            message=(
                "auditor refused per V3 #12 — see refusal_reason for "
                "the structured cause"
            ),
            retryable=False,
        ),
        citation=[],
    )


def _verdict_envelope(
    *,
    project_uuid: str,
    role: str,
    artifact_subject: str,
    outcome: AuditorOutcome,
    audit_id: str,
) -> ToolResponse:
    """V3 #30a + #12 verdict envelope (citations non-empty)."""
    next_actions: list[str] = []
    if outcome.verdict == "passed":
        next_actions.append("advance phase per phase_watcher")
    else:
        next_actions.append("dispatch engineer.remediate for findings")
    return ToolResponse(
        status="ok",
        summary=outcome.summary,
        next_actions=next_actions,
        artifacts=[
            Artifact(
                type="run_id",
                ref=audit_id,
                label=f"{role} verdict on {artifact_subject}",
            ),
        ],
        data={
            "project_uuid": project_uuid,
            "role": role,
            "verdict": outcome.verdict,
            "findings_markdown": outcome.findings_markdown,
            "artifact_subject": artifact_subject,
        },
        citation=list(outcome.citations),
    )


def run_auditor(
    project: dict[str, Any],
    *,
    role: str = "auditor",
    artifact_subject: str = "",
    evidence_pointers: tuple[str, ...] = (),
    audit_callable: AuditCallable | None = None,
) -> ToolResponse:
    """Dispatch an audit pass; returns a V3 #30a envelope.

    Cite-or-Refuse (#12) is enforced here regardless of what the
    callable returns:

      * No citations → refusal envelope.
      * Empty refusal reason → refusal envelope (generic reason).
      * Verdict 'refused' → refusal envelope.
      * Else verdict envelope with citations as supplied.

    ``audit_callable`` defaults to a deterministic stub that REFUSES
    when no evidence pointers are supplied — surfaces the contract
    visibly in environments without a real auditor backend.
    """
    role = role.strip() or "auditor"
    if role not in ("auditor", "security_engineer"):
        raise ValueError(f"unsupported auditor role: {role!r}")

    audit_id = f"audit_{uuid4().hex[:12]}"
    project_uuid = str(project.get("project_uuid", "")).strip()
    project_name = str(project.get("name", "")).strip()
    if not project_uuid:
        return _refusal_envelope(
            project_uuid="(unknown)",
            role=role,
            summary="auditor refusal — project_uuid missing",
            reason="missing_project_uuid",
            audit_id=audit_id,
        )

    callable_ = audit_callable or _stub_audit_callable

    briefing = AuditorBriefing(
        project_uuid=project_uuid,
        project_name=project_name,
        role=role,
        artifact_subject=artifact_subject or "(unspecified)",
        charter=_load_charter(),
        evidence_pointers=tuple(evidence_pointers),
    )

    try:
        outcome = callable_(briefing)
    except Exception as exc:  # noqa: BLE001 — surface as refusal not crash
        logger.exception("auditor_callable_raised")
        return _refusal_envelope(
            project_uuid=project_uuid,
            role=role,
            summary="auditor refusal — callable raised",
            reason=f"callable_exception: {exc.__class__.__name__}",
            audit_id=audit_id,
        )

    if outcome.verdict == "refused" or not outcome.citations:
        reason = (
            outcome.refusal_reason
            or ("no_citations" if not outcome.citations else "callable_refused")
        )
        return _refusal_envelope(
            project_uuid=project_uuid,
            role=role,
            summary=outcome.summary or "auditor refusal",
            reason=reason,
            audit_id=audit_id,
        )

    return _verdict_envelope(
        project_uuid=project_uuid,
        role=role,
        artifact_subject=briefing.artifact_subject,
        outcome=outcome,
        audit_id=audit_id,
    )


def _stub_audit_callable(briefing: AuditorBriefing) -> AuditorOutcome:
    """Deterministic stub. Refuses when no evidence pointers — making
    the Cite-or-Refuse contract visible in any environment that hasn't
    wired a real auditor backend yet."""
    if not briefing.evidence_pointers:
        return AuditorOutcome(
            verdict="refused",
            summary=(
                f"{briefing.role} stub refused — no evidence pointers "
                "supplied for the audit"
            ),
            refusal_reason="no_evidence_pointers",
        )
    citations = tuple(
        Citation(
            type="kg_node" if pointer.startswith("node-") else "file_line",
            ref=pointer,
        )
        for pointer in briefing.evidence_pointers
    )
    return AuditorOutcome(
        verdict="passed",
        summary=(
            f"{briefing.role} stub verdict — {len(citations)} citation(s) "
            f"recorded for {briefing.artifact_subject}"
        ),
        citations=citations,
        findings_markdown=(
            f"# Audit verdict — {briefing.role}\n\n"
            f"- subject: {briefing.artifact_subject}\n"
            f"- citations: {len(citations)}\n"
        ),
    )


__all__ = [
    "AuditCallable",
    "AuditorBriefing",
    "AuditorOutcome",
    "run_auditor",
]
