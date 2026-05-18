"""Anthropic adapter — absorbs the prompt-cache logic from
``shared/cost/prompt_cache.py`` (which Wave 1 deletes per V3 triage row).

Prompt caching behavior preserved:
  - ``cache_breakpoints`` is a list of indices into ``messages`` where
    ``cache_control={'type': 'ephemeral'}`` markers are inserted.
  - When ``cache_breakpoints`` is non-empty AND a system prompt is set,
    the system prompt is *always* marked cacheable (the largest win).
  - At most 4 breakpoints per request (Anthropic SDK limit).
  - Indices must be ``>= 0``; deduped + sorted.

Pricing factors (Jan 2026):
  - Cache reads: ~10% of normal input rate
  - Cache writes: ~25% premium over input rate
These belong in ``shared/cost/router.py`` for cost projection — this
adapter only reports the raw token counts in ``Usage``.

Auth: ``ANTHROPIC_API_KEY`` env var (Wave 0); Wave 1 swaps to
``shared.secrets.get_secret("llm/anthropic_api_key")``.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from ..request import LLMRequest, LLMResponse, Message, ToolCall, Usage
from ..retry import retry_async
from ..streaming import make_chunk
from .base import ProviderAdapter, ProviderConfigError

_PROVIDER = "anthropic"
_MAX_CACHE_BREAKPOINTS = 4


class AnthropicAdapter(ProviderAdapter):
    """Anthropic Messages API adapter with prompt-cache support."""

    name = _PROVIDER
    model_prefix = "claude-"
    supports_prompt_caching = True
    supports_tools = True
    supports_streaming = True
    secret_name = "llm/anthropic_api_key"
    env_var = "ANTHROPIC_API_KEY"

    # ── Translation helpers ──────────────────────────────────────────

    @staticmethod
    def _split_system(request: LLMRequest) -> tuple[str | None, list[Message]]:
        """Extract any leading system messages + ``request.system`` into a
        single system prompt. Anthropic wants ``system`` as a top-level field,
        not a message turn."""
        sys_parts: list[str] = []
        if request.system:
            sys_parts.append(request.system)
        rest: list[Message] = []
        for msg in request.messages:
            if msg.role == "system":
                sys_parts.append(msg.content)
            else:
                rest.append(msg)
        sys = "\n\n".join(sys_parts) if sys_parts else None
        return sys, rest

    @staticmethod
    def _validate_breakpoints(bps: list[int] | None,
                              n_messages: int) -> list[int]:
        """Mirror the legacy ``prompt_cache.py`` validator."""
        if not bps:
            return []
        if any(i < 0 for i in bps):
            raise ValueError("cache_breakpoints must be >= 0")
        if any(i >= n_messages for i in bps):
            raise ValueError(
                f"cache_breakpoints out of range (have {n_messages} messages)")
        unique = sorted(set(bps))
        if len(unique) > _MAX_CACHE_BREAKPOINTS:
            raise ValueError(
                f"at most {_MAX_CACHE_BREAKPOINTS} cache breakpoints per "
                "Anthropic call")
        return unique

    def _build_messages(self, messages: list[Message],
                        breakpoints: list[int]) -> list[dict[str, Any]]:
        """Wrap each message's content in a text block; insert
        ``cache_control`` on the marker indices."""
        out: list[dict[str, Any]] = []
        bp_set = set(breakpoints)
        for i, msg in enumerate(messages):
            # Anthropic accepts "user" / "assistant"; "tool" rendered as a
            # user message with tool_result content for now (Wave 1 will
            # add proper tool_result blocks).
            role = "user" if msg.role == "tool" else msg.role
            block: dict[str, Any] = {"type": "text", "text": msg.content}
            if i in bp_set:
                block["cache_control"] = {"type": "ephemeral"}
            out.append({"role": role, "content": [block]})
        return out

    def _build_system_blocks(self, system: str | None,
                             cache: bool) -> list[dict[str, Any]] | None:
        """System prompt as content-block list so we can attach cache_control."""
        if not system:
            return None
        block: dict[str, Any] = {"type": "text", "text": system}
        if cache:
            block["cache_control"] = {"type": "ephemeral"}
        return [block]

    def _build_payload(self, request: LLMRequest) -> dict[str, Any]:
        """Build the kwargs dict for ``client.messages.create``."""
        system, msgs = self._split_system(request)
        bps = self._validate_breakpoints(request.cache_breakpoints, len(msgs))
        payload: dict[str, Any] = {
            "model": request.model,
            "max_tokens": request.max_tokens,
            "messages": self._build_messages(msgs, bps),
        }
        sys_blocks = self._build_system_blocks(system, cache=bool(bps))
        if sys_blocks is not None:
            payload["system"] = sys_blocks
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.tools:
            payload["tools"] = request.tools
        return payload

    @staticmethod
    def _extract_text(content_blocks: Any) -> str:
        """Concatenate ``text`` from a response.content list."""
        parts: list[str] = []
        for block in content_blocks or []:
            text = (block.get("text") if isinstance(block, dict)
                    else getattr(block, "text", None))
            if text:
                parts.append(text)
        return "".join(parts)

    @staticmethod
    def _extract_tool_calls(content_blocks: Any) -> list[ToolCall] | None:
        """Pull tool_use blocks into our universal ToolCall envelope."""
        calls: list[ToolCall] = []
        for block in content_blocks or []:
            btype = (block.get("type") if isinstance(block, dict)
                     else getattr(block, "type", None))
            if btype != "tool_use":
                continue
            bid = (block.get("id") if isinstance(block, dict)
                   else getattr(block, "id", ""))
            bname = (block.get("name") if isinstance(block, dict)
                     else getattr(block, "name", ""))
            binput = (block.get("input") if isinstance(block, dict)
                      else getattr(block, "input", {}))
            calls.append(ToolCall(id=bid or "", name=bname or "",
                                  arguments=binput or {}))
        return calls or None

    @staticmethod
    def _g(usage: Any, key: str, default: int = 0) -> int:
        """Tolerant dict-or-object accessor (SDK has shipped both shapes)."""
        if usage is None:
            return default
        if isinstance(usage, dict):
            return int(usage.get(key, default))
        return int(getattr(usage, key, default))

    def _extract_usage(self, resp: Any) -> Usage:
        usage = getattr(resp, "usage", None) or {}
        return Usage(
            input_tokens=self._g(usage, "input_tokens"),
            output_tokens=self._g(usage, "output_tokens"),
            cache_read_tokens=self._g(usage, "cache_read_input_tokens"),
            cache_write_tokens=self._g(usage, "cache_creation_input_tokens"),
        )

    @staticmethod
    def _map_stop_reason(reason: Any) -> str:
        """Map Anthropic stop_reason to our FinishReason enum."""
        if reason == "tool_use":
            return "tool_use"
        if reason == "max_tokens":
            return "length"
        if reason is None:
            return "stop"
        return "stop"

    # ── Client construction ──────────────────────────────────────────

    def _make_client(self, *, async_mode: bool) -> Any:
        try:
            import anthropic  # type: ignore[import-not-found]
        except ImportError as exc:
            raise ProviderConfigError(
                "anthropic SDK not installed (pip install anthropic)") from exc
        api_key = self._get_api_key()
        if not api_key:
            raise ProviderConfigError(
                "no Anthropic API key (vault key 'llm/anthropic_api_key' "
                "or env ANTHROPIC_API_KEY)")
        if async_mode:
            return anthropic.AsyncAnthropic(api_key=api_key)
        return anthropic.Anthropic(api_key=api_key)

    # ── Public API ───────────────────────────────────────────────────

    async def call_async(self, request: LLMRequest) -> LLMResponse:
        @retry_async()
        async def _do() -> LLMResponse:
            client = self._make_client(async_mode=True)
            payload = self._build_payload(request)
            resp = await client.messages.create(**payload)
            content = self._extract_text(getattr(resp, "content", None))
            tools = self._extract_tool_calls(getattr(resp, "content", None))
            return LLMResponse(
                content=content,
                tool_calls=tools,
                usage=self._extract_usage(resp),
                provider=_PROVIDER,
                model=request.model,
                finish_reason=self._map_stop_reason(  # type: ignore[arg-type]
                    getattr(resp, "stop_reason", None)),
                raw=resp,
            )

        return await _do()

    async def stream_async(self, request: LLMRequest
                           ) -> AsyncIterator[LLMResponse]:
        client = self._make_client(async_mode=True)
        payload = self._build_payload(request)
        # Anthropic's async streaming context manager yields events; we
        # translate ``content_block_delta`` events into chunks and emit
        # a terminal chunk with final usage on ``message_stop``.
        async with client.messages.stream(**payload) as stream:
            final_usage = Usage()
            async for event in stream:
                etype = getattr(event, "type", None)
                if etype == "content_block_delta":
                    delta = getattr(event, "delta", None)
                    text = (delta.get("text") if isinstance(delta, dict)
                            else getattr(delta, "text", None))
                    if text:
                        yield make_chunk(text, provider=_PROVIDER,
                                         model=request.model,
                                         finish_reason="stop")
                elif etype == "message_delta":
                    usage = getattr(event, "usage", None)
                    if usage is not None:
                        final_usage = Usage(
                            input_tokens=self._g(usage, "input_tokens"),
                            output_tokens=self._g(usage, "output_tokens"),
                            cache_read_tokens=self._g(usage, "cache_read_input_tokens"),
                            cache_write_tokens=self._g(usage, "cache_creation_input_tokens"),
                        )
            # Final synthesis from the accumulated message
            final_message = await stream.get_final_message()
            yield LLMResponse(
                content="",  # deltas already emitted; terminal chunk is metadata-only
                tool_calls=self._extract_tool_calls(
                    getattr(final_message, "content", None)),
                usage=self._extract_usage(final_message) or final_usage,
                provider=_PROVIDER,
                model=request.model,
                finish_reason=self._map_stop_reason(  # type: ignore[arg-type]
                    getattr(final_message, "stop_reason", None)),
                raw=final_message,
            )


__all__ = ["AnthropicAdapter"]
