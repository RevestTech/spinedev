"""capability_checker.py — `can_*` capability enforcement for pipeline edits.

Implements `STORY-1.7.2` (capability grant + check) from `docs/BACKLOG.md`.
Backs PRD REQ-INIT-1 FR-7 in `docs/PRD.md`: titles are NOT authorities;
*capabilities* are. The org bundle declares `capabilities.grants.<cap>` as a
list of principals (`role:<name>` / `user:<id>` / `group:<id>`); a sub-bundle
(team, project) may narrow but never widen. We read the grants off the resolved
`PipelineManifest` (already post-narrowing — see `manifest_loader._capabilities_narrow`).

Known capability keys (mirrored from `shared/standards/bundle-schema.yaml`):
  - can_modify_sdlc_pipeline   — edit `pipeline_overrides.*`
  - can_modify_cost_policy     — edit `tier_routing` / cost caps
  - can_grant_capabilities     — add/remove principals in `capabilities.grants`
  - can_override_security      — relax security packs, ISO agents, etc.
"""
from __future__ import annotations

import re
from typing import Optional

from .manifest_loader import PipelineManifest

KNOWN_CAPABILITIES: set[str] = {
    "can_modify_sdlc_pipeline",
    "can_modify_cost_policy",
    "can_grant_capabilities",
    "can_override_security",
}
PRINCIPAL_RE = re.compile(r"^(role|user|group):[A-Za-z0-9_\-\*]+$")


class CapabilityDenied(PermissionError):
    """Raised when an actor lacks a required capability.

    Carries `actor` + `capability` so the caller (CLI, audit) can log a
    structured rejection without re-parsing the message.
    """

    def __init__(self, actor: str, capability: str, reason: str = "") -> None:
        self.actor = actor
        self.capability = capability
        self.reason = reason
        suffix = f": {reason}" if reason else ""
        super().__init__(f"capability denied for {actor!r}: {capability!r}{suffix}")


def _parse_actor(actor: str) -> tuple[str, str]:
    """('role:engineer') → ('role','engineer'). Tolerates bare 'engineer' (treated as user)."""
    if not actor or not isinstance(actor, str):
        raise CapabilityDenied(actor or "", "(unknown)", "actor must be a non-empty string")
    if ":" in actor:
        kind, _, name = actor.partition(":")
        if kind not in {"role", "user", "group"}:
            raise CapabilityDenied(actor, "(unknown)", f"unsupported principal kind {kind!r}")
        return kind, name
    return "user", actor


def _principal_matches(actor_kind: str, actor_name: str, principal: str) -> bool:
    """Wildcard-aware membership check (`role:*`, `user:alice`, …)."""
    if not PRINCIPAL_RE.match(principal):
        return False
    p_kind, _, p_name = principal.partition(":")
    if p_kind != actor_kind:
        return False
    return p_name == "*" or p_name == actor_name


def check_capability(actor: str, capability: str,
                     current_pipeline: PipelineManifest) -> bool:
    """Return True iff `actor` is granted `capability` by the resolved manifest.

    Unknown capability keys return False (closed-by-default).
    """
    if capability not in KNOWN_CAPABILITIES:
        return False
    try:
        actor_kind, actor_name = _parse_actor(actor)
    except CapabilityDenied:
        return False
    grants = (current_pipeline.capabilities or {}).get("grants") or {}
    principals = grants.get(capability) or []
    return any(_principal_matches(actor_kind, actor_name, p) for p in principals)


def require_capability(actor: str, capability: str,
                       pipeline: PipelineManifest) -> None:
    """Raise `CapabilityDenied` unless `actor` has `capability`.

    Use this as the single chokepoint before any pipeline-mutating operation
    (edit, lock-migrate, capability-grant) — see `versioning.commit_pipeline_edit`
    and `project_lock.migrate_locked_project`.
    """
    if capability not in KNOWN_CAPABILITIES:
        raise CapabilityDenied(actor, capability,
                               f"unknown capability (allowed: {sorted(KNOWN_CAPABILITIES)})")
    if not check_capability(actor, capability, pipeline):
        raise CapabilityDenied(actor, capability, "no matching grant in active bundle")


def list_grants(pipeline: PipelineManifest) -> dict[str, list[str]]:
    """Return the capability → principals map for UI display.

    Defensive copy so callers can mutate the result without affecting the
    manifest in-memory. Unknown-but-declared capabilities are passed through
    so the UI surfaces them as "unrecognized" rather than swallowing silently.
    """
    grants = (pipeline.capabilities or {}).get("grants") or {}
    out: dict[str, list[str]] = {}
    for cap in sorted(set(grants.keys()) | KNOWN_CAPABILITIES):
        out[cap] = list(grants.get(cap) or [])
    return out


def assert_rationale(actor: str, capability: str, rationale: Optional[str]) -> str:
    """Enforce PRD FR-8: rationale is required, never optional.

    Returns the trimmed rationale string. Raises `CapabilityDenied` (with
    capability label preserved) if it's missing or trivially short. Wired
    into `versioning.commit_pipeline_edit` as step 1.
    """
    if rationale is None or not isinstance(rationale, str) or len(rationale.strip()) < 8:
        raise CapabilityDenied(
            actor, capability,
            "rationale is required (min 8 chars) per PRD REQ-INIT-1 FR-8",
        )
    return rationale.strip()


__all__ = [
    "CapabilityDenied",
    "KNOWN_CAPABILITIES",
    "assert_rationale",
    "check_capability",
    "list_grants",
    "require_capability",
]
