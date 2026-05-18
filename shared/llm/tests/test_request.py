"""Tests for ``shared/llm/request.py`` Pydantic models."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from shared.llm.request import (
    LLMRequest,
    LLMResponse,
    Message,
    ToolCall,
    Usage,
)


# ── Message ──────────────────────────────────────────────────────────


def test_message_accepts_all_four_roles():
    for role in ("system", "user", "assistant", "tool"):
        m = Message(role=role, content="hi")  # type: ignore[arg-type]
        assert m.role == role
        assert m.content == "hi"


def test_message_rejects_unknown_role():
    with pytest.raises(ValidationError):
        Message(role="robot", content="hi")  # type: ignore[arg-type]


def test_message_tool_fields_optional():
    m = Message(role="tool", content="result", tool_call_id="t1", name="my_tool")
    assert m.tool_call_id == "t1"
    assert m.name == "my_tool"


# ── ToolCall ─────────────────────────────────────────────────────────


def test_toolcall_accepts_string_or_dict_arguments():
    t1 = ToolCall(id="t1", name="search", arguments='{"q": "foo"}')
    t2 = ToolCall(id="t2", name="search", arguments={"q": "foo"})
    assert isinstance(t1.arguments, str)
    assert isinstance(t2.arguments, dict)


# ── Usage ────────────────────────────────────────────────────────────


def test_usage_defaults_to_zero():
    u = Usage()
    assert u.input_tokens == 0
    assert u.output_tokens == 0
    assert u.cache_read_tokens == 0
    assert u.cache_write_tokens == 0


def test_usage_cache_fields_optional_for_non_caching_providers():
    u = Usage(input_tokens=100, output_tokens=50)
    assert u.cache_read_tokens == 0  # not None — keeps cost arithmetic simple


# ── LLMRequest ───────────────────────────────────────────────────────


def test_request_requires_model_and_messages():
    with pytest.raises(ValidationError):
        LLMRequest(model="", messages=[Message(role="user", content="x")])
    with pytest.raises(ValidationError):
        LLMRequest(model="claude-sonnet-4-6", messages=[])


def test_request_defaults():
    r = LLMRequest(model="gpt-4o", messages=[Message(role="user", content="x")])
    assert r.max_tokens == 4096
    assert r.temperature is None
    assert r.cache_breakpoints is None
    assert r.tools is None
    assert r.stream is False
    assert r.system is None


def test_request_max_tokens_bounds():
    msgs = [Message(role="user", content="x")]
    with pytest.raises(ValidationError):
        LLMRequest(model="gpt-4o", messages=msgs, max_tokens=0)
    with pytest.raises(ValidationError):
        LLMRequest(model="gpt-4o", messages=msgs, max_tokens=200_001)
    # Inside bounds OK
    LLMRequest(model="gpt-4o", messages=msgs, max_tokens=8192)


def test_request_temperature_bounds():
    msgs = [Message(role="user", content="x")]
    with pytest.raises(ValidationError):
        LLMRequest(model="gpt-4o", messages=msgs, temperature=-0.1)
    with pytest.raises(ValidationError):
        LLMRequest(model="gpt-4o", messages=msgs, temperature=2.1)
    LLMRequest(model="gpt-4o", messages=msgs, temperature=0.7)


def test_request_cache_breakpoints_passthrough():
    # Adapter-level validation; the model just accepts the list.
    r = LLMRequest(
        model="claude-sonnet-4-6",
        messages=[Message(role="user", content="x")],
        cache_breakpoints=[0, 2],
    )
    assert r.cache_breakpoints == [0, 2]


# ── LLMResponse ──────────────────────────────────────────────────────


def test_response_defaults():
    r = LLMResponse(content="hi", provider="anthropic", model="claude-sonnet-4-6")
    assert r.usage.input_tokens == 0
    assert r.finish_reason == "stop"
    assert r.tool_calls is None


def test_response_finish_reason_enum():
    for fr in ("stop", "length", "tool_use", "error"):
        LLMResponse(content="", provider="p", model="m",
                    finish_reason=fr)  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        LLMResponse(content="", provider="p", model="m",
                    finish_reason="finished")  # type: ignore[arg-type]
