"""Story sizing heuristic for the Spine decomposer (STORY-1.3.2).

Given a story description, the relevant TRD slice, and (optionally) a KG
`impact_radius` result, we project a t-shirt size, rough cost, and rough
duration. Placeholder rates — refine once `EPIC-1.5` cost-router has real
history.

Heuristics (additive):
- prose volume (LOC proxy)
- KG impact count (strongest signal when available)
- keyword categories: security, novel data model, external integration,
  distributed / async / migration
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from plan.artifacts._base import Size

_SIZE_COST_USD: dict[Size, float] = {
    Size.XS: 1.0, Size.S: 5.0, Size.M: 25.0, Size.L: 100.0, Size.XL: 500.0,
}
_SIZE_HOURS: dict[Size, int] = {
    Size.XS: 4, Size.S: 16, Size.M: 60, Size.L: 180, Size.XL: 600,
}
_SIZE_DURATION: dict[Size, str] = {
    Size.XS: "<1 day", Size.S: "1-3 days", Size.M: "1-2 weeks",
    Size.L: "3-6 weeks", Size.XL: "release-scale",
}

_SECURITY_KW = re.compile(
    r"\b(auth|oauth|jwt|password|secret|encrypt|decrypt|tls|mtls|rbac|acl|"
    r"permission|capability|vault|kms|pii|gdpr|hipaa|compliance)\b", re.IGNORECASE,
)
_NOVEL_MODEL_KW = re.compile(
    r"\b(schema|migration|entity|table|column|index|partition|foreign[- ]key|"
    r"new[- ]?model)\b", re.IGNORECASE,
)
_INTEGRATION_KW = re.compile(
    r"\b(webhook|api|rest|grpc|sqs|kafka|pubsub|sns|s3|stripe|twilio|sendgrid|"
    r"slack|github|jira|linear|integration|third[- ]party)\b", re.IGNORECASE,
)
_DISTRIBUTED_KW = re.compile(
    r"\b(distributed|async|queue|saga|consensus|leader|shard|replica|raft|paxos)\b",
    re.IGNORECASE,
)


@dataclass
class SizingResult:
    """Output of `estimate_size()` — drives Story.size + Story.estimate_*."""

    size: Size
    estimated_cost_usd: float
    estimated_duration_hours: int
    estimated_duration_label: str
    rationale: list[str]


def estimate_size(
    story_text: str,
    trd_section: dict | None = None,
    kg_impact: list[str] | None = None,
) -> SizingResult:
    """Heuristic XS/S/M/L/XL bucket + cost + duration projection."""
    points = 0
    rationale: list[str] = []
    text = (story_text or "").strip()
    word_count = len(text.split())
    if word_count > 200:
        points += 3
        rationale.append(f"long brief ({word_count} words)")
    elif word_count > 80:
        points += 1
        rationale.append(f"medium brief ({word_count} words)")

    impact_count = len(kg_impact or [])
    if impact_count > 50:
        points += 5
        rationale.append(f"KG impact: {impact_count} nodes (large blast radius)")
    elif impact_count > 15:
        points += 3
        rationale.append(f"KG impact: {impact_count} nodes")
    elif impact_count > 3:
        points += 1
        rationale.append(f"KG impact: {impact_count} nodes")

    haystack = text + " " + _flatten_trd(trd_section)
    if _SECURITY_KW.search(haystack):
        points += 2; rationale.append("security/auth touch")
    if _NOVEL_MODEL_KW.search(haystack):
        points += 2; rationale.append("novel data model")
    if _INTEGRATION_KW.search(haystack):
        points += 2; rationale.append("external integration")
    if _DISTRIBUTED_KW.search(haystack):
        points += 3; rationale.append("distributed / async")

    size = _points_to_size(points)
    return SizingResult(
        size=size,
        estimated_cost_usd=_SIZE_COST_USD[size],
        estimated_duration_hours=_SIZE_HOURS[size],
        estimated_duration_label=_SIZE_DURATION[size],
        rationale=rationale or ["base heuristic (no strong signals)"],
    )


def _points_to_size(points: int) -> Size:
    """Bucket the heuristic score into a t-shirt size."""
    if points <= 0:
        return Size.XS
    if points <= 2:
        return Size.S
    if points <= 5:
        return Size.M
    if points <= 9:
        return Size.L
    return Size.XL


def _flatten_trd(trd_section: dict | None) -> str:
    """Best-effort flatten a TRD slice dict into a single string for kw scan."""
    if not trd_section:
        return ""
    parts: list[str] = []

    def _walk(node: object) -> None:
        if isinstance(node, str):
            parts.append(node)
        elif isinstance(node, dict):
            for v in node.values():
                _walk(v)
        elif isinstance(node, (list, tuple)):
            for v in node:
                _walk(v)

    _walk(trd_section)
    return " ".join(parts)


__all__ = ["estimate_size", "SizingResult"]
