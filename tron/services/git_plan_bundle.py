"""Optional git push for Tron PLAN `.tron` bundle (HTTPS + PAT)."""

from __future__ import annotations

import asyncio
import logging
import shutil
from typing import Dict

from tron.services.plan_artifacts import write_tron_bundle_to_dir
from tron.services.repo_scanner import RepoScanner, RepoScanError

logger = logging.getLogger(__name__)


class GitPlanBundleError(Exception):
    """Push or git command failed."""


def _authed_https_url(repo_url: str, token: str) -> str:
    ru = repo_url.strip()
    if not ru.startswith("https://"):
        raise GitPlanBundleError(
            "TRON plan git push only supports https:// clone URLs "
            "(set TRON_PLAN_GIT_TOKEN with a PAT)."
        )
    # GitHub PAT (also works for many providers); see TRON_PLAN_GIT_TOKEN in docs.
    return ru.replace("https://", f"https://x-access-token:{token}@", 1)


async def _git(cwd: str, *args: str) -> None:
    proc = await asyncio.create_subprocess_exec(
        *args,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _out, err = await proc.communicate()
    if proc.returncode != 0:
        msg = err.decode("utf-8", errors="replace").strip()
        raise GitPlanBundleError(msg or f"git failed ({proc.returncode}): {' '.join(args)}")


async def push_tron_plan_bundle(
    *,
    repo_url: str,
    branch: str,
    bundle: Dict[str, str],
    token: str,
) -> None:
    """Clone ``repo_url``, write ``bundle``, commit, push to ``branch``.

    Requires a personal access token with ``contents: write`` (GitHub) or equivalent.
    Environment variable: ``TRON_PLAN_GIT_TOKEN``.
    """
    scanner = RepoScanner()
    root = await scanner.clone_to_tempdir(repo_url, branch)
    try:
        write_tron_bundle_to_dir(root, bundle)
        authed = _authed_https_url(repo_url, token)
        await _git(root, "git", "config", "user.email", "tron-plan@noreply.tron.local")
        await _git(root, "git", "config", "user.name", "Tron PLAN")
        await _git(root, "git", "remote", "set-url", "origin", authed)
        await _git(root, "git", "add", ".tron", ".cursor")
        proc = await asyncio.create_subprocess_exec(
            "git",
            "commit",
            "-m",
            "chore(tron): add Tron PLAN bundle",
            cwd=root,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _o, err = await proc.communicate()
        if proc.returncode != 0:
            err_t = err.decode("utf-8", errors="replace").lower()
            if "nothing to commit" in err_t or "nothing added to commit" in err_t:
                logger.info("TRON plan git: no changes to commit")
                return
            raise GitPlanBundleError(err.decode("utf-8", errors="replace")[:2000])
        await _git(root, "git", "push", "origin", f"HEAD:{branch}")
    except RepoScanError as exc:
        raise GitPlanBundleError(str(exc)) from exc
    finally:
        shutil.rmtree(root, ignore_errors=True)
