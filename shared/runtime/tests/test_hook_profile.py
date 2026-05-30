"""Tests for ``shared.runtime.hook_profile`` (V3 B7)."""
from __future__ import annotations

import pytest

from shared.runtime.hook_profile import (
    DEFAULT_PROFILE,
    DISABLED_ENV,
    PROFILE_ENV,
    active_profile,
    disabled_hooks,
    explain,
    is_hook_active,
)


# ─── active_profile ───


def test_default_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(PROFILE_ENV, raising=False)
    assert active_profile() == DEFAULT_PROFILE


def test_recognised_values_pass_through(monkeypatch: pytest.MonkeyPatch) -> None:
    for value in ("minimal", "standard", "strict"):
        monkeypatch.setenv(PROFILE_ENV, value)
        assert active_profile() == value


def test_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(PROFILE_ENV, "STRICT")
    assert active_profile() == "strict"


def test_unknown_falls_back_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(PROFILE_ENV, "paranoid")
    assert active_profile() == DEFAULT_PROFILE


# ─── disabled_hooks ───


def test_disabled_hooks_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(DISABLED_ENV, raising=False)
    assert disabled_hooks() == frozenset()


def test_disabled_hooks_parses_csv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(DISABLED_ENV, "tron.db.reachable, env.postgres_container ,")
    assert disabled_hooks() == frozenset(
        {"tron.db.reachable", "env.postgres_container"}
    )


# ─── is_hook_active ───


def test_standard_profile_runs_standard_hooks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(PROFILE_ENV, "standard")
    assert is_hook_active("smoke.basic", minimum_profile="standard") is True


def test_minimal_profile_skips_standard_hooks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(PROFILE_ENV, "minimal")
    assert is_hook_active("smoke.basic", minimum_profile="standard") is False


def test_strict_profile_runs_strict_hooks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(PROFILE_ENV, "strict")
    assert is_hook_active("llm.audit", minimum_profile="strict") is True


def test_standard_profile_skips_strict_hooks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(PROFILE_ENV, "standard")
    assert is_hook_active("llm.audit", minimum_profile="strict") is False


def test_disabled_overrides_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(PROFILE_ENV, "strict")
    monkeypatch.setenv(DISABLED_ENV, "llm.audit")
    assert is_hook_active("llm.audit", minimum_profile="strict") is False


def test_empty_name_rejected() -> None:
    assert is_hook_active("") is False
    assert is_hook_active("   ") is False


def test_invalid_minimum_profile_rejected() -> None:
    assert is_hook_active("any", minimum_profile="bogus") is False  # type: ignore[arg-type]


# ─── explain ───


def test_explain_active(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(PROFILE_ENV, "strict")
    assert "active" in explain("a", minimum_profile="standard")


def test_explain_skipped_due_to_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(PROFILE_ENV, "minimal")
    line = explain("a", minimum_profile="standard")
    assert "skipped" in line
    assert "standard" in line and "minimal" in line


def test_explain_skipped_due_to_disable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(PROFILE_ENV, "strict")
    monkeypatch.setenv(DISABLED_ENV, "a")
    assert "disabled" in explain("a")
