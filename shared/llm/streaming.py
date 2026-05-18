"""SSE / streaming multiplexing helpers.

Wave 0 contract: every adapter's ``stream_async`` yields ``LLMResponse``
chunks, where each chunk's ``content`` carries only the *delta* and the
final chunk carries a non-default ``finish_reason``. ``usage`` populates
on the chunks the provider reports it on (typically only the final chunk).

This module provides:

  - ``aggregate``: collect a stream into a single terminal ``LLMResponse``
    (useful when the caller passed ``stream=True`` but later decides to
    collapse — e.g., tool-call interception).
  - ``parse_sse_line``: minimal SSE frame parser for adapters that talk
    to OpenAI-compatible HTTP endpoints (vLLM, Ollama in compat mode).
  - ``iter_sse_chunks``: convert an httpx aiter_lines stream into parsed
    SSE events (``data:`` lines, ``[DONE]`` sentinel, JSON-decoded).

Why hand-rolled SSE: SDKs handle SSE for their own provider; for HTTP
adapters (Ollama, vLLM) we don't want to require a third-party SSE lib.
"""
from __future__ import annotations

import json
from collections.abc import AsyncIterable, AsyncIterator
from typing import Any

from .request import FinishReason, LLMResponse, ToolCall, Usage

SSE_DONE_SENTINEL = "[DONE]"


async def aggregate(stream: AsyncIterable[LLMResponse]) -> LLMResponse:
    """Collapse a stream of delta chunks into a single terminal response.

    Concatenates ``content`` deltas; takes the LAST chunk's ``usage``,
    ``finish_reason``, ``provider``, ``model``, and ``tool_calls`` (the
    final chunk is authoritative). If the stream produces zero chunks,
    returns an empty response with ``finish_reason='error'``.
    """
    text_parts: list[str] = []
    last: LLMResponse | None = None
    async for chunk in stream:
        if chunk.content:
            text_parts.append(chunk.content)
        last = chunk
    if last is None:
        return LLMResponse(
            content="", provider="unknown", model="unknown",
            finish_reason="error", usage=Usage())
    return LLMResponse(
        content="".join(text_parts),
        tool_calls=last.tool_calls,
        usage=last.usage,
        provider=last.provider,
        model=last.model,
        finish_reason=last.finish_reason,
        raw=last.raw,
    )


def parse_sse_line(line: str) -> dict[str, Any] | str | None:
    """Parse one line of an SSE stream.

    Returns:
      - ``None`` for empty / comment / non-data lines (skip)
      - The string ``"[DONE]"`` for the OpenAI / vLLM terminator
      - A parsed dict for ``data: {...}`` JSON frames

    Raises ``json.JSONDecodeError`` if data is malformed JSON.
    """
    line = line.strip()
    if not line or line.startswith(":"):
        return None
    if not line.startswith("data:"):
        # ``event:`` / ``id:`` / ``retry:`` lines — adapters typically ignore
        return None
    payload = line[len("data:"):].strip()
    if payload == SSE_DONE_SENTINEL:
        return SSE_DONE_SENTINEL
    return json.loads(payload)


async def iter_sse_chunks(line_iter: AsyncIterator[str]
                          ) -> AsyncIterator[dict[str, Any]]:
    """Yield parsed JSON dicts from an SSE line iterator.

    Stops at the ``[DONE]`` sentinel. Skips non-data frames. Adapters
    typically feed ``httpx.Response.aiter_lines()`` into this.
    """
    async for raw_line in line_iter:
        parsed = parse_sse_line(raw_line)
        if parsed is None:
            continue
        if parsed == SSE_DONE_SENTINEL:
            return
        if isinstance(parsed, dict):
            yield parsed


def make_chunk(content: str, *, provider: str, model: str,
               finish_reason: FinishReason = "stop",
               usage: Usage | None = None,
               tool_calls: list[ToolCall] | None = None,
               raw: Any | None = None) -> LLMResponse:
    """Adapter convenience for constructing a stream chunk.

    Keeps adapters from importing ``LLMResponse`` / ``Usage`` directly
    when they only need to emit deltas.
    """
    return LLMResponse(
        content=content, provider=provider, model=model,
        finish_reason=finish_reason, usage=usage or Usage(),
        tool_calls=tool_calls, raw=raw,
    )


__all__ = [
    "SSE_DONE_SENTINEL",
    "aggregate",
    "parse_sse_line",
    "iter_sse_chunks",
    "make_chunk",
]
