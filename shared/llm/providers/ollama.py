"""Local Ollama adapter (HTTP to localhost:11434 by default).

Routing prefix: ``ollama:`` — suffix is the local model tag, e.g.
``ollama:llama3.1:70b``, ``ollama:qwen2.5:32b-instruct``.

Auth: none. Per V3 #17, Ollama is the laptop-tier default LLM. Endpoint
override via ``OLLAMA_HOST`` env var OR ``bundle.llm.ollama.endpoint``
(Wave 1 wiring). Per #15 (NOT SaaS) this adapter MUST keep working
fully offline — no telemetry, no fallback to remote.

We talk to Ollama's native ``/api/chat`` endpoint (more capable than
the OpenAI-compatible shim). Ollama also exposes ``/v1/chat/completions``
for OpenAI-compatible clients — Wave 1+ might add a flag to use that
path for OpenAI tool-format reuse.
"""
from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from typing import Any

from ..request import LLMRequest, LLMResponse, Message, Usage
from ..retry import retry_async
from ..streaming import make_chunk
from .base import ProviderAdapter, ProviderConfigError

_PROVIDER = "ollama"
_DEFAULT_HOST = "http://localhost:11434"


class OllamaAdapter(ProviderAdapter):
    """Local Ollama HTTP adapter."""

    name = _PROVIDER
    model_prefix = "ollama:"
    supports_prompt_caching = False
    supports_tools = True  # Ollama supports tools for models that do (llama3.1+, qwen2.5+)
    supports_streaming = True
    secret_name = None  # local — no auth
    env_var = None

    @staticmethod
    def _host() -> str:
        return os.environ.get("OLLAMA_HOST", _DEFAULT_HOST).rstrip("/")

    # ── Translation ──────────────────────────────────────────────────

    @staticmethod
    def _to_messages(request: LLMRequest) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        if request.system:
            out.append({"role": "system", "content": request.system})
        for msg in request.messages:
            out.append({"role": msg.role, "content": msg.content})
        return out

    def _build_payload(self, request: LLMRequest, *, stream: bool
                       ) -> dict[str, Any]:
        opts: dict[str, Any] = {"num_predict": request.max_tokens}
        if request.temperature is not None:
            opts["temperature"] = request.temperature
        payload: dict[str, Any] = {
            "model": self._strip_prefix(request.model),
            "messages": self._to_messages(request),
            "stream": stream,
            "options": opts,
        }
        if request.tools:
            payload["tools"] = request.tools
        return payload

    @staticmethod
    def _extract_usage(data: dict[str, Any]) -> Usage:
        # Ollama returns prompt_eval_count + eval_count (token counts).
        return Usage(
            input_tokens=int(data.get("prompt_eval_count") or 0),
            output_tokens=int(data.get("eval_count") or 0),
        )

    @staticmethod
    def _client():
        try:
            import httpx  # type: ignore[import-not-found]
        except ImportError as exc:
            raise ProviderConfigError(
                "httpx not installed (pip install httpx)") from exc
        return httpx

    # ── Public ───────────────────────────────────────────────────────

    async def call_async(self, request: LLMRequest) -> LLMResponse:
        httpx = self._client()

        @retry_async()
        async def _do() -> LLMResponse:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(
                    f"{self._host()}/api/chat",
                    json=self._build_payload(request, stream=False),
                )
                resp.raise_for_status()
                data = resp.json()
            msg = data.get("message") or {}
            return LLMResponse(
                content=msg.get("content", "") or "",
                usage=self._extract_usage(data),
                provider=_PROVIDER,
                model=request.model,
                finish_reason="length" if data.get("done_reason") == "length" else "stop",
                raw=data,
            )

        return await _do()

    async def stream_async(self, request: LLMRequest
                           ) -> AsyncIterator[LLMResponse]:
        """Ollama streams NDJSON (one JSON object per line) rather than SSE.
        Each line is a partial message with a ``done`` bool flag.
        """
        httpx = self._client()
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream(
                "POST", f"{self._host()}/api/chat",
                json=self._build_payload(request, stream=True),
            ) as resp:
                resp.raise_for_status()
                final_usage = Usage()
                finish = "stop"
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    msg = data.get("message") or {}
                    text = msg.get("content", "") or ""
                    if text:
                        yield make_chunk(text, provider=_PROVIDER,
                                         model=request.model)
                    if data.get("done"):
                        final_usage = self._extract_usage(data)
                        if data.get("done_reason") == "length":
                            finish = "length"
                yield LLMResponse(
                    content="", provider=_PROVIDER, model=request.model,
                    finish_reason=finish, usage=final_usage,  # type: ignore[arg-type]
                )


__all__ = ["OllamaAdapter"]
