"""
federation/tests/test_consent.py
================================

Unit tests for `federation.consent.ConsentEngine`:

* peer-consent default: empty registry → deny
* `grant` + `is_allowed` → allow
* `revoke` removes the grant
* `from_bundle_policy` enforces rationale-on-mandatory
* mandatory upward flow → allow regardless of peer grant
* mandatory upward flow → revoke raises MandatoryFlowDenied
"""

from __future__ import annotations

import asyncio
import unittest

from federation.consent import ConsentEngine, MandatoryFlowDenied
from federation.tests._mock_pool import make_pool, new_uuid


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class TestConsentDefaults(unittest.TestCase):
    def test_empty_registry_denies(self):
        eng = ConsentEngine(pool=make_pool())
        peer = new_uuid()
        self.assertFalse(_run(eng.is_allowed(peer, "telemetry")))

    def test_grant_then_allow(self):
        eng = ConsentEngine(pool=make_pool())
        child = new_uuid()
        parent = new_uuid()

        async def go():
            await eng.grant(
                child_hub_id=child,
                parent_hub_id=parent,
                consent_class="telemetry",
                granted_by="alice@example.com",
            )
            self.assertTrue(await eng.is_allowed(child, "telemetry"))
            self.assertTrue(await eng.is_allowed(parent, "telemetry"))
            # different class → still denied
            self.assertFalse(await eng.is_allowed(child, "audit_export"))

        _run(go())

    def test_grant_requires_granted_by(self):
        eng = ConsentEngine(pool=make_pool())

        async def go():
            await eng.grant(
                child_hub_id=new_uuid(),
                parent_hub_id=new_uuid(),
                consent_class="telemetry",
                granted_by="",
            )

        self.assertRaises(ValueError, _run, go())

    def test_revoke_drops_grant(self):
        eng = ConsentEngine(pool=make_pool())
        child = new_uuid()
        parent = new_uuid()

        async def go():
            await eng.grant(
                child_hub_id=child,
                parent_hub_id=parent,
                consent_class="telemetry",
                granted_by="alice",
            )
            await eng.revoke(
                child_hub_id=child,
                parent_hub_id=parent,
                consent_class="telemetry",
            )
            self.assertFalse(await eng.is_allowed(child, "telemetry"))

        _run(go())


class TestMandatoryUpward(unittest.TestCase):
    def test_from_bundle_policy_empty_ok(self):
        eng = ConsentEngine.from_bundle_policy(make_pool(), None)
        self.assertEqual(eng.mandatory_upward, ())

    def test_from_bundle_policy_requires_rationale(self):
        bad = {
            "consent": {
                "mandatory_upward": [{"class": "security_incident"}],
            },
        }
        with self.assertRaises(ValueError):
            ConsentEngine.from_bundle_policy(make_pool(), bad)

    def test_mandatory_overrides_default_deny(self):
        good = {
            "consent": {
                "mandatory_upward": [
                    {
                        "class": "security_incident",
                        "rationale": "SOC2 CC7.4",
                    },
                ],
            },
        }
        eng = ConsentEngine.from_bundle_policy(make_pool(), good)
        peer = new_uuid()
        # No grant in registry, but mandatory_upward → allowed.
        self.assertTrue(_run(eng.is_allowed(peer, "security_incident")))
        # Non-mandatory class still denied.
        self.assertFalse(_run(eng.is_allowed(peer, "telemetry")))

    def test_revoke_mandatory_class_raises(self):
        good = {
            "consent": {
                "mandatory_upward": [
                    {
                        "class": "security_incident",
                        "rationale": "Compliance",
                    },
                ],
            },
        }
        eng = ConsentEngine.from_bundle_policy(make_pool(), good)

        async def go():
            await eng.revoke(
                child_hub_id=new_uuid(),
                parent_hub_id=new_uuid(),
                consent_class="security_incident",
            )

        self.assertRaises(MandatoryFlowDenied, _run, go())

    def test_mandatory_rationale_lookup(self):
        good = {
            "consent": {
                "mandatory_upward": [
                    {"class": "audit_export", "rationale": "evidence chain"},
                ],
            },
        }
        eng = ConsentEngine.from_bundle_policy(make_pool(), good)
        self.assertEqual(
            eng.mandatory_rationale("audit_export"), "evidence chain"
        )
        self.assertIsNone(eng.mandatory_rationale("telemetry"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
