"""Tests for per-project git workspace bootstrap."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from shared.runtime.project_workspace import (
    bootstrap_project_git_repo,
    commit_workspace,
    is_spine_on_spine,
    metadata_patch_from_bootstrap,
    project_code_dir,
    repo_slug,
    repo_slug_for_project,
    resolve_code_dir,
    promote_plan_artifacts,
)


@pytest.fixture
def projects_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("SPINE_PROJECTS_ROOT", str(tmp_path))
    monkeypatch.delenv("SPINE_DB_URL", raising=False)
    return tmp_path


def test_bootstrap_creates_git_repo_and_hook(projects_root: Path) -> None:
    uid = "00000000-0000-0000-0000-000000000099"
    result = bootstrap_project_git_repo(uid, "Demo App", cold_index=False)

    cwd = project_code_dir(uid)
    assert cwd.is_dir()
    assert (cwd / ".git").is_dir()
    assert (cwd / "README.md").is_file()
    assert result.git_initialized is True
    assert result.hook_installed is True
    assert result.initial_commit_sha
    assert (cwd / ".git" / "hooks" / "post-commit").is_file()

    patch = metadata_patch_from_bootstrap(result)
    assert patch["repo"] == repo_slug(uid)
    assert patch["git_initialized"] is True


def test_commit_workspace_stages_new_files(projects_root: Path) -> None:
    uid = "00000000-0000-0000-0000-000000000088"
    bootstrap_project_git_repo(uid, "Commit Test", cold_index=False)
    cwd = project_code_dir(uid)
    (cwd / "main.py").write_text("print('hi')\n", encoding="utf-8")

    out = commit_workspace(uid, "feat: add main", index_now=False)
    assert out.ok is True
    assert out.commit_sha

    log = subprocess.run(
        ["git", "-C", str(cwd), "log", "--oneline"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "feat: add main" in log.stdout


def test_spine_on_spine_sandbox(projects_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    uid = "00000000-0000-0000-0000-000000000077"
    md = {"spine_on_spine": True}
    code_dir = resolve_code_dir(uid, md)
    assert ".spine" in str(code_dir)
    assert "dogfood" in str(code_dir)
    assert is_spine_on_spine(md) is True
    assert repo_slug_for_project(uid, md) == f"dogfood-{uid[:8]}"


def test_spine_on_spine_repo_write(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    uid = "00000000-0000-0000-0000-000000000066"
    platform = tmp_path / "platform"
    platform.mkdir()
    monkeypatch.setenv("SPINE_ON_SPINE_REPO", str(platform))
    monkeypatch.setenv("SPINE_ON_SPINE_ALLOW_REPO_WRITE", "1")
    md = {"spine_on_spine": True}
    assert resolve_code_dir(uid, md) == platform.resolve()


def test_promote_plan_artifacts_writes_and_commits(projects_root: Path) -> None:
    uid = "00000000-0000-0000-0000-000000000055"
    bootstrap_project_git_repo(uid, "Plan Promo", cold_index=False)
    patch = promote_plan_artifacts(
        uid,
        {"roadmap_md": "# Roadmap\n\nShip it.\n"},
        role="planner",
        project_name="Plan Promo",
    )
    assert patch.get("last_commit_sha")
    cwd = project_code_dir(uid)
    assert (cwd / "docs" / "roadmap.md").is_file()
    assert "Ship it." in (cwd / "docs" / "roadmap.md").read_text(encoding="utf-8")
