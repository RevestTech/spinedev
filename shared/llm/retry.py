"""Retry policy for LLM provider calls.

Hand-rolled (no tenacity dep) so ``shared/llm/`` stays free of optional
runtime requirements. Decorator style mirrors tenacity for familiarity.

Policy (locked Wave 0 defaults):
  - Exponential backoff with full jitter
  - Base delay 1.0s, multiplier 2.0, max delay 30.0s
  - 5 attempts total (initial + 4 retries)
  - Honors ``Retry-After`` header when surfaced as an attribute on the
    raised exception (``retry_after_seconds``); otherwise uses backoff
  - Retries: rate-limit (HTTP 429), server errors (5xx), connection
    errors, timeouts; classifier in ``is_retryable_error``
  - Never retries: auth errors (401/403), validation errors (400/422)

Wave 1+ may replace this with a richer policy (circuit breakers,
per-provider budgets, cost-aware retry) — keep the decorator signature
stable so adapters don't rewrite.
"""
from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import wraps
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass(frozen=True)
class RetryPolicy:
    """Backoff parameters. Override via ``retry_async(policy=...)``."""

    max_attempts: int = 5
    base_delay_seconds: float = 1.0
    multiplier: float = 2.0
    max_delay_seconds: float = 30.0
    # Full jitter — delay = uniform(0, computed_backoff). Avoids thundering
    # herd when many in-flight requests hit a 429 simultaneously.
    jitter: bool = True


DEFAULT_POLICY = RetryPolicy()


class RetryableError(Exception):
    """Raise from inside adapters to force a retry regardless of class.

    Optional ``retry_after_seconds`` is honored by the decorator.
    """

    def __init__(self, message: str, retry_after_seconds: float | None = None):
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class NonRetryableError(Exception):
    """Auth / validation / quota-exhausted — never retry."""


def is_retryable_error(exc: BaseException) -> bool:
    """Best-effort classifier across SDKs.

    SDKs vary wildly — some raise ``RateLimitError``, some attach
    ``status_code`` attributes, some surface stdlib ``TimeoutError``.
    We check class names + common attributes rather than importing every
    SDK (which would couple shared/llm/ to SDK install state).
    """
    if isinstance(exc, NonRetryableError):
        return False
    if isinstance(exc, RetryableError):
        return True
    # stdlib retryables
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return True
    if isinstance(exc, asyncio.TimeoutError):
        return True
    # SDK retryables — duck-typed
    name = type(exc).__name__.lower()
    if "ratelimit" in name or "timeout" in name or "overloaded" in name:
        return True
    if "apiconnection" in name or "serviceunavailable" in name:
        return True
    # HTTP-status-bearing exceptions (openai SDK, httpx)
    status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
    if isinstance(status, int):
        if status == 429 or 500 <= status < 600:
            return True
        if status in (401, 403, 400, 404, 422):
            return False
    return False


def _compute_delay(attempt: int, policy: RetryPolicy,
                   retry_after: float | None) -> float:
    """Honor server-provided Retry-After when present; else exp backoff."""
    if retry_after is not None and retry_after > 0:
        return min(retry_after, policy.max_delay_seconds)
    raw = policy.base_delay_seconds * (policy.multiplier ** attempt)
    raw = min(raw, policy.max_delay_seconds)
    if policy.jitter:
        return random.uniform(0.0, raw)
    return raw


def retry_async(policy: RetryPolicy | None = None
                ) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    """Decorator: retry an async callable per ``policy``.

    Usage::

        @retry_async()
        async def _provider_call(...): ...

    Adapters wrap their inner provider call (the network-touching one),
    NOT the whole ``call_async``, so request validation errors surface
    immediately instead of being retried.
    """
    p = policy or DEFAULT_POLICY

    def _decorate(fn: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:

        @wraps(fn)
        async def _wrapper(*args: Any, **kwargs: Any) -> T:
            last: BaseException | None = None
            for attempt in range(p.max_attempts):
                try:
                    return await fn(*args, **kwargs)
                except Exception as exc:  # noqa: BLE001 — explicit policy check below
                    last = exc
                    if not is_retryable_error(exc) or attempt == p.max_attempts - 1:
                        raise
                    retry_after = getattr(exc, "retry_after_seconds", None) \
                        or getattr(exc, "retry_after", None)
                    delay = _compute_delay(attempt, p, retry_after)
                    logger.warning(
                        "llm_retry attempt=%d/%d delay=%.2fs err=%s: %s",
                        attempt + 1, p.max_attempts, delay,
                        type(exc).__name__, exc)
                    await asyncio.sleep(delay)
            # Unreachable: loop either returns or raises. Re-raise for type checker.
            assert last is not None
            raise last

        return _wrapper

    return _decorate


__all__ = [
    "RetryPolicy",
    "RetryableError",
    "NonRetryableError",
    "DEFAULT_POLICY",
    "is_retryable_error",
    "retry_async",
]
