"""Pydantic models for the single LLM call surface (Wave 0; per V3 #2).

Public contract — every Wave 1+ feature that calls an LLM uses these types.
No provider-specific fields here. Adapters in ``providers/`` translate to
provider-native shapes. Locked signatures (do not break without Wave 0 sign-off):

    LLMRequest, LLMResponse, Message, ToolCall, Usage

MVP scope: ``Message.content`` is a string; multimodal (images/files) lands
in Wave 1+ as ``list[ContentBlock]``. Same with structured outputs / JSON
mode — Wave 1 augments ``LLMRequest`` with ``response_format``.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# `model` is a public field; suppress Pydantic's protected_namespaces warning.
_PYD_CONFIG = ConfigDict(protected_namespaces=())

Role = Literal["system", "user", "assistant", "tool"]
FinishReason = Literal["stop", "length", "tool_use", "error"]


class Message(BaseModel):
    """One conversation turn.

    Wave 0 MVP: ``content`` is a string. Wave 1+ replaces it with a
    discriminated union of content blocks (``text`` / ``image`` / ``file`` /
    ``tool_result``). Keep callers off ``content`` introspection beyond
    string ops until then.
    """

    model_config = _PYD_CONFIG
    role: Role
    content: str
    # Optional: tool-call envelope when ``role == "tool"`` (forwarded raw).
    tool_call_id: str | None = None
    name: str | None = None


class ToolCall(BaseModel):
    """A tool/function invocation requested by the model.

    Mirrors OpenAI's shape (function name + JSON-string arguments). Anthropic
    tool_use blocks map cleanly onto this; Bedrock's converse-API toolUse
    blocks do too. Adapters are responsible for the translation.
    """

    model_config = _PYD_CONFIG
    id: str
    name: str
    # JSON-encoded string OR a parsed dict — adapters MAY pass through
    # whichever is cheaper; callers should ``json.loads`` if str.
    arguments: str | dict[str, Any]


class Usage(BaseModel):
    """Token accounting. ``cache_*`` fields are populated by providers
    that support prompt caching (Anthropic today; others as they ship).
    Zero on providers without cache support — not None, to keep arithmetic
    simple for cost-ledger code (``shared/cost/router.py`` reads this).
    """

    model_config = _PYD_CONFIG
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


class LLMRequest(BaseModel):
    """Universal request envelope.

    ``model`` is a routing key. Prefix rules (locked, see ``providers/__init__.py``):

      - ``claude-*``    -> anthropic
      - ``gpt-*``       -> openai
      - ``bedrock:*``   -> bedrock (suffix passed to AWS as the modelId)
      - ``vertex:*``    -> vertex  (suffix is the Vertex model name)
      - ``ollama:*``    -> ollama  (suffix is the local model tag)
      - ``qwen:*``      -> qwen    (suffix is the DashScope model name)
      - ``vllm:*``      -> vllm    (suffix is the served model name)

    No other implicit defaults. An unknown prefix raises ``UnknownProviderError``.

    ``cache_breakpoints`` is honored only by providers whose adapter declares
    ``supports_prompt_caching = True``. Others silently ignore — surface the
    capability via ``get_provider(model).supports_prompt_caching`` if you
    care to branch on it.
    """

    model_config = _PYD_CONFIG

    model: str = Field(..., min_length=1)
    messages: list[Message] = Field(..., min_length=1)
    max_tokens: int = Field(default=4096, gt=0, le=200_000)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    # Indices into ``messages`` where prompt-cache breakpoints should be
    # inserted. Anthropic enforces at most 4 markers per request; the
    # adapter validates that bound at call time. None = no caching.
    cache_breakpoints: list[int] | None = None
    # OpenAI / Anthropic tool definitions. Pass-through; adapters translate.
    tools: list[dict[str, Any]] | None = None
    # When True, ``call_async`` returns an async iterator of partial
    # ``LLMResponse`` chunks (see ``streaming.py``).
    stream: bool = False
    # Optional system prompt extracted from messages by adapters that need
    # a separate top-level ``system`` field (Anthropic). Callers may also
    # pass ``role="system"`` messages and let the adapter split.
    system: str | None = None


class LLMResponse(BaseModel):
    """Universal response envelope.

    Streaming uses the same envelope; each chunk carries the *delta* in
    ``content`` and the cumulative ``usage`` when the provider reports it.
    The final chunk carries a non-None ``finish_reason``.
    """

    model_config = _PYD_CONFIG

    content: str
    tool_calls: list[ToolCall] | None = None
    usage: Usage = Field(default_factory=Usage)
    provider: str
    model: str
    finish_reason: FinishReason = "stop"
    # Provider-native raw response, included for debugging + audit. Not
    # part of the stable contract; callers MUST NOT branch on its shape.
    raw: Any | None = None


__all__ = [
    "Role",
    "FinishReason",
    "Message",
    "ToolCall",
    "Usage",
    "LLMRequest",
    "LLMResponse",
]
