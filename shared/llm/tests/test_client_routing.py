"""Tests for prefix-based provider routing in ``client.call_async``.

Uses an in-memory ``MockAdapter`` that records the call and returns a
canned response — no real SDK / network involved.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest

from shared.llm.client import call, call_async, stream_async
from shared.llm.providers import (
    UnknownProviderError,
    _reset_registry_for_tests,
    get_provider,
    register_provider,
)
from shared.llm.providers.base import ProviderAdapter
from shared.llm.request import LLMRequest, LLMResponse, Message, Usage


class MockAdapter(ProviderAdapter):
    """Test double — records the last request, returns canned response."""

    name = "mock"
    supports_streaming = True

    def __init__(self, label: str):
        self.label = label
        self.calls: list[LLMRequest] = []
        self.stream_calls: list[LLMRequest] = []

    async def call_async(self, request: LLMRequest) -> LLMResponse:
        self.calls.append(request)
        return LLMResponse(
            content=f"[{self.label}] response to: {request.messages[-1].content}",
            provider=self.label, model=request.model,
            usage=Usage(input_tokens=10, output_tokens=5),
            finish_reason="stop",
        )

    async def stream_async(self, request: LLMRequest
                           ) -> AsyncIterator[LLMResponse]:
        self.stream_calls.append(request)
        for word in ["hello", " ", "world"]:
            yield LLMResponse(content=word, provider=self.label,
                              model=request.model, finish_reason="stop",
                              usage=Usage())
        yield LLMResponse(
            content="", provider=self.label, model=request.model,
            finish_reason="stop",
            usage=Usage(input_tokens=8, output_tokens=3))


# Singletons we can inspect across tests.
_mock_anthropic = MockAdapter("anthropic")
_mock_openai = MockAdapter("openai")
_mock_bedrock = MockAdapter("bedrock")
_mock_vertex = MockAdapter("vertex")
_mock_ollama = MockAdapter("ollama")
_mock_qwen = MockAdapter("qwen")
_mock_vllm = MockAdapter("vllm")


@pytest.fixture(autouse=True)
def _install_mock_registry():
    """Replace the production registry with mock factories for each test."""
    _reset_registry_for_tests()
    register_provider("claude-", lambda: _mock_anthropic)
    register_provider("gpt-", lambda: _mock_openai)
    register_provider("bedrock:", lambda: _mock_bedrock)
    register_provider("vertex:", lambda: _mock_vertex)
    register_provider("ollama:", lambda: _mock_ollama)
    register_provider("qwen:", lambda: _mock_qwen)
    register_provider("vllm:", lambda: _mock_vllm)
    # Reset call records
    for m in (_mock_anthropic, _mock_openai, _mock_bedrock, _mock_vertex,
              _mock_ollama, _mock_qwen, _mock_vllm):
        m.calls.clear()
        m.stream_calls.clear()
    yield
    _reset_registry_for_tests()


# ── Routing matrix ───────────────────────────────────────────────────


@pytest.mark.parametrize("model,expected_label", [
    ("claude-sonnet-4-6", "anthropic"),
    ("claude-opus-4", "anthropic"),
    ("gpt-4o", "openai"),
    ("gpt-5", "openai"),
    ("bedrock:anthropic.claude-3-5-sonnet-20240620-v1:0", "bedrock"),
    ("vertex:gemini-2.0-flash-001", "vertex"),
    ("ollama:llama3.1:70b", "ollama"),
    ("qwen:qwen-max", "qwen"),
    ("vllm:my-finetune-v2", "vllm"),
])
def test_prefix_routing(model: str, expected_label: str):
    resp = call(LLMRequest(model=model, messages=[
        Message(role="user", content="ping")]))
    assert resp.provider == expected_label
    assert resp.model == model
    # Verify it landed on the right mock
    labels = {
        "anthropic": _mock_anthropic, "openai": _mock_openai,
        "bedrock": _mock_bedrock, "vertex": _mock_vertex,
        "ollama": _mock_ollama, "qwen": _mock_qwen, "vllm": _mock_vllm,
    }
    assert len(labels[expected_label].calls) == 1
    # Confirm no spillover to others
    for label, mock in labels.items():
        if label != expected_label:
            assert len(mock.calls) == 0


def test_unknown_prefix_raises():
    with pytest.raises(UnknownProviderError):
        call(LLMRequest(model="mistral-large-2",
                        messages=[Message(role="user", content="x")]))


def test_longest_prefix_wins():
    """Custom-registered ``bedrock:custom:`` should beat the built-in
    ``bedrock:`` for matching models."""
    custom = MockAdapter("bedrock_custom")
    register_provider("bedrock:custom:", lambda: custom)
    resp = call(LLMRequest(model="bedrock:custom:my-model",
                           messages=[Message(role="user", content="x")]))
    assert resp.provider == "bedrock_custom"
    assert len(custom.calls) == 1
    assert len(_mock_bedrock.calls) == 0


def test_get_provider_caches_instances():
    a = get_provider("claude-sonnet-4-6")
    b = get_provider("claude-opus-4")
    assert a is b  # same factory => same cached instance


# ── Streaming ────────────────────────────────────────────────────────


def test_stream_async_yields_chunks():
    async def _drive():
        out: list[str] = []
        async for chunk in stream_async(LLMRequest(
            model="claude-sonnet-4-6",
            messages=[Message(role="user", content="hi")],
        )):
            out.append(chunk.content)
        return out

    chunks = asyncio.run(_drive())
    # MockAdapter yields "hello"+" "+"world" + a terminal empty chunk
    assert chunks == ["hello", " ", "world", ""]
    assert len(_mock_anthropic.stream_calls) == 1


def test_call_async_with_stream_true_aggregates():
    """``call_async`` with ``request.stream=True`` collapses the stream
    into a single response."""
    async def _drive():
        return await call_async(LLMRequest(
            model="gpt-4o",
            messages=[Message(role="user", content="hi")],
            stream=True,
        ))

    resp = asyncio.run(_drive())
    assert resp.content == "hello world"
    assert resp.usage.input_tokens == 8  # from terminal chunk
    assert resp.provider == "openai"


# ── Sync wrapper guardrail ───────────────────────────────────────────


def test_call_sync_raises_inside_event_loop():
    async def _inner():
        with pytest.raises(RuntimeError, match="use call_async"):
            call(LLMRequest(model="gpt-4o",
                            messages=[Message(role="user", content="x")]))

    asyncio.run(_inner())
