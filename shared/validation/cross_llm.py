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

Wave 1 (v3) changes — BREAKING for persisted ``ValidationRequest`` /
``ProviderResult`` records:

  * ``Provider`` Literal extends from the original 4 values
    (``anthropic``, ``openai``, ``google``, ``local``) to the full 7-tuple
    locked by V3 #2 (``anthropic``, ``openai``, ``bedrock``, ``vertex``,
    ``ollama``, ``qwen``, ``vllm``). Note: ``google`` and ``local`` are
    DROPPED — they map to ``vertex`` (Gemini on Vertex AI) and to one of
    ``ollama`` / ``vllm`` respectively. Any persisted rows carrying the
    old labels must be migrated by a one-time backfill (V21+ migration):

        UPDATE spine_audit.audit_event
        SET metadata = jsonb_set(metadata, '{providers}', ...)
        WHERE metadata->>'providers' ~* '"(google|local)"';

    The new value is determined by the row's ``primary_model`` field; if
    ambiguous, default to ``vertex`` (for google) or ``ollama`` (for
    local).
  * All provider calls now dispatch through ``shared.llm.call_async`` so
    every adapter, prompt-cache trait, retry policy, and credential
    surface flows through a single entry point (per V3 #2). The legacy
    inline SDK calls (``_call_anthropic`` / ``_call_openai``) have been
    removed; ``_DISPATCH`` is gone.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from shared.mcp.schemas import ToolStatus
from shared.validation.config import should_cross_validate
from shared.validation.consensus import ConsensusResult, Verdict, compute_consensus

logger = logging.getLogger(__name__)

# Provider catalog per V3 design decision #2 (LLM-agnostic):
#   anthropic / openai / bedrock / vertex / ollama / qwen / vllm
#
# Migration note (BREAKING): the previous 4-value Literal (anthropic /
# openai / google / local) is no longer accepted. Persisted rows carrying
# those labels must be backfilled — see module docstring.
Provider = Literal[
    "anthropic", "openai", "bedrock", "vertex", "ollama", "qwen", "vllm"
]
ContentType = Literal["prd", "trd", "code_change", "audit_finding", "decomposition"]
Severity = Literal["critical", "high", "medium", "low"]

_SINGLE_KEY_CONFIDENCE_CAP: float = 0.7
_MAX_INPUT_CHARS: int = 16_000  # ~4k tokens; trimmed to keep cost bounded

# Default validator model per provider. The model string is also the
# routing key for shared.llm — adapters resolve via prefix match.
_DEFAULT_VALIDATOR_MODELS: dict[str, str] = {
    "anthropic": "claude-sonnet-4",
    "openai":    "gpt-4o",
    "bedrock":   "bedrock:anthropic.claude-3-5-sonnet-20240620-v1:0",
    "vertex":    "vertex:gemini-1.5-pro",
    "ollama":    "ollama:llama3.1:8b",
    "qwen":      "qwen:qwen2.5-72b-instruct",
    "vllm":      "vllm:meta-llama/Meta-Llama-3.1-8B-Instruct",
}
# Approx per-call cost ≈ 500 in + 200 out tokens at typical 2026 pricing.
# Local providers (ollama / vllm) are zero; bedrock/vertex roughly match
# the underlying model's marginal cost.
_APPROX_COST: dict[str, float] = {
    "anthropic": 0.0045, "openai": 0.00325,
    "bedrock":   0.0045, "vertex":   0.0040,
    "ollama":    0.0,    "vllm":     0.0,
    "qwen":      0.0010,
}


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
#
# Per V3 #9 (vault-only): we MUST NOT read provider API keys from
# environment variables. Availability is therefore determined by the
# provider adapter registry in ``shared.llm`` — the adapter declares
# whether its credentials resolve (via shared.secrets) at call time.
#
# The legacy ``_KEY_ENV`` map (ANTHROPIC_API_KEY / OPENAI_API_KEY env
# discovery) has been removed. Tests inject availability by patching
# ``_available_providers``; production resolution is governed by which
# secrets the operator has provisioned in the vault.

# Maps a model-string prefix to a logical Provider name. These mirror
# the routing rules in ``shared.llm.providers.__init__`` so that a model
# string flows identically through both the cross-LLM detector here and
# the LLM dispatch in shared.llm.
_MODEL_PREFIX_PROVIDER: tuple[tuple[tuple[str, ...], Provider], ...] = (
    (("claude",),                "anthropic"),
    (("gpt", "o1", "o3"),        "openai"),
    (("bedrock:",),              "bedrock"),
    (("vertex:",),               "vertex"),
    (("ollama:",),               "ollama"),
    (("qwen:",),                 "qwen"),
    (("vllm:",),                 "vllm"),
)


def _available_providers() -> dict[str, str]:
    """Map ``provider -> default_validator_model`` for providers whose
    adapter can be resolved through ``shared.llm``.

    The shared.llm provider registry is the single source of truth for
    "is this provider wired in?". If the adapter is registered, the
    provider is considered available — credential resolution happens
    inside the adapter (via ``shared.secrets``) at call time.
    """
    try:
        from shared.llm.providers import get_provider
    except Exception:  # noqa: BLE001 — defensive: shared.llm import failure
        return {}
    out: dict[str, str] = {}
    for prov, model in _DEFAULT_VALIDATOR_MODELS.items():
        try:
            get_provider(model)
        except Exception:  # noqa: BLE001 — provider not registered
            continue
        out[prov] = model
    return out


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


# ── Provider dispatch via shared.llm (V3 #2) ──────────────────────────
#
# All provider calls now flow through ``shared.llm.call_async``. The
# legacy per-provider helpers (lazy anthropic / openai imports) are
# deleted — credentials, prompt-cache, retry, streaming, and adapter
# selection are all the provider adapter's concern, not this module's.


async def _call_via_shared_llm(
    provider: Provider, model: str, system: str, user: str,
) -> tuple[str, float]:
    """Dispatch one validator call through ``shared.llm``.

    Returns ``(response_text, approx_cost_usd)``. Approx cost is a
    lookup — the authoritative ledger is ``shared/cost/router.py``,
    which reads ``Usage`` from the response.
    """
    from shared.llm import LLMRequest, Message, call_async  # noqa: PLC0415

    request = LLMRequest(
        model=model,
        max_tokens=500,
        temperature=0.1,
        system=system,
        messages=[Message(role="user", content=user)],
    )
    response = await call_async(request)
    return response.content, _APPROX_COST.get(provider, 0.0)


def _validate_with_provider(
    request: ValidationRequest, provider: Provider, model: str,
) -> ProviderResult:
    """Call the secondary provider via ``shared.llm``; degrade to
    ``verdict='error'`` on any failure (the validator must never raise
    into the caller — that would defeat the cross-LLM safety net)."""
    start = time.monotonic()
    _ms = lambda: int((time.monotonic() - start) * 1000)
    _err = lambda msg: ProviderResult(provider=provider, model=model,
        verdict="error", confidence=0.0, rationale=msg, duration_ms=_ms())

    if provider not in _DEFAULT_VALIDATOR_MODELS:
        return _err(f"provider {provider!r} not in v3 catalog")
    system, user = _build_validator_prompt(request)
    try:
        raw, cost = _run_async(_call_via_shared_llm(provider, model, system, user))
    except ImportError as exc:
        return _err(f"{provider} adapter dependency missing: {exc}")
    except Exception as exc:  # noqa: BLE001 — never let validator faults raise
        logger.warning("cross_llm_provider_error",
            extra={"provider": provider, "err": str(exc)})
        return _err(f"provider call failed: {exc}")
    verdict, conf, rationale = _parse_validator_reply(raw)
    return ProviderResult(provider=provider, model=model, verdict=verdict,
        confidence=conf, rationale=rationale, cost_usd=Decimal(str(cost)),
        duration_ms=_ms())


def _run_async(coro):
    """Run an awaitable from sync code.

    The cross-validator's public surface (``cross_validate``) is sync —
    keep it that way to preserve binary compatibility with all current
    callers. When invoked from inside a running event loop, this raises
    so the caller knows to switch to an async cross-validator (planned
    for v1.1).
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None and loop.is_running():
        raise RuntimeError(
            "cross_validate called from inside a running event loop; "
            "use the async variant once available"
        )
    return asyncio.run(coro)


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
            "single-provider deployment: no secondary provider available "
            "via shared.llm (configure additional providers in shared.llm "
            "registry + provide credentials via shared.secrets); "
            "capping effective confidence at 0.7",
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
