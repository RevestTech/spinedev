"""Normalize vault LLM key names so one canonical dict shape reaches agents."""

from __future__ import annotations

from typing import Dict, Mapping


def merge_anthropic_key_aliases(secrets: Mapping[str, str]) -> Dict[str, str]:
    """Pick Anthropic API key from supported vault paths.

    **Precedence:** ``anthropic-key`` (KMac: ``tron:anthropic_key``) wins over
    ``llm/anthropic-key`` (``tron:llm_anthropic_key``) when both are non-empty
    and not placeholders, so newer short-path entries override legacy rows.

    The chosen value is written to ``llm/anthropic-key``; callers and agents
    keep using that single logical path.

    Args:
        secrets: Raw dict from ``get_secrets`` (optionally including
            ``anthropic-key`` from a separate ``get_secret`` call).

    Returns:
        A shallow copy of ``secrets`` with ``llm/anthropic-key`` set when any
        alias resolves to a real key.
    """
    out: Dict[str, str] = dict(secrets)

    def _real(v: str | None) -> str | None:
        if not v:
            return None
        s = str(v).strip()
        if not s or s == "REPLACE_ME_IN_VAULT":
            return None
        return s

    chosen = _real(out.get("anthropic-key")) or _real(out.get("llm/anthropic-key"))
    if chosen:
        out["llm/anthropic-key"] = chosen
    return out
