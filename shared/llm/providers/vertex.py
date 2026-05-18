"""GCP Vertex AI Gemini adapter.

Routing prefix: ``vertex:`` — suffix is the Vertex model name:
``vertex:gemini-2.0-flash-001``, ``vertex:gemini-1.5-pro-002``, etc.

Wave 0 covers Gemini-family models on Vertex. Anthropic-on-Vertex and
Mistral-on-Vertex are also routed here when the model name maps to a
Vertex endpoint — for those, the customer should prefer the native
``claude-*`` prefix (and we'll add a Vertex backend toggle in Wave 1).

Auth: application default credentials (ADC) via
``google.cloud.aiplatform``. Project ID + location resolved from
``GOOGLE_CLOUD_PROJECT`` / ``GOOGLE_CLOUD_REGION`` env vars OR explicit
bundle config. Per #9, Wave 1 wires through vault-minted service account
keys.

Sync SDK — wrapped with ``asyncio.to_thread``.
"""
from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from typing import Any

from ..request import LLMRequest, LLMResponse, Message, ToolCall, Usage
from ..retry import retry_async
from ..streaming import make_chunk
from .base import ProviderAdapter, ProviderConfigError

_PROVIDER = "vertex"


class VertexAdapter(ProviderAdapter):
    """GCP Vertex AI Gemini adapter."""

    name = _PROVIDER
    model_prefix = "vertex:"
    supports_prompt_caching = False  # Vertex context caching is a separate API; Wave 1+
    supports_tools = True
    supports_streaming = True
    secret_name = "llm/vertex_service_account"
    env_var = None  # ADC chain handles auth; project/region read separately.

    # ── Translation ──────────────────────────────────────────────────

    @staticmethod
    def _to_contents(messages: list[Message]) -> list[dict[str, Any]]:
        """Gemini ``contents`` format: list of {role, parts: [{text}]}.

        Gemini roles are ``user`` / ``model`` (not assistant). System
        prompts go in a separate ``system_instruction`` argument.
        """
        out: list[dict[str, Any]] = []
        for msg in messages:
            if msg.role == "system":
                continue
            role = "model" if msg.role == "assistant" else "user"
            out.append({"role": role, "parts": [{"text": msg.content}]})
        return out

    @staticmethod
    def _system_instruction(request: LLMRequest) -> str | None:
        parts: list[str] = []
        if request.system:
            parts.append(request.system)
        for msg in request.messages:
            if msg.role == "system":
                parts.append(msg.content)
        return "\n\n".join(parts) if parts else None

    def _build_generation_config(self, request: LLMRequest) -> dict[str, Any]:
        cfg: dict[str, Any] = {"max_output_tokens": request.max_tokens}
        if request.temperature is not None:
            cfg["temperature"] = request.temperature
        return cfg

    @staticmethod
    def _extract_content(resp: Any) -> tuple[str, list[ToolCall] | None]:
        # Vertex SDK exposes .candidates[0].content.parts; each part has
        # .text or .function_call.
        cands = getattr(resp, "candidates", None) or []
        if not cands:
            return "", None
        content = getattr(cands[0], "content", None)
        parts = getattr(content, "parts", None) or []
        text_parts: list[str] = []
        tools: list[ToolCall] = []
        for part in parts:
            txt = getattr(part, "text", None)
            if txt:
                text_parts.append(txt)
            fc = getattr(part, "function_call", None)
            if fc is not None:
                tools.append(ToolCall(
                    id=getattr(fc, "name", "") or "",  # Gemini doesn't issue ids
                    name=getattr(fc, "name", "") or "",
                    arguments=dict(getattr(fc, "args", {}) or {}),
                ))
        return "".join(text_parts), (tools or None)

    @staticmethod
    def _extract_usage(resp: Any) -> Usage:
        u = getattr(resp, "usage_metadata", None)
        if u is None:
            return Usage()
        return Usage(
            input_tokens=int(getattr(u, "prompt_token_count", 0) or 0),
            output_tokens=int(getattr(u, "candidates_token_count", 0) or 0),
            cache_read_tokens=int(
                getattr(u, "cached_content_token_count", 0) or 0),
        )

    @staticmethod
    def _map_finish(reason: Any) -> str:
        # FinishReason enum in Vertex: STOP / MAX_TOKENS / SAFETY / RECITATION / OTHER.
        name = str(reason).upper().split(".")[-1] if reason is not None else "STOP"
        if name == "MAX_TOKENS":
            return "length"
        return "stop"

    # ── Client ───────────────────────────────────────────────────────

    def _make_model(self, request: LLMRequest) -> Any:
        try:
            from google.cloud import aiplatform  # type: ignore[import-not-found]
            from vertexai.generative_models import GenerativeModel  # type: ignore[import-not-found]
            import vertexai  # type: ignore[import-not-found]
        except ImportError as exc:
            raise ProviderConfigError(
                "google-cloud-aiplatform not installed "
                "(pip install google-cloud-aiplatform)") from exc
        project = os.environ.get("GOOGLE_CLOUD_PROJECT")
        location = os.environ.get("GOOGLE_CLOUD_REGION", "us-central1")
        if not project:
            raise ProviderConfigError(
                "GOOGLE_CLOUD_PROJECT must be set (Wave 1: read from bundle)")
        vertexai.init(project=project, location=location)
        sys_inst = self._system_instruction(request)
        model_name = self._strip_prefix(request.model)
        kwargs: dict[str, Any] = {}
        if sys_inst:
            kwargs["system_instruction"] = sys_inst
        if request.tools:
            kwargs["tools"] = request.tools  # pass-through to Vertex SDK
        return GenerativeModel(model_name, **kwargs)

    # ── Public ───────────────────────────────────────────────────────

    async def call_async(self, request: LLMRequest) -> LLMResponse:
        @retry_async()
        async def _do() -> LLMResponse:
            model = self._make_model(request)
            resp = await asyncio.to_thread(
                model.generate_content,
                self._to_contents(request.messages),
                generation_config=self._build_generation_config(request),
            )
            text, tools = self._extract_content(resp)
            finish_reason = "stop"
            cands = getattr(resp, "candidates", None) or []
            if cands:
                finish_reason = self._map_finish(
                    getattr(cands[0], "finish_reason", None))
            return LLMResponse(
                content=text,
                tool_calls=tools,
                usage=self._extract_usage(resp),
                provider=_PROVIDER,
                model=request.model,
                finish_reason=finish_reason,  # type: ignore[arg-type]
                raw=resp,
            )

        return await _do()

    async def stream_async(self, request: LLMRequest
                           ) -> AsyncIterator[LLMResponse]:
        model = self._make_model(request)
        # ``generate_content(stream=True)`` returns a sync iterator; pump it.
        stream_iter = await asyncio.to_thread(
            model.generate_content,
            self._to_contents(request.messages),
            generation_config=self._build_generation_config(request),
            stream=True,
        )

        queue: asyncio.Queue[Any] = asyncio.Queue()
        _SENTINEL = object()
        loop = asyncio.get_running_loop()

        def _pump() -> None:
            try:
                for chunk in stream_iter:
                    asyncio.run_coroutine_threadsafe(
                        queue.put(chunk), loop).result()
            finally:
                asyncio.run_coroutine_threadsafe(
                    queue.put(_SENTINEL), loop).result()

        pump_task = asyncio.create_task(asyncio.to_thread(_pump))
        try:
            last_resp: Any = None
            while True:
                chunk = await queue.get()
                if chunk is _SENTINEL:
                    break
                last_resp = chunk
                text, _tools = self._extract_content(chunk)
                if text:
                    yield make_chunk(text, provider=_PROVIDER,
                                     model=request.model)
            finish = "stop"
            usage = Usage()
            if last_resp is not None:
                cands = getattr(last_resp, "candidates", None) or []
                if cands:
                    finish = self._map_finish(  # type: ignore[assignment]
                        getattr(cands[0], "finish_reason", None))
                usage = self._extract_usage(last_resp)
            yield LLMResponse(
                content="", provider=_PROVIDER, model=request.model,
                finish_reason=finish, usage=usage,  # type: ignore[arg-type]
            )
        finally:
            await pump_task


__all__ = ["VertexAdapter"]
