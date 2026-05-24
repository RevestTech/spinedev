"""Per-project git workspace bootstrap and commit helpers (SPINE_MASTER §4 P1).

Git is the source of truth for project code under ``<projects_root>/<uuid>/``.
The KG indexes that repo on every commit via the post-commit hook installed
here at project creation.
"""

from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("spine.runtime.project_workspace")

_REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class BootstrapResult:
    project_uuid: str
    workspace_path: str
    repo: str
    git_initialized: bool = False
    hook_installed: bool = False
    initial_commit_sha: str | None = None
    cold_index_files: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass
class CommitResult:
    ok: bool
    commit_sha: str | None = None
    files_indexed: int = 0
    node_count: int = 0
    edge_count: int = 0
    error: str | None = None


def projects_root() -> Path:
    """Return the directory holding per-project code workspaces."""
    if raw := os.environ.get("SPINE_PROJECTS_ROOT"):
        return Path(raw).expanduser()
    hub_mount = Path("/var/lib/spine/projects")
    if hub_mount.is_dir():
        return hub_mount
    return _REPO_ROOT / ".spine" / "work"


def project_code_dir(project_uuid: str) -> Path:
    return (projects_root() / project_uuid).resolve()


def is_spine_on_spine(metadata: dict[str, Any] | None) -> bool:
    return bool((metadata or {}).get("spine_on_spine"))


def resolve_code_dir(project_uuid: str, metadata: dict[str, Any] | None = None) -> Path:
    """Return engineer workspace path; dogfood sandbox unless repo write allowed."""
    md = metadata or {}
    if is_spine_on_spine(md):
        allow = os.environ.get("SPINE_ON_SPINE_ALLOW_REPO_WRITE", "0").strip().lower()
        if allow in ("1", "true", "yes"):
            repo = os.environ.get("SPINE_ON_SPINE_REPO", str(_REPO_ROOT))
            return Path(repo).expanduser().resolve()
        # Hub docker bind-mount: keep dogfood under /var/lib/spine/projects so
        # code survives container rebuilds. Dev checkout fallback stays under
        # .spine/dogfood/ in the repo tree.
        hub_projects = Path("/var/lib/spine/projects")
        if hub_projects.is_dir():
            dogfood = (hub_projects / "dogfood" / project_uuid).resolve()
            dogfood.mkdir(parents=True, exist_ok=True)
            return dogfood
        dogfood = (_REPO_ROOT / ".spine" / "dogfood" / project_uuid).resolve()
        dogfood.mkdir(parents=True, exist_ok=True)
        return dogfood
    return project_code_dir(project_uuid)


def workspace_host_path(project_uuid: str, metadata: dict[str, Any] | None = None) -> str:
    """Host-visible path for UI (bind-mount target on laptop Hub)."""
    host = os.environ.get("SPINE_PROJECTS_DIR_HOST", str(projects_root()))
    host = host.rstrip("/")
    if host.startswith("~"):
        host = str(Path(host).expanduser())
    if is_spine_on_spine(metadata):
        return f"{host}/dogfood/{project_uuid}"
    return f"{host}/{project_uuid}"


def count_workspace_files(project_uuid: str, metadata: dict[str, Any] | None = None) -> int:
    """Count implementation files on disk (excludes .git, node_modules, etc.)."""
    root = resolve_code_dir(project_uuid, metadata)
    if not root.is_dir():
        return 0
    skip_dirs = {".next", "node_modules", ".git", ".claude", "__pycache__"}
    n = 0
    for f in root.rglob("*"):
        if not f.is_file():
            continue
        rel = f.relative_to(root)
        if any(part in skip_dirs for part in rel.parts):
            continue
        n += 1
    return n


def repo_slug_for_project(project_uuid: str, metadata: dict[str, Any] | None = None) -> str:
    if is_spine_on_spine(metadata):
        return f"dogfood-{project_uuid[:8]}"
    return repo_slug(project_uuid)


def repo_slug(project_uuid: str) -> str:
    """KG ``repo`` column — directory name under projects root."""
    return project_uuid


def _run_git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        check=check,
    )


def _has_commits(cwd: Path) -> bool:
    proc = _run_git(cwd, "rev-parse", "HEAD", check=False)
    return proc.returncode == 0


def bootstrap_project_git_repo(
    project_uuid: str,
    project_name: str,
    *,
    cold_index: bool | None = None,
    metadata: dict[str, Any] | None = None,
) -> BootstrapResult:
    """Create workspace dir, ``git init``, README, hook, optional cold index."""
    md = metadata or {}
    cwd = resolve_code_dir(project_uuid, md)
    slug = repo_slug_for_project(project_uuid, md)

    if is_spine_on_spine(md):
        allow = os.environ.get("SPINE_ON_SPINE_ALLOW_REPO_WRITE", "0").strip().lower()
        if allow in ("1", "true", "yes"):
            out = BootstrapResult(
                project_uuid=project_uuid,
                workspace_path=str(cwd),
                repo=slug,
            )
            out.git_initialized = (cwd / ".git").is_dir()
            if out.git_initialized:
                try:
                    from build.kg.indexer_commit_hook import install_post_commit_hook  # noqa: PLC0415

                    install_post_commit_hook(cwd)
                    out.hook_installed = True
                except Exception as exc:  # noqa: BLE001
                    out.errors.append(f"hook install failed: {exc}")
            return out

    out = BootstrapResult(
        project_uuid=project_uuid,
        workspace_path=str(cwd),
        repo=slug,
    )
    cwd.mkdir(parents=True, exist_ok=True)

    git_dir = cwd / ".git"
    if not git_dir.exists():
        try:
            _run_git(cwd, "init", "-b", "main")
            out.git_initialized = True
        except subprocess.CalledProcessError as exc:
            out.errors.append(f"git init failed: {exc.stderr.strip()}")
            return out

    readme = cwd / "README.md"
    if not readme.exists():
        readme.write_text(
            f"# {project_name}\n\nSpine-managed project workspace.\n",
            encoding="utf-8",
        )

    if not _has_commits(cwd):
        try:
            _run_git(cwd, "add", "README.md")
            _run_git(
                cwd,
                "-c",
                "user.email=spine@localhost",
                "-c",
                "user.name=Spine Hub",
                "commit",
                "-m",
                f"chore: bootstrap {project_name}",
            )
            out.initial_commit_sha = _run_git(cwd, "rev-parse", "HEAD").stdout.strip()
        except subprocess.CalledProcessError as exc:
            out.errors.append(f"initial commit failed: {exc.stderr.strip()}")

    try:
        from build.kg.indexer_commit_hook import install_post_commit_hook  # noqa: PLC0415

        install_post_commit_hook(cwd)
        out.hook_installed = True
    except Exception as exc:  # noqa: BLE001
        out.errors.append(f"hook install failed: {exc}")
        logger.warning("kg_hook_install_failed", extra={"project": project_uuid, "err": str(exc)})

    do_cold = cold_index if cold_index is not None else bool(os.environ.get("SPINE_DB_URL"))
    if do_cold and _has_commits(cwd):
        try:
            from build.kg.indexer.indexer import cold_start_index  # noqa: PLC0415

            idx = cold_start_index(cwd, database_url=os.environ.get("SPINE_DB_URL"))
            out.cold_index_files = idx.files_indexed
            if idx.errors:
                out.errors.extend(idx.errors[:3])
        except Exception as exc:  # noqa: BLE001
            out.errors.append(f"cold index skipped: {exc}")
            logger.debug("cold_index_skipped", extra={"project": project_uuid, "err": str(exc)})

    return out


def commit_workspace(
    project_uuid: str,
    message: str,
    *,
    index_now: bool = True,
    metadata: dict[str, Any] | None = None,
) -> CommitResult:
    """Stage all changes, commit, and optionally run the KG indexer."""
    cwd = resolve_code_dir(project_uuid, metadata)
    if not (cwd / ".git").exists():
        return CommitResult(ok=False, error="workspace is not a git repo")

    try:
        status = _run_git(cwd, "status", "--porcelain", check=False)
        if not status.stdout.strip():
            sha = _run_git(cwd, "rev-parse", "HEAD", check=False).stdout.strip() or None
            return CommitResult(ok=True, commit_sha=sha, files_indexed=0)

        _run_git(cwd, "add", "-A")
        _run_git(
            cwd,
            "-c",
            "user.email=spine@localhost",
            "-c",
            "user.name=Spine Hub",
            "commit",
            "-m",
            message,
        )
        sha = _run_git(cwd, "rev-parse", "HEAD").stdout.strip()
    except subprocess.CalledProcessError as exc:
        return CommitResult(ok=False, error=exc.stderr.strip() or str(exc))

    files_indexed = node_count = edge_count = 0
    if index_now and sha:
        try:
            from build.kg.indexer_commit_hook import run_commit_hook  # noqa: PLC0415

            hook = run_commit_hook(sha, repo_root=cwd, database_url=os.environ.get("SPINE_DB_URL"))
            files_indexed = hook.result.files_indexed
            node_count = hook.result.node_count
            edge_count = hook.result.edge_count
        except Exception as exc:  # noqa: BLE001
            logger.warning("commit_index_failed", extra={"project": project_uuid, "err": str(exc)})

    return CommitResult(
        ok=True,
        commit_sha=sha,
        files_indexed=files_indexed,
        node_count=node_count,
        edge_count=edge_count,
    )


def metadata_patch_from_bootstrap(result: BootstrapResult) -> dict[str, object]:
    """Project-row metadata fields to persist after bootstrap."""
    patch: dict[str, object] = {
        "repo": result.repo,
        "code_workspace": result.workspace_path,
        "git_initialized": result.git_initialized,
        "kg_hook_installed": result.hook_installed,
    }
    if result.initial_commit_sha:
        patch["last_commit_sha"] = result.initial_commit_sha
    if result.cold_index_files:
        patch["kg_cold_index_files"] = result.cold_index_files
    if result.errors:
        patch["workspace_bootstrap_warnings"] = result.errors[:5]
    return patch


_PLAN_ARTIFACT_FILES: dict[str, str] = {
    "prd_md": "docs/PRD.md",
    "roadmap_md": "docs/roadmap.md",
    "trd_md": "docs/TRD.md",
    "sprint_plan_md": "docs/sprint-plan.md",
    "qa_md": "docs/test-plan.md",
    "release_gate_md": "docs/release-gate.md",
}


def promote_plan_artifacts_enabled() -> bool:
    return os.environ.get("SPINE_PROMOTE_PLAN_ARTIFACTS", "1").strip().lower() not in (
        "0", "false", "no",
    )


def promote_plan_artifacts(
    project_uuid: str,
    patch: dict[str, Any],
    *,
    metadata: dict[str, Any] | None = None,
    role: str = "plan",
    directive_id: str = "",
    project_name: str = "",
) -> dict[str, Any]:
    """Write plan markdown from a metadata patch into the git workspace."""
    if not promote_plan_artifacts_enabled():
        return {}

    md = metadata or {}
    cwd = resolve_code_dir(project_uuid, md)
    written: list[str] = []

    for key, val in patch.items():
        rel = _PLAN_ARTIFACT_FILES.get(key)
        if not rel or not isinstance(val, str) or not val.strip():
            continue
        if not (cwd / ".git").exists():
            bootstrap_project_git_repo(
                project_uuid,
                project_name or project_uuid[:8],
                cold_index=False,
                metadata=md,
            )
            cwd = resolve_code_dir(project_uuid, md)
        dest = (cwd / rel).resolve()
        try:
            dest.relative_to(cwd)
        except ValueError:
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(val, encoding="utf-8")
        written.append(rel)

    if not written:
        return {}

    msg = f"plan/{role}: {', '.join(written)}"
    if directive_id:
        msg += f" ({directive_id})"
    commit = commit_workspace(project_uuid, msg, metadata=md)
    out: dict[str, Any] = {}
    if commit.ok and commit.commit_sha:
        out["last_commit_sha"] = commit.commit_sha
    if commit.files_indexed:
        out["kg_last_index_files"] = commit.files_indexed
    return out


__all__ = [
    "BootstrapResult",
    "CommitResult",
    "bootstrap_project_git_repo",
    "commit_workspace",
    "is_spine_on_spine",
    "metadata_patch_from_bootstrap",
    "project_code_dir",
    "projects_root",
    "promote_plan_artifacts",
    "promote_plan_artifacts_enabled",
    "repo_slug",
    "repo_slug_for_project",
    "resolve_code_dir",
    "workspace_host_path",
    "count_workspace_files",
]
