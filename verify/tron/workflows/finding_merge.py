"""Merge and dedupe finding dicts from multiple ISO agents (Temporal audit pipeline)."""

from __future__ import annotations

from typing import Any, Dict, List
from uuid import uuid4


def _layer3_rank(val: str | None) -> int:
    """Prefer stronger verification signals when merging duplicate fingerprints."""
    v = (val or "").lower()
    order = {"verified": 4, "skipped": 3, "unverified": 2, "not_applicable": 1}
    return order.get(v, 0)


def dedupe_findings_dicts(all_findings_dicts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Deduplicate by fingerprint; prefer tool-confirmed, then confidence, then Layer 3 strength."""
    seen: Dict[str, Dict[str, Any]] = {}
    for f in all_findings_dicts:
        fp = f.get("finding_fingerprint") or str(uuid4())
        if fp not in seen:
            seen[fp] = f
            continue
        existing = seen[fp]
        if f.get("deterministic_tool_confirmed") and not existing.get("deterministic_tool_confirmed"):
            seen[fp] = f
            continue
        if existing.get("deterministic_tool_confirmed") and not f.get("deterministic_tool_confirmed"):
            continue
        if float(f.get("confidence") or 0) > float(existing.get("confidence") or 0):
            seen[fp] = f
            continue
        if float(f.get("confidence") or 0) < float(existing.get("confidence") or 0):
            continue
        # Tie-break: prefer stronger layer3_execution
        if _layer3_rank(str(f.get("layer3_execution"))) > _layer3_rank(str(existing.get("layer3_execution"))):
            seen[fp] = f
    return list(seen.values())
