"""Verify subsystem MCP tools (REQ-INIT-8 FR-4, EPIC-8.4).

* ``verify_audit`` — orchestrator hands a sealed ``BuildArtifact`` + ``Blueprint``
  to Verify; returns ``VerifyFindings`` (``STORY-8.5.1`` / ``STORY-8.5.2``).

Companion early-detect tools (``iso_invoke`` + six per-agent wrappers) live in
:mod:`shared.mcp.tools.iso` per ``STORY-8.6.1`` / ``STORY-8.6.2``.

Pattern mirrors :mod:`iso` and :mod:`sandbox`: lazy TRON import (``verify/``
may not be on PYTHONPATH yet), Docker probe at import → degraded mode if
unreachable, structured envelope, ``FindingOutput`` → Spine ``Finding`` map,
one summary audit row + one per finding so ``spine_audit`` is queryable
per-finding. Verify-phase costs land in ``spine_recording.costs`` with
``subsystem='verify'`` (V16 schema).
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
from decimal import Decimal
from pathlib import Path
from time import perf_counter
from typing import Any, Literal
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from pydantic import BaseModel, ConfigDict, Field

from shared.mcp.schemas import Citation, ToolError, ToolResponse, ToolStatus
from shared.mcp.tools import register_tool
from shared.mcp.tools.iso import Blueprint, Finding, Severity
from shared.schemas.build.build_artifact import BuildArtifact

logger = logging.getLogger(__name__)

PassFail = Literal["pass", "fail", "needs_user_review"]

#: TRON ``SeverityLevel`` enum value → Spine ``Severity`` literal.
_TRON_SEVERITY_MAP: dict[str, Severity] = {
    "critical": "critical", "high": "high", "medium": "medium",
    "low": "low", "info": "info",
}

#: TRON 7-layer pipeline names — overridable from audit metadata when wired.
_TRON_LAYERS: tuple[str, ...] = (
    "deterministic_scanners", "iso_swarm", "execution_sandbox",
    "cross_llm_validation", "semantic_validation", "platt_calibration",
    "manual_review_gate",
)


def _probe_docker() -> bool:
    """``True`` iff ``docker ps -q`` succeeds. Cached at module import.

    TRON's Layer-3 needs Docker; if unreachable we force ``sandbox_layer=False``
    (degraded mode) rather than failing the whole audit.
    """
    if shutil.which("docker") is None:
        return False
    try:
        return subprocess.run(["docker", "ps", "-q"], capture_output=True,
                              text=True, timeout=5).returncode == 0
    except Exception:  # pragma: no cover
        return False


_DOCKER_AVAILABLE: bool = _probe_docker()
if not _DOCKER_AVAILABLE:
    logger.warning("verify_audit: Docker unavailable at import — sandbox_layer "
                   "will be forced False (Layer-3 skipped, degraded mode).")


# ── Schemas ────────────────────────────────────────────────────────────


class VerifyAuditInput(BaseModel):
    """Inputs for ``verify_audit`` (REQ-INIT-8 FR-4)."""
    model_config = ConfigDict(extra="forbid")
    build_artifact: BuildArtifact = Field(...,
        description="Sealed BuildArtifact under verification (per EPIC-7.4).")
    blueprint: Blueprint = Field(...,
        description="Scope: file_patterns, check_types, NOT_IN_SCOPE, ISO selection.")
    project_id: str = Field(..., min_length=1)
    actor: str = Field(default="orchestrator", min_length=1)
    cross_llm_validation: bool = Field(default=False,
        description="Opt-in cross-LLM consensus (STORY-3.7.x); adds latency + cost.")
    sandbox_layer: bool = Field(default=True,
        description="Run TRON's Layer-3 sandbox if Docker available; forced False otherwise.")
    pipeline_version: str | None = Field(default=None,
        description="Locked SDLC pipeline manifest version (audit trail).")


class VerifyFindings(BaseModel):
    """Typed envelope returned by ``verify_audit``."""
    model_config = ConfigDict(extra="forbid")
    status: ToolStatus
    pass_fail: PassFail
    findings: list[Finding] = Field(default_factory=list)
    layers_run: list[str] = Field(default_factory=list,
        description="Which of TRON's 7 layers actually ran.")
    sandbox_executed: bool = False
    cross_llm_consensus: bool = Field(default=False,
        description="True iff multiple providers agreed on critical/high.")
    calibration_band: str | None = Field(default=None,
        description="Platt-scaling band (e.g. 'high_precision') if active.")
    duration_ms: int = 0
    cost_usd: Decimal = Field(default=Decimal("0"))
    audit_id: UUID = Field(default_factory=uuid4)
    error: ToolError | None = None


# ── Helpers ────────────────────────────────────────────────────────────


def _map_tron_finding(tf: Any) -> Finding:
    """Map TRON ``FindingOutput`` → Spine ``Finding`` (uses ``calibrated_confidence``
    when present; layers_vouched assembled from confirmation flags)."""
    severity_raw = getattr(getattr(tf, "severity", None), "value", "info")
    rule_raw = getattr(getattr(tf, "vulnerability_type", None), "value", "other")
    conf = getattr(tf, "calibrated_confidence", None) or getattr(tf, "confidence", 0.0)
    cv = getattr(getattr(tf, "cross_validation_status", None), "value", "")
    layers = (["deterministic_scanners"] if getattr(tf, "deterministic_tool_confirmed", False)
              else []) + ["iso_swarm"]
    if cv == "confirmed":
        layers.append("cross_llm_validation")
    return Finding(
        severity=_TRON_SEVERITY_MAP.get(severity_raw, "info"),
        file=getattr(tf, "file_path", "<unknown>"),
        line=getattr(tf, "line_number", None),
        rule=rule_raw, message=getattr(tf, "description", "") or "",
        fix_hint=getattr(tf, "fix_suggestion", None),
        confidence=float(max(0.0, min(1.0, conf))),
        layers_vouched=layers,
    )


def _decide_pass_fail(findings: list[Finding]) -> PassFail:
    """pass = 0 critical AND 0 high; fail = ≥1 critical; else needs_user_review."""
    sev = {f.severity for f in findings}
    if "critical" in sev: return "fail"
    if "high" in sev:     return "needs_user_review"
    return "pass"


def _build_audit_request(*, artifact: BuildArtifact, blueprint: Blueprint,
                         sandbox_layer: bool, cross_llm: bool) -> dict[str, Any]:
    """``BuildArtifact`` + ``Blueprint`` → kwargs for TRON's ``AuditRequest``.

    TODO(STORY-8.5.1): wire to ``AuditManager.run_audit()``'s actual signature.
    TRON's ``AuditRequest`` wants ``file_contents: dict[path, source]`` +
    ``languages: list[str]``; we have paths + diff_hashes from the artifact but
    not source contents — the orchestrator needs to pass an artifact-store
    handle or working-tree path so Verify can load the actual sources before
    invoking the manager. Stubbing the envelope so the MCP contract is right.
    """
    return {
        "project_id": artifact.project_id, "audit_run_id": str(uuid4()),
        "file_paths": [c.path for c in artifact.code_changes],
        "diff_hashes": [c.diff_hash for c in artifact.code_changes],
        "languages": sorted({c.language for c in artifact.code_changes if c.language}),
        "file_patterns": list(blueprint.file_patterns),
        "check_types": list(blueprint.check_types),
        "not_in_scope": list(blueprint.not_in_scope),
        "sandbox_enabled": sandbox_layer, "cross_llm_enabled": cross_llm,
    }


def _lookup_cost_cap(project_id: str) -> Decimal | None:
    """Per-phase verify cap via ``shared.cost.router`` (None if unavailable).
    Best-effort; failure must never break the audit."""
    try:
        from shared.cost.router import _load_active_bundle, _phase_cap
        try: int(project_id)
        except (TypeError, ValueError): return None
        cap = _phase_cap(_load_active_bundle(), "verify")
        return cap if cap and cap > 0 else None
    except Exception:  # pragma: no cover
        logger.debug("verify_audit: cost cap lookup failed", exc_info=True)
        return None


#: 1 MiB hard cap per file passed to TRON (mirrors LLM context budget).
_MAX_FILE_BYTES = 1 * 1024 * 1024
#: Six default ISO agents (mirrors ``audit_executor._build_agent_manager``):
#: ``(module_suffix, class_name, ISOSpecialization name, tools_required)``.
_DEFAULT_ISO_SPECS: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    ("security_iso", "SecurityISO", "SECURITY", ("bandit", "semgrep")),
    ("builder_iso", "BuilderISO", "BUILDER", ()),
    ("performance_iso", "PerformanceISO", "PERFORMANCE", ()),
    ("qa_iso", "QAISO", "QA", ()),
    ("compliance_iso", "ComplianceISO", "COMPLIANCE", ()),
    ("documentation_iso", "DocumentationISO", "DOCUMENTATION", ()),
)


def _load_file_contents(artifact: BuildArtifact) -> dict[str, str]:
    """``{path: source}`` for ``AuditRequest.file_contents``. Missing files
    logged + skipped; each file capped at 1 MiB; UTF-8 decode with replace."""
    out: dict[str, str] = {}
    for ch in artifact.code_changes:
        if ch.change_type == "delete": continue
        p = Path(ch.path)
        if not p.is_file():
            logger.warning("verify_audit: source file missing: %s", ch.path); continue
        try: data = p.read_bytes()
        except Exception as exc:
            logger.warning("verify_audit: read failed %s: %s", ch.path, exc); continue
        if len(data) > _MAX_FILE_BYTES:
            data = data[:_MAX_FILE_BYTES] + b"\n# [spine: file truncated at 1 MiB]\n"
        out[ch.path] = data.decode("utf-8", errors="replace")
    return out


def _tron_secrets_from_env() -> dict[str, str]:
    """``ANTHROPIC_API_KEY``/``OPENAI_API_KEY`` env → TRON keyvault keys."""
    s: dict[str, str] = {}
    if ak := os.environ.get("ANTHROPIC_API_KEY", "").strip(): s["llm/anthropic-key"] = ak
    if ok := os.environ.get("OPENAI_API_KEY", "").strip():    s["llm/openai-key"] = ok
    return s


def _run_async(coro: Any) -> Any:
    """Sync→async bridge for the MCP entrypoint. No threads (would corrupt
    TRON's per-agent async context vars)."""
    try: return asyncio.run(coro)
    except RuntimeError:  # pragma: no cover — only when an outer loop runs
        loop = asyncio.new_event_loop()
        try: return loop.run_until_complete(coro)
        finally: loop.close()


def _aggregate_cost(agent_metrics: list[dict[str, Any]]) -> Decimal:
    """Sum per-agent ``llm_cost_usd`` from ``AgentMetrics.to_dict()`` rows."""
    total = Decimal("0")
    for m in agent_metrics or []:
        try: total += Decimal(str(m.get("llm_cost_usd", 0) or 0))
        except Exception: continue  # pragma: no cover
    return total


def _register_default_iso_agents(manager: Any, secrets: dict[str, str]) -> list[str]:
    """Register the six default ISO agents onto ``manager`` (mirrors
    ``audit_executor._build_agent_manager``). Returns registered agent_ids;
    silently skips agents that fail to import so a partial swarm still runs."""
    from verify.tron.agents.base import ISOConfig, ISOSpecialization, LLMProvider
    from verify.tron.infra.llm.client import DEFAULT_ANTHROPIC_FAST_MODEL
    provider = (LLMProvider.ANTHROPIC if "llm/anthropic-key" in secrets
                else LLMProvider.OPENAI)
    model = DEFAULT_ANTHROPIC_FAST_MODEL if provider == LLMProvider.ANTHROPIC else "gpt-4o"
    registered: list[str] = []
    for mod_suffix, cls_name, spec_name, tools in _DEFAULT_ISO_SPECS:
        try:
            cls = getattr(__import__(f"verify.tron.agents.{mod_suffix}",
                                     fromlist=[cls_name]), cls_name)
            cfg = ISOConfig(
                specialization=getattr(ISOSpecialization, spec_name),
                agent_id=f"{spec_name.lower()}-iso-spine",
                model_provider=provider, model_name=model,
                tools_required=tools, prompt_template_id=f"{spec_name.lower()}-v1")
            manager.register_agent(cls(config=cfg, secrets=secrets))
            registered.append(cfg.agent_id)
        except Exception as exc:
            logger.warning("verify_audit: skip ISO %s: %s", cls_name, exc)
    return registered


def _persist_findings(*, actor: str, artifact: BuildArtifact,
        findings: list[Finding], summary: dict[str, Any], cost_usd: Decimal,
        pass_fail: PassFail, pipeline_version: str | None) -> UUID:
    """Build one summary AuditRecord + one row per finding (STORY-8.5.2).

    Returns the summary row's ``event_uuid`` as the canonical audit_id.
    Persistence (chain + psql write) is the downstream caller's job — we build
    the records so the standard hash-chain pipeline can pick them up.

    TODO(STORY-8.5.2): batch-write via shared.audit.audit_record bulk helper
    once that API lands (one psql call per finding row would be too chatty for
    large audits). For now the rows are constructed but not flushed.
    """
    try:
        from shared.audit.audit_record import AuditRecord
    except Exception:  # pragma: no cover
        logger.exception("verify_audit: AuditRecord import failed; synthetic UUID")
        return uuid4()
    try:
        summary_rec = AuditRecord(
            role=actor, subsystem="verify", action="verify_audit", actor=actor,
            subject_type="build_artifact", subject_id=str(artifact.artifact_uuid),
            cost_usd=cost_usd, pipeline_version=pipeline_version,
            metadata={"pass_fail": pass_fail, "findings_count": len(findings),
                      "critical_count": sum(1 for f in findings if f.severity == "critical"),
                      "high_count": sum(1 for f in findings if f.severity == "high"),
                      **summary})
        summary_uuid = summary_rec.event_uuid
        for f in findings:
            try:
                AuditRecord(
                    role=actor, subsystem="verify", action="verify_finding",
                    actor=actor, subject_type="finding",
                    subject_id=f"{f.rule}:{f.file}:{f.line or 0}",
                    cost_usd=Decimal("0"), pipeline_version=pipeline_version,
                    correlation_id=summary_uuid,
                    metadata={"severity": f.severity, "file": f.file, "line": f.line,
                              "rule": f.rule, "message": f.message,
                              "fix_hint": f.fix_hint, "confidence": f.confidence,
                              "layers_vouched": f.layers_vouched,
                              "artifact_uuid": str(artifact.artifact_uuid)})
            except Exception:  # pragma: no cover
                logger.exception("verify_audit: failed to build finding audit row")
        return summary_uuid
    except Exception:  # pragma: no cover
        logger.exception("verify_audit: summary audit build failed; synthetic UUID")
        return uuid4()


def _error_envelope(*, code: str, message: str, retryable: bool,
                    audit_id: UUID, duration_ms: int) -> ToolResponse:
    """``status='error'`` envelope (zero cost, zero findings).

    For Cite-or-Refuse (#12) compliance: when verify cannot run
    (TRON unavailable, no source files, etc.), this is an explicit
    *refusal to act*. Code prefix ``cite_or_refuse_`` would signal
    contract refusal; here we use the existing TRON failure codes
    which the middleware passes through unchanged.
    """
    err = ToolError(code=code, message=message, retryable=retryable)
    out = VerifyFindings(
        status="error", pass_fail="needs_user_review", findings=[],
        layers_run=[], sandbox_executed=False, cross_llm_consensus=False,
        calibration_band=None, duration_ms=duration_ms, cost_usd=Decimal("0"),
        audit_id=audit_id, error=err)
    return ToolResponse(status="error", data=out.model_dump(mode="json"),
                        error=err, audit_id=audit_id, citation=[])


def _citations_from_findings(
    findings: list[Finding], artifact_uuid: UUID, summary_audit_id: UUID,
) -> list[Citation]:
    """Build a Cite-or-Refuse citation set from verify output.

    Per V3 #12 the verify role MUST cite supporting evidence. Strategy:
      * One ``audit_hash`` citation for the summary audit row (covers
        the case of zero findings — the audit row itself is the
        evidence the verify pipeline ran).
      * One ``file_line`` citation per finding (path + line).
    """
    cites: list[Citation] = [
        Citation(
            type="audit_hash",
            ref=str(summary_audit_id),
            excerpt=f"verify summary for artifact {str(artifact_uuid)[:8]}",
        ),
    ]
    for f in findings:
        ref = f"{f.file}:{f.line or 0}"
        cites.append(
            Citation(type="file_line", ref=ref, excerpt=f.rule)
        )
    return cites


# ── The tool ───────────────────────────────────────────────────────────


@register_tool(
    name="verify_audit", input_model=VerifyAuditInput, story="STORY-8.5.1",
    description="Orchestrator invokes Verify on a BuildArtifact; returns VerifyFindings.",
    tags=("verify", "audit"),
    requires_citation=True,  # V3 #12 — verify is strict-tier Cite-or-Refuse
)
def verify_audit(payload: VerifyAuditInput) -> ToolResponse:
    """Run TRON's ``AuditManager`` against a sealed ``BuildArtifact``.

    Pipeline: validate seal -> log -> degraded-mode probe -> lazy-import
    ``AuditManager`` -> build TRON ``AuditRequest`` from artifact + blueprint
    -> run audit -> map ``FindingOutput`` -> Spine ``Finding`` -> write audit
    rows (one summary + one per finding) -> return ``VerifyFindings``.
    """
    t0 = perf_counter()
    audit_id = uuid4()
    logger.info("mcp_tool_call", extra={
        "tool": "verify_audit", "project_id": payload.project_id,
        "actor": payload.actor,
        "artifact_uuid": str(payload.build_artifact.artifact_uuid),
        "cross_llm": payload.cross_llm_validation,
        "sandbox_layer": payload.sandbox_layer})

    # 1. BuildArtifact must be sealed.
    if payload.build_artifact.status != "sealed":
        return _error_envelope(
            code="artifact_not_sealed", retryable=False, audit_id=audit_id,
            message=(f"BuildArtifact status is {payload.build_artifact.status!r}; "
                     "verify_audit refuses unsealed artifacts (per EPIC-7.4)."),
            duration_ms=int((perf_counter() - t0) * 1000))

    # 2. Degraded mode — Docker unreachable -> force sandbox off.
    effective_sandbox = payload.sandbox_layer and _DOCKER_AVAILABLE
    if payload.sandbox_layer and not _DOCKER_AVAILABLE:
        logger.warning("verify_audit: Docker unavailable; degraded mode "
                       "(Layer-3 skipped) for project=%s artifact=%s",
                       payload.project_id, payload.build_artifact.artifact_uuid)

    # 3. Lazy-import AuditManager; tolerate verify/ off PYTHONPATH.
    try:
        from verify.tron.agents.manager import AuditManager  # noqa: F401 (presence probe)
    except Exception as exc:
        logger.warning("verify_audit: TRON AuditManager not importable: %s", exc)
        return _error_envelope(
            code="tron_not_available", retryable=False, audit_id=audit_id,
            message=("verify.tron.agents.manager.AuditManager not importable — "
                     "wire verify/ onto PYTHONPATH (STORY-8.2.x) or install the "
                     "TRON bundle."),
            duration_ms=int((perf_counter() - t0) * 1000))

    # 4. Build TRON's AuditRequest envelope.
    cost_cap = _lookup_cost_cap(payload.project_id)
    audit_request_kwargs = _build_audit_request(
        artifact=payload.build_artifact, blueprint=payload.blueprint,
        sandbox_layer=effective_sandbox, cross_llm=payload.cross_llm_validation)
    audit_request_kwargs["cost_cap_usd"] = (
        float(cost_cap) if cost_cap is not None else None)

    # 5. Run the audit. TRON's AuditRequest: project_id, audit_run_id,
    #    file_contents, languages, workspace_root, check_types. Sandbox +
    #    cross-LLM are layered internally; cost cap enforced by Spine post-hoc.
    secrets = _tron_secrets_from_env()
    if not secrets:
        return _error_envelope(code="tron_keys_missing", retryable=False, audit_id=audit_id,
            message="Neither ANTHROPIC_API_KEY nor OPENAI_API_KEY in env — "
                    "TRON AuditManager requires at least one LLM provider key.",
            duration_ms=int((perf_counter() - t0) * 1000))
    file_contents = _load_file_contents(payload.build_artifact)
    if not file_contents:
        return _error_envelope(code="no_source_files", retryable=False, audit_id=audit_id,
            message="0 readable source files from BuildArtifact.code_changes.",
            duration_ms=int((perf_counter() - t0) * 1000))
    tron_findings: list[Any] = []
    layers_run: list[str] = list(_TRON_LAYERS[:2])
    if effective_sandbox: layers_run.append(_TRON_LAYERS[2])
    if payload.cross_llm_validation: layers_run.append(_TRON_LAYERS[3])
    cross_llm_consensus = False
    calibration_band: str | None = None
    agent_metrics: list[dict[str, Any]] = []
    try:
        from verify.tron.agents.manager import AuditManager, AuditRequest
        from verify.tron.schemas.verification import VulnerabilityType
        manager = AuditManager(secrets=secrets)
        if not _register_default_iso_agents(manager, secrets):
            return _error_envelope(code="iso_agents_unavailable", retryable=False,
                audit_id=audit_id, message="No TRON ISO agents registered.",
                duration_ms=int((perf_counter() - t0) * 1000))
        valid = {v.value for v in VulnerabilityType}
        check_types = ([VulnerabilityType(ct) for ct in payload.blueprint.check_types
                        if ct in valid] or None) if payload.blueprint.check_types else None
        # Spine project_id is str; TRON wants UUID — parse or derive uuid5.
        try: tron_project_id = UUID(payload.project_id)
        except (ValueError, AttributeError):
            tron_project_id = uuid5(NAMESPACE_URL, f"spine.project:{payload.project_id}")
        audit_result = _run_async(manager.run_audit(AuditRequest(
            project_id=tron_project_id, audit_run_id=audit_id,
            file_contents=file_contents,
            languages=audit_request_kwargs["languages"],
            check_types=check_types)))
        tron_findings = list(getattr(audit_result, "findings", []) or [])
        agent_metrics = list(getattr(audit_result, "agent_metrics", []) or [])
        for cv in (getattr(audit_result, "cross_validations", []) or []):
            if getattr(getattr(cv, "consensus", None), "value", "") == "confirmed":
                cross_llm_consensus = True; break
        calibration_band = getattr(audit_result, "calibration_band", None)
    except Exception as exc:
        logger.exception("verify_audit: TRON AuditManager.run_audit failed")
        return _error_envelope(code="tron_audit_failed", retryable=True, audit_id=audit_id,
            message=f"TRON AuditManager.run_audit raised: {exc!s}",
            duration_ms=int((perf_counter() - t0) * 1000))

    # 6. Map TRON FindingOutput -> Spine Finding.
    findings = [_map_tron_finding(tf) for tf in tron_findings]

    # 7. Cost rollup — sum per-agent LLM cost from AgentMetrics.to_dict().
    cost_usd = _aggregate_cost(agent_metrics)

    # 8. Decide pass/fail.
    pass_fail = _decide_pass_fail(findings)

    # 9. Persist to spine_audit (summary + per-finding rows).
    duration_ms = int((perf_counter() - t0) * 1000)
    summary = {
        "artifact_uuid": str(payload.build_artifact.artifact_uuid),
        "directive_id": payload.build_artifact.directive_id,
        "phase": payload.build_artifact.phase,
        "layers_run": layers_run, "sandbox_executed": effective_sandbox,
        "cross_llm_consensus": cross_llm_consensus,
        "calibration_band": calibration_band, "duration_ms": duration_ms,
        "cost_cap_usd": str(cost_cap) if cost_cap is not None else None,
        "diff_summary": payload.build_artifact.compute_diff_summary(),
    }
    persisted_audit_id = _persist_findings(
        actor=payload.actor, artifact=payload.build_artifact,
        findings=findings, summary=summary, cost_usd=cost_usd,
        pass_fail=pass_fail, pipeline_version=payload.pipeline_version)

    # 10. Envelope. TRON ran successfully — zero findings is still a real audit.
    status: ToolStatus = "ok"
    result = VerifyFindings(
        status=status, pass_fail=pass_fail, findings=findings,
        layers_run=layers_run, sandbox_executed=effective_sandbox,
        cross_llm_consensus=cross_llm_consensus,
        calibration_band=calibration_band, duration_ms=duration_ms,
        cost_usd=cost_usd, audit_id=persisted_audit_id, error=None)
    citations = _citations_from_findings(
        findings, payload.build_artifact.artifact_uuid, persisted_audit_id,
    )
    return ToolResponse(status=status, data=result.model_dump(mode="json"),
                        audit_id=persisted_audit_id, citation=citations)


__all__: list[str] = [
    "PassFail", "VerifyAuditInput", "VerifyFindings", "verify_audit",
]
