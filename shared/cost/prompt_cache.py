"""Anthropic prompt-cache wrapper (STORY-1.5.4; REQ-INIT-1 FR-6 §4).

Long intake conversations reuse a stable prefix (system + role intro +
retrieved context) across many turns. Anthropic prompt caching charges
~10 % of normal input rate on cache reads, so wrapping these calls is a
5-10× cost win on a typical intake session.

Pure wrapper — does not modify `router.py`. Callers opt in by routing
through `call_with_caching()` once `router.route()` has chosen a model.
The Anthropic SDK is lazy-imported so unit tests + non-Anthropic callers
never pay the import cost; missing SDK raises `PromptCacheError` with an
install hint. Cost projection (`estimate_savings`) is illustrative —
production should reconcile against the V16 ledger.
"""
from __future__ import annotations
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

_PYD_CONFIG = ConfigDict(protected_namespaces=())
Role = Literal["user", "assistant"]
ZERO = Decimal("0")

# Anthropic pricing factors (Jan 2026): 10% rate on cache reads, 25%
# premium on cache-creation writes. Override via kwargs if pricing shifts.
_CACHE_READ_FACTOR = Decimal("0.10")
_CACHE_WRITE_FACTOR = Decimal("1.25")


class PromptCacheError(RuntimeError):
    """Raised for missing SDK / bad cache breakpoints / API failures."""


class Message(BaseModel):
    """One conversation turn. Pydantic mirror of Anthropic's message shape."""
    model_config = _PYD_CONFIG
    role: Role
    content: str


class CachedPromptCall(BaseModel):
    """Inputs for a cache-aware Anthropic call.

    `cache_breakpoints` is a list of indices into `user_messages` where
    Anthropic `cache_control={'type': 'ephemeral'}` markers are inserted
    — everything UP TO AND INCLUDING that index becomes the cache prefix.
    Most callers want either `[]` (no caching) or `[0]` (cache just the
    system prompt — common for stable role intros)."""
    model_config = _PYD_CONFIG
    system_prompt: str = Field(min_length=1)
    cache_breakpoints: list[int] = Field(default_factory=list)
    user_messages: list[Message]
    model: str
    max_tokens: int = Field(default=1024, gt=0, le=200_000)

    @field_validator("cache_breakpoints")
    @classmethod
    def _validate_breakpoints(cls, v: list[int]) -> list[int]:
        if any(i < 0 for i in v):
            raise ValueError("cache_breakpoints must be >= 0")
        # Anthropic supports at most 4 cache_control markers per request.
        if len(v) > 4:
            raise ValueError("at most 4 cache breakpoints per Anthropic call")
        return sorted(set(v))


class CacheStats(BaseModel):
    """Returned alongside the response text. Use to populate cost ledger."""
    model_config = _PYD_CONFIG
    cache_creation_input_tokens: int = 0   # one-time write cost
    cache_read_input_tokens: int = 0        # cheap reads (10 % factor)
    input_tokens: int = 0                   # uncached portion
    output_tokens: int = 0
    cache_hit: bool = False
    estimated_savings_usd: Decimal = ZERO


def _build_messages(call: CachedPromptCall) -> list[dict[str, Any]]:
    """Turn `user_messages` into Anthropic message dicts with
    `cache_control` markers at the requested breakpoint indices."""
    out: list[dict[str, Any]] = []
    breakpoints = set(call.cache_breakpoints)
    for i, msg in enumerate(call.user_messages):
        block: dict[str, Any] = {"type": "text", "text": msg.content}
        if i in breakpoints:
            block["cache_control"] = {"type": "ephemeral"}
        out.append({"role": msg.role, "content": [block]})
    return out


def _build_system(call: CachedPromptCall) -> list[dict[str, Any]]:
    """System prompt is *always* cached when caching is enabled — that's
    the biggest single win. Anthropic accepts a list of content blocks
    for system with `cache_control` per block."""
    block: dict[str, Any] = {"type": "text", "text": call.system_prompt}
    if call.cache_breakpoints:  # only mark cacheable if caller opted in
        block["cache_control"] = {"type": "ephemeral"}
    return [block]


def call_with_caching(call: CachedPromptCall, *, anthropic_client: Any = None
                      ) -> tuple[str, CacheStats]:
    """Invoke Anthropic Messages API with cache_control markers + return
    (response_text, CacheStats). Pure wrapper — no DB writes, no audit
    emission; callers (typically the daemon) own ledger reconciliation.

    The Anthropic SDK is lazy-imported. Pass `anthropic_client=` in tests
    to inject a stub (anything with `.messages.create()`)."""
    if anthropic_client is None:
        try:
            import anthropic  # noqa: PLC0415 — lazy optional dep
        except ImportError as e:
            raise PromptCacheError(
                "prompt_cache: `pip install anthropic` required") from e
        anthropic_client = anthropic.Anthropic()

    try:
        resp = anthropic_client.messages.create(
            model=call.model, max_tokens=call.max_tokens,
            system=_build_system(call), messages=_build_messages(call))
    except Exception as e:  # noqa: BLE001
        raise PromptCacheError(f"anthropic call failed: {e}") from e

    text = _extract_text(resp)
    usage = getattr(resp, "usage", None) or {}
    cc = int(_g(usage, "cache_creation_input_tokens", 0))
    cr = int(_g(usage, "cache_read_input_tokens", 0))
    inp = int(_g(usage, "input_tokens", 0))
    out = int(_g(usage, "output_tokens", 0))

    stats = CacheStats(
        cache_creation_input_tokens=cc, cache_read_input_tokens=cr,
        input_tokens=inp, output_tokens=out, cache_hit=cr > 0)
    return text, stats


def _g(usage: Any, key: str, default: int) -> int:
    """Tolerate either an object (.attr) or a dict ([key]) usage shape —
    Anthropic SDK has shipped both over time."""
    if isinstance(usage, dict):
        return int(usage.get(key, default))
    return int(getattr(usage, key, default))


def _extract_text(resp: Any) -> str:
    """Concatenate all `text` blocks from the response content list."""
    parts: list[str] = []
    for block in getattr(resp, "content", []) or []:
        text = block.get("text") if isinstance(block, dict) else getattr(block, "text", None)
        if text:
            parts.append(text)
    return "".join(parts)


def estimate_savings(*, without_cache_tokens: int,
                     with_cache_creation: int, with_cache_reads: int,
                     cost_per_1k_input_usd: Decimal,
                     read_factor: Decimal = _CACHE_READ_FACTOR,
                     write_factor: Decimal = _CACHE_WRITE_FACTOR) -> Decimal:
    """Compute $ saved by using cache vs. paying full input price for the
    same token volume. Negative means cache cost MORE (e.g. one-shot call
    where the write premium outweighed the read discount)."""
    rate = Decimal(cost_per_1k_input_usd) / 1000
    no_cache_cost = Decimal(without_cache_tokens) * rate
    with_cache_cost = (Decimal(with_cache_creation) * rate * write_factor
                       + Decimal(with_cache_reads) * rate * read_factor)
    return (no_cache_cost - with_cache_cost).quantize(Decimal("0.000001"))


def should_use_cache(*, prefix_tokens: int, expected_turns: int,
                     min_prefix_tokens: int = 1024, min_turns: int = 2) -> bool:
    """Caching pays off when a large prefix is reused. Defaults match
    Anthropic's break-even guidance (~1k prefix tokens, 2+ reuses)."""
    return prefix_tokens >= min_prefix_tokens and expected_turns >= min_turns


__all__ = ["PromptCacheError", "Message", "CachedPromptCall", "CacheStats",
           "call_with_caching", "estimate_savings", "should_use_cache"]
