"""Learning-scope resolver — Wave 4 Squad D / V3 #27.

Given a directive (hub_id, project_id, data_category) and the active
org-bundle policy snapshot, decide which of the three Smart Spine tiers
a lesson may flow to:

    Tier 1a — project    always granted
    Tier 1b — within_hub bundle-default ON; admin-disable per scope_policy
    Tier 2  — cross_org  bundle-default OFF; explicit, granular opt-in

The resolver is a PURE function operating on a :class:`ScopePolicy`
snapshot — the caller (typically :mod:`learning.contribute`) is
responsible for loading the snapshot from ``spine_learning.scope_policy``
or the org-bundle YAML. This keeps the resolver synchronous, DB-free,
and trivially unit-testable, while still letting Wave 5 wire a real
loader in front of it.

Snapshot loader contract (loose, optional):

    def loader(hub_id, project_id) -> ScopePolicy

Anything more sophisticated (caching / federation overlay) is the
loader's problem, not ours.

See ``db/flyway/sql/V29__smart_spine_learning.sql`` for the underlying
``spine_learning.scope_policy`` schema:

    within_hub_enabled     bool DEFAULT true
    cross_org_consent      bool DEFAULT false
    granular_consent_jsonb jsonb DEFAULT '{}'
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional


class LearningScope(str, Enum):
    """The 3 visibility tiers in V3 #27 (matches V29 ENUM).

    ``denied`` is a 4th, synthetic value meaning *no tier permitted*;
    used by :mod:`learning.contribute` to skip writes cleanly without
    raising.
    """
    PROJECT = "project"
    WITHIN_HUB = "within_hub"
    CROSS_ORG = "cross_org"
    DENIED = "denied"


#: Default data-category set. Matches the categories called out in the
#: Squad D spec ("granular opt-in per data class").
KNOWN_DATA_CATEGORIES: tuple[str, ...] = (
    "calibration_outcomes",
    "role_success_rates",
    "pattern_frequencies",
)


@dataclass(frozen=True)
class ScopePolicy:
    """Snapshot of a (hub, project) row from ``spine_learning.scope_policy``.

    Defaults align with V29 / #27:
        within_hub_enabled = True
        cross_org_consent  = False
        granular_consent   = {} (every category falls back to cross_org_consent)
    """
    hub_id: Optional[str] = None
    project_id: Optional[str] = None
    within_hub_enabled: bool = True
    cross_org_consent: bool = False
    granular_consent: dict[str, bool] = field(default_factory=dict)

    def cross_org_for(self, data_category: Optional[str]) -> bool:
        """Granular consent check.

        If ``granular_consent`` has an explicit entry for the category,
        that wins. Otherwise the overall ``cross_org_consent`` flag
        governs. Unknown categories follow the overall flag — the policy
        is *deny-friendly* (False default) so this is safe.
        """
        if data_category and data_category in self.granular_consent:
            return bool(self.granular_consent[data_category])
        return bool(self.cross_org_consent)


@dataclass(frozen=True)
class ScopeContext:
    """Per-directive context the resolver decides against."""
    hub_id: Optional[str] = None
    project_id: Optional[str] = None
    requested_scope: LearningScope = LearningScope.PROJECT
    data_category: Optional[str] = None
    # Optional bundle-policy overlay; e.g. an org bundle can set
    # ``learning.within_hub.enabled: false`` for a joint venture.
    bundle_within_hub_enabled: Optional[bool] = None
    # Optional bundle-policy overlay for cross_org default; can flip
    # the floor from False to True for vendor's own deployment but
    # explicit per-category consent still applies.
    bundle_cross_org_default: Optional[bool] = None


@dataclass(frozen=True)
class ResolvedScope:
    """Decision returned by :func:`resolve_scope`.

    ``granted_scope`` is the highest tier permitted that does not exceed
    ``requested_scope``. ``reason`` is a stable machine-readable token
    so audit + UI surfaces (Hub decision queue) can render it.
    """
    granted_scope: LearningScope
    requested_scope: LearningScope
    reason: str
    policy_snapshot: ScopePolicy

    def is_denied(self) -> bool:
        return self.granted_scope == LearningScope.DENIED


PolicyLoader = Callable[[Optional[str], Optional[str]], Optional[ScopePolicy]]
"""(hub_id, project_id) -> ScopePolicy | None — Wave-5-wired loader signature."""


def _merge_bundle_overlay(policy: ScopePolicy, ctx: ScopeContext) -> ScopePolicy:
    """Apply optional bundle-policy overlays onto a DB snapshot.

    Bundle overlays let an org admin tighten (or — for vendor — loosen)
    the DB default. The DB snapshot is still the persistent source of
    truth for explicit user consent, so bundle overlays cannot *force*
    cross_org consent to True; they may only adjust the *default* the
    granular check falls back to.
    """
    within = (
        ctx.bundle_within_hub_enabled
        if ctx.bundle_within_hub_enabled is not None
        else policy.within_hub_enabled
    )
    cross = (
        ctx.bundle_cross_org_default
        if ctx.bundle_cross_org_default is not None
        else policy.cross_org_consent
    )
    if within == policy.within_hub_enabled and cross == policy.cross_org_consent:
        return policy
    return ScopePolicy(
        hub_id=policy.hub_id,
        project_id=policy.project_id,
        within_hub_enabled=bool(within),
        cross_org_consent=bool(cross),
        granular_consent=dict(policy.granular_consent),
    )


def resolve_scope(
    ctx: ScopeContext,
    *,
    loader: Optional[PolicyLoader] = None,
    explicit_policy: Optional[ScopePolicy] = None,
) -> ResolvedScope:
    """Decide the highest tier a lesson may flow to.

    Precedence on the policy snapshot:
      1. ``explicit_policy`` if provided (tests / Hub UI preview).
      2. ``loader(hub_id, project_id)`` if provided.
      3. Default :class:`ScopePolicy` (within_hub ON, cross_org OFF).

    Then the bundle overlay is layered on top, and the requested scope
    is clamped down to whatever the policy permits.
    """
    if explicit_policy is not None:
        snapshot = explicit_policy
    elif loader is not None:
        snapshot = loader(ctx.hub_id, ctx.project_id) or ScopePolicy(
            hub_id=ctx.hub_id, project_id=ctx.project_id,
        )
    else:
        snapshot = ScopePolicy(hub_id=ctx.hub_id, project_id=ctx.project_id)

    snapshot = _merge_bundle_overlay(snapshot, ctx)
    requested = ctx.requested_scope

    # Tier 1a — project: always granted. Nothing to gate.
    if requested == LearningScope.PROJECT:
        return ResolvedScope(
            granted_scope=LearningScope.PROJECT,
            requested_scope=requested,
            reason="tier_1a_always_on",
            policy_snapshot=snapshot,
        )

    # Tier 1b — within_hub: bundle/scope policy may disable.
    if requested == LearningScope.WITHIN_HUB:
        if snapshot.within_hub_enabled:
            return ResolvedScope(
                granted_scope=LearningScope.WITHIN_HUB,
                requested_scope=requested,
                reason="tier_1b_default_on",
                policy_snapshot=snapshot,
            )
        # Disabled by admin (joint venture / legally isolated subsidiary):
        # silently downshift to project tier so callers don't lose the
        # lesson entirely. #27 explicitly allows project to always work.
        return ResolvedScope(
            granted_scope=LearningScope.PROJECT,
            requested_scope=requested,
            reason="tier_1b_disabled_by_policy",
            policy_snapshot=snapshot,
        )

    # Tier 2 — cross_org: explicit per-category opt-in required.
    if requested == LearningScope.CROSS_ORG:
        if snapshot.cross_org_for(ctx.data_category):
            return ResolvedScope(
                granted_scope=LearningScope.CROSS_ORG,
                requested_scope=requested,
                reason="tier_2_consent_granted",
                policy_snapshot=snapshot,
            )
        # No consent — downshift to highest tier still permitted, but
        # never *upshift* cross_org silently. If within_hub is on, allow
        # that; else project. Caller can detect via reason.
        if snapshot.within_hub_enabled:
            return ResolvedScope(
                granted_scope=LearningScope.WITHIN_HUB,
                requested_scope=requested,
                reason="tier_2_no_consent_downshifted_to_within_hub",
                policy_snapshot=snapshot,
            )
        return ResolvedScope(
            granted_scope=LearningScope.PROJECT,
            requested_scope=requested,
            reason="tier_2_no_consent_downshifted_to_project",
            policy_snapshot=snapshot,
        )

    # DENIED requested → DENIED returned.
    return ResolvedScope(
        granted_scope=LearningScope.DENIED,
        requested_scope=requested,
        reason="explicit_deny",
        policy_snapshot=snapshot,
    )


def policy_from_db_row(row: dict[str, Any]) -> ScopePolicy:
    """Convert a ``spine_learning.scope_policy`` row dict to a snapshot.

    Helper for Wave-5 loaders. Tolerates psql JSON casing variations.
    """
    granular_raw = row.get("granular_consent_jsonb") or {}
    if isinstance(granular_raw, str):
        # If psql returned JSON as text, leave the conversion to the
        # caller — we don't import json here for a quiet path. Drop to
        # empty + log nothing (resolver is hot-path-safe).
        granular: dict[str, bool] = {}
    else:
        granular = {str(k): bool(v) for k, v in granular_raw.items()}
    return ScopePolicy(
        hub_id=row.get("hub_id"),
        project_id=row.get("project_id"),
        within_hub_enabled=bool(row.get("within_hub_enabled", True)),
        cross_org_consent=bool(row.get("cross_org_consent", False)),
        granular_consent=granular,
    )


__all__ = [
    "KNOWN_DATA_CATEGORIES",
    "LearningScope",
    "PolicyLoader",
    "ResolvedScope",
    "ScopeContext",
    "ScopePolicy",
    "policy_from_db_row",
    "resolve_scope",
]
