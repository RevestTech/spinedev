"""Optional git branch push for BUILD results (HTTPS + PAT)."""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
from pathlib import Path

from tron.services.git_plan_bundle import GitPlanBundleError, _authed_https_url, _git
from tron.services.repo_scanner import RepoScanner, RepoScanError

logger = logging.getLogger(__name__)


class GitBuildReportError(Exception):
    """Git push for build report failed."""


async def push_build_report_branch(
    *,
    repo_url: str,
    branch_default: str,
    target_branch: str,
    token: str,
    artifact_json: str,
) -> None:
    """Clone default branch, add ``.tron/build-result.json``, commit, push ``target_branch``."""
    scanner = RepoScanner()
    root = await scanner.clone_to_tempdir(repo_url, branch_default)
    try:
        tron_dir = Path(root) / ".tron"
        tron_dir.mkdir(parents=True, exist_ok=True)
        (tron_dir / "build-result.json").write_text(
            json.dumps(json.loads(artifact_json), indent=2), encoding="utf-8"
        )
        authed = _authed_https_url(repo_url, token)
        await _git(root, "git", "config", "user.email", "tron-build@noreply.tron.local")
        await _git(root, "git", "config", "user.name", "Tron BUILD")
        await _git(root, "git", "remote", "set-url", "origin", authed)
        await _git(root, "git", "checkout", "-B", target_branch)
        await _git(root, "git", "add", ".tron/build-result.json")
        proc = await asyncio.create_subprocess_exec(
            "git",
            "commit",
            "-m",
            f"chore(tron): BUILD report ({target_branch})",
            cwd=root,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _o, err = await proc.communicate()
        if proc.returncode != 0:
            err_t = err.decode("utf-8", errors="replace").lower()
            if "nothing to commit" in err_t or "nothing added to commit" in err_t:
                logger.info("TRON build git: no changes to commit")
            else:
                raise GitBuildReportError(err.decode("utf-8", errors="replace")[:2000])
        await _git(root, "git", "push", "-u", "origin", target_branch)
    except (RepoScanError, GitPlanBundleError) as exc:
        raise GitBuildReportError(str(exc)) from exc
    finally:
        shutil.rmtree(root, ignore_errors=True)
