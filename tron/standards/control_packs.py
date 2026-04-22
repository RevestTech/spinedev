"""Shipped compliance *reference* control packs (structured JSON, not third-party attestation)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

_PACKS_DIR = Path(__file__).resolve().parent / "packs"


def _pack_path(pack_id: str) -> Path:
    if not pack_id or "/" in pack_id or "\\" in pack_id or ".." in pack_id:
        raise ValueError("invalid pack id")
    return _PACKS_DIR / f"{pack_id}.json"


def list_pack_ids() -> list[str]:
    """Return ids of built-in packs shipped with Tron."""
    if not _PACKS_DIR.is_dir():
        return []
    return sorted(p.stem for p in _PACKS_DIR.glob("*.json"))


@lru_cache(maxsize=32)
def _read_pack_bytes(pack_id: str) -> bytes:
    path = _pack_path(pack_id)
    if not path.is_file():
        raise FileNotFoundError(pack_id)
    return path.read_bytes()


def load_pack(pack_id: str) -> dict[str, Any]:
    """Load one pack by id (raises FileNotFoundError if unknown)."""
    return json.loads(_read_pack_bytes(pack_id).decode("utf-8"))


def summarize_pack_for_prompt(pack: dict[str, Any], max_chars: int = 6000) -> str:
    lines = [
        f"## Reference pack: {pack.get('title', pack.get('id', 'unknown'))}",
        str(pack.get("disclaimer", "")),
        "",
    ]
    for t in pack.get("themes") or []:
        if isinstance(t, dict):
            lines.append(f"- **{t.get('id', '')}**: {t.get('summary', '')}")
    text = "\n".join(lines).strip()
    if len(text) > max_chars:
        return text[: max_chars - 20] + "\n…(truncated)"
    return text


def format_packs_for_prompt(pack_ids: Optional[list[str]], max_total_chars: int = 12000) -> str:
    """Merge selected built-in packs into one user prompt section."""
    if not pack_ids:
        return ""
    chunks: list[str] = []
    total = 0
    for raw in pack_ids:
        pid = (raw or "").strip()
        if not pid:
            continue
        try:
            pack = load_pack(pid)
        except (FileNotFoundError, ValueError, json.JSONDecodeError):
            continue
        chunk = summarize_pack_for_prompt(pack)
        if total + len(chunk) > max_total_chars:
            break
        chunks.append(chunk)
        total += len(chunk)
    if not chunks:
        return ""
    return (
        "## Compliance reference packs (built-in)\n"
        "Use these themes to prioritize findings. Do not claim external certification.\n\n"
        + "\n\n".join(chunks)
    )
