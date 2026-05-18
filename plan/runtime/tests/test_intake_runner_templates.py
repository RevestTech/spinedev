"""Tests for ``plan.runtime.intake_runner`` template router + loader.

OP3 Wave 3.5 cleanup — verifies the runner can now load the Wave-2
Squad-2 work-item-type templates (bug/incident/support/refactor/infra/
compliance) in addition to the legacy product-archetype templates
(cli-tool/web-app/internal-tool/data-pipeline/mobile/api-service).
"""

from __future__ import annotations

import unittest

from plan.runtime import intake_runner


LEGACY_TEMPLATES = (
    "cli-tool", "web-app", "internal-tool", "data-pipeline",
    "mobile", "api-service",
)
WAVE2_TEMPLATES = ("bug", "incident", "support", "refactor", "infra", "compliance")


class TemplateLoaderTest(unittest.TestCase):
    """`load_template` should normalise BOTH template shapes."""

    def test_legacy_templates_load_with_questions_key(self) -> None:
        for name in LEGACY_TEMPLATES:
            with self.subTest(template=name):
                parsed, version = intake_runner.load_template(name)
                self.assertIn("questions", parsed, name)
                self.assertGreater(len(parsed["questions"]), 0, name)
                self.assertIn("mtime=", version)

    def test_wave2_templates_normalise_required_fields_to_questions(self) -> None:
        for name in WAVE2_TEMPLATES:
            with self.subTest(template=name):
                parsed, _ = intake_runner.load_template(name)
                self.assertIn(
                    "questions", parsed,
                    f"{name}: load_template MUST surface a 'questions' key "
                    f"(normalised from required_fields)",
                )
                self.assertGreater(len(parsed["questions"]), 0, name)
                # First field must always be the title (Wave-2 convention)
                first = parsed["questions"][0]
                self.assertEqual(first.get("id"), "title", name)
                self.assertTrue(first.get("required"), name)

    def test_wave2_type_multi_normalised_to_multi_choice(self) -> None:
        """Wave-2 uses ``type: multi``; runner only speaks ``multi_choice``."""
        parsed, _ = intake_runner.load_template("bug")
        affected = next(
            (q for q in parsed["questions"] if q["id"] == "affected_versions"), None
        )
        self.assertIsNotNone(affected, "bug template missing affected_versions")
        # type: multi  →  type: multi_choice  (or open if no options)
        self.assertIn(affected["type"], ("multi_choice", "open"))


class TemplateRouterTest(unittest.TestCase):
    """`_resolve_template_name` should honour work_item_type per #19."""

    def test_work_item_type_routes_to_matching_template(self) -> None:
        for wit in WAVE2_TEMPLATES:
            with self.subTest(work_item_type=wit):
                resolved = intake_runner._resolve_template_name(
                    explicit=None,
                    project_metadata={},
                    project_type="greenfield",
                    work_item_type=wit,
                )
                self.assertEqual(resolved, wit)

    def test_feature_work_item_type_falls_through_to_project_type(self) -> None:
        """``feature`` is the catch-all; should defer to project_type default."""
        resolved = intake_runner._resolve_template_name(
            explicit=None,
            project_metadata={},
            project_type="greenfield",
            work_item_type="feature",
        )
        # greenfield default is cli-tool; should NOT collapse to literal "feature"
        self.assertEqual(resolved, "cli-tool")

    def test_explicit_template_wins(self) -> None:
        resolved = intake_runner._resolve_template_name(
            explicit="web-app",
            project_metadata={},
            project_type="greenfield",
            work_item_type="bug",
        )
        self.assertEqual(resolved, "web-app")

    def test_metadata_template_overrides_work_item_type(self) -> None:
        resolved = intake_runner._resolve_template_name(
            explicit=None,
            project_metadata={"intake_template": "data-pipeline"},
            project_type="greenfield",
            work_item_type="bug",
        )
        self.assertEqual(resolved, "data-pipeline")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
