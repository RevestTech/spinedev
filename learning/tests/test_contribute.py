"""Contribution-gate tests — V3 #27."""
from __future__ import annotations

import unittest
from typing import Any

from learning.contribute import (
    LessonPayload,
    contribute_lesson,
    gate,
)
from learning.scope import (
    LearningScope,
    ScopeContext,
    ScopePolicy,
)


class FakeWriter:
    """Captures writes; configurable failure per tier."""
    def __init__(self, failing_tier: str | None = None) -> None:
        self.rows: list[tuple[str, str]] = []
        self.failing_tier = failing_tier

    def __call__(self, payload, tier, extras: dict[str, Any]) -> str:
        if tier.value == self.failing_tier:
            raise RuntimeError("simulated psql failure")
        row_id = f"row-{tier.value}-{len(self.rows)}"
        self.rows.append((tier.value, payload.lesson_text))
        return row_id


class GateTest(unittest.TestCase):
    def test_project_only_includes_just_tier_1a(self) -> None:
        ctx = ScopeContext(
            project_id="p1", requested_scope=LearningScope.PROJECT,
        )
        d = gate(ctx)
        self.assertEqual(
            list(d.tiers_to_write), [LearningScope.PROJECT],
        )

    def test_within_hub_stacks_project_plus_hub(self) -> None:
        ctx = ScopeContext(
            hub_id="h", project_id="p", requested_scope=LearningScope.WITHIN_HUB,
        )
        d = gate(ctx)
        self.assertEqual(
            list(d.tiers_to_write),
            [LearningScope.PROJECT, LearningScope.WITHIN_HUB],
        )

    def test_cross_org_without_consent_skips_tier_2(self) -> None:
        ctx = ScopeContext(
            hub_id="h", project_id="p",
            requested_scope=LearningScope.CROSS_ORG,
            data_category="calibration_outcomes",
        )
        d = gate(ctx)  # default: within_hub on, cross_org off
        self.assertEqual(
            list(d.tiers_to_write),
            [LearningScope.PROJECT, LearningScope.WITHIN_HUB],
        )
        self.assertIn("cross_org", d.skipped_reasons)
        self.assertIn("calibration_outcomes", d.skipped_reasons["cross_org"])

    def test_cross_org_with_granular_consent_includes_tier_2(self) -> None:
        policy = ScopePolicy(
            cross_org_consent=False,
            granular_consent={"calibration_outcomes": True},
        )
        ctx = ScopeContext(
            hub_id="h", project_id="p",
            requested_scope=LearningScope.CROSS_ORG,
            data_category="calibration_outcomes",
        )
        d = gate(ctx, explicit_policy=policy)
        self.assertEqual(
            list(d.tiers_to_write),
            [LearningScope.PROJECT, LearningScope.WITHIN_HUB, LearningScope.CROSS_ORG],
        )

    def test_within_hub_disabled_records_skip_reason(self) -> None:
        policy = ScopePolicy(within_hub_enabled=False)
        ctx = ScopeContext(
            hub_id="h", project_id="p",
            requested_scope=LearningScope.WITHIN_HUB,
        )
        d = gate(ctx, explicit_policy=policy)
        self.assertEqual(list(d.tiers_to_write), [LearningScope.PROJECT])
        self.assertIn("within_hub", d.skipped_reasons)


class ContributeLessonTest(unittest.TestCase):
    def test_writes_one_row_per_permitted_tier(self) -> None:
        ctx = ScopeContext(
            hub_id="h", project_id="p",
            requested_scope=LearningScope.WITHIN_HUB,
        )
        payload = LessonPayload(lesson_text="phase advance succeeded")
        fw = FakeWriter()
        out = contribute_lesson(payload, ctx, writer=fw)
        self.assertEqual(out.total_written, 2)
        self.assertEqual(set(out.written), {"project", "within_hub"})
        self.assertEqual({r[0] for r in fw.rows}, {"project", "within_hub"})

    def test_per_tier_failure_isolated(self) -> None:
        ctx = ScopeContext(
            hub_id="h", project_id="p",
            requested_scope=LearningScope.WITHIN_HUB,
        )
        payload = LessonPayload(lesson_text="text")
        fw = FakeWriter(failing_tier="within_hub")
        out = contribute_lesson(payload, ctx, writer=fw)
        self.assertEqual(set(out.written), {"project"})  # tier 1a still wrote
        self.assertIn("within_hub", out.failed)

    def test_tier_2_blocked_without_consent_doesnt_write_cross_org(self) -> None:
        ctx = ScopeContext(
            hub_id="h", project_id="p",
            requested_scope=LearningScope.CROSS_ORG,
            data_category="role_success_rates",
        )
        payload = LessonPayload(lesson_text="text")
        fw = FakeWriter()
        out = contribute_lesson(payload, ctx, writer=fw)
        self.assertNotIn("cross_org", out.written)
        self.assertIn("cross_org", out.decision.skipped_reasons)

    def test_lesson_text_hash_stable(self) -> None:
        p = LessonPayload(lesson_text="hello")
        self.assertEqual(p.text_hash(), p.text_hash())


if __name__ == "__main__":
    unittest.main()
