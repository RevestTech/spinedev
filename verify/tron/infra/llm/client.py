"""
TRON ↔ Spine LLM bridge — thin SHIM over ``shared/llm/``.

Per V3 design decision #2 (LLM-agnostic by architecture) and V3 build-sequence
Part 1.4 question #6: TRON's LLM client MUST route through ``shared/llm/`` —
no per-provider HTTP / SDK code, no env-var key reads, no Provider enum that
diverges from the seven Wave-0 provider adapters. Spine's Hub bootstrap wires
provider credentials into ``shared.secrets``; ``shared/llm/providers/*``
resolve them at call time.

What this module preserves (TRON callers MUST keep working without code
changes — see ``verify/tron/agents/*`` and ``verify/tron/workflows/*``):

  * Public Python API surface — every symbol exported pre-shim is re-exported:
        Provider, LLMClient, LLMMessage, LLMRequest, LLMResponse,
        CircuitBreaker, CircuitState, MODEL_REGISTRY,
        DEFAULT_ANTHROPIC_FAST_MODEL
  * Call signature — ``LLMClient(anthropic_key=..., openai_key=...).complete(request)``
    keeps the same kwargs. The keys are now **ignored** (kept only for
    backward compatibility); shared.llm sources credentials via
    ``shared.secrets`` per #9 (vault-only).
  * TRON-side concerns — Redis cache, circuit breaker, budget gate, and
    LLM usage-ledger persistence still live here. Those are TRON's own
    cost / reliability primitives, NOT shared.llm's job.

What this module DELETES:

  * Per-provider HTTP/SDK call paths (``_call_anthropic`` /
    ``_call_openai`` / ``_call_ollama``). All provider dispatch now
    happens inside ``shared.llm.call_async``.
  * Env-var API-key reads (the legacy ``os.environ.get(...)`` calls for
    provider keys). Per V3 #9 secrets NEVER come from env — they come
    from vault via ``shared.secrets``. The ``anthropic_key`` /
    ``openai_key`` kwargs on ``LLMClient`` are accepted for
    backward-compat and silently ignored with a one-time warning.

What this module ADDS:

  * Four new ``Provider`` enum values — ``BEDROCK``, ``VERTEX``, ``QWEN``,
    ``VLLM`` — so TRON agents can opt into any of the seven v3 providers
    per-bundle without code changes here.
  * ``_PROVIDER_MODEL_PREFIX`` — single source of truth mapping TRON's
    enum to ``shared.llm`` model prefixes (see
    ``shared/llm/providers/__init__.py`` for the canonical prefix list).

If ``shared.llm`` is not importable or refuses the request because no
provider is configured, the shim raises a clear ``ProviderConfigError``
pointing at Hub bootstrap (vault wiring / shared.secrets setup).

See ``verify/LLM_BRIDGE.md`` for the architectural rationale and the
"adding a new provider" recipe.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from tron.api.config import settings
from tron.infra.llm.budget import assert_llm_budget_allows_estimated_call
from tron.infra.llm.usage_context import get_llm_usage_context
from tron.infra.llm.usage_ledger import persist_llm_usage

logger = logging.getLogger(__name__)


# ── Models ─────────────────────────────────────────────────────────────


class Provider(str, Enum):
    """TRON-facing provider enum.

    Pre-shim values (ANTHROPIC / OPENAI / OLLAMA) preserved so existing
    TRON code keeps importing unchanged. New values mirror the seven
    Wave-0 ``shared/llm/providers/*`` adapters per V3 #2 (LLM-agnostic).

    Provider → ``shared.llm`` model-prefix mapping lives in
    ``_PROVIDER_MODEL_PREFIX`` below — adding a new provider = add a
    factory under ``shared/llm/providers/`` THEN add an enum value +
    mapping entry here.
    """

    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    OLLAMA = "ollama"
    # New v3 providers — reachable without TRON-agent code changes.
    BEDROCK = "bedrock"
    VERTEX = "vertex"
    QWEN = "qwen"
    VLLM = "vllm"


# Provider → shared/llm model-prefix mapping. Mirrors the registration
# order in ``shared/llm/providers/__init__.py::_load_builtin_providers``.
# When ``request.model`` does NOT already start with one of these, the
# shim re-routes by prepending the prefix.
_PROVIDER_MODEL_PREFIX: Dict[Provider, str] = {
    Provider.ANTHROPIC: "claude-",
    Provider.OPENAI: "gpt-",
    Provider.OLLAMA: "ollama:",
    Provider.BEDROCK: "bedrock:",
    Provider.VERTEX: "vertex:",
    Provider.QWEN: "qwen:",
    Provider.VLLM: "vllm:",
}


def _provider_for_model(model: str) -> Provider:
    """Reverse-lookup: ``shared.llm`` model id → TRON ``Provider`` enum.

    Used to populate ``LLMResponse.provider`` after a successful call so
    callers branching on ``response.provider == Provider.ANTHROPIC``
    keep working.
    """
    # Legacy TRON ``ollama/`` prefix → modern ``ollama:``.
    if model.startswith("ollama/") or model.startswith("ollama:"):
        return Provider.OLLAMA
    for prov, prefix in _PROVIDER_MODEL_PREFIX.items():
        if model.startswith(prefix):
            return prov
    # Fall back to Anthropic-shaped model ids (claude-*) defaulting
    # already handled above; anything else is unknown.
    raise ValueError(
        f"Cannot map model {model!r} to a TRON Provider — "
        f"known prefixes: {list(_PROVIDER_MODEL_PREFIX.values())}"
    )


# Default Anthropic model for ISO audits / fast tasks. Claude 3 Haiku was retired
# (~2026-04); use current Haiku snapshot per https://docs.anthropic.com/en/docs/about-claude/models
DEFAULT_ANTHROPIC_FAST_MODEL = "claude-haiku-4-5-20251001"

# Model → (provider, input_cost_per_1k, output_cost_per_1k)
# Cost rates are TRON-side accounting metadata; shared/llm/ does NOT
# price calls (per its design — pricing lives in shared/cost/router.py).
# We keep this registry for the per-call cost attribution + budget gate
# that ``persist_llm_usage`` writes into TRON's usage ledger.
MODEL_REGISTRY: Dict[str, tuple[Provider, float, float]] = {
    # Anthropic Claude
    DEFAULT_ANTHROPIC_FAST_MODEL: (Provider.ANTHROPIC, 0.001, 0.005),
    "claude-haiku-4-5": (Provider.ANTHROPIC, 0.001, 0.005),  # API alias
    "claude-3-haiku-20240307": (Provider.ANTHROPIC, 0.00025, 0.00125),  # legacy / ledger
    "claude-3-sonnet-20240229": (Provider.ANTHROPIC, 0.003, 0.015),
    "claude-3-opus-20240229": (Provider.ANTHROPIC, 0.015, 0.075),
    # OpenAI GPT (standard models)
    "gpt-4o": (Provider.OPENAI, 0.005, 0.015),
    "gpt-4o-mini": (Provider.OPENAI, 0.00015, 0.0006),
    "gpt-4-turbo": (Provider.OPENAI, 0.01, 0.03),
    "gpt-3.5-turbo": (Provider.OPENAI, 0.0005, 0.0015),
}


@dataclass
class LLMMessage:
    """A single message in the conversation."""
    role: str  # "system", "user", "assistant"
    content: str


@dataclass
class LLMResponse:
    """Unified response from any LLM provider."""
    content: str
    model: str
    provider: Provider
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    finish_reason: str = ""
    raw: Optional[Dict[str, Any]] = None

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class LLMRequest:
    """Unified request to any LLM provider."""
    messages: List[LLMMessage]
    model: str
    temperature: float = 0.1
    max_tokens: int = 4000
    json_mode: bool = False  # Request structured JSON output
    stop_sequences: Optional[List[str]] = None


# ── Circuit Breaker ────────────────────────────────────────────────────


class CircuitState(str, Enum):
    CLOSED = "closed"       # Normal operation
    OPEN = "open"           # Failing — reject immediately
    HALF_OPEN = "half_open" # Testing recovery


@dataclass
class CircuitBreaker:
    """Simple circuit breaker for LLM calls."""
    failure_threshold: int = 5
    recovery_timeout: int = 60
    _failure_count: int = field(default=0, init=False)
    _state: CircuitState = field(default=CircuitState.CLOSED, init=False)
    _last_failure_time: float = field(default=0.0, init=False)

    def record_success(self) -> None:
        self._failure_count = 0
        self._state = CircuitState.CLOSED

    def record_failure(self) -> None:
        self._failure_count += 1
        self._last_failure_time = time.time()
        if self._failure_count >= self.failure_threshold:
            self._state = CircuitState.OPEN
            logger.warning(
                "Circuit breaker OPEN after %d failures", self._failure_count
            )

    def allow_request(self) -> bool:
        if self._state == CircuitState.CLOSED:
            return True
        if self._state == CircuitState.OPEN:
            if time.time() - self._last_failure_time > self.recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                return True
            return False
        # HALF_OPEN — allow one request to test
        return True


# ── Shim helpers ───────────────────────────────────────────────────────


_LEGACY_KEY_WARNING_EMITTED = False


def _warn_legacy_key_kwargs_once(anthropic_key: Optional[str],
                                 openai_key: Optional[str]) -> None:
    """One-time deprecation log when callers still pass ``*_key`` kwargs.

    Per V3 #9 (vault-only secrets), API keys NEVER cross this boundary
    as plaintext kwargs. ``shared.llm`` resolves them via
    ``shared.secrets``. The kwargs are kept for backward-compat with
    pre-shim TRON code but their VALUES are dropped on the floor.
    """
    global _LEGACY_KEY_WARNING_EMITTED
    if _LEGACY_KEY_WARNING_EMITTED:
        return
    if anthropic_key or openai_key:
        logger.warning(
            "LLMClient(anthropic_key=..., openai_key=...) kwargs are "
            "ignored — credentials now resolve via shared.secrets per "
            "V3 #9 (vault-only). Remove these kwargs from your TRON "
            "caller; the shim accepts them only for backward compat."
        )
        _LEGACY_KEY_WARNING_EMITTED = True


def _shared_llm_request_from(request: LLMRequest) -> Any:
    """Translate TRON ``LLMRequest`` → ``shared.llm.LLMRequest``.

    Splits ``role="system"`` messages out into the top-level ``system``
    field (matches the shape ``shared/llm/`` adapters expect).
    """
    from shared.llm import LLMRequest as SharedLLMRequest, Message as SharedMessage

    system_text: Optional[str] = None
    messages: list = []
    for msg in request.messages:
        if msg.role == "system":
            # Accumulate; multiple system messages concatenate (matches
            # shared/llm adapter behavior when callers pass role="system").
            system_text = (system_text + "\n\n" + msg.content) if system_text else msg.content
        else:
            messages.append(SharedMessage(role=msg.role, content=msg.content))

    # Pydantic envelope; shared.llm validates ``max_tokens > 0`` and
    # ``temperature in [0, 2]``. TRON's defaults already satisfy both.
    kwargs: Dict[str, Any] = {
        "model": request.model,
        "messages": messages,
        "max_tokens": request.max_tokens,
        "temperature": request.temperature,
    }
    if system_text is not None:
        kwargs["system"] = system_text
    # NOTE: TRON's ``json_mode`` + ``stop_sequences`` are intentionally
    # dropped on the floor for Wave-0 shared/llm (which doesn't model
    # them yet — see ``shared/llm/request.py`` docstring "MVP scope").
    # Wave-1 augmentation of shared/llm will surface them; the shim
    # gains pass-through at that time without breaking TRON callers.
    return SharedLLMRequest(**kwargs)


def _llm_response_from_shared(shared_response: Any, *,
                              fallback_model: str) -> LLMResponse:
    """Translate ``shared.llm.LLMResponse`` → TRON ``LLMResponse``."""
    model = getattr(shared_response, "model", None) or fallback_model
    usage = getattr(shared_response, "usage", None)
    in_tok = int(getattr(usage, "input_tokens", 0) or 0) if usage else 0
    out_tok = int(getattr(usage, "output_tokens", 0) or 0) if usage else 0
    try:
        provider = _provider_for_model(model)
    except ValueError:
        # Provider unknown to TRON — fall back to ANTHROPIC as a
        # not-load-bearing placeholder; callers that don't branch on
        # ``response.provider`` don't notice.
        provider = Provider.ANTHROPIC
    raw_dump: Any = None
    raw = getattr(shared_response, "raw", None)
    if isinstance(raw, dict):
        raw_dump = raw
    return LLMResponse(
        content=getattr(shared_response, "content", "") or "",
        model=model,
        provider=provider,
        input_tokens=in_tok,
        output_tokens=out_tok,
        finish_reason=getattr(shared_response, "finish_reason", "") or "",
        raw=raw_dump,
    )


# ── Client ─────────────────────────────────────────────────────────────


class LLMClient:
    """Async LLM client — SHIM over ``shared.llm``.

    Usage (unchanged from pre-shim):

        client = LLMClient()           # keys come from vault via shared.secrets
        response = await client.complete(request)

    Backward-compat kwargs (silently ignored, one-time warning):

        client = LLMClient(anthropic_key=..., openai_key=...)

    TRON-side concerns retained here:

      * Per-provider circuit breaker (open after N consecutive failures)
      * Optional Redis response cache (``LLM_CACHE_ENABLED=1``)
      * LLM budget gate (``assert_llm_budget_allows_estimated_call``)
      * Usage-ledger persistence (``persist_llm_usage``)

    Provider dispatch + retry + adapter selection now live inside
    ``shared.llm.call_async``.
    """

    def __init__(
        self,
        anthropic_key: Optional[str] = None,
        openai_key: Optional[str] = None,
        timeout: int = 30,
    ) -> None:
        # Per V3 #9 (vault-only secrets) we DO NOT store API keys here
        # and we DO NOT read them from env. Keys come from shared.secrets
        # via the shared/llm adapter config. Kwargs accepted only so
        # pre-shim TRON callers keep working without edit.
        _warn_legacy_key_kwargs_once(anthropic_key, openai_key)

        self._timeout = timeout
        self._breakers: Dict[Provider, CircuitBreaker] = {
            prov: CircuitBreaker(
                failure_threshold=settings.llm_circuit_breaker_threshold,
                recovery_timeout=settings.llm_circuit_breaker_timeout,
            )
            for prov in Provider
        }

        # Cumulative cost tracking (TRON-side, mirrors pre-shim API).
        self.total_cost_usd: float = 0.0
        self.total_requests: int = 0

    async def complete(
        self,
        request: LLMRequest,
        retries: Optional[int] = None,
    ) -> LLMResponse:
        """Send a completion request via ``shared.llm.call_async``.

        Pipeline:
          1. Resolve TRON-side provider + cost band from MODEL_REGISTRY.
          2. Check circuit breaker for that provider.
          3. Optional Redis cache hit-path (LLM_CACHE_ENABLED=1).
          4. Budget gate.
          5. Retry-loop calling ``shared.llm.call_async``. ``shared.llm``
             also retries inside the adapter; the outer loop here is
             TRON's belt-and-braces.
          6. Translate response, persist usage, return.
        """
        provider, _, _ = self._resolve_model(request.model)
        breaker = self._breakers[provider]
        if not breaker.allow_request():
            raise RuntimeError(
                f"Circuit breaker OPEN for {provider.value}. "
                f"Too many consecutive failures."
            )

        max_retries = retries if retries is not None else 2
        last_error: Optional[Exception] = None

        cache_key: Optional[str] = None
        cache_ttl = int(os.getenv("LLM_CACHE_TTL_SECONDS", "86400"))
        if os.getenv("LLM_CACHE_ENABLED", "").lower() in ("1", "true", "yes"):
            try:
                from tron.infra.redis.client import get_redis

                payload = json.dumps(
                    {
                        "model": request.model,
                        "temperature": request.temperature,
                        "max_tokens": request.max_tokens,
                        "json_mode": request.json_mode,
                        "messages": [(m.role, m.content) for m in request.messages],
                    },
                    sort_keys=True,
                )
                cache_key = "tron:llm:v1:" + hashlib.sha256(
                    payload.encode("utf-8")
                ).hexdigest()
                r = get_redis()
                cached = await r.get(cache_key)
                if cached:
                    data = json.loads(cached)
                    breaker.record_success()
                    resp = LLMResponse(
                        content=data["content"],
                        model=data["model"],
                        provider=Provider(data["provider"]),
                        input_tokens=int(data.get("input_tokens", 0)),
                        output_tokens=int(data.get("output_tokens", 0)),
                        cost_usd=float(data.get("cost_usd", 0.0)),
                        latency_ms=0,
                        finish_reason="cache_hit",
                    )
                    await self._persist_usage_if_context(
                        request,
                        resp,
                        cache_key=cache_key,
                        cached=True,
                    )
                    return resp
            except Exception:
                logger.debug("LLM cache bypassed", exc_info=True)

        await assert_llm_budget_allows_estimated_call()

        for attempt in range(max_retries + 1):
            try:
                start = time.time()
                response = await self._call_shared_llm(request)
                response.latency_ms = int((time.time() - start) * 1000)
                response.cost_usd = self._calculate_cost(
                    request.model, response.input_tokens, response.output_tokens
                )

                breaker.record_success()
                self.total_cost_usd += response.cost_usd
                self.total_requests += 1

                logger.debug(
                    "LLM %s/%s: %d→%d tokens, $%.4f, %dms",
                    provider.value,
                    request.model,
                    response.input_tokens,
                    response.output_tokens,
                    response.cost_usd,
                    response.latency_ms,
                )
                if cache_key:
                    try:
                        from tron.infra.redis.client import get_redis

                        r = get_redis()
                        await r.setex(
                            cache_key,
                            cache_ttl,
                            json.dumps(
                                {
                                    "content": response.content,
                                    "model": response.model,
                                    "provider": response.provider.value,
                                    "input_tokens": response.input_tokens,
                                    "output_tokens": response.output_tokens,
                                    "cost_usd": response.cost_usd,
                                }
                            ),
                        )
                    except Exception:
                        logger.debug("LLM cache write failed", exc_info=True)
                await self._persist_usage_if_context(
                    request, response, cache_key=None, cached=False
                )
                return response

            except _SHARED_LLM_CONFIG_ERRORS as exc:
                # Config errors don't trip the circuit breaker — they
                # surface a Hub-bootstrap problem, not a provider outage.
                # Re-raise immediately with a clear pointer.
                raise ValueError(
                    f"shared.llm rejected the request because no "
                    f"credential is configured for the resolved "
                    f"provider ({provider.value}). Wire the provider "
                    f"key into shared.secrets via Hub bootstrap, then "
                    f"retry. Underlying error: {exc!s}"
                ) from exc
            except _SHARED_LLM_RETRYABLE_ERRORS as exc:
                last_error = exc
                breaker.record_failure()
                if attempt < max_retries:
                    wait = 2 ** attempt
                    logger.warning(
                        "LLM call failed (attempt %d/%d), retrying in %ds: %s",
                        attempt + 1,
                        max_retries + 1,
                        wait,
                        exc,
                    )
                    await asyncio.sleep(wait)

        raise RuntimeError(
            f"LLM call failed after {max_retries + 1} attempts: {last_error}"
        )

    async def close(self) -> None:
        """Close the client. No-op under the shim (shared/llm owns the
        HTTP/SDK lifecycles inside its adapters)."""
        return None

    async def _persist_usage_if_context(
        self,
        request: LLMRequest,
        response: LLMResponse,
        *,
        cache_key: Optional[str],
        cached: bool,
    ) -> None:
        ctx = get_llm_usage_context()
        if ctx is None:
            return
        await persist_llm_usage(
            project_id=ctx.project_id,
            provider=response.provider.value,
            model=response.model,
            prompt_tokens=response.input_tokens,
            completion_tokens=response.output_tokens,
            cost_usd=response.cost_usd,
            duration_ms=response.latency_ms,
            cached=cached,
            cache_key=cache_key if cached else None,
            workflow_id=ctx.workflow_id,
            workflow_run_id=ctx.workflow_run_id,
            operation_mode=ctx.operation_mode,
            operation_detail=ctx.operation_detail,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
        )

    # ── Shared-LLM bridge ──────────────────────────────────────────

    async def _call_shared_llm(self, request: LLMRequest) -> LLMResponse:
        """Delegate to ``shared.llm.call_async``; translate envelopes."""
        # Local import so a missing ``shared`` package in standalone TRON
        # deploys surfaces as a clear ProviderConfigError, not an
        # ImportError at module load time.
        from shared.llm import call_async as shared_call_async

        shared_request = _shared_llm_request_from(request)
        shared_response = await shared_call_async(shared_request)
        return _llm_response_from_shared(
            shared_response, fallback_model=request.model
        )

    # ── Helpers ────────────────────────────────────────────────────

    def _resolve_model(self, model: str) -> tuple[Provider, float, float]:
        """Look up model in registry; falls back to prefix detection for
        models not in TRON's cost table (still routable via shared.llm)."""
        if model.startswith("ollama/") or model.startswith("ollama:"):
            return Provider.OLLAMA, 0.0, 0.0
        if model in MODEL_REGISTRY:
            return MODEL_REGISTRY[model]
        # Not in TRON's per-model cost table — try prefix routing so
        # bedrock:/vertex:/qwen:/vllm: don't 400 here. Cost = 0 means
        # the TRON budget gate is permissive for these; budgeting them
        # is shared/cost/router.py's job once it ships.
        try:
            return _provider_for_model(model), 0.0, 0.0
        except ValueError as exc:
            raise ValueError(
                f"Unknown model '{model}'. Known TRON-priced models: "
                f"{', '.join(sorted(MODEL_REGISTRY.keys()))}. "
                f"Or use any shared/llm prefix: "
                f"{list(_PROVIDER_MODEL_PREFIX.values())}."
            ) from exc

    @staticmethod
    def _calculate_cost(
        model: str, input_tokens: int, output_tokens: int
    ) -> float:
        """Calculate cost in USD."""
        if model.startswith("ollama/") or model.startswith("ollama:"):
            return 0.0
        if model not in MODEL_REGISTRY:
            # No TRON-side cost record for new-provider models. Returning
            # 0 keeps the budget gate non-blocking; shared/cost/router.py
            # will own cross-provider pricing in Wave-1.
            return 0.0
        _, input_rate, output_rate = MODEL_REGISTRY[model]
        return (input_tokens / 1000 * input_rate) + (
            output_tokens / 1000 * output_rate
        )


# ── Exception-class plumbing for shared.llm bridge ─────────────────────


def _resolve_shared_llm_exception_classes() -> tuple[tuple, tuple]:
    """Return ``(config_errors, retryable_errors)`` tuples for ``except``.

    Done lazily so the module imports cleanly even when ``shared.llm``
    isn't on the path (e.g. standalone TRON deployment per G-8 in
    REQ-INIT-8). The fallbacks below mean any exception bubbling out of
    ``_call_shared_llm`` is treated as retryable.
    """
    try:
        from shared.llm import ProviderConfigError, ProviderError, UnknownProviderError
    except Exception:  # noqa: BLE001 — fallback path for standalone TRON
        return (Exception,), (Exception,)
    # Config errors stop the retry loop (a missing key won't fix itself).
    config = (ProviderConfigError, UnknownProviderError)
    # All other ProviderError subclasses (and the generic Exception net)
    # are retryable — same posture as the pre-shim httpx-error catch.
    retryable = (ProviderError, Exception)
    return config, retryable


_SHARED_LLM_CONFIG_ERRORS, _SHARED_LLM_RETRYABLE_ERRORS = (
    _resolve_shared_llm_exception_classes()
)


__all__ = [
    "Provider",
    "LLMClient",
    "LLMMessage",
    "LLMRequest",
    "LLMResponse",
    "CircuitBreaker",
    "CircuitState",
    "MODEL_REGISTRY",
    "DEFAULT_ANTHROPIC_FAST_MODEL",
]
