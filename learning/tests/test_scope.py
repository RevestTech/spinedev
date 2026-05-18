"""Scope-resolver tests — V3 #27."""
from __future__ import annotations

import unittest

from learning.scope import (
    KNOWN_DATA_CATEGORIES,
    LearningScope,
    ScopeContext,
    ScopePolicy,
    policy_from_db_row,
    resolve_scope,
)


class ResolveScopeTest(unittest.TestCase):
    """Per-tier gating decisions."""

    def test_tier_1a_always_granted(self) -> None:
        ctx = ScopeContext(
            project_id="p1", requested_scope=LearningScope.PROJECT,
        )
        r = resolve_scope(ctx)
        self.assertEqual(r.granted_scope, LearningScope.PROJECT)
        self.assertEqual(r.reason, "tier_1a_always_on")

    def test_tier_1b_default_on(self) -> None:
        ctx = ScopeContext(
            hub_id="h1", project_id="p1",
            requested_scope=LearningScope.WITHIN_HUB,
        )
        r = resolve_scope(ctx)  # default policy: within_hub=True
        self.assertEqual(r.granted_scope, LearningScope.WITHIN_HUB)
        self.assertEqual(r.reason, "tier_1b_default_on")

    def test_tier_1b_disabled_by_policy(self) -> None:
        policy = ScopePolicy(
            hub_id="h1", project_id="p1", within_hub_enabled=False,
        )
        ctx = ScopeContext(
            hub_id="h1", project_id="p1",
            requested_scope=LearningScope.WITHIN_HUB,
        )
        r = resolve_scope(ctx, explicit_policy=policy)
        self.assertEqual(r.granted_scope, LearningScope.PROJECT)
        self.assertEqual(r.reason, "tier_1b_disabled_by_policy")

    def test_tier_2_default_off(self) -> None:
        ctx = ScopeContext(
            hub_id="h1", project_id="p1",
            requested_scope=LearningScope.CROSS_ORG,
            data_category="calibration_outcomes",
        )
        r = resolve_scope(ctx)
        # default policy has cross_org_consent=False AND within_hub=True
        # so caller is downshifted to within_hub, not all the way to project.
        self.assertEqual(r.granted_scope, LearningScope.WITHIN_HUB)
        self.assertEqual(
            r.reason, "tier_2_no_consent_downshifted_to_within_hub",
        )

    def test_tier_2_granular_consent_grants(self) -> None:
        policy = ScopePolicy(
            hub_id="h1", project_id="p1",
            within_hub_enabled=True,
            cross_org_consent=False,
            granular_consent={"calibration_outcomes": True},
        )
        ctx = ScopeContext(
            hub_id="h1", project_id="p1",
            requested_scope=LearningScope.CROSS_ORG,
            data_category="calibration_outcomes",
        )
        r = resolve_scope(ctx, explicit_policy=policy)
        self.assertEqual(r.granted_scope, LearningScope.CROSS_ORG)
        self.assertEqual(r.reason, "tier_2_consent_granted")

    def test_tier_2_granular_consent_denies_other_category(self) -> None:
        policy = ScopePolicy(
            hub_id="h1", project_id="p1",
            cross_org_consent=False,
            granular_consent={"calibration_outcomes": True},
        )
        ctx = ScopeContext(
            hub_id="h1", project_id="p1",
            requested_scope=LearningScope.CROSS_ORG,
            data_category="role_success_rates",  # NOT granted
        )
        r = resolve_scope(ctx, explicit_policy=policy)
        self.assertEqual(r.granted_scope, LearningScope.WITHIN_HUB)

    def test_tier_2_full_downshift_when_within_hub_off(self) -> None:
        policy = ScopePolicy(
            within_hub_enabled=False, cross_org_consent=False,
        )
        ctx = ScopeContext(
            hub_id="h1", project_id="p1",
            requested_scope=LearningScope.CROSS_ORG,
        )
        r = resolve_scope(ctx, explicit_policy=policy)
        self.assertEqual(r.granted_scope, LearningScope.PROJECT)
        self.assertEqual(r.reason, "tier_2_no_consent_downshifted_to_project")

    def test_bundle_overlay_can_disable_within_hub(self) -> None:
        # DB allows within_hub but bundle disables it (joint venture).
        policy = ScopePolicy(within_hub_enabled=True)
        ctx = ScopeContext(
            hub_id="h1", project_id="p1",
            requested_scope=LearningScope.WITHIN_HUB,
            bundle_within_hub_enabled=False,
        )
        r = resolve_scope(ctx, explicit_policy=policy)
        self.assertEqual(r.granted_scope, LearningScope.PROJECT)

    def test_loader_supplies_policy(self) -> None:
        seen: dict[str, str] = {}

        def loader(hub_id, project_id):
            seen["hub"] = hub_id or ""
            seen["proj"] = project_id or ""
            return ScopePolicy(hub_id=hub_id, project_id=project_id,
                               within_hub_enabled=False)

        ctx = ScopeContext(
            hub_id="hX", project_id="pY",
            requested_scope=LearningScope.WITHIN_HUB,
        )
        r = resolve_scope(ctx, loader=loader)
        self.assertEqual(seen, {"hub": "hX", "proj": "pY"})
        self.assertEqual(r.granted_scope, LearningScope.PROJECT)

    def test_loader_returns_none_uses_default(self) -> None:
        ctx = ScopeContext(
            hub_id="h", project_id="p",
            requested_scope=LearningScope.WITHIN_HUB,
        )
        r = resolve_scope(ctx, loader=lambda *_: None)
        # default policy → within_hub on
        self.assertEqual(r.granted_scope, LearningScope.WITHIN_HUB)

    def test_explicit_deny(self) -> None:
        ctx = ScopeContext(
            project_id="p", requested_scope=LearningScope.DENIED,
        )
        r = resolve_scope(ctx)
        self.assertTrue(r.is_denied())


class PolicySnapshotTest(unittest.TestCase):
    def test_from_db_row(self) -> None:
        row = {
            "hub_id": "h1", "project_id": None,
            "within_hub_enabled": True, "cross_org_consent": False,
            "granular_consent_jsonb": {"calibration_outcomes": True},
        }
        p = policy_from_db_row(row)
        self.assertTrue(p.within_hub_enabled)
        self.assertFalse(p.cross_org_consent)
        self.assertTrue(p.cross_org_for("calibration_outcomes"))
        self.assertFalse(p.cross_org_for("role_success_rates"))

    def test_known_categories_constant(self) -> None:
        self.assertIn("calibration_outcomes", KNOWN_DATA_CATEGORIES)
        self.assertIn("role_success_rates", KNOWN_DATA_CATEGORIES)
        self.assertIn("pattern_frequencies", KNOWN_DATA_CATEGORIES)


if __name__ == "__main__":
    unittest.main()
