"""shared/llm — single LLM call surface (V3 Wave 0, BUILD-NEW per V3 #2).

Public API — every Wave 1+ feature that calls an LLM uses these names:

    from shared.llm import call, call_async, stream_async
    from shared.llm import LLMRequest, LLMResponse, Message, ToolCall, Usage
    from shared.llm import get_provider, register_provider

See ``README.md`` for the provider matrix + auth posture + usage examples.
"""
from __future__ import annotations

from .client import call, call_async, stream_async
from .providers import (
    ProviderAdapter,
    ProviderConfigError,
    ProviderError,
    UnknownProviderError,
    get_provider,
    register_provider,
)
from .request import (
    FinishReason,
    LLMRequest,
    LLMResponse,
    Message,
    Role,
    ToolCall,
    Usage,
)
from .retry import (
    DEFAULT_POLICY,
    NonRetryableError,
    RetryableError,
    RetryPolicy,
    retry_async,
)

__all__ = [
    # client
    "call",
    "call_async",
    "stream_async",
    # request / response models
    "LLMRequest",
    "LLMResponse",
    "Message",
    "ToolCall",
    "Usage",
    "Role",
    "FinishReason",
    # provider surface
    "ProviderAdapter",
    "ProviderError",
    "ProviderConfigError",
    "UnknownProviderError",
    "get_provider",
    "register_provider",
    # retry surface
    "RetryPolicy",
    "RetryableError",
    "NonRetryableError",
    "DEFAULT_POLICY",
    "retry_async",
]
