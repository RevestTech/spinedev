"""OpenAI Chat Completions adapter.

Wave 0 uses ``chat.completions.create`` (broad model coverage, mature
SDK). Wave 1 may switch to the Responses API for built-in tools / file
support — keep the adapter contract stable when that happens.

Auth: ``OPENAI_API_KEY`` env var (Wave 0); Wave 1 swaps to
``shared.secrets.get_secret("llm/openai_api_key")``.
"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from ..request import LLMRequest, LLMResponse, Message, ToolCall, Usage
from ..retry import retry_async
from ..streaming import make_chunk
from .base import ProviderAdapter, ProviderConfigError

_PROVIDER = "openai"


class OpenAIAdapter(ProviderAdapter):
    """OpenAI Chat Completions adapter."""

    name = _PROVIDER
    model_prefix = "gpt-"
    supports_prompt_caching = False  # OpenAI caching is automatic + no API hook
    supports_tools = True
    supports_streaming = True
    secret_name = "llm/openai_api_key"
    env_var = "OPENAI_API_KEY"

    # ── Translation ──────────────────────────────────────────────────

    @staticmethod
    def _to_messages(request: LLMRequest) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        if request.system:
            out.append({"role": "system", "content": request.system})
        for msg in request.messages:
            m: dict[str, Any] = {"role": msg.role, "content": msg.content}
            if msg.role == "tool" and msg.tool_call_id:
                m["tool_call_id"] = msg.tool_call_id
            if msg.name:
                m["name"] = msg.name
            out.append(m)
        return out

    def _build_payload(self, request: LLMRequest, *, stream: bool
                       ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": self._to_messages(request),
            "max_tokens": request.max_tokens,
            "stream": stream,
        }
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.tools:
            # OpenAI tool format: {"type": "function", "function": {...}}.
            # We pass-through; callers can supply either raw OpenAI tools or
            # the universal {"name", "description", "input_schema"} shape
            # (translated below).
            payload["tools"] = [
                t if "type" in t else {"type": "function", "function": t}
                for t in request.tools
            ]
        return payload

    @staticmethod
    def _extract_usage(resp: Any) -> Usage:
        usage = getattr(resp, "usage", None)
        if usage is None:
            return Usage()
        get = (lambda k: usage.get(k, 0)) if isinstance(usage, dict) \
            else (lambda k: getattr(usage, k, 0))
        return Usage(
            input_tokens=int(get("prompt_tokens") or 0),
            output_tokens=int(get("completion_tokens") or 0),
            # OpenAI reports cached prompt tokens in
            # prompt_tokens_details.cached_tokens on newer SDK versions.
            cache_read_tokens=int(
                (get("prompt_tokens_details") or {}).get("cached_tokens", 0)
                if isinstance(get("prompt_tokens_details"), dict) else 0),
        )

    @staticmethod
    def _extract_tool_calls(message: Any) -> list[ToolCall] | None:
        tc = getattr(message, "tool_calls", None) or (
            message.get("tool_calls") if isinstance(message, dict) else None)
        if not tc:
            return None
        out: list[ToolCall] = []
        for t in tc:
            tid = (t.get("id") if isinstance(t, dict) else getattr(t, "id", ""))
            fn = (t.get("function") if isinstance(t, dict)
                  else getattr(t, "function", None))
            if fn is None:
                continue
            name = (fn.get("name") if isinstance(fn, dict)
                    else getattr(fn, "name", ""))
            args = (fn.get("arguments") if isinstance(fn, dict)
                    else getattr(fn, "arguments", ""))
            out.append(ToolCall(id=tid or "", name=name or "",
                                arguments=args or ""))
        return out or None

    @staticmethod
    def _map_finish(reason: Any) -> str:
        if reason in ("stop", "length", "tool_calls", "function_call"):
            return "tool_use" if reason in ("tool_calls", "function_call") \
                else reason
        return "stop"

    # ── Client ───────────────────────────────────────────────────────

    def _make_client(self) -> Any:
        try:
            import openai  # type: ignore[import-not-found]
        except ImportError as exc:
            raise ProviderConfigError(
                "openai SDK not installed (pip install openai)") from exc
        api_key = self._get_api_key()
        if not api_key:
            raise ProviderConfigError(
                "no OpenAI API key (vault 'llm/openai_api_key' or env OPENAI_API_KEY)")
        return openai.AsyncOpenAI(api_key=api_key)

    # ── Public ───────────────────────────────────────────────────────

    async def call_async(self, request: LLMRequest) -> LLMResponse:
        @retry_async()
        async def _do() -> LLMResponse:
            client = self._make_client()
            resp = await client.chat.completions.create(
                **self._build_payload(request, stream=False))
            choice = resp.choices[0] if getattr(resp, "choices", None) else None
            msg = getattr(choice, "message", None)
            content = (getattr(msg, "content", None) or "") if msg else ""
            return LLMResponse(
                content=content,
                tool_calls=self._extract_tool_calls(msg) if msg else None,
                usage=self._extract_usage(resp),
                provider=_PROVIDER,
                model=request.model,
                finish_reason=self._map_finish(  # type: ignore[arg-type]
                    getattr(choice, "finish_reason", None) if choice else None),
                raw=resp,
            )

        return await _do()

    async def stream_async(self, request: LLMRequest
                           ) -> AsyncIterator[LLMResponse]:
        client = self._make_client()
        stream = await client.chat.completions.create(
            **self._build_payload(request, stream=True))
        finish: str = "stop"
        tool_calls_buf: dict[int, dict[str, Any]] = {}
        async for chunk in stream:
            choice = chunk.choices[0] if getattr(chunk, "choices", None) else None
            if choice is None:
                continue
            delta = getattr(choice, "delta", None)
            text = (getattr(delta, "content", None) or "") if delta else ""
            if text:
                yield make_chunk(text, provider=_PROVIDER, model=request.model)
            # Tool-call streaming arrives in fragments — accumulate by index
            dtc = (getattr(delta, "tool_calls", None) or []) if delta else []
            for tc in dtc:
                idx = getattr(tc, "index", 0)
                slot = tool_calls_buf.setdefault(
                    idx, {"id": "", "name": "", "arguments": ""})
                if getattr(tc, "id", None):
                    slot["id"] = tc.id
                fn = getattr(tc, "function", None)
                if fn is not None:
                    if getattr(fn, "name", None):
                        slot["name"] = fn.name
                    if getattr(fn, "arguments", None):
                        slot["arguments"] += fn.arguments
            if getattr(choice, "finish_reason", None):
                finish = self._map_finish(choice.finish_reason)
        # Terminal chunk
        tools = ([ToolCall(**v) for v in tool_calls_buf.values()]
                 if tool_calls_buf else None)
        yield LLMResponse(
            content="",
            tool_calls=tools,
            usage=Usage(),  # openai SSE doesn't include usage by default
            provider=_PROVIDER,
            model=request.model,
            finish_reason=finish,  # type: ignore[arg-type]
        )


__all__ = ["OpenAIAdapter"]
