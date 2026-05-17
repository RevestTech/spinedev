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

import asyncio
import logging
import os
import time
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from shared.mcp.schemas import ToolError, ToolResponse
from shared.mcp.tools import register_tool

logger = logging.getLogger(__name__)

#: 1 MiB hard cap per file passed to TRON (matches verify.py's cap).
_MAX_FILE_BYTES = 1 * 1024 * 1024

#: TRON SeverityLevel.value → Spine Severity literal. Matches verify._TRON_SEVERITY_MAP.
_TRON_SEVERITY_MAP: dict[str, str] = {
    "critical": "critical", "high": "high", "medium": "medium",
    "low": "low", "info": "info",
}

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
    """Successful payload returned by :func:`iso_invoke`. ``status='degraded'``
    means the agent ran but a sub-layer (e.g. deterministic tool) was skipped
    — findings are still real but partial; ``confidence_band`` describes the
    Platt-calibration bucket if TRON computed one."""
    model_config = ConfigDict(extra="forbid")
    status: Literal["ok", "degraded"]
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


def _tron_secrets_from_env() -> dict[str, str]:
    """``ANTHROPIC_API_KEY`` / ``OPENAI_API_KEY`` env → TRON keyvault keys.

    Mirrors verify._tron_secrets_from_env (keeping a local copy avoids a
    circular import: verify.py imports from this module)."""
    out: dict[str, str] = {}
    if ak := os.environ.get("ANTHROPIC_API_KEY", "").strip():
        out["llm/anthropic-key"] = ak
    if ok := os.environ.get("OPENAI_API_KEY", "").strip():
        out["llm/openai-key"] = ok
    return out


def _load_region_contents(region: "CodeRegion") -> dict[str, str]:
    """Read the CodeRegion's file from disk; optionally slice to ``[line_start,
    line_end]``. Returns ``{path: source}`` with a 1 MiB cap per file so the
    LLM context stays bounded. Empty dict on missing/unreadable file."""
    p = Path(region.file_path)
    if not p.is_file():
        logger.warning("iso_invoke: source file missing: %s", region.file_path)
        return {}
    try:
        data = p.read_bytes()
    except Exception as exc:  # noqa: BLE001
        logger.warning("iso_invoke: read failed %s: %s", region.file_path, exc)
        return {}
    if len(data) > _MAX_FILE_BYTES:
        data = data[:_MAX_FILE_BYTES] + b"\n# [spine: file truncated at 1 MiB]\n"
    text = data.decode("utf-8", errors="replace")
    if region.line_start is not None or region.line_end is not None:
        lines = text.splitlines(keepends=True)
        lo = max(0, (region.line_start or 1) - 1)
        hi = region.line_end if region.line_end is not None else len(lines)
        text = "".join(lines[lo:hi])
    return {region.file_path: text}


def _build_tron_blueprint(payload_blueprint: "Blueprint | None",
                          region: "CodeRegion", agent_name: str) -> Any:
    """Construct TRON's ``Blueprint`` from the Spine-facing one + the region.

    If the caller supplied ``blueprint=None`` we synthesise a minimal one
    scoped to the region's file. TRON's ``BlueprintScope.check_types`` requires
    valid ``VulnerabilityType`` enum members — we drop anything unknown rather
    than crashing the agent boot.
    """
    from verify.tron.schemas.verification import (
        Blueprint as TronBlueprint,
        BlueprintScope,
        VerificationMethod,
        VulnerabilityType,
    )
    valid_checks = {v.value for v in VulnerabilityType}
    raw_checks = list(payload_blueprint.check_types) if payload_blueprint else []
    typed_checks = [VulnerabilityType(c) for c in raw_checks if c in valid_checks]
    file_patterns = (list(payload_blueprint.file_patterns)
                     if payload_blueprint and payload_blueprint.file_patterns
                     else [region.file_path])
    not_in_scope = list(payload_blueprint.not_in_scope) if payload_blueprint else []
    scope = BlueprintScope(
        file_patterns=file_patterns,
        check_types=typed_checks,
        languages=[],  # let the agent infer from the file extension
    )
    return TronBlueprint(
        id=f"spine-iso-{agent_name.lower()}-{uuid4().hex[:8]}",
        name=f"Spine {agent_name} early-detect on {region.file_path}",
        description=f"MCP iso_invoke for {agent_name} on {region.file_path}",
        scope=scope,
        not_in_scope=not_in_scope,
        verification_method=VerificationMethod.DETERMINISTIC_CROSSCHECK,
    )


def _map_tron_finding(tf: Any) -> Finding:
    """Map TRON ``FindingOutput`` → Spine ``Finding``. Mirrors verify._map_tron_finding
    (kept local to avoid the circular import; the two should stay in sync)."""
    severity_raw = getattr(getattr(tf, "severity", None), "value", "info")
    rule_raw = getattr(getattr(tf, "vulnerability_type", None), "value", "other")
    conf = getattr(tf, "calibrated_confidence", None) or getattr(tf, "confidence", 0.0)
    cv = getattr(getattr(tf, "cross_validation_status", None), "value", "")
    layers = (["deterministic_scanners"]
              if getattr(tf, "deterministic_tool_confirmed", False) else []
              ) + ["iso_swarm"]
    if cv == "confirmed":
        layers.append("cross_llm_validation")
    return Finding(
        severity=_TRON_SEVERITY_MAP.get(severity_raw, "info"),  # type: ignore[arg-type]
        file=getattr(tf, "file_path", "<unknown>"),
        line=getattr(tf, "line_number", None),
        rule=rule_raw, message=getattr(tf, "description", "") or "",
        fix_hint=getattr(tf, "fix_suggestion", None),
        confidence=float(max(0.0, min(1.0, conf))),
        layers_vouched=layers,
    )


def _run_async(coro: Any) -> Any:
    """Sync→async bridge for the MCP entrypoint. Mirrors verify._run_async."""
    try:
        return asyncio.run(coro)
    except RuntimeError:  # pragma: no cover — only when an outer loop runs
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()


def _build_iso_agent(agent_cls: type, agent_name: str,
                     secrets: dict[str, str]) -> Any:
    """Instantiate an ISO agent with sensible defaults. Mirrors the per-agent
    factory in verify._register_default_iso_agents but for a single agent."""
    from verify.tron.agents.base import ISOConfig, ISOSpecialization, LLMProvider
    from verify.tron.infra.llm.client import DEFAULT_ANTHROPIC_FAST_MODEL
    provider = (LLMProvider.ANTHROPIC if "llm/anthropic-key" in secrets
                else LLMProvider.OPENAI)
    model = (DEFAULT_ANTHROPIC_FAST_MODEL if provider == LLMProvider.ANTHROPIC
             else "gpt-4o")
    # Specialization is the agent_name minus the "ISO" suffix.
    spec_name = agent_name.replace("ISO", "").upper()
    tools_required: tuple[str, ...] = (
        ("bandit", "semgrep") if agent_name == "SecurityISO" else ()
    )
    cfg = ISOConfig(
        specialization=getattr(ISOSpecialization, spec_name),
        agent_id=f"{spec_name.lower()}-iso-spine-mcp",
        model_provider=provider, model_name=model,
        tools_required=tools_required,
        prompt_template_id=f"{spec_name.lower()}-v1",
    )
    return agent_cls(config=cfg, secrets=secrets)


def _error(*, code: str, message: str, retryable: bool,
           audit_id: UUID) -> ToolResponse:
    err = ToolError(code=code, message=message, retryable=retryable)
    return ToolResponse(status="error", audit_id=audit_id, error=err)


@register_tool(
    name="iso_invoke", input_model=IsoInvokeInput, story="STORY-8.6.2",
    description="Invoke a specific TRON ISO agent on a code region (early-detect from Build).",
    tags=("verify", "iso", "early_detect"),
)
def iso_invoke(payload: IsoInvokeInput) -> ToolResponse:
    """Dispatch a code region to one TRON ISO agent.

    Pipeline: validate -> log -> lazy-import TRON agent class -> load file
    contents from CodeRegion -> build Blueprint -> ``await agent.execute(...)``
    -> map ``FindingBatch`` -> Spine ``Finding[]`` -> write audit row
    (subsystem per ``cost_attribution``) -> return envelope.
    """
    started = time.perf_counter()
    logger.info("mcp_tool_call", extra={
        "tool": "iso_invoke", "project_id": payload.project_id,
        "actor": payload.actor, "agent_name": payload.agent_name,
        "cost_attribution": payload.cost_attribution,
    })

    # 1. Lazy-import the agent class (verify/ may not be on PYTHONPATH yet).
    agent_cls = _try_import_agent(payload.agent_name)
    if agent_cls is None:
        audit_id = _audit_from_iso_invoke(
            project_id=payload.project_id, actor=payload.actor,
            agent_name=payload.agent_name, cost_usd=Decimal("0"),
            cost_attribution=payload.cost_attribution)
        return _error(
            code="tron_not_importable",
            message=(f"verify.tron.agents.{_AGENT_MODULES[payload.agent_name]}."
                     f"{payload.agent_name} not importable — wire verify/ onto "
                     "PYTHONPATH (STORY-8.2.x)."),
            retryable=False, audit_id=audit_id)

    # 2. Need at least one LLM key — TRON ISO agents are LLM-driven.
    secrets = _tron_secrets_from_env()
    if not secrets:
        audit_id = _audit_from_iso_invoke(
            project_id=payload.project_id, actor=payload.actor,
            agent_name=payload.agent_name, cost_usd=Decimal("0"),
            cost_attribution=payload.cost_attribution)
        return _error(
            code="tron_keys_missing",
            message=("Neither ANTHROPIC_API_KEY nor OPENAI_API_KEY in env — "
                     "TRON ISO agents require at least one LLM provider key."),
            retryable=False, audit_id=audit_id)

    # 3. Load the file slice and build TRON's Blueprint.
    file_contents = _load_region_contents(payload.code_region)
    if not file_contents:
        audit_id = _audit_from_iso_invoke(
            project_id=payload.project_id, actor=payload.actor,
            agent_name=payload.agent_name, cost_usd=Decimal("0"),
            cost_attribution=payload.cost_attribution)
        return _error(
            code="no_source_files",
            message=(f"Could not read code_region.file_path="
                     f"{payload.code_region.file_path!r} — file missing or "
                     "unreadable."),
            retryable=False, audit_id=audit_id)

    try:
        tron_blueprint = _build_tron_blueprint(
            payload.blueprint, payload.code_region, payload.agent_name)
    except Exception as exc:
        audit_id = _audit_from_iso_invoke(
            project_id=payload.project_id, actor=payload.actor,
            agent_name=payload.agent_name, cost_usd=Decimal("0"),
            cost_attribution=payload.cost_attribution)
        return _error(
            code="blueprint_build_failed",
            message=f"Failed to construct TRON Blueprint: {exc}",
            retryable=False, audit_id=audit_id)

    # 4. Instantiate the agent and run it.
    try:
        agent = _build_iso_agent(agent_cls, payload.agent_name, secrets)
    except Exception as exc:
        audit_id = _audit_from_iso_invoke(
            project_id=payload.project_id, actor=payload.actor,
            agent_name=payload.agent_name, cost_usd=Decimal("0"),
            cost_attribution=payload.cost_attribution)
        return _error(
            code="agent_init_failed",
            message=f"Failed to instantiate {payload.agent_name}: {exc}",
            retryable=False, audit_id=audit_id)

    try:
        batch = _run_async(agent.execute(tron_blueprint, file_contents))
    except Exception as exc:
        audit_id = _audit_from_iso_invoke(
            project_id=payload.project_id, actor=payload.actor,
            agent_name=payload.agent_name, cost_usd=Decimal("0"),
            cost_attribution=payload.cost_attribution)
        return _error(
            code="agent_execution_failed",
            message=f"{payload.agent_name}.execute raised: {exc}",
            retryable=True, audit_id=audit_id)

    # 5. Map FindingBatch → Spine Finding[]; pull cost from AgentMetrics.
    tron_findings = list(getattr(batch, "findings", []) or [])
    findings = [_map_tron_finding(tf) for tf in tron_findings]
    metrics = getattr(agent, "metrics", None)
    raw_cost = getattr(metrics, "llm_cost_usd", 0.0) if metrics else 0.0
    try:
        cost_usd = Decimal(str(raw_cost or 0))
    except Exception:
        cost_usd = Decimal("0")
    duration_ms = int((time.perf_counter() - started) * 1000)
    # If the agent recorded errors mid-flight the result is real but partial.
    status: Literal["ok", "degraded"] = (
        "degraded" if (metrics and getattr(metrics, "errors", [])) else "ok"
    )

    audit_id = _audit_from_iso_invoke(
        project_id=payload.project_id, actor=payload.actor,
        agent_name=payload.agent_name, cost_usd=cost_usd,
        cost_attribution=payload.cost_attribution)

    result = IsoInvokeOutput(
        status=status, findings=findings,
        agent_invoked=payload.agent_name, cost_usd=cost_usd,
        duration_ms=duration_ms, confidence_band=None, audit_id=audit_id,
    )
    return ToolResponse(status="ok", data=result.model_dump(mode="json"),
                        audit_id=audit_id)


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
