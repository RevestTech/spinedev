"""Qwen adapter via Alibaba DashScope.

Routing prefix: ``qwen:`` — suffix is the DashScope model name:
``qwen:qwen-max``, ``qwen:qwen-plus``, ``qwen:qwen2.5-72b-instruct``.

DashScope exposes an OpenAI-compatible REST endpoint at
``https://dashscope-intl.aliyuncs.com/compatible-mode/v1`` (international)
or ``https://dashscope.aliyuncs.com/compatible-mode/v1`` (CN). We use
that path so the wire format is identical to OpenAI Chat Completions —
this keeps the adapter small and SDK-free (no ``dashscope`` dep needed).

Auth: ``DASHSCOPE_API_KEY`` env var (Wave 0); Wave 1 vault key
``llm/dashscope_api_key``. Endpoint base via ``DASHSCOPE_BASE_URL``.
"""
from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from typing import Any

from ..request import LLMRequest, LLMResponse, Message, ToolCall, Usage
from ..retry import retry_async
from ..streaming import iter_sse_chunks, make_chunk
from .base import ProviderAdapter, ProviderConfigError

_PROVIDER = "qwen"
_DEFAULT_BASE = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"


class QwenAdapter(ProviderAdapter):
    """Qwen / DashScope adapter (OpenAI-compatible wire format)."""

    name = _PROVIDER
    model_prefix = "qwen:"
    supports_prompt_caching = False
    supports_tools = True
    supports_streaming = True
    secret_name = "llm/dashscope_api_key"
    env_var = "DASHSCOPE_API_KEY"

    @staticmethod
    def _base_url() -> str:
        return os.environ.get("DASHSCOPE_BASE_URL", _DEFAULT_BASE).rstrip("/")

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
        payload: dict[str, Any] = {
            "model": self._strip_prefix(request.model),
            "messages": self._to_messages(request),
            "max_tokens": request.max_tokens,
            "stream": stream,
        }
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.tools:
            payload["tools"] = [
                t if "type" in t else {"type": "function", "function": t}
                for t in request.tools
            ]
        return payload

    @staticmethod
    def _extract_usage(data: dict[str, Any]) -> Usage:
        u = data.get("usage") or {}
        return Usage(
            input_tokens=int(u.get("prompt_tokens") or 0),
            output_tokens=int(u.get("completion_tokens") or 0),
        )

    @staticmethod
    def _extract_tool_calls(message: dict[str, Any]) -> list[ToolCall] | None:
        tc = message.get("tool_calls") or []
        if not tc:
            return None
        out: list[ToolCall] = []
        for t in tc:
            fn = t.get("function") or {}
            out.append(ToolCall(
                id=t.get("id", "") or "",
                name=fn.get("name", "") or "",
                arguments=fn.get("arguments", "") or "",
            ))
        return out or None

    @staticmethod
    def _map_finish(reason: Any) -> str:
        if reason in ("tool_calls", "function_call"):
            return "tool_use"
        if reason in ("stop", "length"):
            return reason
        return "stop"

    def _client(self) -> Any:
        try:
            import httpx  # type: ignore[import-not-found]
        except ImportError as exc:
            raise ProviderConfigError(
                "httpx not installed (pip install httpx)") from exc
        return httpx

    def _auth_headers(self) -> dict[str, str]:
        key = self._get_api_key()
        if not key:
            raise ProviderConfigError(
                "no DashScope API key (vault 'llm/dashscope_api_key' or "
                "env DASHSCOPE_API_KEY)")
        return {"Authorization": f"Bearer {key}",
                "Content-Type": "application/json"}

    async def call_async(self, request: LLMRequest) -> LLMResponse:
        httpx = self._client()

        @retry_async()
        async def _do() -> LLMResponse:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(
                    f"{self._base_url()}/chat/completions",
                    headers=self._auth_headers(),
                    json=self._build_payload(request, stream=False),
                )
                resp.raise_for_status()
                data = resp.json()
            choice = (data.get("choices") or [{}])[0]
            msg = choice.get("message") or {}
            return LLMResponse(
                content=msg.get("content", "") or "",
                tool_calls=self._extract_tool_calls(msg),
                usage=self._extract_usage(data),
                provider=_PROVIDER,
                model=request.model,
                finish_reason=self._map_finish(  # type: ignore[arg-type]
                    choice.get("finish_reason")),
                raw=data,
            )

        return await _do()

    async def stream_async(self, request: LLMRequest
                           ) -> AsyncIterator[LLMResponse]:
        httpx = self._client()
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream(
                "POST", f"{self._base_url()}/chat/completions",
                headers=self._auth_headers(),
                json=self._build_payload(request, stream=True),
            ) as resp:
                resp.raise_for_status()
                finish: str = "stop"
                async for event in iter_sse_chunks(resp.aiter_lines()):
                    choice = (event.get("choices") or [{}])[0]
                    delta = choice.get("delta") or {}
                    text = delta.get("content") or ""
                    if text:
                        yield make_chunk(text, provider=_PROVIDER,
                                         model=request.model)
                    if choice.get("finish_reason"):
                        finish = self._map_finish(  # type: ignore[assignment]
                            choice["finish_reason"])
                yield LLMResponse(
                    content="", provider=_PROVIDER, model=request.model,
                    finish_reason=finish, usage=Usage(),  # type: ignore[arg-type]
                )


__all__ = ["QwenAdapter"]
