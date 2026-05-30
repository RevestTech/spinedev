"""Tests for :mod:`verify.charter_evals.anthropic_callable`."""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from verify.charter_evals.anthropic_callable import (
    AnthropicCallableError,
    make_anthropic_role_callable,
)
from verify.charter_evals.harness import CapabilityEval, EvalCriterion


# ─── helpers ─────────────────────────────────────────────────────────


def _eval() -> CapabilityEval:
    return CapabilityEval(
        name="cites-req",
        role="engineer",
        task="Implement REQ-FOO-1 with input validation.",
        criteria=[
            EvalCriterion(name="ok", required_substrings=("REQ-FOO-1",)),
        ],
        target_k=1,
        target_pass_rate=1.0,
    )


def _charter(tmp_path: Path) -> Path:
    p = tmp_path / "engineer.md"
    p.write_text("You are the Engineer charter.", encoding="utf-8")
    return p


class _FakeContent:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeResponse:
    def __init__(self, content: list[_FakeContent]) -> None:
        self.content = content


class _FakeMessages:
    def __init__(self, response: _FakeResponse | None, raises: Exception | None = None) -> None:
        self._response = response
        self._raises = raises
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self._raises is not None:
            raise self._raises
        return self._response


class _FakeClient:
    def __init__(self, messages: _FakeMessages) -> None:
        self.messages = messages


def _install_fake_anthropic(
    monkeypatch: pytest.MonkeyPatch,
    *,
    response: _FakeResponse | None = None,
    raises: Exception | None = None,
) -> _FakeMessages:
    """Stub ``import anthropic`` with a fake module whose ``Anthropic``
    class returns a client backed by ``_FakeMessages``."""
    fake_messages = _FakeMessages(response=response, raises=raises)

    def _client_factory(*, api_key: str) -> _FakeClient:
        # surface the api_key into the messages object for assertions
        fake_messages.api_key = api_key  # type: ignore[attr-defined]
        return _FakeClient(fake_messages)

    fake_mod = types.ModuleType("anthropic")
    fake_mod.Anthropic = _client_factory  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "anthropic", fake_mod)
    return fake_messages


def _uninstall_anthropic(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure ``import anthropic`` fails inside the factory."""
    monkeypatch.setitem(sys.modules, "anthropic", None)


# ─── SDK missing ─────────────────────────────────────────────────────


def test_factory_raises_when_sdk_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _uninstall_anthropic(monkeypatch)
    with pytest.raises(AnthropicCallableError, match="anthropic SDK not installed"):
        make_anthropic_role_callable(
            api_key="sk-test",
            charter_path=_charter(tmp_path),
        )


# ─── Charter file missing ────────────────────────────────────────────


def test_factory_raises_when_charter_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _install_fake_anthropic(monkeypatch, response=_FakeResponse([_FakeContent("ok")]))
    missing = tmp_path / "nope.md"
    with pytest.raises(AnthropicCallableError, match="charter file not found"):
        make_anthropic_role_callable(
            api_key="sk-test",
            charter_path=missing,
        )


# ─── Happy path ──────────────────────────────────────────────────────


def test_callable_returns_response_text(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    fake = _install_fake_anthropic(
        monkeypatch,
        response=_FakeResponse([_FakeContent("REQ-FOO-1 implemented.")]),
    )
    callable_ = make_anthropic_role_callable(
        api_key="sk-test",
        charter_path=_charter(tmp_path),
    )
    out = callable_(_eval(), 0)
    assert out == "REQ-FOO-1 implemented."
    assert fake.calls, "expected client.messages.create to be invoked"
    call = fake.calls[0]
    assert call["model"] == "claude-sonnet-4-6"
    assert call["max_tokens"] == 1024
    assert call["system"] == "You are the Engineer charter."
    assert call["messages"] == [
        {"role": "user", "content": "Implement REQ-FOO-1 with input validation."},
    ]
    assert getattr(fake, "api_key", None) == "sk-test"


def test_callable_respects_custom_model_and_max_tokens(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    fake = _install_fake_anthropic(
        monkeypatch,
        response=_FakeResponse([_FakeContent("hi")]),
    )
    callable_ = make_anthropic_role_callable(
        api_key="sk-test",
        model="claude-haiku-4-5",
        charter_path=_charter(tmp_path),
        max_tokens=256,
    )
    callable_(_eval(), 0)
    call = fake.calls[0]
    assert call["model"] == "claude-haiku-4-5"
    assert call["max_tokens"] == 256


# ─── API exception ───────────────────────────────────────────────────


def test_callable_wraps_api_exception(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    boom = RuntimeError("upstream 500")
    _install_fake_anthropic(monkeypatch, response=None, raises=boom)
    callable_ = make_anthropic_role_callable(
        api_key="sk-test",
        charter_path=_charter(tmp_path),
    )
    with pytest.raises(AnthropicCallableError, match="anthropic API call failed") as info:
        callable_(_eval(), 0)
    assert info.value.__cause__ is boom


# ─── Empty response ──────────────────────────────────────────────────


def test_callable_raises_on_empty_content_list(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _install_fake_anthropic(monkeypatch, response=_FakeResponse([]))
    callable_ = make_anthropic_role_callable(
        api_key="sk-test",
        charter_path=_charter(tmp_path),
    )
    with pytest.raises(AnthropicCallableError, match="no content"):
        callable_(_eval(), 0)


def test_callable_raises_on_missing_content_attr(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    class _NoContent:
        pass

    _install_fake_anthropic(monkeypatch, response=_NoContent())  # type: ignore[arg-type]
    callable_ = make_anthropic_role_callable(
        api_key="sk-test",
        charter_path=_charter(tmp_path),
    )
    with pytest.raises(AnthropicCallableError, match="no content"):
        callable_(_eval(), 0)


def test_callable_raises_on_empty_text(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _install_fake_anthropic(
        monkeypatch,
        response=_FakeResponse([_FakeContent("")]),
    )
    callable_ = make_anthropic_role_callable(
        api_key="sk-test",
        charter_path=_charter(tmp_path),
    )
    with pytest.raises(AnthropicCallableError, match="no content"):
        callable_(_eval(), 0)
