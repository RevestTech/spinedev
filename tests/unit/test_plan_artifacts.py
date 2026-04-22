"""Tests for Tron PLAN on-disk / bundle layout."""

from tron.services.plan_artifacts import (
    build_tron_plan_files_dict,
    write_tron_bundle_to_dir,
)


def test_build_tron_plan_files_dict_contains_core_paths():
    artifact = {
        "architecture_summary": "Microservices API",
        "requirements_bullets": ["Must scale", "Must be secure"],
        "quality_gates_suggested": {"security": {"required": True}},
        "test_plan_outline": ["Load test"],
        "risks": ["Vendor lock-in"],
    }
    d = build_tron_plan_files_dict(
        project_id="00000000-0000-0000-0000-000000000001",
        project_name="Demo",
        repo_url="https://github.com/org/repo.git",
        default_branch="main",
        goals="Ship v1",
        constraints="Python3.12",
        artifact=artifact,
    )
    assert ".tron/project.json" in d
    assert ".tron/architecture.md" in d
    assert "Microservices API" in d[".tron/architecture.md"]
    assert ".tron/quality-gates.json" in d
    assert ".tron/risks.md" in d
    assert ".cursor/skills/tron-project.md" in d


def test_write_tron_bundle_to_dir(tmp_path):
    bundle = {
        ".tron/a.md": "# x\n",
        "nested/b.txt": "ok",
    }
    written = write_tron_bundle_to_dir(tmp_path, bundle)
    assert set(written) == {".tron/a.md", "nested/b.txt"}
    assert (tmp_path / ".tron" / "a.md").read_text() == "# x\n"
