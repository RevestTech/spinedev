"""Cross-LLM validation service (STORY-3.7.1 / EPIC-3.7).

Generalizes TRON's ``AuditManager._validate_single_finding`` pattern
(``verify/tron/agents/manager.py``) into a reusable capability for Plan
(PRD/TRD synthesis), Build (security-critical engineer work), and Verify
(severe findings).

Contract: one model produces ``content``; one-or-more *other* providers
independently verify it. Consensus = high confidence; disagreement =
``needs_review``. When only one provider key is present (STORY-3.7.3),
we degrade gracefully — skip the secondary call, cap effective confidence
at 0.7. Cost (STORY-3.7.4): roughly 2x the LLM cost for the affected
output; ``total_cost_usd`` surfaces that to the cost meter.
"""

from __future__ import annotations

import json
import logging
import os
import time
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from shared.mcp.schemas import ToolStatus
from shared.validation.config import should_cross_validate
from shared.validation.consensus import ConsensusResult, Verdict, compute_consensus

logger = logging.getLogger(__name__)

Provider = Literal["anthropic", "openai", "google", "local"]
ContentType = Literal["prd", "trd", "code_change", "audit_finding", "decomposition"]
Severity = Literal["critical", "high", "medium", "low"]

_SINGLE_KEY_CONFIDENCE_CAP: float = 0.7
_MAX_INPUT_CHARS: int = 16_000  # ~4k tokens; trimmed to keep cost bounded
_DEFAULT_VALIDATOR_MODELS: dict[str, str] = {
    "anthropic": "claude-sonnet-4",
    "openai": "gpt-4o",
}
# Approx per-call cost ≈ 500 in + 200 out tokens at sonnet / gpt-4o pricing.
_APPROX_COST: dict[str, float] = {"anthropic": 0.0045, "openai": 0.00325}


class ValidationRequest(BaseModel):
    """Input: the artifact a primary model produced + how to cross-check it."""

    model_config = ConfigDict(protected_namespaces=())

    content: str = Field(..., min_length=1)
    content_type: ContentType
    primary_model: str = Field(..., min_length=1)
    project_id: str = Field(..., min_length=1)
    phase: str = Field(..., min_length=1)
    severity: Severity = "high"
    actor: str = "orchestrator"


class ProviderResult(BaseModel):
    """One secondary provider's independent verdict on the primary's output."""

    model_config = ConfigDict(protected_namespaces=())

    provider: Provider
    model: str
    verdict: Verdict
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = ""
    cost_usd: Decimal = Decimal("0")
    duration_ms: int = Field(ge=0, default=0)


class CrossLLMValidationResult(BaseModel):
    """Envelope returned by ``cross_validate``; never raises."""

    model_config = ConfigDict(protected_namespaces=())

    status: ToolStatus
    request: ValidationRequest
    provider_results: list[ProviderResult] = Field(default_factory=list)
    consensus: ConsensusResult
    total_cost_usd: Decimal = Decimal("0")
    duration_ms: int = Field(ge=0, default=0)
    audit_id: UUID = Field(default_factory=uuid4)
    skipped_reason: str | None = None
    effective_confidence_cap: float = Field(ge=0.0, le=1.0, default=1.0)


# ── Provider detection ────────────────────────────────────────────────

_KEY_ENV = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}
_MODEL_PREFIX_PROVIDER: tuple[tuple[tuple[str, ...], Provider], ...] = (
    (("claude",), "anthropic"),
    (("gpt", "o1", "o3"), "openai"),
    (("gemini", "palm"), "google"),
)


def _available_providers() -> dict[str, str]:
    """Map ``provider -> default_validator_model`` for providers with keys set."""
    return {p: _DEFAULT_VALIDATOR_MODELS[p] for p, env in _KEY_ENV.items()
            if os.environ.get(env) and p in _DEFAULT_VALIDATOR_MODELS}


def _infer_primary_provider(model_id: str) -> Provider | None:
    """Best-effort: identify which provider the primary model came from."""
    mid = model_id.lower()
    for prefixes, provider in _MODEL_PREFIX_PROVIDER:
        if mid.startswith(prefixes):
            return provider
    return None


# ── Validator prompts + reply parsing ─────────────────────────────────


def _build_validator_prompt(request: ValidationRequest) -> tuple[str, str]:
    """Return (system, user) prompts for the secondary validator."""
    system = (
        "You are an independent validator. The user message contains output "
        "produced by another LLM. Verify it independently for correctness, "
        "safety, and scope. Be precise, skeptical, brief. Reply ONLY with "
        'strict JSON: {"verdict": "agree|disagree|partial_agree|abstain",'
        ' "confidence": 0.0-1.0, "rationale": "<= 280 chars"}'
    )
    content = request.content
    if len(content) > _MAX_INPUT_CHARS:
        content = content[:_MAX_INPUT_CHARS] + "\n…[truncated]"
    user = (f"Content type: {request.content_type}\nPrimary model: "
            f"{request.primary_model}\nPhase: {request.phase}\nSeverity: "
            f"{request.severity}\n---\n{content}\n---\nReply JSON only.")
    return system, user


def _parse_validator_reply(raw: str) -> tuple[Verdict, float, str]:
    """Best-effort parse of the validator's JSON reply; defaults on failure."""
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return ("error", 0.0, "validator reply was not valid JSON")
    v = str(data.get("verdict", "")).lower()
    if v not in ("agree", "disagree", "partial_agree", "abstain"):
        return ("error", 0.0, f"unknown verdict: {v!r}")
    try:
        c = max(0.0, min(1.0, float(data.get("confidence", 0.0))))
    except (TypeError, ValueError):
        c = 0.0
    return (v, c, str(data.get("rationale", ""))[:512])  # type: ignore[return-value]


# ── Per-provider calls (lazy SDK imports — SDKs are optional) ─────────


def _call_anthropic(model: str, system: str, user: str) -> tuple[str, float]:
    """Lazy ``anthropic`` SDK call; raises ImportError if SDK absent."""
    import anthropic  # noqa: F401

    client = anthropic.Anthropic()  # type: ignore[attr-defined]
    resp = client.messages.create(  # type: ignore[attr-defined]
        model=model, system=system, max_tokens=500, temperature=0.1,
        messages=[{"role": "user", "content": user}])
    text = "".join(getattr(b, "text", "") for b in getattr(resp, "content", []))
    return text, _APPROX_COST["anthropic"]


def _call_openai(model: str, system: str, user: str) -> tuple[str, float]:
    """Lazy ``openai`` SDK call; raises ImportError if SDK absent."""
    import openai  # noqa: F401

    client = openai.OpenAI()  # type: ignore[attr-defined]
    resp = client.chat.completions.create(  # type: ignore[attr-defined]
        model=model, max_tokens=500, temperature=0.1,
        response_format={"type": "json_object"},
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])
    text = (resp.choices[0].message.content or "") if getattr(resp, "choices", None) else ""
    return text, _APPROX_COST["openai"]


_DISPATCH = {"anthropic": _call_anthropic, "openai": _call_openai}


def _validate_with_provider(
    request: ValidationRequest, provider: Provider, model: str,
) -> ProviderResult:
    """Call the secondary provider; degrade to verdict='error' on any failure."""
    start = time.monotonic()
    _ms = lambda: int((time.monotonic() - start) * 1000)
    _err = lambda msg: ProviderResult(provider=provider, model=model,
        verdict="error", confidence=0.0, rationale=msg, duration_ms=_ms())

    fn = _DISPATCH.get(provider)
    if fn is None:
        return _err(f"provider {provider!r} not implemented")
    try:
        raw, cost = fn(model, *_build_validator_prompt(request))
    except ImportError as exc:
        return _err(f"{provider} SDK not installed: {exc}")
    except Exception as exc:  # noqa: BLE001 — never let validator faults raise
        logger.warning("cross_llm_provider_error",
            extra={"provider": provider, "err": str(exc)})
        return _err(f"provider call failed: {exc}")
    verdict, conf, rationale = _parse_validator_reply(raw)
    return ProviderResult(provider=provider, model=model, verdict=verdict,
        confidence=conf, rationale=rationale, cost_usd=Decimal(str(cost)),
        duration_ms=_ms())


# ── Audit row ─────────────────────────────────────────────────────────


def _write_audit(request: ValidationRequest, consensus: ConsensusResult,
                 results: list[ProviderResult], total_cost: Decimal,
                 skipped: str | None) -> UUID:
    """Best-effort audit write; never blocks on audit failure."""
    audit_uuid = uuid4()
    try:
        from shared.audit.audit_record import (
            AuditRecord, chain_to_previous, write_via_psql,
        )
        try:
            pid: int | None = int(request.project_id)
        except (TypeError, ValueError):
            pid = None
        meta: dict[str, Any] = {
            "content_type": request.content_type,
            "primary_model": request.primary_model,
            "severity": request.severity,
            "final_verdict": consensus.final_verdict,
            "confidence_band": consensus.confidence_band,
            "providers": [r.model_dump(mode="json") for r in results],
            "dissenting": consensus.dissenting_providers,
            "skipped_reason": skipped,
        }
        rec = AuditRecord(
            event_uuid=audit_uuid, project_id=pid, phase=request.phase,
            role="validator", subsystem="shared", action="cross_llm_validate",
            actor=request.actor, subject_type=request.content_type,
            subject_id=request.primary_model, cost_usd=total_cost, metadata=meta)
        write_via_psql(chain_to_previous(rec, None))
    except Exception as exc:  # noqa: BLE001 — audit is best-effort
        logger.warning("cross_llm_audit_write_failed", extra={"err": str(exc)})
    return audit_uuid


def _skip_result(request: ValidationRequest, reason: str, cap: float,
                 start: float, band: Literal["low", "untrusted"]) -> CrossLLMValidationResult:
    """Build a 'skipped' result with audit row; never raises."""
    consensus = ConsensusResult(achieved=False, primary_agrees_with_majority=False,
        dissenting_providers=[], final_verdict="indeterminate",
        confidence_band=band, avg_confidence=0.0)
    return CrossLLMValidationResult(status="ok", request=request, consensus=consensus,
        duration_ms=int((time.monotonic() - start) * 1000),
        audit_id=_write_audit(request, consensus, [], Decimal("0"), reason),
        skipped_reason=reason, effective_confidence_cap=cap)


# ── Public entry-point ────────────────────────────────────────────────


def cross_validate(
    request: ValidationRequest, *,
    bundle: dict[str, Any] | None = None,
    additional_providers: list[Provider] | None = None,
) -> CrossLLMValidationResult:
    """Independently verify ``request.content`` across non-primary providers.

    Returns a result envelope even on skip / error — never raises.
    ``status='ok'`` always; the embedded ``consensus.final_verdict`` is
    the decision surface (validated | needs_review | rejected | indeterminate).
    """
    start = time.monotonic()

    # 1. Phase gate (STORY-3.7.2)
    if not should_cross_validate(request.phase, request.severity, bundle=bundle):
        return _skip_result(request,
            f"phase {request.phase!r} + severity {request.severity!r} below"
            " threshold (shared/validation/config.py DEFAULT_CROSS_LLM_PHASES)",
            cap=1.0, start=start, band="low")

    # 2. Detect secondaries (skip primary's own provider to avoid correlated failure)
    available = _available_providers()
    primary_provider = _infer_primary_provider(request.primary_model)
    secondaries: dict[str, str] = {
        p: m for p, m in available.items() if p != primary_provider}
    for extra in additional_providers or []:
        if extra not in secondaries and extra in available:
            secondaries[extra] = available[extra]

    # 3. Single-key deployment → graceful degradation (STORY-3.7.3)
    if not secondaries:
        return _skip_result(request,
            "single-provider deployment: no secondary key available (checked "
            "ANTHROPIC_API_KEY, OPENAI_API_KEY); capping effective confidence at 0.7",
            cap=_SINGLE_KEY_CONFIDENCE_CAP, start=start, band="untrusted")

    # 4. Call each secondary; reduce to consensus; audit
    results = [_validate_with_provider(request, p, m)  # type: ignore[arg-type]
               for p, m in secondaries.items()]
    consensus = compute_consensus(request.primary_model, results)
    total_cost = sum((r.cost_usd for r in results), Decimal("0"))
    audit_id = _write_audit(request, consensus, results, total_cost, None)
    return CrossLLMValidationResult(
        status="ok", request=request, provider_results=results,
        consensus=consensus, total_cost_usd=total_cost,
        duration_ms=int((time.monotonic() - start) * 1000),
        audit_id=audit_id, skipped_reason=None, effective_confidence_cap=1.0)


__all__ = [
    "ContentType", "CrossLLMValidationResult", "Provider", "ProviderResult",
    "Severity", "ValidationRequest", "cross_validate",
]
