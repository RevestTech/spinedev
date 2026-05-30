"""Anthropic-backed :data:`RoleCallable` for the V3 #7a charter eval harness.

Implements the contract documented in
:mod:`verify.charter_evals.role_callables` (see the trailing comment
block) as a real LLM-driven callable that plugs into
:func:`verify.charter_evals.harness.evaluate_charter`.

Design notes
------------

* The ``anthropic`` SDK is imported **lazily inside the factory** so
  this module stays importable in environments without the SDK
  installed (V3 keeps the harness provider-agnostic at import time).
* The factory takes ``api_key`` as an explicit argument. It never
  reads ``os.environ`` — secrets handling stays at the call site per
  V3 #9 (vault-only secrets).
* Failures (SDK missing, API exception, empty response, charter file
  missing) raise :class:`AnthropicCallableError`. The empty-string
  contract belongs to the fixture/stub callables only — a real LLM
  call that silently returns ``""`` would mask regressions.

Wiring
------

A follow-up patch to :mod:`verify.charter_evals.run` may expose a
``--callable anthropic`` flag that constructs this via
:func:`make_anthropic_role_callable`. This module exports that
factory as its sole public entry point.
"""
from __future__ import annotations

from pathlib import Path

from verify.charter_evals.harness import CapabilityEval, RoleCallable


DEFAULT_MODEL = "claude-sonnet-4-6"
"""Default Anthropic model id for charter eval runs."""

DEFAULT_MAX_TOKENS = 1024
"""Default ``max_tokens`` budget for one trial response."""


class AnthropicCallableError(RuntimeError):
    """Raised when the Anthropic-backed role_callable cannot reach a verdict."""


def make_anthropic_role_callable(
    *,
    api_key: str,
    model: str = DEFAULT_MODEL,
    charter_path: Path,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> RoleCallable:
    """Build a :data:`RoleCallable` that dispatches each trial via Anthropic.

    The returned callable sends one ``messages.create`` request per
    trial using the charter at ``charter_path`` as the system prompt
    and ``eval_.task`` as the user message. Returns
    ``resp.content[0].text``.

    Raises :class:`AnthropicCallableError` at factory time if the SDK
    is not installed or the charter file is missing, and per-call if
    the Anthropic API raises or returns no content.
    """
    try:
        from anthropic import Anthropic  # type: ignore[import-not-found]
    except ImportError as exc:
        raise AnthropicCallableError("anthropic SDK not installed") from exc

    charter = Path(charter_path)
    if not charter.is_file():
        raise AnthropicCallableError(
            f"charter file not found: {charter}"
        )
    system_prompt = charter.read_text(encoding="utf-8")
    client = Anthropic(api_key=api_key)

    def _call(eval_: CapabilityEval, trial_index: int) -> str:
        try:
            resp = client.messages.create(
                model=model,
                system=system_prompt,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": eval_.task}],
            )
        except Exception as exc:  # noqa: BLE001 — surface as typed error
            raise AnthropicCallableError(
                f"anthropic API call failed: {exc}"
            ) from exc
        content = getattr(resp, "content", None)
        if not content:
            raise AnthropicCallableError(
                "anthropic response had no content"
            )
        first = content[0]
        text = getattr(first, "text", None)
        if not text:
            raise AnthropicCallableError(
                "anthropic response had no content"
            )
        return text

    return _call


__all__ = [
    "DEFAULT_MAX_TOKENS",
    "DEFAULT_MODEL",
    "AnthropicCallableError",
    "make_anthropic_role_callable",
]
