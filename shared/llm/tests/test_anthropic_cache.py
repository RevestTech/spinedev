"""Tests for the Anthropic adapter's prompt-cache behavior — preserves
the contract previously enforced by ``shared/cost/prompt_cache.py``.

We don't import the real ``anthropic`` SDK; we monkey-patch
``_make_client`` to return a stub whose ``messages.create`` records the
exact payload that would have been sent.
"""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

from shared.llm.providers.anthropic import AnthropicAdapter
from shared.llm.request import LLMRequest, Message, Usage


class _StubResponse:
    """Mimics enough of ``anthropic.types.Message`` for our extractors."""

    def __init__(self, text: str = "ok", usage: dict[str, int] | None = None,
                 stop_reason: str = "end_turn"):
        self.content = [{"type": "text", "text": text}]
        self.usage = usage or {
            "input_tokens": 100,
            "output_tokens": 20,
            "cache_creation_input_tokens": 50,
            "cache_read_input_tokens": 30,
        }
        self.stop_reason = stop_reason


class _StubMessagesAPI:
    def __init__(self, response: _StubResponse):
        self.response = response
        self.last_payload: dict[str, Any] | None = None

    async def create(self, **kwargs: Any) -> _StubResponse:
        self.last_payload = kwargs
        return self.response


class _StubClient:
    def __init__(self, response: _StubResponse):
        self.messages = _StubMessagesAPI(response)


@pytest.fixture
def patched_adapter(monkeypatch):
    """Adapter with ``_make_client`` replaced by a stub factory."""
    adapter = AnthropicAdapter()
    stub_resp = _StubResponse()
    stub_client = _StubClient(stub_resp)
    monkeypatch.setattr(adapter, "_make_client",
                        lambda async_mode=True: stub_client)
    return adapter, stub_client


# ── Payload-shape contract ───────────────────────────────────────────


def test_no_breakpoints_sends_no_cache_control(patched_adapter):
    adapter, client = patched_adapter
    req = LLMRequest(
        model="claude-sonnet-4-6",
        messages=[Message(role="user", content="hello")],
        max_tokens=512,
    )
    asyncio.run(adapter.call_async(req))
    payload = client.messages.last_payload
    assert payload is not None
    assert payload["model"] == "claude-sonnet-4-6"
    assert payload["max_tokens"] == 512
    msgs = payload["messages"]
    assert all("cache_control" not in m["content"][0] for m in msgs)
    assert "system" not in payload  # no system prompt was supplied


def test_breakpoints_insert_cache_control_at_indices(patched_adapter):
    adapter, client = patched_adapter
    req = LLMRequest(
        model="claude-sonnet-4-6",
        messages=[
            Message(role="user", content="turn 0"),
            Message(role="assistant", content="reply 0"),
            Message(role="user", content="turn 1"),
        ],
        cache_breakpoints=[0, 2],
    )
    asyncio.run(adapter.call_async(req))
    msgs = client.messages.last_payload["messages"]
    assert msgs[0]["content"][0].get("cache_control") == {"type": "ephemeral"}
    assert "cache_control" not in msgs[1]["content"][0]
    assert msgs[2]["content"][0].get("cache_control") == {"type": "ephemeral"}


def test_system_prompt_marked_cacheable_when_breakpoints_set(patched_adapter):
    adapter, client = patched_adapter
    req = LLMRequest(
        model="claude-sonnet-4-6",
        system="You are a helpful assistant.",
        messages=[Message(role="user", content="hello")],
        cache_breakpoints=[0],
    )
    asyncio.run(adapter.call_async(req))
    payload = client.messages.last_payload
    assert "system" in payload
    assert payload["system"][0]["text"] == "You are a helpful assistant."
    # System block must carry cache_control when breakpoints are enabled
    # — that's the biggest single cache win, matching legacy prompt_cache.py.
    assert payload["system"][0]["cache_control"] == {"type": "ephemeral"}


def test_system_prompt_not_marked_cacheable_without_breakpoints(patched_adapter):
    adapter, client = patched_adapter
    req = LLMRequest(
        model="claude-sonnet-4-6",
        system="You are helpful.",
        messages=[Message(role="user", content="x")],
    )
    asyncio.run(adapter.call_async(req))
    sys_block = client.messages.last_payload["system"][0]
    assert "cache_control" not in sys_block


def test_system_role_messages_merged_into_top_level_system(patched_adapter):
    """Legacy code accepted system as a turn; we extract it transparently."""
    adapter, client = patched_adapter
    req = LLMRequest(
        model="claude-sonnet-4-6",
        messages=[
            Message(role="system", content="You are X."),
            Message(role="system", content="And also Y."),
            Message(role="user", content="hi"),
        ],
    )
    asyncio.run(adapter.call_async(req))
    payload = client.messages.last_payload
    assert payload["system"][0]["text"] == "You are X.\n\nAnd also Y."
    # The system messages should NOT appear in the messages list
    assert all(m["role"] in ("user", "assistant") for m in payload["messages"])
    assert len(payload["messages"]) == 1


# ── Breakpoint validation ────────────────────────────────────────────


def test_more_than_4_breakpoints_rejected(patched_adapter):
    adapter, _ = patched_adapter
    req = LLMRequest(
        model="claude-sonnet-4-6",
        messages=[Message(role="user", content=f"t{i}") for i in range(6)],
        cache_breakpoints=[0, 1, 2, 3, 4],
    )
    with pytest.raises(ValueError, match="at most 4 cache breakpoints"):
        asyncio.run(adapter.call_async(req))


def test_negative_breakpoints_rejected(patched_adapter):
    adapter, _ = patched_adapter
    req = LLMRequest(
        model="claude-sonnet-4-6",
        messages=[Message(role="user", content="x")],
        cache_breakpoints=[-1],
    )
    with pytest.raises(ValueError, match=">= 0"):
        asyncio.run(adapter.call_async(req))


def test_out_of_range_breakpoints_rejected(patched_adapter):
    adapter, _ = patched_adapter
    req = LLMRequest(
        model="claude-sonnet-4-6",
        messages=[Message(role="user", content="x")],
        cache_breakpoints=[5],  # only 1 message
    )
    with pytest.raises(ValueError, match="out of range"):
        asyncio.run(adapter.call_async(req))


def test_duplicate_breakpoints_deduped(patched_adapter):
    adapter, client = patched_adapter
    req = LLMRequest(
        model="claude-sonnet-4-6",
        messages=[Message(role="user", content="x"),
                  Message(role="user", content="y")],
        cache_breakpoints=[0, 0, 1, 1],
    )
    asyncio.run(adapter.call_async(req))
    # Should succeed (dedup brings count to 2 distinct, within limit)
    msgs = client.messages.last_payload["messages"]
    assert msgs[0]["content"][0].get("cache_control") == {"type": "ephemeral"}
    assert msgs[1]["content"][0].get("cache_control") == {"type": "ephemeral"}


# ── Usage extraction (cache tokens preserved) ────────────────────────


def test_usage_populates_cache_token_fields():
    adapter = AnthropicAdapter()
    resp = adapter._extract_usage(_StubResponse())
    assert resp.input_tokens == 100
    assert resp.output_tokens == 20
    assert resp.cache_write_tokens == 50  # cache_creation_input_tokens
    assert resp.cache_read_tokens == 30   # cache_read_input_tokens


def test_usage_tolerates_object_shape():
    """SDK has shipped both dict and object usage shapes — must handle both."""

    class _ObjUsage:
        input_tokens = 7
        output_tokens = 3
        cache_creation_input_tokens = 0
        cache_read_input_tokens = 0

    class _R:
        usage = _ObjUsage()

    adapter = AnthropicAdapter()
    u = adapter._extract_usage(_R())
    assert u.input_tokens == 7
    assert u.output_tokens == 3
