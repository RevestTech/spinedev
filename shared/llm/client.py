"""Single LLM call surface — the one function every Wave 1+ caller uses.

Per V3 #2 (LLM-agnostic by architecture): every LLM call MUST flow
through ``call`` / ``call_async``. Adapters in ``providers/`` translate
to provider-native shapes. Routing is prefix-based on ``request.model``
(see ``providers/__init__.py`` for the lock-list).

This module deliberately does NOT:
  - Choose models (that's ``shared/cost/router.py`` — it produces a
    ``model_id`` string we accept here).
  - Project costs (that's ``shared/cost/router.py`` reading our ``Usage``).
  - Write audit rows (the caller's daemon owns audit emission so we
    don't couple ``shared/llm/`` to ``shared/audit/``).
  - Validate phase / severity gates (that's ``shared/validation/``).

It DOES:
  - Validate the request envelope.
  - Resolve the adapter via the registry.
  - Dispatch ``call_async`` or ``stream_async``.
  - Provide a sync wrapper for non-async callers (CLI scripts, tests).
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import overload

from .providers import get_provider
from .request import LLMRequest, LLMResponse


async def call_async(request: LLMRequest) -> LLMResponse:
    """Unary LLM call. Use this from any async code path.

    Raises:
      - ``UnknownProviderError`` if ``request.model`` has no matching prefix.
      - ``ProviderConfigError`` for missing credentials / missing SDK.
      - ``ProviderError`` (or subclass) for non-retryable failures.
      - Whatever the underlying SDK raises after retry exhaustion.
    """
    if request.stream:
        # Stream mode invoked through ``call_async`` collapses to a unary
        # response by aggregating the stream. Callers that want true
        # streaming should use ``stream_async`` directly.
        from .streaming import aggregate
        return await aggregate(stream_async(request))
    adapter = get_provider(request.model)
    return await adapter.call_async(request)


async def stream_async(request: LLMRequest) -> AsyncIterator[LLMResponse]:
    """Streaming LLM call. Yields delta chunks; final chunk carries
    ``finish_reason`` and authoritative ``usage`` when the provider
    reports it (see ``streaming.py``)."""
    adapter = get_provider(request.model)
    # ``stream_async`` is itself an async generator method on the adapter.
    async for chunk in adapter.stream_async(request):
        yield chunk


def call(request: LLMRequest) -> LLMResponse:
    """Sync wrapper around ``call_async`` for non-async callers.

    Behavior:
      - If called from outside a running event loop: starts one via
        ``asyncio.run`` (the normal CLI / script path).
      - If called from inside a running loop: raises ``RuntimeError``.
        Use ``call_async`` directly in async code.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None and loop.is_running():
        raise RuntimeError(
            "shared.llm.call() called from inside a running event loop; "
            "use call_async() instead")
    return asyncio.run(call_async(request))


__all__ = ["call", "call_async", "stream_async"]
