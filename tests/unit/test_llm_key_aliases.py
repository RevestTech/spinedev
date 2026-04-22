"""Tests for Anthropic vault path merge (anthropic-key vs llm/anthropic-key)."""

from __future__ import annotations

from tron.infra.secrets.llm_aliases import merge_anthropic_key_aliases


def test_merge_prefers_anthropic_key_when_both_set() -> None:
    out = merge_anthropic_key_aliases(
        {
            "anthropic-key": "sk-ant-new",
            "llm/anthropic-key": "sk-ant-old",
        }
    )
    assert out["llm/anthropic-key"] == "sk-ant-new"
    assert out["anthropic-key"] == "sk-ant-new"


def test_merge_falls_back_to_llm_only() -> None:
    out = merge_anthropic_key_aliases({"llm/anthropic-key": "sk-ant-only"})
    assert out["llm/anthropic-key"] == "sk-ant-only"


def test_merge_ignores_placeholders() -> None:
    out = merge_anthropic_key_aliases(
        {
            "anthropic-key": "REPLACE_ME_IN_VAULT",
            "llm/anthropic-key": "sk-ant-from-llm",
        }
    )
    assert out["llm/anthropic-key"] == "sk-ant-from-llm"


def test_merge_strips_whitespace() -> None:
    out = merge_anthropic_key_aliases({"anthropic-key": "  sk-ant-trimmed  "})
    assert out["llm/anthropic-key"] == "sk-ant-trimmed"
