"""Abstract provider adapter interface.

Every provider adapter (anthropic / openai / bedrock / vertex / ollama /
qwen / vllm) implements this contract. The single ``client.py`` routes
requests to ``get_provider(request.model)`` and dispatches to
``call_async`` (unary) or ``stream_async`` (SSE deltas).

Adapters MUST:
  - Be self-contained — no inheriting fields beyond what's here.
  - Lazy-import provider SDKs in the call methods, not at module load.
    (We don't want Wave-1 features to require ``boto3`` installed to
    import the OpenAI adapter.)
  - Fetch auth via ``_get_api_key`` (Wave 0 fallback to env; Wave 1
    swaps in ``shared.secrets.get_secret``).
  - Wrap network calls with ``retry_async()`` from ``..retry``.
  - Translate provider-native shapes to ``LLMRequest`` / ``LLMResponse``.
  - Populate ``Usage.cache_read_tokens`` / ``cache_write_tokens`` when
    the provider reports them; zero otherwise.

Adapters MUST NOT:
  - Touch any module outside ``shared/llm/``.
  - Hardcode API keys, endpoints (unless documented), or model lists.
  - Do their own retry — let the decorator handle it.
  - Log request/response bodies at INFO+ (PII risk).
"""
from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import ClassVar

from ..request import LLMRequest, LLMResponse

logger = logging.getLogger(__name__)


class ProviderError(Exception):
    """Base for all provider errors raised after retry exhaustion."""


class ProviderConfigError(ProviderError):
    """Missing API key / misconfigured endpoint / SDK not installed."""


class ProviderAdapter(ABC):
    """Abstract base. Subclasses implement ``call_async`` / ``stream_async``.

    Class-level metadata (override in subclasses):
      - ``name``                        — short provider identifier
      - ``model_prefix``                — routing prefix (e.g. ``"claude-"``,
                                          ``"bedrock:"``); empty for catch-all
      - ``supports_prompt_caching``     — True for Anthropic; False elsewhere
                                          for Wave 0
      - ``supports_tools``              — True if tool/function-calling works
      - ``supports_streaming``          — True if ``stream_async`` is real
                                          (we ship True everywhere)
      - ``secret_name``                 — ``shared.secrets`` key for the API
                                          credential (Wave 1 wiring)
      - ``env_var``                     — fallback env var (Wave 0 only)
    """

    name: ClassVar[str] = "abstract"
    model_prefix: ClassVar[str] = ""
    supports_prompt_caching: ClassVar[bool] = False
    supports_tools: ClassVar[bool] = True
    supports_streaming: ClassVar[bool] = True
    secret_name: ClassVar[str | None] = None
    env_var: ClassVar[str | None] = None

    def _get_api_key(self) -> str | None:
        """Resolve provider credential.

        Wave 0 implementation: try ``shared.secrets.get_secret`` (soft
        import — module may not exist yet) then fall back to the documented
        env var. Wave 1 MUST replace this with vault-only per design #9 —
        production deployments will fail-closed on env-var-only auth.

        TODO Wave 1: replace with ``shared.secrets.get_secret(secret_name)``
        and remove the env-var fallback. Tracking: V3_TRIAGE.md row for
        shared/secrets/ + #9 (vault-only secrets).
        """
        if self.secret_name:
            try:
                from shared.secrets import get_secret  # type: ignore[import-not-found]
                value = get_secret(self.secret_name)
                if value:
                    return value
            except (ImportError, ModuleNotFoundError):
                pass  # Wave 0: shared/secrets/ may not exist yet
            except Exception as exc:  # noqa: BLE001 — vault read is best-effort here
                logger.warning("vault_lookup_failed name=%s err=%s",
                               self.secret_name, exc)
        if self.env_var:
            return os.environ.get(self.env_var)
        return None

    def _strip_prefix(self, model: str) -> str:
        """Return the provider-native model id (e.g. ``bedrock:foo`` -> ``foo``).

        For prefix-only adapters (Anthropic ``claude-*``, OpenAI ``gpt-*``)
        we return the model unchanged — the SDK expects the prefix.
        For ``scheme:value`` adapters we strip the scheme.
        """
        if self.model_prefix and self.model_prefix.endswith(":") \
                and model.startswith(self.model_prefix):
            return model[len(self.model_prefix):]
        return model

    @abstractmethod
    async def call_async(self, request: LLMRequest) -> LLMResponse:
        """Unary call. Returns the full response. Use retry decorator inside."""

    @abstractmethod
    async def stream_async(self, request: LLMRequest) -> AsyncIterator[LLMResponse]:
        """Streaming call. Yields ``LLMResponse`` chunks; final chunk carries
        ``finish_reason`` and authoritative ``usage`` when provider reports it.
        """


__all__ = ["ProviderAdapter", "ProviderError", "ProviderConfigError"]
