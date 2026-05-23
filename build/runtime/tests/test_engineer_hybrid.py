"""Tests for engineer hybrid executor wrapper."""

from __future__ import annotations

from build.runtime.engineer_hybrid import executor_available, hybrid_enabled


def test_hybrid_disabled_by_env(monkeypatch) -> None:
    monkeypatch.setenv("SPINE_ENGINEER_HYBRID", "0")
    assert hybrid_enabled() is False


def test_executor_available_with_kind_override(monkeypatch) -> None:
    monkeypatch.setenv("EXECUTOR_KIND", "generic")
    monkeypatch.setenv("EXECUTOR_CMD", "echo ok")
    assert executor_available() is True
