"""Engineer hybrid (#13) — wrapper over ``shared/runtime/executor.sh`` CLIs."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("spine.build.engineer_hybrid")
_REPO_ROOT = Path(__file__).resolve().parents[2]
_EXECUTOR = _REPO_ROOT / "shared" / "runtime" / "executor.sh"
_DEFAULT_TIMEOUT = int(os.environ.get("SPINE_ENGINEER_HYBRID_TIMEOUT", "900"))


@dataclass
class HybridEngineerResult:
    ok: bool
    output: str = ""
    executor: str = ""
    error: str | None = None


def hybrid_enabled() -> bool:
    return os.environ.get("SPINE_ENGINEER_HYBRID", "1").strip().lower() not in ("0", "false", "no")


def executor_available() -> bool:
    if os.environ.get("EXECUTOR_CMD") or os.environ.get("EXECUTOR_KIND"):
        return True
    for bin_name in ("cursor-agent", "cursor", "claude", "aider", "opencode", "codex"):
        if shutil.which(bin_name):
            return True
    return False


def run_hybrid_engineer(
    *,
    prompt: str,
    workspace: Path,
    timeout_secs: int | None = None,
) -> HybridEngineerResult:
    """Invoke external coding CLI via executor.sh; returns stdout or error."""
    if not _EXECUTOR.is_file():
        return HybridEngineerResult(ok=False, error=f"executor missing: {_EXECUTOR}")

    workspace.mkdir(parents=True, exist_ok=True)
    timeout = timeout_secs or _DEFAULT_TIMEOUT

    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as fh:
        fh.write(prompt)
        prompt_path = fh.name

    try:
        proc = subprocess.run(
            ["bash", str(_EXECUTOR), prompt_path],
            cwd=str(workspace),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return HybridEngineerResult(ok=False, error=f"executor timeout after {timeout}s")
    except OSError as exc:
        return HybridEngineerResult(ok=False, error=str(exc))
    finally:
        Path(prompt_path).unlink(missing_ok=True)

    if proc.returncode == 127 or "no AI CLI found" in (proc.stderr or ""):
        return HybridEngineerResult(ok=False, error=(proc.stderr or "executor: CLI not found").strip())

    if proc.returncode != 0 and not (proc.stdout or "").strip():
        return HybridEngineerResult(
            ok=False,
            output=proc.stdout or "",
            error=(proc.stderr or f"exit {proc.returncode}").strip()[:500],
        )

    logger.info(
        "engineer_hybrid_ok",
        extra={"workspace": str(workspace), "bytes": len(proc.stdout or "")},
    )
    return HybridEngineerResult(ok=True, output=(proc.stdout or "").strip(), executor="executor.sh")


__all__ = [
    "HybridEngineerResult",
    "executor_available",
    "hybrid_enabled",
    "run_hybrid_engineer",
]
