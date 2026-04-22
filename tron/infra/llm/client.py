"""
Unified LLM client — abstracts Anthropic and OpenAI behind a single interface.

All API keys come from keyvault at runtime. No secrets in env or config.

Features:
- Provider-agnostic request/response
- Retry with exponential backoff
- Circuit breaker (fail-fast after consecutive errors)
- Token counting and cost tracking
- Structured JSON output mode
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

import httpx

from tron.api.config import settings
from tron.infra.llm.budget import assert_llm_budget_allows_estimated_call
from tron.infra.llm.usage_context import get_llm_usage_context
from tron.infra.llm.usage_ledger import persist_llm_usage

logger = logging.getLogger(__name__)


# ── Models ─────────────────────────────────────────────────────────────


class Provider(str, Enum):
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    OLLAMA = "ollama"


# Default Anthropic model for ISO audits / fast tasks. Claude 3 Haiku was retired
# (~2026-04); use current Haiku snapshot per https://docs.anthropic.com/en/docs/about-claude/models
DEFAULT_ANTHROPIC_FAST_MODEL = "claude-haiku-4-5-20251001"

# Model → (provider, input_cost_per_1k, output_cost_per_1k)
# Anthropic Haiku 4.5: $1 / $5 per MTok (docs pricing) → per-1k-token rates below.
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


# ── Client ─────────────────────────────────────────────────────────────


class LLMClient:
    """Async LLM client with retry, circuit breaker, and cost tracking.

    Usage:
        client = LLMClient(
            anthropic_key=secrets.get("llm/anthropic-key"),
            openai_key=secrets.get("llm/openai-key"),
        )
        response = await client.complete(request)
    """

    def __init__(
        self,
        anthropic_key: Optional[str] = None,
        openai_key: Optional[str] = None,
        timeout: int = 30,
    ) -> None:
        self._keys: Dict[Provider, str] = {}
        if anthropic_key and anthropic_key != "REPLACE_ME_IN_VAULT":
            self._keys[Provider.ANTHROPIC] = anthropic_key
        if openai_key and openai_key != "REPLACE_ME_IN_VAULT":
            self._keys[Provider.OPENAI] = openai_key

        self._timeout = timeout
        self._breakers: Dict[Provider, CircuitBreaker] = {
            Provider.ANTHROPIC: CircuitBreaker(
                failure_threshold=settings.llm_circuit_breaker_threshold,
                recovery_timeout=settings.llm_circuit_breaker_timeout,
            ),
            Provider.OPENAI: CircuitBreaker(
                failure_threshold=settings.llm_circuit_breaker_threshold,
                recovery_timeout=settings.llm_circuit_breaker_timeout,
            ),
            Provider.OLLAMA: CircuitBreaker(
                failure_threshold=settings.llm_circuit_breaker_threshold,
                recovery_timeout=settings.llm_circuit_breaker_timeout,
            ),
        }
        self._http = httpx.AsyncClient(timeout=timeout)

        # Cumulative cost tracking
        self.total_cost_usd: float = 0.0
        self.total_requests: int = 0

    async def complete(
        self,
        request: LLMRequest,
        retries: Optional[int] = None,
    ) -> LLMResponse:
        """Send a completion request to the appropriate provider.

        Handles retry with exponential backoff and circuit breaker.
        """
        provider, _, _ = self._resolve_model(request.model)

        if provider != Provider.OLLAMA and provider not in self._keys:
            raise ValueError(
                f"No API key available for provider '{provider.value}'. "
                f"Ensure the key is set in the container keyvault."
            )

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
                if provider == Provider.ANTHROPIC:
                    response = await self._call_anthropic(request)
                elif provider == Provider.OLLAMA:
                    response = await self._call_ollama(request)
                else:
                    response = await self._call_openai(request)

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

            except (httpx.TimeoutException, httpx.HTTPStatusError) as exc:
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
        """Close the HTTP client."""
        await self._http.aclose()

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

    # ── Provider-Specific Calls ────────────────────────────────────

    async def _call_anthropic(self, request: LLMRequest) -> LLMResponse:
        """Call the Anthropic Messages API."""
        api_key = self._keys[Provider.ANTHROPIC]

        # Separate system message from conversation
        system_text = ""
        messages = []
        for msg in request.messages:
            if msg.role == "system":
                system_text = msg.content
            else:
                messages.append({"role": msg.role, "content": msg.content})

        body: Dict[str, Any] = {
            "model": request.model,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "messages": messages,
        }
        if system_text:
            body["system"] = system_text
        if request.stop_sequences:
            body["stop_sequences"] = request.stop_sequences

        resp = await self._http.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=body,
        )
        sc = getattr(resp, "status_code", None)
        if isinstance(sc, int) and sc >= 400:
            logger.error(
                "Anthropic Messages API HTTP %s model=%s body=%s",
                sc,
                request.model,
                (resp.text or "")[:4000],
            )
        resp.raise_for_status()
        data = resp.json()

        content = ""
        for block in data.get("content", []):
            if block.get("type") == "text":
                content += block["text"]

        usage = data.get("usage", {})
        return LLMResponse(
            content=content,
            model=data.get("model", request.model),
            provider=Provider.ANTHROPIC,
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            finish_reason=data.get("stop_reason", ""),
            raw=data,
        )

    async def _call_ollama(self, request: LLMRequest) -> LLMResponse:
        """Call a local Ollama server (OpenAI-compatible chat)."""
        base = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
        model_id = request.model[7:] if request.model.startswith("ollama/") else os.getenv(
            "OLLAMA_MODEL", "llama3.2"
        )
        messages = [{"role": msg.role, "content": msg.content} for msg in request.messages]
        resp = await self._http.post(
            f"{base}/api/chat",
            json={
                "model": model_id,
                "messages": messages,
                "stream": False,
                "options": {"temperature": request.temperature},
            },
        )
        resp.raise_for_status()
        data = resp.json()
        msg = data.get("message") or {}
        content = msg.get("content") or ""
        prompt_n = int(data.get("prompt_eval_count", 0) or 0)
        in_tok = prompt_n or max(len(content) // 4, 1)
        out_tok = max(len(content) // 4, 0)
        return LLMResponse(
            content=content,
            model=request.model,
            provider=Provider.OLLAMA,
            input_tokens=in_tok,
            output_tokens=out_tok,
            finish_reason="stop",
            raw=data,
        )

    async def _call_openai(self, request: LLMRequest) -> LLMResponse:
        """Call the OpenAI Chat Completions API."""
        api_key = self._keys[Provider.OPENAI]

        messages = [
            {"role": msg.role, "content": msg.content}
            for msg in request.messages
        ]

        body: Dict[str, Any] = {
            "model": request.model,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "messages": messages,
        }
        if request.json_mode:
            body["response_format"] = {"type": "json_object"}
        if request.stop_sequences:
            body["stop"] = request.stop_sequences

        resp = await self._http.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=body,
        )
        resp.raise_for_status()
        data = resp.json()

        choice = data["choices"][0]
        usage = data.get("usage", {})
        return LLMResponse(
            content=choice["message"]["content"],
            model=data.get("model", request.model),
            provider=Provider.OPENAI,
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            finish_reason=choice.get("finish_reason", ""),
            raw=data,
        )

    # ── Helpers ────────────────────────────────────────────────────

    def _resolve_model(self, model: str) -> tuple[Provider, float, float]:
        """Look up model in registry."""
        if model.startswith("ollama/"):
            return Provider.OLLAMA, 0.0, 0.0
        if model not in MODEL_REGISTRY:
            raise ValueError(
                f"Unknown model '{model}'. Known models: "
                f"{', '.join(sorted(MODEL_REGISTRY.keys()))}, ollama/<model_id>"
            )
        return MODEL_REGISTRY[model]

    @staticmethod
    def _calculate_cost(
        model: str, input_tokens: int, output_tokens: int
    ) -> float:
        """Calculate cost in USD."""
        if model.startswith("ollama/"):
            return 0.0
        if model not in MODEL_REGISTRY:
            return 0.0
        _, input_rate, output_rate = MODEL_REGISTRY[model]
        return (input_tokens / 1000 * input_rate) + (
            output_tokens / 1000 * output_rate
        )
