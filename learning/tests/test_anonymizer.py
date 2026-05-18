"""Tier 2 anonymization tests — V3 #27 (anonymized + aggregated only)."""
from __future__ import annotations

import unittest

from learning.anonymizer import (
    AnonymizationMethodKind,
    anonymize_for_cross_org,
    available_methods,
    differential_privacy_method,
    k_anonymity_method,
    synthetic_method,
)


class KAnonymityTest(unittest.TestCase):
    def test_passes_when_k_met(self) -> None:
        result = anonymize_for_cross_org(
            pattern_class="late_qa_gate",
            count=42, period="2026-05",
            contributor_ids=[f"c-{i}" for i in range(5)],
        )
        self.assertTrue(result.release_ok)
        self.assertEqual(result.count, 42)
        self.assertEqual(result.anonymization_method, "k_anonymity_5")
        self.assertEqual(result.report.contributor_count, 5)

    def test_suppressed_below_k(self) -> None:
        result = anonymize_for_cross_org(
            pattern_class="late_qa_gate",
            count=10, period="2026-05",
            contributor_ids=["a", "b", "c"],
        )
        self.assertFalse(result.release_ok)
        self.assertEqual(result.count, 0)
        self.assertIn("k_anonymity_violation", result.report.suppressed_reason or "")

    def test_custom_k(self) -> None:
        result = anonymize_for_cross_org(
            pattern_class="repeated_rollback",
            count=7, period="2026-05",
            contributor_ids=[f"c-{i}" for i in range(10)],
            method=k_anonymity_method(k=10),
        )
        self.assertTrue(result.release_ok)
        self.assertEqual(result.anonymization_method, "k_anonymity_10")

    def test_distinct_contributors_only(self) -> None:
        # 8 entries but only 3 distinct → fails k=5
        result = anonymize_for_cross_org(
            pattern_class="foo", count=1, period="p",
            contributor_ids=["a"] * 3 + ["b"] * 3 + ["c"] * 2,
        )
        self.assertFalse(result.release_ok)


class FieldScrubTest(unittest.TestCase):
    def test_denylist_fields_scrubbed(self) -> None:
        result = anonymize_for_cross_org(
            pattern_class="foo",
            count=20, period="2026-05",
            contributor_ids=[f"c-{i}" for i in range(5)],
            extra_fields={
                "user_email": "khash@khash.com",
                "project_name": "secret-project",
                "ok_field": "fine",
            },
        )
        self.assertIn("user_email", result.redacted_fields)
        self.assertIn("project_name", result.redacted_fields)
        self.assertNotIn("ok_field", result.redacted_fields)

    def test_pii_regex_in_other_field(self) -> None:
        result = anonymize_for_cross_org(
            pattern_class="foo", count=10, period="p",
            contributor_ids=[f"c-{i}" for i in range(5)],
            extra_fields={"freeform": "ping me at user@example.com"},
        )
        self.assertIn("freeform", result.redacted_fields)

    def test_pattern_class_with_pii_refused(self) -> None:
        result = anonymize_for_cross_org(
            pattern_class="failed for user@bank.com",
            count=10, period="p",
            contributor_ids=[f"c-{i}" for i in range(5)],
        )
        self.assertFalse(result.release_ok)
        self.assertEqual(result.report.suppressed_reason, "pii_in_pattern_class")


class DifferentialPrivacyTest(unittest.TestCase):
    def test_dp_method_releases_with_noise(self) -> None:
        method = differential_privacy_method(epsilon=1)
        result = anonymize_for_cross_org(
            pattern_class="late_qa_gate",
            count=100, period="2026-05",
            contributor_ids=["a", "b"],  # k=2 ignored for DP
            method=method,
            deterministic_noise_seed=7,
        )
        self.assertTrue(result.release_ok)
        self.assertEqual(result.anonymization_method, "differential_privacy_eps1")
        self.assertIsNotNone(result.report.noise_added)

    def test_dp_invalid_epsilon(self) -> None:
        with self.assertRaises(ValueError):
            differential_privacy_method(epsilon=0)


class SyntheticTest(unittest.TestCase):
    def test_synthetic_collapses_count(self) -> None:
        result = anonymize_for_cross_org(
            pattern_class="late_qa_gate",
            count=10000, period="2026-05",
            contributor_ids=["a", "b"],  # k=2 — DP/synthetic don't care
            method=synthetic_method(),
        )
        self.assertTrue(result.release_ok)
        self.assertEqual(result.count, 1)
        self.assertEqual(result.anonymization_method, "synthetic")

    def test_synthetic_zero_stays_zero(self) -> None:
        result = anonymize_for_cross_org(
            pattern_class="late_qa_gate",
            count=0, period="2026-05",
            contributor_ids=[],
            method=synthetic_method(),
        )
        self.assertTrue(result.release_ok)
        self.assertEqual(result.count, 0)


class IntrospectionTest(unittest.TestCase):
    def test_available_methods_contains_default(self) -> None:
        self.assertIn("k_anonymity_5", available_methods())

    def test_method_kind_enum(self) -> None:
        self.assertEqual(
            k_anonymity_method().kind, AnonymizationMethodKind.K_ANONYMITY,
        )


if __name__ == "__main__":
    unittest.main()
