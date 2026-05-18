"""Provider adapter registry + prefix-based routing.

The routing rules are LOCKED per V3 #2 and ``shared/llm/`` README:

    claude-*    -> AnthropicAdapter
    gpt-*       -> OpenAIAdapter
    bedrock:*   -> BedrockAdapter   (suffix is the AWS modelId)
    vertex:*    -> VertexAdapter    (suffix is the Vertex model name)
    ollama:*    -> OllamaAdapter    (suffix is the local tag)
    qwen:*      -> QwenAdapter      (suffix is the DashScope model name)
    vllm:*      -> VllmAdapter      (suffix is the served model name)

Unknown prefixes raise ``UnknownProviderError`` — no implicit default.
Customers extend via ``register_provider``.

Adapters are constructed lazily (one instance per provider, cached) so
SDK imports stay deferred to first use.
"""
from __future__ import annotations

import logging
from typing import Callable

from .base import ProviderAdapter, ProviderConfigError, ProviderError

logger = logging.getLogger(__name__)


class UnknownProviderError(ProviderError):
    """Raised when ``model`` doesn't match any registered prefix."""


# Registry: list of (prefix, factory). Order = registration order; first
# match wins. Empty-prefix entries serve as catch-alls and should be
# appended last (we don't ship any in Wave 0).
_REGISTRY: list[tuple[str, Callable[[], ProviderAdapter]]] = []
_INSTANCES: dict[str, ProviderAdapter] = {}


def register_provider(prefix: str,
                      factory: Callable[[], ProviderAdapter]) -> None:
    """Register a new adapter factory.

    Idempotent on (prefix, factory) — duplicate registrations are
    silently coalesced to support test re-imports. Customer plugins
    that need to override a built-in MUST first call
    ``_REGISTRY.clear()`` or pop their entry directly.
    """
    for existing_prefix, existing_factory in _REGISTRY:
        if existing_prefix == prefix and existing_factory is factory:
            return
    _REGISTRY.append((prefix, factory))


def _load_builtin_providers() -> None:
    """Register the seven Wave 0 built-ins. Idempotent."""
    # Lazy imports so a missing optional SDK in any one adapter doesn't
    # break registry initialization.
    from .anthropic import AnthropicAdapter
    from .bedrock import BedrockAdapter
    from .ollama import OllamaAdapter
    from .openai import OpenAIAdapter
    from .qwen import QwenAdapter
    from .vertex import VertexAdapter
    from .vllm import VllmAdapter

    for prefix, cls in (
        ("claude-", AnthropicAdapter),
        ("gpt-", OpenAIAdapter),
        ("bedrock:", BedrockAdapter),
        ("vertex:", VertexAdapter),
        ("ollama:", OllamaAdapter),
        ("qwen:", QwenAdapter),
        ("vllm:", VllmAdapter),
    ):
        register_provider(prefix, cls)


def get_provider(model: str) -> ProviderAdapter:
    """Return (cached) adapter instance for ``model``.

    Routing: longest matching prefix wins, then registration order
    breaks ties. Built-ins use unambiguous prefixes (the ``:``-suffixed
    schemes can't collide with the bare ``claude-`` / ``gpt-`` prefixes).
    """
    if not _REGISTRY:
        _load_builtin_providers()

    # Longest-prefix match: e.g. ``"vertex:gemini-2.0"`` shouldn't ever
    # match a hypothetical ``"v"`` prefix. Ties broken by registration order.
    candidates = [(prefix, factory) for prefix, factory in _REGISTRY
                  if not prefix or model.startswith(prefix)]
    if not candidates:
        raise UnknownProviderError(
            f"no provider registered for model {model!r}; known prefixes: "
            f"{[p for p, _ in _REGISTRY]}")
    # Sort by prefix length descending; stable for registration-order tiebreak.
    candidates.sort(key=lambda pf: len(pf[0]), reverse=True)
    _, factory = candidates[0]
    key = factory.__module__ + "." + factory.__qualname__
    if key not in _INSTANCES:
        _INSTANCES[key] = factory()
    return _INSTANCES[key]


def _reset_registry_for_tests() -> None:
    """Test-only: drop registered providers + cached instances.

    Used by ``tests/test_client_routing.py`` to install mocks. Not part
    of the public API.
    """
    _REGISTRY.clear()
    _INSTANCES.clear()


__all__ = [
    "ProviderAdapter",
    "ProviderError",
    "ProviderConfigError",
    "UnknownProviderError",
    "register_provider",
    "get_provider",
]
