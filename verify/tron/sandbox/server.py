"""HTTP sandbox API — runs inside tron-sandbox container with Docker socket access."""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional

import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, model_validator

from tron.services.sandbox_client import SandboxClient

logger = logging.getLogger(__name__)


async def _prewarm_executions(n: int) -> None:
    """Best-effort Docker image / path warm-up (capped at 10)."""
    await asyncio.sleep(0.5)
    client = SandboxClient()
    capped = min(max(n, 0), 10)
    for i in range(capped):
        try:
            await client.run_python(
                script="print('tron-sandbox-prewarm')",
                timeout=20,
            )
        except Exception as exc:
            logger.warning("Sandbox prewarm execution %s failed: %s", i, exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        n = int(os.environ.get("SANDBOX_PREWARM_EXECUTIONS", "0"))
    except ValueError:
        n = 0
    if n > 0:
        asyncio.create_task(_prewarm_executions(n))
    yield


app = FastAPI(title="Tron Sandbox", version="1.0", lifespan=lifespan)
_started = time.time()
_local: SandboxClient | None = None


def _get_local_client() -> SandboxClient:
    global _local
    if _local is None:
        _local = SandboxClient()
    return _local


class ExecuteBody(BaseModel):
    code: Optional[str] = None
    script: Optional[str] = None
    language: str = "python"
    timeout: int = Field(default=10, ge=1, le=300)
    # Only the isolating network modes are accepted. ``host`` would hand the
    # container the service's own network namespace (no isolation); any
    # ``container:<id>`` mode shares another container's netns and is a
    # lateral-movement vector. See tron/services/sandbox_client.py.
    network_mode: str = "none"
    workdir: Optional[str] = None
    volumes: Optional[Dict[str, Any]] = None

    @model_validator(mode="after")
    def require_code(self) -> ExecuteBody:
        if not (self.code or self.script):
            raise ValueError("code or script is required")
        if self.network_mode not in {"none", "bridge"}:
            # Raised as ValueError so FastAPI turns it into a 422 rather than
            # allowing the request to reach SandboxClient where it would be
            # rejected again (good defense-in-depth, but noisy in logs).
            raise ValueError(
                f"network_mode={self.network_mode!r} not allowed; "
                "use 'none' (default) or 'bridge'"
            )
        return self

    def source(self) -> str:
        return (self.code or self.script or "").strip()


@app.get("/health")
def health() -> dict[str, Any]:
    return {"healthy": True, "uptime_seconds": int(time.time() - _started)}


class VerifyBody(BaseModel):
    """Verify a proposed fix by executing checks in the sandbox (parity with audit Layer 3)."""

    original_code: str = ""
    fixed_code: str = ""
    test_code: str = ""
    language: str = "python"

    @model_validator(mode="after")
    def require_fixed(self) -> VerifyBody:
        if not (self.fixed_code or "").strip():
            raise ValueError("fixed_code is required")
        return self


@app.post("/verify")
async def verify_fix(body: VerifyBody) -> dict[str, Any]:
    """Run execution-backed verification for a fix (default: compile + AST parse smoke test)."""
    t0 = time.time()
    lang = (body.language or "python").lower().strip()
    if lang != "python":
        return {
            "passed": False,
            "test_output": "",
            "errors": [f"sandbox /verify currently supports only python, got {lang!r}"],
            "duration_seconds": time.time() - t0,
        }

    fixed = body.fixed_code.strip()
    original = (body.original_code or "").strip()
    test_code = (body.test_code or "").strip()

    # Default verification: fixed snippet must parse and compile (execution parity baseline).
    if not test_code:
        test_code = (
            "import ast\n"
            "ast.parse(__FIX__)\n"
            "compile(__FIX__, '<tron_fix>', 'exec')\n"
            "print('tron_verify_fix_ok')\n"
        )

    client = _get_local_client()
    full_script = (
        f"__FIX__ = {fixed!r}\n"
        f"__ORIG__ = {original!r}\n"
        + test_code
    )
    result = await client.run_python(script=full_script, timeout=45, network_mode="none")
    exit_code = int(result.get("exit_code", -1))
    out = (result.get("output") or "").strip()
    err = result.get("error")
    duration = time.time() - t0
    errors: list[str] = []
    if err:
        errors.append(str(err))
    if exit_code != 0:
        errors.append(out or f"exit_code={exit_code}")
    passed = exit_code == 0 and not err
    return {
        "passed": passed,
        "test_output": out,
        "errors": errors,
        "duration_seconds": duration,
    }


@app.post("/execute")
async def execute(body: ExecuteBody) -> dict[str, Any]:
    src = body.source()
    if not src:
        raise HTTPException(status_code=400, detail="code/script cannot be empty")
    client = _get_local_client()
    if body.language == "python":
        return await client.run_python(
            script=src,
            timeout=body.timeout,
            network_mode=body.network_mode,
            workdir=body.workdir,
            volumes=body.volumes,
        )
    if body.language in ("bash", "shell"):
        return await client.run_bash(
            script=src,
            timeout=body.timeout,
            network_mode=body.network_mode,
            workdir=body.workdir,
            volumes=body.volumes,
        )
    raise HTTPException(status_code=400, detail=f"unsupported language: {body.language}")
