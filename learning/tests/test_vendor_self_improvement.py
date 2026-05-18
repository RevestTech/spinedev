"""Tier 3 vendor self-improvement tests — V3 #27 Tier 3 + #21."""
from __future__ import annotations

import os
import unittest
from typing import Any
from unittest import mock

from learning.scope import LearningScope
from learning.vendor_self_improvement import (
    VENDOR_ENV_KEY,
    VENDOR_ENV_VALUE,
    VendorSelfImprovementEvent,
    is_vendor_deployment,
    vendor_self_improvement_record,
)


class FakeWriter:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str]] = []

    def __call__(self, payload, tier, extras: dict[str, Any]) -> str:
        rid = f"row-{tier.value}-{len(self.rows)}"
        self.rows.append((tier.value, payload.lesson_text))
        return rid


class VendorDetectionTest(unittest.TestCase):
    def test_env_var_marks_vendor(self) -> None:
        with mock.patch.dict(os.environ, {VENDOR_ENV_KEY: VENDOR_ENV_VALUE}):
            self.assertTrue(is_vendor_deployment())

    def test_unset_env_is_not_vendor(self) -> None:
        env = {k: v for k, v in os.environ.items() if k != VENDOR_ENV_KEY}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertFalse(is_vendor_deployment())

    def test_bundle_flag_overrides_env(self) -> None:
        with mock.patch.dict(os.environ, {VENDOR_ENV_KEY: VENDOR_ENV_VALUE}):
            self.assertFalse(is_vendor_deployment(bundle_flag=False))

    def test_force_vendor_wins(self) -> None:
        env = {k: v for k, v in os.environ.items() if k != VENDOR_ENV_KEY}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertTrue(is_vendor_deployment(force_vendor=True))


class RecordTest(unittest.TestCase):
    def test_non_vendor_is_noop(self) -> None:
        ev = VendorSelfImprovementEvent(
            source_audit_record_id="11111111-1111-1111-1111-111111111111",
            lesson_text="x", event_key="verify.passed",
        )
        fw = FakeWriter()
        result = vendor_self_improvement_record(ev, writer=fw)
        self.assertFalse(result.accepted)
        self.assertEqual(fw.rows, [])

    def test_vendor_writes_all_3_tiers(self) -> None:
        ev = VendorSelfImprovementEvent(
            source_audit_record_id="22222222-2222-2222-2222-222222222222",
            lesson_text="phase advance succeeded",
            event_key="phase.advance.success",
            hub_id="vendor-hub", project_id="vendor-proj",
        )
        fw = FakeWriter()
        result = vendor_self_improvement_record(
            ev, force_vendor=True, writer=fw,
        )
        self.assertTrue(result.accepted)
        self.assertEqual(result.reason, "vendor_self_improvement_recorded")
        # All 3 tiers wrote (project, within_hub, cross_org).
        self.assertEqual({r[0] for r in fw.rows},
                         {"project", "within_hub", "cross_org"})

    def test_upstream_publisher_called(self) -> None:
        ev = VendorSelfImprovementEvent(
            source_audit_record_id="33333333-3333-3333-3333-333333333333",
            lesson_text="x", event_key="incident.resolved",
        )
        fw = FakeWriter()
        seen: list[str] = []

        def pub(event, outcome) -> bool:
            seen.append(event.event_key)
            return True

        result = vendor_self_improvement_record(
            ev, force_vendor=True, writer=fw, upstream_publisher=pub,
        )
        self.assertTrue(result.upstream_dispatched)
        self.assertEqual(seen, ["incident.resolved"])

    def test_upstream_failure_does_not_crash(self) -> None:
        ev = VendorSelfImprovementEvent(
            source_audit_record_id="44444444-4444-4444-4444-444444444444",
            lesson_text="x", event_key="build.completed",
        )

        def pub(event, outcome):
            raise RuntimeError("network down")

        result = vendor_self_improvement_record(
            ev, force_vendor=True, writer=FakeWriter(),
            upstream_publisher=pub,
        )
        self.assertTrue(result.accepted)
        self.assertFalse(result.upstream_dispatched)

    def test_recorded_at_uses_utc(self) -> None:
        ev = VendorSelfImprovementEvent(
            source_audit_record_id="55555555-5555-5555-5555-555555555555",
            lesson_text="x", event_key="approval.granted",
        )
        result = vendor_self_improvement_record(
            ev, force_vendor=True, writer=FakeWriter(),
        )
        self.assertIsNotNone(result.recorded_at.tzinfo)

    def test_default_writer_path_skipped_with_force(self) -> None:
        # Smoke: ensure passing scope CROSS_ORG via vendor doesn't blow
        # up on the policy-snapshot construction.
        ev = VendorSelfImprovementEvent(
            source_audit_record_id="66666666-6666-6666-6666-666666666666",
            lesson_text="x", event_key="verify.failed",
        )
        out = vendor_self_improvement_record(
            ev, force_vendor=True, writer=FakeWriter(),
        )
        assert out.outcome is not None
        self.assertEqual(
            out.outcome.decision.resolved.granted_scope,
            LearningScope.CROSS_ORG,
        )


if __name__ == "__main__":
    unittest.main()
