"""AWS Bedrock adapter via the Converse API.

Routing prefix: ``bedrock:`` — suffix is the AWS ``modelId``, e.g.
``bedrock:anthropic.claude-3-5-sonnet-20240620-v1:0``,
``bedrock:meta.llama3-1-70b-instruct-v1:0``,
``bedrock:amazon.titan-text-premier-v1:0``.

We use the unified **Converse API** (vs invoke_model) so this single
adapter handles every Bedrock-hosted foundation model with one shape.

Auth: boto3 default credential chain (env / shared/credentials / IAM
role / SSO). Per V3 #9 (vault-only secrets) Wave 1 wraps this in a
``shared.secrets.get_aws_credentials("llm/bedrock")`` shim that returns
ephemeral STS credentials minted from a vault-held role assumption.
No env-var override is exposed here — boto3's resolver already does that.

Sync SDK only (boto3 has no native asyncio); we wrap in
``asyncio.to_thread`` to avoid blocking the event loop.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from ..request import LLMRequest, LLMResponse, Message, ToolCall, Usage
from ..retry import retry_async
from ..streaming import make_chunk
from .base import ProviderAdapter, ProviderConfigError

_PROVIDER = "bedrock"


class BedrockAdapter(ProviderAdapter):
    """AWS Bedrock Converse API adapter."""

    name = _PROVIDER
    model_prefix = "bedrock:"
    supports_prompt_caching = False  # Bedrock prompt caching is per-model + still rolling out
    supports_tools = True
    supports_streaming = True
    # boto3 uses its own credential chain; secret_name is documented for
    # Wave 1 when ``shared/secrets`` mints STS credentials.
    secret_name = "llm/bedrock_role_arn"
    env_var = None  # boto3 reads AWS_* itself; we don't shadow.

    # ── Translation ──────────────────────────────────────────────────

    @staticmethod
    def _to_converse_messages(messages: list[Message]
                              ) -> list[dict[str, Any]]:
        """Converse API messages: roles user/assistant only; content is a
        list of blocks like ``[{"text": "..."}]``. Tool messages render
        as user toolResult blocks (Wave 1 properly handles that)."""
        out: list[dict[str, Any]] = []
        for msg in messages:
            if msg.role == "system":
                continue  # handled separately
            role = "user" if msg.role == "tool" else msg.role
            out.append({"role": role, "content": [{"text": msg.content}]})
        return out

    @staticmethod
    def _to_system_blocks(request: LLMRequest
                          ) -> list[dict[str, Any]] | None:
        sys_parts: list[str] = []
        if request.system:
            sys_parts.append(request.system)
        for msg in request.messages:
            if msg.role == "system":
                sys_parts.append(msg.content)
        if not sys_parts:
            return None
        return [{"text": "\n\n".join(sys_parts)}]

    def _build_payload(self, request: LLMRequest) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "modelId": self._strip_prefix(request.model),
            "messages": self._to_converse_messages(request.messages),
            "inferenceConfig": {"maxTokens": request.max_tokens},
        }
        sys = self._to_system_blocks(request)
        if sys:
            payload["system"] = sys
        if request.temperature is not None:
            payload["inferenceConfig"]["temperature"] = request.temperature
        if request.tools:
            # Converse API tool spec: {"toolSpec": {"name", "description",
            # "inputSchema": {"json": {...}}}}. We pass-through if already
            # in that shape; else wrap.
            payload["toolConfig"] = {"tools": [
                t if "toolSpec" in t else {"toolSpec": t}
                for t in request.tools
            ]}
        return payload

    @staticmethod
    def _extract_content(resp: dict[str, Any]) -> tuple[str, list[ToolCall] | None]:
        out_msg = (resp.get("output") or {}).get("message") or {}
        text_parts: list[str] = []
        tools: list[ToolCall] = []
        for block in out_msg.get("content") or []:
            if "text" in block:
                text_parts.append(block["text"])
            elif "toolUse" in block:
                tu = block["toolUse"]
                tools.append(ToolCall(
                    id=tu.get("toolUseId", ""),
                    name=tu.get("name", ""),
                    arguments=tu.get("input", {}),
                ))
        return "".join(text_parts), (tools or None)

    @staticmethod
    def _extract_usage(resp: dict[str, Any]) -> Usage:
        u = resp.get("usage") or {}
        return Usage(
            input_tokens=int(u.get("inputTokens") or 0),
            output_tokens=int(u.get("outputTokens") or 0),
        )

    @staticmethod
    def _map_stop_reason(reason: Any) -> str:
        if reason == "tool_use":
            return "tool_use"
        if reason == "max_tokens":
            return "length"
        return "stop"

    # ── Client ───────────────────────────────────────────────────────

    def _make_client(self) -> Any:
        try:
            import boto3  # type: ignore[import-not-found]
        except ImportError as exc:
            raise ProviderConfigError(
                "boto3 not installed (pip install boto3)") from exc
        # Region resolution defers to boto3's chain (AWS_REGION / config /
        # IMDS). Customers passing arbitrary models will need to set this.
        return boto3.client("bedrock-runtime")

    # ── Public ───────────────────────────────────────────────────────

    async def call_async(self, request: LLMRequest) -> LLMResponse:
        @retry_async()
        async def _do() -> LLMResponse:
            client = self._make_client()
            payload = self._build_payload(request)
            resp = await asyncio.to_thread(client.converse, **payload)
            text, tools = self._extract_content(resp)
            return LLMResponse(
                content=text,
                tool_calls=tools,
                usage=self._extract_usage(resp),
                provider=_PROVIDER,
                model=request.model,
                finish_reason=self._map_stop_reason(  # type: ignore[arg-type]
                    resp.get("stopReason")),
                raw=resp,
            )

        return await _do()

    async def stream_async(self, request: LLMRequest
                           ) -> AsyncIterator[LLMResponse]:
        """Bedrock ``converse_stream`` returns an EventStream of dict events.

        We pump it on a worker thread and bridge to async via a queue.
        boto3's EventStream isn't async-iterable, hence this dance.
        """
        client = self._make_client()
        payload = self._build_payload(request)
        # Synchronous call returns the open stream; iteration is blocking.
        stream_resp = await asyncio.to_thread(client.converse_stream, **payload)
        event_stream = stream_resp.get("stream")
        if event_stream is None:
            yield make_chunk("", provider=_PROVIDER, model=request.model,
                             finish_reason="error")
            return

        queue: asyncio.Queue[Any] = asyncio.Queue()
        _SENTINEL = object()
        loop = asyncio.get_running_loop()

        def _pump() -> None:
            try:
                for event in event_stream:
                    asyncio.run_coroutine_threadsafe(
                        queue.put(event), loop).result()
            finally:
                asyncio.run_coroutine_threadsafe(
                    queue.put(_SENTINEL), loop).result()

        pump_task = asyncio.create_task(asyncio.to_thread(_pump))
        try:
            finish: str = "stop"
            usage = Usage()
            while True:
                event = await queue.get()
                if event is _SENTINEL:
                    break
                if "contentBlockDelta" in event:
                    delta = event["contentBlockDelta"].get("delta", {})
                    text = delta.get("text", "")
                    if text:
                        yield make_chunk(text, provider=_PROVIDER,
                                         model=request.model)
                elif "messageStop" in event:
                    finish = self._map_stop_reason(  # type: ignore[assignment]
                        event["messageStop"].get("stopReason"))
                elif "metadata" in event:
                    u = (event["metadata"].get("usage") or {})
                    usage = Usage(
                        input_tokens=int(u.get("inputTokens") or 0),
                        output_tokens=int(u.get("outputTokens") or 0),
                    )
            yield LLMResponse(
                content="", provider=_PROVIDER, model=request.model,
                finish_reason=finish, usage=usage,  # type: ignore[arg-type]
            )
        finally:
            await pump_task


__all__ = ["BedrockAdapter"]
