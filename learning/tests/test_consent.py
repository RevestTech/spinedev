"""Consent-registry tests — V3 #27 cross-org opt-in."""
from __future__ import annotations

import unittest
from typing import Any

from learning.consent import (
    ConsentRecord,
    grant_cross_org_consent,
    list_cross_org_consents,
    revoke_cross_org_consent,
)
from learning.scope import KNOWN_DATA_CATEGORIES, ScopePolicy


class FakeStore:
    """In-memory consent backend used to drive writer + reader."""
    def __init__(self) -> None:
        self.policies: dict[tuple[str | None, str | None], ScopePolicy] = {}

    def writer(self, record: ConsentRecord, extras: dict[str, Any]) -> ScopePolicy:
        key = (record.hub_id, record.project_id)
        prior = self.policies.get(key)
        merged_granular = dict(prior.granular_consent if prior else {})
        merged_granular.update({k: bool(v) for k, v in record.granular.items()})
        policy = ScopePolicy(
            hub_id=record.hub_id,
            project_id=record.project_id,
            within_hub_enabled=True,
            cross_org_consent=bool(record.cross_org_consent),
            granular_consent=merged_granular,
        )
        self.policies[key] = policy
        return policy

    def reader(self, hub_id, extras: dict[str, Any]) -> list[ScopePolicy]:
        return [
            p for (h, _), p in self.policies.items()
            if hub_id is None or h == hub_id
        ]


class ConsentRecordTest(unittest.TestCase):
    def test_validate_requires_hub_or_project(self) -> None:
        with self.assertRaises(ValueError):
            ConsentRecord(hub_id=None, project_id=None).validate()

    def test_validate_accepts_hub(self) -> None:
        ConsentRecord(hub_id="h").validate()


class GrantConsentTest(unittest.TestCase):
    def test_grant_writes_policy(self) -> None:
        store = FakeStore()
        rec = ConsentRecord(
            hub_id="h1",
            cross_org_consent=True,
            granular={"calibration_outcomes": True},
            granted_by="admin@org",
            rationale="enterprise SOC2 needs benchmark data",
        )
        d = grant_cross_org_consent(rec, writer=store.writer)
        self.assertEqual(d.operation, "grant")
        self.assertTrue(d.effective_policy.cross_org_consent)
        self.assertTrue(
            d.effective_policy.cross_org_for("calibration_outcomes"),
        )

    def test_grant_merges_granular_not_overwrite(self) -> None:
        store = FakeStore()
        grant_cross_org_consent(
            ConsentRecord(
                hub_id="h", cross_org_consent=True,
                granular={"calibration_outcomes": True},
            ),
            writer=store.writer,
        )
        # second grant: add a different category WITHOUT touching the first
        grant_cross_org_consent(
            ConsentRecord(
                hub_id="h", cross_org_consent=True,
                granular={"role_success_rates": True},
            ),
            writer=store.writer,
        )
        policies = list_cross_org_consents(reader=store.reader)
        self.assertEqual(len(policies), 1)
        granular = policies[0].granular_consent
        self.assertTrue(granular.get("calibration_outcomes"))
        self.assertTrue(granular.get("role_success_rates"))


class RevokeConsentTest(unittest.TestCase):
    def test_full_revoke_clears_umbrella(self) -> None:
        store = FakeStore()
        grant_cross_org_consent(
            ConsentRecord(
                hub_id="h", cross_org_consent=True,
                granular={c: True for c in KNOWN_DATA_CATEGORIES},
            ),
            writer=store.writer,
        )
        d = revoke_cross_org_consent("h", writer=store.writer)
        self.assertEqual(d.operation, "revoke")
        self.assertFalse(d.effective_policy.cross_org_consent)
        for cat in KNOWN_DATA_CATEGORIES:
            self.assertFalse(d.effective_policy.cross_org_for(cat))

    def test_category_revoke_keeps_umbrella(self) -> None:
        store = FakeStore()
        grant_cross_org_consent(
            ConsentRecord(
                hub_id="h", cross_org_consent=True,
                granular={"calibration_outcomes": True,
                          "role_success_rates": True},
            ),
            writer=store.writer,
        )
        d = revoke_cross_org_consent(
            "h", category="calibration_outcomes", writer=store.writer,
        )
        self.assertEqual(d.operation, "revoke_category")
        self.assertTrue(d.effective_policy.cross_org_consent)
        self.assertFalse(d.effective_policy.cross_org_for("calibration_outcomes"))
        self.assertTrue(d.effective_policy.cross_org_for("role_success_rates"))


class ListConsentTest(unittest.TestCase):
    def test_filter_by_hub(self) -> None:
        store = FakeStore()
        grant_cross_org_consent(
            ConsentRecord(hub_id="h1", cross_org_consent=True),
            writer=store.writer,
        )
        grant_cross_org_consent(
            ConsentRecord(hub_id="h2", cross_org_consent=True),
            writer=store.writer,
        )
        only = list_cross_org_consents("h1", reader=store.reader)
        self.assertEqual(len(only), 1)
        self.assertEqual(only[0].hub_id, "h1")


if __name__ == "__main__":
    unittest.main()
