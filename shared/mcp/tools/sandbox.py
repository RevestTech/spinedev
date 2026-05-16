"""TRON Docker sandbox exposed as an MCP tool (REQ-INIT-3 EPIC-3.5; STORY-3.5.2).

Closes "engineer self-reports success but never ran the code": any Spine role
can execute untrusted code in TRON's ephemeral container (caps dropped,
read-only rootfs, no network by default, seccomp) and get a structured
stdout/stderr/exit/resource envelope. Wrapper-only — :mod:`verify.tron.sandbox`
is imported lazily; standalone TRON is unaffected. See ``sandbox_README.md``
for cost attribution + threat-model summary.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import tempfile
from decimal import Decimal
from os import environ
from time import perf_counter
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from shared.mcp.schemas import ToolError, ToolResponse, ToolStatus
from shared.mcp.tools import register_tool

logger = logging.getLogger(__name__)

# ── Caps + cost rates ──────────────────────────────────────────────────

_MAX_CODE_BYTES = 1 * 1024 * 1024            # 1 MB
_MAX_TIMEOUT_SECONDS = 600                   # 10 min hard ceiling
_MAX_MEMORY_MB = 4096                        # 4 GB hard ceiling
_OUTPUT_CAP_BYTES = 64 * 1024                # 64 KB stdout/stderr each
_TRUNC_MARKER = "\n…[TRUNCATED — sandbox capped at 64KB]"

#: Placeholder v1 rates; overridable via env. STORY-3.5.5 will finalize.
_CPU_USD_PER_SEC = Decimal(environ.get("SPINE_SANDBOX_CPU_USD_PER_SEC", "0.0001"))
_MEM_USD_PER_MB_SEC = Decimal(environ.get("SPINE_SANDBOX_MEM_USD_PER_MB_SEC", "0.00001"))

Language = Literal["python", "bash", "node", "shell"]
NetworkMode = Literal["none", "isolated", "internet"]
CostAttribution = Literal["build", "verify", "plan"]


def _probe_docker() -> bool:
    """``True`` iff ``docker ps -q`` succeeds. Cached at module import."""
    if shutil.which("docker") is None:
        return False
    try:
        proc = subprocess.run(
            ["docker", "ps", "-q"], capture_output=True, text=True, timeout=5,
        )
        return proc.returncode == 0
    except Exception:  # pragma: no cover
        return False


_DOCKER_AVAILABLE: bool = _probe_docker()
if not _DOCKER_AVAILABLE:
    logger.warning(
        "sandbox_run: Docker daemon not reachable at import; all calls will "
        "return ToolError(code='docker_unavailable').",
    )


# ── Schemas ────────────────────────────────────────────────────────────


class SandboxRunInput(BaseModel):
    """Inputs for :func:`sandbox_run`. Defaults match TRON's hardened posture
    (no network, 30 s wall clock, 512 MB, 1 CPU)."""
    model_config = ConfigDict(extra="forbid")
    code: str = Field(..., min_length=1, description="Source to execute inside the sandbox.")
    language: Language = "python"
    project_id: str = Field(..., min_length=1)
    actor: str = Field(..., min_length=1, description="Role / subsystem invoking the sandbox.")
    setup_commands: list[str] = Field(default_factory=list,
        description="Shell commands run before ``code`` (e.g. ``pip install foo``).")
    timeout_seconds: int = Field(default=30, ge=1, le=_MAX_TIMEOUT_SECONDS)
    memory_limit_mb: int = Field(default=512, ge=16, le=_MAX_MEMORY_MB)
    cpu_limit_cores: float = Field(default=1.0, gt=0.0, le=16.0)
    network: NetworkMode = "none"
    env: dict[str, str] = Field(default_factory=dict,
        description="Extra env vars; secrets must be injected upstream.")
    files: dict[str, str] = Field(default_factory=dict,
        description="Path → contents; mounted read-only into the container.")
    cost_attribution: CostAttribution = "build"
    seccomp_profile: str | None = Field(default=None,
        description="Override seccomp profile path; else TRON bundle default.")


class SandboxRunOutput(BaseModel):
    """Successful payload returned by :func:`sandbox_run`."""
    model_config = ConfigDict(extra="forbid")
    status: ToolStatus
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    duration_ms: int = 0
    memory_peak_mb: int = 0
    cpu_seconds: float = 0.0
    timed_out: bool = False
    sandbox_used: bool = False
    error: ToolError | None = None
    cost_usd: Decimal = Field(default=Decimal("0"))
    audit_id: UUID = Field(default_factory=uuid4)


# ── Helpers ────────────────────────────────────────────────────────────


def _cap(s: str | None) -> str:
    """Truncate ``s`` to 64 KB; append a marker if cut. ``None`` -> ``""``."""
    if not s:
        return ""
    encoded = s.encode("utf-8", errors="replace")
    if len(encoded) <= _OUTPUT_CAP_BYTES:
        return s
    return encoded[:_OUTPUT_CAP_BYTES].decode("utf-8", errors="replace") + _TRUNC_MARKER


def _compute_cost(cpu_seconds: float, memory_peak_mb: int, duration_ms: int) -> Decimal:
    """CPU-sec × $rate + MB-sec × $rate. Cheap, deterministic, replaceable."""
    cpu = Decimal(str(max(cpu_seconds, 0.0))) * _CPU_USD_PER_SEC
    mb_sec = (Decimal(str(max(memory_peak_mb, 0)))
              * Decimal(str(max(duration_ms, 0))) / Decimal("1000"))
    return (cpu + mb_sec * _MEM_USD_PER_MB_SEC).quantize(Decimal("0.000001"))


def _audit_from_sandbox_run(*, actor: str, language: str, exit_code: int,
        timed_out: bool, cost_usd: Decimal, cost_attribution: CostAttribution) -> UUID:
    """AuditRecord -> event_uuid. Subsystem = ``cost_attribution`` (STORY-3.5.5).

    TODO(STORY-3.5.2): promote to ``AuditRecord.from_sandbox_run`` once that
    classmethod API stabilizes (mirrors the iso_invoke TODO).
    """
    try:
        from shared.audit.audit_record import AuditRecord
        return AuditRecord(
            role=actor, subsystem=cost_attribution, action="sandbox_run",
            actor=actor, subject_type="sandbox_exec",
            subject_id=f"{language}:{exit_code}", cost_usd=cost_usd,
            metadata={"cost_attribution": cost_attribution, "language": language,
                      "exit_code": exit_code, "timed_out": timed_out},
        ).event_uuid
    except Exception:  # pragma: no cover — audit must never break the tool path
        logger.exception("sandbox_run: audit record build failed; synthetic UUID")
        return uuid4()


def _error_envelope(*, code: str, message: str, retryable: bool, actor: str,
        language: str, cost_attribution: CostAttribution, sandbox_used: bool) -> ToolResponse:
    """Build a ``status='error'`` envelope + audit row (zero cost)."""
    err = ToolError(code=code, message=message, retryable=retryable)
    audit_id = _audit_from_sandbox_run(
        actor=actor, language=language, exit_code=-1, timed_out=False,
        cost_usd=Decimal("0"), cost_attribution=cost_attribution)
    out = SandboxRunOutput(status="error", exit_code=-1, sandbox_used=sandbox_used,
                           error=err, audit_id=audit_id)
    return ToolResponse(status="error", data=out.model_dump(mode="json"),
                        error=err, audit_id=audit_id)


# ── The tool ───────────────────────────────────────────────────────────


@register_tool(
    name="sandbox_run", input_model=SandboxRunInput, story="STORY-3.5.2",
    description="Execute code in TRON's ephemeral Docker sandbox; return stdout/stderr/exit + resource usage.",
    tags=("verify", "sandbox", "execute"),
)
def sandbox_run(payload: SandboxRunInput) -> ToolResponse:
    """Run ``payload.code`` in a fresh hardened container; return resource-usage envelope.

    Pipeline: validate -> log -> lazy-import TRON sandbox client -> build TRON
    request -> execute container -> cap stdout/stderr -> compute cost ->
    write audit row (subsystem per ``cost_attribution``) -> return envelope.
    """
    logger.info("mcp_tool_call", extra={
        "tool": "sandbox_run", "project_id": payload.project_id,
        "actor": payload.actor, "language": payload.language,
        "network": payload.network, "cost_attribution": payload.cost_attribution})

    _err = lambda **kw: _error_envelope(  # noqa: E731 — local sugar only
        actor=payload.actor, language=payload.language,
        cost_attribution=payload.cost_attribution, **kw)

    # 1. Input validation (length guards Pydantic can't express cheaply).
    if len(payload.code.encode("utf-8", errors="replace")) > _MAX_CODE_BYTES:
        return _err(code="code_too_large", retryable=False, sandbox_used=False,
            message=f"code exceeds {_MAX_CODE_BYTES} bytes (sandbox refuses >1 MB payloads).")

    # 2. Degraded mode — Docker unreachable at import time.
    if not _DOCKER_AVAILABLE:
        return _err(code="docker_unavailable", retryable=True, sandbox_used=False,
            message=("Docker daemon not reachable; sandbox_run cannot execute. "
                     "Install Docker + start the daemon, or run on a host where "
                     "the TRON sandbox bundle is wired up."))

    # 3. Lazy-import TRON sandbox client; tolerate verify/ not on PYTHONPATH.
    # Canonical entry point: verify.tron.services.sandbox_client.SandboxClient
    # (the verify/tron/sandbox/ package hosts the FastAPI server; the client
    # lives in services/). Adapter is local — no TRON code modified.
    try:
        from verify.tron.services.sandbox_client import SandboxClient
    except Exception as exc:
        logger.warning("sandbox_run: TRON SandboxClient not importable: %s", exc)
        return _err(code="sandbox_not_available", retryable=False, sandbox_used=False,
            message=("verify.tron.services.sandbox_client not importable — wire "
                     "verify/ onto PYTHONPATH (STORY-8.2.x) or install the bundle."))

    # 4. Mismatched-surface guards — TRON doesn't model these yet (refined TODOs).
    if payload.language == "node":
        return _err(code="unsupported_language", retryable=False, sandbox_used=False,
            message="TRON sandbox supports python|bash|shell only; node not wired.")
    if payload.seccomp_profile is not None:
        # TODO(STORY-3.5.2): pass-through once TRON SandboxClient exposes security_opt.
        return _err(code="sandbox_unsupported_option", retryable=False, sandbox_used=False,
            message="seccomp_profile override not supported by current TRON client.")

    # 5. Map Spine inputs onto TRON's surface.
    # network: Spine has no "isolated" tier in TRON; collapse to "none" and log.
    _net_map = {"none": "none", "isolated": "none", "internet": "bridge"}
    network_mode = _net_map[payload.network]
    if payload.network == "isolated":
        logger.info("sandbox_run: 'isolated' network downgraded to 'none' (TRON parity).")

    # env + setup_commands: TRON's run_* takes no env kwarg — inline a preamble.
    def _python_preamble() -> str:
        lines: list[str] = []
        if payload.env:
            lines.append("import os")
            lines.extend(f"os.environ[{k!r}] = {v!r}" for k, v in payload.env.items())
        if payload.setup_commands:
            lines.append("import subprocess")
            lines.extend(f"subprocess.run({c!r}, shell=True, check=True)"
                        for c in payload.setup_commands)
        return ("\n".join(lines) + "\n") if lines else ""

    def _bash_preamble() -> str:
        lines = [f"export {k}={v!r}" for k, v in payload.env.items()]
        lines.extend(payload.setup_commands)
        return ("\n".join(lines) + "\n") if lines else ""

    script = (_python_preamble() if payload.language == "python"
              else _bash_preamble()) + payload.code

    # files: stage inline path->contents into a tempdir, mount read-only at /workspace.
    tmp_ctx = tempfile.TemporaryDirectory(prefix="spine-sandbox-") if payload.files else None
    volumes: dict | None = None
    workdir: str | None = None
    if tmp_ctx is not None:
        for rel, contents in payload.files.items():
            dst = os.path.normpath(os.path.join(tmp_ctx.name, rel.lstrip("/")))
            if not dst.startswith(tmp_ctx.name):
                tmp_ctx.cleanup()
                return _err(code="invalid_file_path", retryable=False, sandbox_used=False,
                    message=f"file path escapes sandbox staging dir: {rel!r}")
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, "w", encoding="utf-8") as fh:
                fh.write(contents)
        volumes = {tmp_ctx.name: {"bind": "/workspace", "mode": "ro"}}
        workdir = "/workspace"

    memory_limit_str = f"{payload.memory_limit_mb}m"
    cpu_quota = int(payload.cpu_limit_cores * 100_000)  # default period = 100_000us

    # 6. Execute via TRON (async-to-sync bridge).
    t0 = perf_counter()
    timed_out = False
    raw_stdout = raw_stderr = ""
    exit_code = -1
    tron_duration_ms = 0
    try:
        client = SandboxClient(default_memory_limit=memory_limit_str, default_cpu_quota=cpu_quota)
        runner = client.run_python if payload.language == "python" else client.run_bash
        kwargs: dict = {"script": script, "timeout": payload.timeout_seconds,
                        "network_mode": network_mode, "workdir": workdir, "volumes": volumes}
        if payload.language == "python":
            kwargs.update(memory_limit=memory_limit_str, cpu_quota=cpu_quota)
        result = asyncio.run(runner(**kwargs))
        exit_code = int(result.get("exit_code", -1))
        raw_stdout = result.get("output") or ""  # TRON combines stdout+stderr here.
        err_field = result.get("error")
        if err_field:
            raw_stderr = str(err_field)
            if "timeout" in raw_stderr.lower():
                timed_out = True
        tron_duration_ms = int(result.get("duration_ms") or 0)
    except Exception as exc:
        logger.exception("sandbox_run: TRON SandboxClient.run failed")
        return _err(code="sandbox_execution_failed", retryable=True, sandbox_used=True,
            message=f"TRON sandbox raised {type(exc).__name__}: {exc}")
    finally:
        if tmp_ctx is not None:
            tmp_ctx.cleanup()

    duration_ms = tron_duration_ms or int((perf_counter() - t0) * 1000)
    # TODO(STORY-3.5.5): plumb cgroup memory.peak + cpu-acct through TRON.
    memory_peak_mb = 0
    cpu_seconds = 0.0

    # 7. Compute cost. 8/9. Audit + envelope.
    cost_usd = _compute_cost(cpu_seconds, memory_peak_mb, duration_ms)
    audit_id = _audit_from_sandbox_run(
        actor=payload.actor, language=payload.language, exit_code=exit_code,
        timed_out=timed_out, cost_usd=cost_usd,
        cost_attribution=payload.cost_attribution)
    status: ToolStatus = "ok" if exit_code == 0 and not timed_out else "error"
    out = SandboxRunOutput(
        status=status, exit_code=exit_code,
        stdout=_cap(raw_stdout), stderr=_cap(raw_stderr),
        duration_ms=duration_ms, memory_peak_mb=memory_peak_mb,
        cpu_seconds=cpu_seconds, timed_out=timed_out, sandbox_used=True,
        error=None, cost_usd=cost_usd, audit_id=audit_id)
    return ToolResponse(status=status, data=out.model_dump(mode="json"), audit_id=audit_id)


__all__: list[str] = [
    "CostAttribution", "Language", "NetworkMode",
    "SandboxRunInput", "SandboxRunOutput", "sandbox_run",
]
