"""Unit tests for the TRON ↔ shared.llm SHIM.

Covers FIX1 from the v3 drift audit (TRON LLM provider must route
through ``shared/llm/``). Each test mocks ``shared.llm.call_async``
entirely — no real LLM traffic, no real adapter import.

What's verified:

  * The 3 pre-shim Provider values (ANTHROPIC / OPENAI / OLLAMA) still
    round-trip — TRON callers don't break.
  * The 4 new Provider values (BEDROCK / VERTEX / QWEN / VLLM) reach
    shared.llm with the correct model prefix per V3 #2.
  * The Provider→prefix mapping table matches
    ``shared/llm/providers/__init__.py`` exactly.
  * Legacy ``anthropic_key`` / ``openai_key`` kwargs are silently
    accepted but their VALUES are never persisted (V3 #9 vault-only).
  * ``ProviderConfigError`` from shared.llm surfaces as a clear
    ``ValueError`` pointing at Hub bootstrap (does NOT trip the
    circuit breaker — config errors don't auto-recover).
"""
from __future__ import annotations

import asyncio
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _run(coro):
    """Helper: run an async test body via ``asyncio.run`` so this test
    file doesn't depend on pytest-asyncio (not installed in every venv).
    """
    return asyncio.run(coro)


# ── Test-only ``shared.llm`` stub ─────────────────────────────────────


class _StubProviderError(Exception):
    """Stand-in for shared.llm.ProviderError."""


class _StubProviderConfigError(_StubProviderError):
    """Stand-in for shared.llm.ProviderConfigError."""


class _StubUnknownProviderError(_StubProviderError):
    """Stand-in for shared.llm.UnknownProviderError."""


def _build_stub_shared_llm_module() -> types.ModuleType:
    """Construct an in-memory ``shared.llm`` module sufficient for the shim.

    The shim only imports ``LLMRequest``, ``Message``, ``call_async``,
    ``ProviderConfigError``, ``ProviderError``, and ``UnknownProviderError``.
    """
    mod = types.ModuleType("shared.llm")

    class _StubLLMRequest:
        def __init__(self, *, model, messages, max_tokens, temperature,
                     system=None, **_ignored):
            self.model = model
            self.messages = messages
            self.max_tokens = max_tokens
            self.temperature = temperature
            self.system = system

    class _StubMessage:
        def __init__(self, *, role, content):
            self.role = role
            self.content = content

    class _StubUsage:
        def __init__(self, input_tokens=0, output_tokens=0):
            self.input_tokens = input_tokens
            self.output_tokens = output_tokens

    class _StubLLMResponse:
        def __init__(self, *, content="ok", model="claude-haiku-4-5-20251001",
                     provider="anthropic", finish_reason="stop",
                     input_tokens=10, output_tokens=20, raw=None):
            self.content = content
            self.model = model
            self.provider = provider
            self.finish_reason = finish_reason
            self.usage = _StubUsage(input_tokens, output_tokens)
            self.raw = raw

    mod.LLMRequest = _StubLLMRequest
    mod.Message = _StubMessage
    mod.LLMResponse = _StubLLMResponse
    mod.Usage = _StubUsage
    mod.ProviderError = _StubProviderError
    mod.ProviderConfigError = _StubProviderConfigError
    mod.UnknownProviderError = _StubUnknownProviderError
    mod.call_async = AsyncMock(return_value=_StubLLMResponse())
    return mod


@pytest.fixture(autouse=True)
def stub_shared_llm(monkeypatch):
    """Install the in-memory ``shared.llm`` stub for the test.

    The shim resolves ``shared.llm`` lazily (inside the ``_call_shared_llm``
    method body and inside the module-level
    ``_resolve_shared_llm_exception_classes`` helper), so we re-install the
    stub on the module's exception-tuple to match the freshly-imported types.
    """
    # Ensure ``shared`` package exists so the dotted import works.
    shared_pkg = sys.modules.get("shared")
    if shared_pkg is None:
        shared_pkg = types.ModuleType("shared")
        shared_pkg.__path__ = []  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "shared", shared_pkg)

    stub = _build_stub_shared_llm_module()
    monkeypatch.setitem(sys.modules, "shared.llm", stub)

    # Force the shim to pick up our stub's exception classes.
    from tron.infra.llm import client as shim_mod
    monkeypatch.setattr(
        shim_mod,
        "_SHARED_LLM_CONFIG_ERRORS",
        (_StubProviderConfigError, _StubUnknownProviderError),
    )
    monkeypatch.setattr(
        shim_mod,
        "_SHARED_LLM_RETRYABLE_ERRORS",
        (_StubProviderError, Exception),
    )
    yield stub


@pytest.fixture(autouse=True)
def _silence_tron_side_effects(monkeypatch):
    """The shim's ``complete()`` calls into the TRON budget gate + usage
    ledger. Mock both so this test exercises only the shim itself."""
    from tron.infra.llm import client as shim_mod

    async def _allow_budget():
        return None

    async def _noop_persist(*_a, **_kw):
        return None

    monkeypatch.setattr(
        shim_mod, "assert_llm_budget_allows_estimated_call", _allow_budget
    )
    monkeypatch.setattr(shim_mod, "persist_llm_usage", _noop_persist)
    monkeypatch.setattr(shim_mod, "get_llm_usage_context", lambda: None)


# ── Provider enum + mapping table ─────────────────────────────────────


def test_provider_enum_keeps_legacy_values_and_adds_v3_providers():
    """All 3 pre-shim values preserved + all 4 new v3 providers reachable."""
    from tron.infra.llm.client import Provider

    legacy = {"anthropic", "openai", "ollama"}
    new = {"bedrock", "vertex", "qwen", "vllm"}
    actual = {p.value for p in Provider}
    assert legacy.issubset(actual), "shim dropped a pre-shim Provider value"
    assert new.issubset(actual), "shim missing a v3 provider"


def test_provider_prefix_mapping_matches_shared_llm_lock_list():
    """The shim's ``_PROVIDER_MODEL_PREFIX`` must match shared/llm's
    locked prefix list (see ``shared/llm/providers/__init__.py``).
    Drift here = #2 LLM-agnostic invariant broken."""
    from tron.infra.llm.client import Provider, _PROVIDER_MODEL_PREFIX

    expected = {
        Provider.ANTHROPIC: "claude-",
        Provider.OPENAI: "gpt-",
        Provider.OLLAMA: "ollama:",
        Provider.BEDROCK: "bedrock:",
        Provider.VERTEX: "vertex:",
        Provider.QWEN: "qwen:",
        Provider.VLLM: "vllm:",
    }
    assert _PROVIDER_MODEL_PREFIX == expected


# ── shared.llm call_async receives the right model id ──────────────────


@pytest.mark.parametrize(
    "tron_model, expected_provider_value",
    [
        # Pre-shim providers — unchanged routing.
        ("claude-haiku-4-5-20251001", "anthropic"),
        ("claude-3-opus-20240229", "anthropic"),
        ("gpt-4o", "openai"),
        ("gpt-4o-mini", "openai"),
        ("ollama:llama3.2", "ollama"),
        # New v3 providers — must reach shared.llm with the right prefix.
        ("bedrock:anthropic.claude-3-sonnet-20240229-v1:0", "bedrock"),
        ("vertex:gemini-2.0-flash-exp", "vertex"),
        ("qwen:qwen2.5-72b-instruct", "qwen"),
        ("vllm:meta-llama/Meta-Llama-3-8B-Instruct", "vllm"),
    ],
)
def test_complete_routes_via_shared_llm_with_correct_model(
    tron_model, expected_provider_value, stub_shared_llm
):
    """``LLMClient.complete()`` forwards the model unchanged to
    ``shared.llm.call_async`` AND returns a TRON Provider matching
    the prefix-derived expectation."""
    from tron.infra.llm.client import (
        LLMClient,
        LLMMessage,
        LLMRequest,
        Provider,
    )

    # Stub the response to advertise the same model id back so
    # ``_provider_for_model`` resolves to the expected Provider.
    stub_shared_llm.call_async = AsyncMock(
        return_value=stub_shared_llm.LLMResponse(
            content="stub-response",
            model=tron_model,
            provider=expected_provider_value,
            finish_reason="stop",
            input_tokens=5,
            output_tokens=7,
        )
    )

    client = LLMClient()
    request = LLMRequest(
        messages=[
            LLMMessage(role="system", content="be terse"),
            LLMMessage(role="user", content="hello"),
        ],
        model=tron_model,
    )

    response = _run(client.complete(request, retries=0))

    # 1. shared.llm.call_async was called exactly once.
    assert stub_shared_llm.call_async.await_count == 1
    sent_request = stub_shared_llm.call_async.await_args.args[0]
    # 2. The forwarded request carries the TRON model unchanged.
    assert sent_request.model == tron_model
    # 3. The system message was split out (matches shared/llm/ shape).
    assert sent_request.system == "be terse"
    assert len(sent_request.messages) == 1
    assert sent_request.messages[0].role == "user"
    # 4. Response provider is the right TRON enum value.
    assert response.provider == Provider(expected_provider_value)
    assert response.model == tron_model
    assert response.input_tokens == 5
    assert response.output_tokens == 7


def test_complete_concatenates_multiple_system_messages():
    """Multiple ``role="system"`` messages merge into a single shared.llm
    ``system`` field (anthropic / others want one top-level system blob)."""
    from tron.infra.llm.client import LLMClient, LLMMessage, LLMRequest

    sl = sys.modules["shared.llm"]
    sl.call_async = AsyncMock(
        return_value=sl.LLMResponse(
            content="ok", model="claude-haiku-4-5-20251001",
            provider="anthropic"
        )
    )

    client = LLMClient()
    _run(
        client.complete(
            LLMRequest(
                messages=[
                    LLMMessage(role="system", content="rule A"),
                    LLMMessage(role="system", content="rule B"),
                    LLMMessage(role="user", content="hi"),
                ],
                model="claude-haiku-4-5-20251001",
            ),
            retries=0,
        )
    )
    sent = sl.call_async.await_args.args[0]
    assert sent.system == "rule A\n\nrule B"


# ── Vault-only posture (V3 #9) ────────────────────────────────────────


def test_legacy_key_kwargs_are_accepted_but_not_stored():
    """Pre-shim callers still pass ``anthropic_key=...`` / ``openai_key=...``.
    The shim must accept them silently and NEVER store them as instance
    state (V3 #9 — keys live in vault, not in process memory)."""
    from tron.infra.llm.client import LLMClient

    client = LLMClient(anthropic_key="sk-ant-bogus", openai_key="sk-bogus")

    # No attribute may carry the plaintext key value.
    for attr_name in dir(client):
        if attr_name.startswith("__"):
            continue
        attr = getattr(client, attr_name)
        # Skip methods / callables.
        if callable(attr):
            continue
        # The plaintext key string must not appear in any client state.
        rendered = repr(attr)
        assert "sk-ant-bogus" not in rendered
        assert "sk-bogus" not in rendered


def test_legacy_key_kwargs_emit_one_deprecation_warning(caplog):
    """The first call with legacy kwargs logs once; subsequent calls quiet."""
    import logging as _logging
    from tron.infra.llm import client as shim_mod

    # Reset the one-shot flag — other tests may have flipped it.
    shim_mod._LEGACY_KEY_WARNING_EMITTED = False

    with caplog.at_level(_logging.WARNING, logger=shim_mod.__name__):
        shim_mod.LLMClient(anthropic_key="sk-ant-x")
        shim_mod.LLMClient(anthropic_key="sk-ant-y")

    warnings = [r for r in caplog.records if "kwargs are" in r.message]
    assert len(warnings) == 1, (
        f"expected exactly one deprecation warning, got {len(warnings)}"
    )


# ── ProviderConfigError surfaces clearly ─────────────────────────────


def test_provider_config_error_raises_value_error_with_pointer(
    stub_shared_llm,
):
    """When ``shared.llm`` says "no credential," the shim raises a
    ValueError naming Hub bootstrap so the caller knows where to look."""
    from tron.infra.llm.client import LLMClient, LLMMessage, LLMRequest

    stub_shared_llm.call_async = AsyncMock(
        side_effect=_StubProviderConfigError("missing key in vault")
    )

    client = LLMClient()
    with pytest.raises(ValueError) as excinfo:
        _run(
            client.complete(
                LLMRequest(
                    messages=[LLMMessage(role="user", content="hi")],
                    model="claude-haiku-4-5-20251001",
                ),
                retries=0,
            )
        )
    msg = str(excinfo.value)
    assert "shared.secrets" in msg or "Hub bootstrap" in msg
    assert "anthropic" in msg.lower()


def test_provider_config_error_does_not_trip_circuit_breaker(
    stub_shared_llm,
):
    """Config errors are NOT a provider outage — they shouldn't open the
    breaker (otherwise a misconfigured Hub becomes self-poisoning)."""
    from tron.infra.llm.client import (
        CircuitState,
        LLMClient,
        LLMMessage,
        LLMRequest,
        Provider,
    )

    stub_shared_llm.call_async = AsyncMock(
        side_effect=_StubProviderConfigError("no key")
    )

    client = LLMClient()
    for _ in range(10):  # well past the default failure_threshold (5).
        with pytest.raises(ValueError):
            _run(
                client.complete(
                    LLMRequest(
                        messages=[LLMMessage(role="user", content="x")],
                        model="claude-haiku-4-5-20251001",
                    ),
                    retries=0,
                )
            )

    breaker = client._breakers[Provider.ANTHROPIC]
    assert breaker._state == CircuitState.CLOSED


# ── Sanity: deleted methods really are gone ──────────────────────────


def test_per_provider_http_methods_deleted():
    """The pre-shim ``_call_anthropic`` / ``_call_openai`` / ``_call_ollama``
    methods are gone — drift would re-introduce the dual-codepath bug."""
    from tron.infra.llm.client import LLMClient

    client = LLMClient()
    for forbidden in ("_call_anthropic", "_call_openai", "_call_ollama"):
        assert not hasattr(client, forbidden), (
            f"{forbidden} should be deleted; route through shared.llm instead"
        )


def test_no_env_var_reads_in_shim_source():
    """The shim module's source must not reference the legacy env vars.

    Belt-and-braces with the repo-level grep — protects against a future
    edit slipping ``os.environ.get('ANTHROPIC_API_KEY', ...)`` back in."""
    import inspect
    from tron.infra.llm import client as shim_mod

    src = inspect.getsource(shim_mod)
    # Comments explaining the constraint are fine; but actual env reads
    # (``os.environ`` / ``getenv``) of the API key names are not.
    # We assert the API-key names don't appear as string literals at all.
    for forbidden in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        assert forbidden not in src, (
            f"{forbidden} found in shim source — violates V3 #9 vault-only"
        )
