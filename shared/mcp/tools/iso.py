"""TRON ISO agent MCP tools (REQ-INIT-8 FR-5, EPIC-8.5; STORY-8.6.1/8.6.2).

Exposes TRON's six ISO agents as individually-addressable MCP tools so any
Spine subsystem — especially **Build** — can invoke them for early-detect
before sealing a ``BuildArtifact``. Core tool is :func:`iso_invoke`; one
convenience tool per ISO delegates to it with a fixed ``agent_name``.

Wrapper layer only — TRON classes under ``verify/tron/agents/`` are imported
lazily and called via their existing public API. Nothing here modifies TRON.

Cost attribution (FR-5): ``cost_attribution`` controls which subsystem the
audit/cost row is tagged with. ``pre_verify`` charges Build (early-detect
counts against the Build phase budget — no double charging when the canonical
Verify pass runs later); ``verify_phase`` charges Verify. See ``iso_README.md``.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from shared.mcp.schemas import ToolError, ToolResponse
from shared.mcp.tools import register_tool

logger = logging.getLogger(__name__)

# ── Agent registry ─────────────────────────────────────────────────────

AgentName = Literal[
    "SecurityISO", "BuilderISO", "QAISO",
    "PerformanceISO", "ComplianceISO", "DocumentationISO",
]
CostAttribution = Literal["pre_verify", "verify_phase"]
Severity = Literal["critical", "high", "medium", "low", "info"]

#: Module suffix within ``verify/tron/agents/`` for each ISO class.
_AGENT_MODULES: dict[str, str] = {
    "SecurityISO": "security_iso", "BuilderISO": "builder_iso",
    "QAISO": "qa_iso", "PerformanceISO": "performance_iso",
    "ComplianceISO": "compliance_iso", "DocumentationISO": "documentation_iso",
}

# ── Sub-models (promote to shared/schemas/verify/ in a follow-up story) ─


class CodeRegion(BaseModel):
    """Slice of source code the ISO agent should focus on."""
    model_config = ConfigDict(extra="forbid")
    file_path: str = Field(..., min_length=1, description="Repo-relative path.")
    line_start: int | None = Field(default=None, ge=1)
    line_end: int | None = Field(default=None, ge=1)


class Blueprint(BaseModel):
    """Spine mirror of TRON's Blueprint shape (canonical model lives in
    ``verify/tron/schemas/verification.py``; built lazily inside iso_invoke)."""
    model_config = ConfigDict(extra="forbid")
    file_patterns: list[str] = Field(default_factory=list)
    check_types: list[str] = Field(default_factory=list)
    not_in_scope: list[str] = Field(default_factory=list)


class Finding(BaseModel):
    """Spine envelope for one ISO finding (mirrors TRON ``FindingOutput``)."""
    model_config = ConfigDict(extra="forbid")
    severity: Severity
    file: str
    line: int | None = None
    rule: str
    message: str
    fix_hint: str | None = None
    confidence: float = Field(..., ge=0.0, le=1.0)
    layers_vouched: list[str] = Field(default_factory=list)


# ── Core tool: iso_invoke ──────────────────────────────────────────────


class IsoInvokeInput(BaseModel):
    """Inputs for :func:`iso_invoke` (REQ-INIT-8 FR-5).

    ``cost_attribution='pre_verify'`` charges Build; ``'verify_phase'``
    charges Verify. ``blueprint=None`` falls back to project's locked one.
    """
    model_config = ConfigDict(extra="forbid")
    project_id: str = Field(..., min_length=1)
    actor: str = Field(..., min_length=1, description="Role / subsystem invoking the agent.")
    agent_name: AgentName
    code_region: CodeRegion
    blueprint: Blueprint | None = None
    cost_attribution: CostAttribution = "pre_verify"


class IsoInvokeOutput(BaseModel):
    """Successful payload returned by :func:`iso_invoke`."""
    model_config = ConfigDict(extra="forbid")
    status: Literal["ok", "stub_implementation"]
    findings: list[Finding] = Field(default_factory=list)
    agent_invoked: str
    cost_usd: Decimal = Field(default=Decimal("0"))
    duration_ms: int = 0
    confidence_band: str | None = None
    audit_id: UUID = Field(default_factory=uuid4)


def _audit_from_iso_invoke(
    *, project_id: str, actor: str, agent_name: str,
    cost_usd: Decimal, cost_attribution: CostAttribution,
) -> UUID:
    """Build an AuditRecord for one iso_invoke call; return its event_uuid.
    Subsystem is chosen per ``cost_attribution`` so ``pre_verify`` charges
    Build (FR-5) and ``verify_phase`` charges Verify. Persisting (chain +
    psql write) is the downstream caller's job; we just return the
    event_uuid as the correlation handle.

    TODO(STORY-8.6.1): promote to ``AuditRecord.from_iso_invoke`` in
    ``shared/audit/audit_record.py`` once that module's classmethod API
    stabilizes (designed in parallel).
    """
    subsystem = "build" if cost_attribution == "pre_verify" else "verify"
    try:
        from shared.audit.audit_record import AuditRecord
        return AuditRecord(
            role=actor, subsystem=subsystem, action="iso_invoke", actor=actor,
            subject_type="iso_agent", subject_id=agent_name, cost_usd=cost_usd,
            metadata={"cost_attribution": cost_attribution, "agent_name": agent_name},
        ).event_uuid
    except Exception:  # pragma: no cover — audit must never break the tool path
        logger.exception("iso_invoke: audit record build failed; returning synthetic UUID")
        return uuid4()


def _try_import_agent(agent_name: str) -> type | None:
    """Lazily import the TRON agent class; None if unavailable (e.g.
    ``verify/`` not on PYTHONPATH yet — wired in STORY-8.2.x)."""
    suffix = _AGENT_MODULES.get(agent_name)
    if suffix is None:
        return None
    try:
        mod = __import__(f"verify.tron.agents.{suffix}", fromlist=[agent_name])
        return getattr(mod, agent_name, None)
    except Exception as exc:  # pragma: no cover
        logger.warning("iso_invoke: TRON agent %s not importable: %s", agent_name, exc)
        return None


@register_tool(
    name="iso_invoke", input_model=IsoInvokeInput, story="STORY-8.6.1",
    description="Invoke a specific TRON ISO agent on a code region (early-detect from Build).",
    tags=("verify", "iso", "early_detect"),
)
def iso_invoke(payload: IsoInvokeInput) -> ToolResponse:
    """Dispatch a code region to one TRON ISO agent.

    Pipeline: validate -> log -> lazy-import TRON agent class -> build
    Blueprint + invoke -> map ``FindingOutput`` -> Spine ``Finding`` -> write
    audit row (subsystem per ``cost_attribution``) -> return envelope.
    """
    logger.info("mcp_tool_call", extra={
        "tool": "iso_invoke", "project_id": payload.project_id,
        "actor": payload.actor, "agent_name": payload.agent_name,
        "cost_attribution": payload.cost_attribution,
    })
    agent_cls = _try_import_agent(payload.agent_name)
    if agent_cls is None:
        return ToolResponse(status="error", error=ToolError(
            code="tron_not_importable",
            message=(
                f"verify.tron.agents.{_AGENT_MODULES[payload.agent_name]}."
                f"{payload.agent_name} not importable — wire verify/ onto "
                "PYTHONPATH (STORY-8.2.x)."
            ),
            retryable=False,
        ))
    # TODO(STORY-8.6.2): wire to TRON's actual BaseISO.execute(blueprint,
    # file_contents). Needs (a) ISOConfig + secrets from project's locked
    # blueprint + keyvault, (b) file_contents loaded for code_region, (c) await
    # agent.execute(...) from sync MCP entry (asyncio.run/executor), (d) map
    # FindingBatch -> Finding[]. Returning a structurally-correct envelope so
    # the MCP contract is right.
    findings: list[Finding] = []
    cost_usd = Decimal("0")
    audit_id = _audit_from_iso_invoke(
        project_id=payload.project_id, actor=payload.actor,
        agent_name=payload.agent_name, cost_usd=cost_usd,
        cost_attribution=payload.cost_attribution,
    )
    result = IsoInvokeOutput(
        status="stub_implementation", findings=findings,
        agent_invoked=payload.agent_name, cost_usd=cost_usd,
        duration_ms=0, confidence_band=None, audit_id=audit_id,
    )
    return ToolResponse(
        status="stub_implementation",
        data=result.model_dump(mode="json"), audit_id=audit_id,
    )


# ── Per-agent convenience tools (generated via factory) ────────────────

class _PerAgentInput(BaseModel):
    """Shared input shape for the six convenience tools (no ``agent_name``)."""
    model_config = ConfigDict(extra="forbid")
    project_id: str = Field(..., min_length=1)
    actor: str = Field(..., min_length=1)
    code_region: CodeRegion
    blueprint: Blueprint | None = None
    cost_attribution: CostAttribution = "pre_verify"


def _make_convenience(agent_name: AgentName, tool_name: str, tag: str):
    """Build + register a thin convenience tool that delegates to iso_invoke."""
    def _tool(payload: _PerAgentInput) -> ToolResponse:
        return iso_invoke(IsoInvokeInput(
            project_id=payload.project_id, actor=payload.actor,
            agent_name=agent_name, code_region=payload.code_region,
            blueprint=payload.blueprint, cost_attribution=payload.cost_attribution,
        ))
    _tool.__name__ = tool_name
    _tool.__doc__ = f"Convenience wrapper: ``iso_invoke(agent_name={agent_name!r}, ...)``."
    return register_tool(
        name=tool_name, input_model=_PerAgentInput, story="STORY-8.6.1",
        description=f"Run {agent_name} (early-detect convenience wrapper).",
        tags=("verify", "iso", tag),
    )(_tool)


#: ``(AgentName, registered_tool_name, tag)`` for each convenience tool.
_CONVENIENCE_SPECS: tuple[tuple[AgentName, str, str], ...] = (
    ("SecurityISO", "security_iso_scan", "security"),
    ("BuilderISO", "builder_iso_scan", "builder"),
    ("QAISO", "qa_iso_scan", "qa"),
    ("PerformanceISO", "performance_iso_scan", "performance"),
    ("ComplianceISO", "compliance_iso_scan", "compliance"),
    ("DocumentationISO", "documentation_iso_scan", "documentation"),
)
# Register at import; each callable is also exposed module-globally under
# its tool name so tests/callers can import them directly.
for _agent, _name, _tag in _CONVENIENCE_SPECS:
    globals()[_name] = _make_convenience(_agent, _name, _tag)


__all__: list[str] = [
    "AgentName", "Blueprint", "CodeRegion", "CostAttribution", "Finding",
    "IsoInvokeInput", "IsoInvokeOutput", "Severity", "iso_invoke",
    *(name for _, name, _ in _CONVENIENCE_SPECS)]
