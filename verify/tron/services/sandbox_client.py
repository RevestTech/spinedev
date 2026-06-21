"""
Sandbox Client - Execute code safely in isolated Docker containers.

This client provides a safe way to execute untrusted code for verification testing.
Containers are ephemeral, isolated, and resource-limited.

Architecture ref: docs/architecture/ZERO_DRIFT_VERIFICATION_PIPELINE.md Layer 3
"""

import asyncio
import logging
import os
from datetime import datetime
from typing import Dict, Optional

import httpx

_httpx_remote: dict[str, httpx.AsyncClient] = {}
_httpx_remote_lock = asyncio.Lock()


async def _remote_httpx_client(base_url: str, default_timeout: int) -> httpx.AsyncClient:
    """One shared AsyncClient per sandbox base URL (connection pool / keep-alive)."""
    base = base_url.rstrip("/") + "/"
    async with _httpx_remote_lock:
        if base not in _httpx_remote:
            pool = int(os.environ.get("TRON_SANDBOX_HTTP_POOL_SIZE", "10") or "10")
            pool = max(1, min(pool, 32))
            _httpx_remote[base] = httpx.AsyncClient(
                base_url=base,
                limits=httpx.Limits(
                    max_keepalive_connections=pool,
                    max_connections=pool,
                ),
                timeout=float(default_timeout) + 30.0,
            )
        return _httpx_remote[base]

try:
    import docker
    # Imports kept for their side effect of validating the docker SDK at import
    # time — the symbols are referenced below only via ``docker.errors.*`` style
    # access and don't all need to be name-visible. Re-exported for callers that
    # want to catch them.
    from docker.errors import (  # noqa: F401
        APIError,
        ContainerError,
        DockerException,
        ImageNotFound,
    )
except ImportError:
    docker = None  # Handle gracefully if docker SDK not installed


class SandboxExecutionError(Exception):
    """Raised when sandbox execution fails"""
    pass


# ── Defense-in-depth container hardening ─────────────────────────────────────
# These values are applied to EVERY container this client launches — both
# ``run_python`` and ``run_bash``. See docs/security/SANDBOX_THREAT_MODEL.md
# for the rationale behind each flag. Any change here should come with a
# threat-model update.

# Only network modes that actually isolate a sandboxed payload are acceptable.
# ``host`` gives the container the host's network namespace (no isolation).
# ``container:<id>`` shares another container's namespace (lateral movement
# vector). Custom bridges are allowed for the outbound-HTTPS-only audit mode,
# which is set up separately and not reachable from raw user input.
_ALLOWED_NETWORK_MODES = frozenset({"none", "bridge"})

# Non-root user inside the container. 65534:65534 is the ``nobody:nogroup``
# pair on every Debian/Ubuntu-derived base image, including python:3.11-slim.
# Picking an existing UID avoids ``chown -R`` headaches on bind-mounted dirs.
_SANDBOX_USER = "65534:65534"

# Custom seccomp profile path. The file under config/sandbox/seccomp.json
# is stricter than Docker's default — it removes mount/swap/kexec/ptrace
# and ~20 other syscall classes the Python/bash payload demonstrably
# doesn't need (see the file for the rationale per syscall). Override
# with TRON_SANDBOX_SECCOMP=disabled if you need to debug a payload that
# the profile is rejecting.
_SECCOMP_PROFILE_PATH = os.environ.get(
    "TRON_SANDBOX_SECCOMP",
    "/etc/tron/sandbox/seccomp.json",
)

# Cap on concurrent processes — defeats fork bombs even if a payload bypasses
# the memory limit.
_SANDBOX_PIDS_LIMIT = 64

# ulimits are enforced by the kernel inside the container. ``fsize`` caps any
# single file created inside the sandbox at 10 MiB (defeats disk-fill attacks
# against the tmpfs); ``nofile`` caps open file descriptors.
_SANDBOX_ULIMITS_SPEC = (
    {"name": "fsize", "soft": 10 * 1024 * 1024, "hard": 10 * 1024 * 1024},
    {"name": "nofile", "soft": 128, "hard": 256},
)

# Environment applied to every execution. ``PYTHONDONTWRITEBYTECODE`` keeps
# the interpreter from emitting .pyc files next to source — otherwise we'd
# need a writable workdir which defeats the tmpfs-only writable model.
_SANDBOX_ENV = {
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONUNBUFFERED": "1",
    # HOME points at the per-container tmpfs mounted above — not the host's
    # /tmp. See SANDBOX_THREAT_MODEL.md. The only writable location inside
    # the container IS /tmp, so HOME has to live there.
    "HOME": "/tmp",  # nosec B108
}


def _build_ulimits() -> list:
    """Return docker.types.Ulimit instances, or dicts if SDK unavailable.

    Kept as a function rather than a module constant so test environments
    without the docker SDK can still import ``sandbox_client``.
    """
    if docker is None:  # pragma: no cover - SDK always present in runtime images
        return [dict(spec) for spec in _SANDBOX_ULIMITS_SPEC]
    return [docker.types.Ulimit(**spec) for spec in _SANDBOX_ULIMITS_SPEC]


def _validate_network_mode(mode: str) -> str:
    """Enforce the allowlist above. Rejects ``host`` / ``container:...``."""
    if mode not in _ALLOWED_NETWORK_MODES:
        raise ValueError(
            f"Sandbox network_mode={mode!r} is not in the allowlist "
            f"{sorted(_ALLOWED_NETWORK_MODES)!r}. Refusing to launch — "
            f"``host`` and ``container:...`` break the isolation boundary."
        )
    return mode


def _build_security_opt() -> list:
    """Compose the Docker ``security_opt`` list including the seccomp profile.

    Resolution order:
      1. ``TRON_SANDBOX_SECCOMP=disabled`` — drop the seccomp clause
         entirely, fall back to Docker's default profile. Use only for
         debugging a payload the strict profile is rejecting.
      2. The configured path (default ``/etc/tron/sandbox/seccomp.json``)
         — Docker reads the file at container start and applies it.
      3. If the file isn't present at runtime, log a warning and fall
         back to default. We don't fail-closed here because that would
         take down the audit pipeline if the operator hasn't mounted
         the profile yet; the warning makes the misconfig visible.
    """
    base = ["no-new-privileges:true"]

    if _SECCOMP_PROFILE_PATH.lower() in ("disabled", "off", "default"):
        return base

    if os.path.isfile(_SECCOMP_PROFILE_PATH):
        return base + [f"seccomp={_SECCOMP_PROFILE_PATH}"]

    # File configured but missing — warn loudly, return base. Don't
    # crash the executor for a config issue.
    logging.getLogger(__name__).warning(
        "Sandbox seccomp profile not found at %s — falling back to Docker "
        "default. Mount the file or set TRON_SANDBOX_SECCOMP=disabled to "
        "silence this warning.",
        _SECCOMP_PROFILE_PATH,
    )
    return base


def _hardened_run_kwargs(
    *,
    memory_limit: str,
    cpu_quota: int,
    network_mode: str,
    workdir: Optional[str],
    volumes: Optional[Dict],
) -> dict:
    """Build the full ``containers.run`` kwargs with all hardening applied.

    One code path for both ``run_python`` and ``run_bash`` — drifting two
    independently-secured callsites is how holes appear.
    """
    return {
        # ── Identity ─────────────────────────────────────────────────
        "user": _SANDBOX_USER,
        "hostname": "tron-sandbox",  # don't leak the host's hostname

        # ── Network ──────────────────────────────────────────────────
        "network_mode": _validate_network_mode(network_mode),
        "network_disabled": network_mode == "none",

        # ── Resource limits ─────────────────────────────────────────
        "mem_limit": memory_limit,
        "memswap_limit": memory_limit,  # disable swap — match RAM cap
        "cpu_quota": cpu_quota,
        "pids_limit": _SANDBOX_PIDS_LIMIT,
        "ulimits": _build_ulimits(),

        # ── Filesystem ──────────────────────────────────────────────
        # Root FS is read-only; the only writable region is the 10 MiB
        # per-container tmpfs mounted at /tmp. Everything else a payload
        # can touch must be in a caller-provided volume.
        "read_only": True,
        "tmpfs": {"/tmp": "size=10M,mode=1777"},  # nosec B108

        # ── Kernel-enforced isolation ───────────────────────────────
        "cap_drop": ["ALL"],
        "security_opt": _build_security_opt(),
        "ipc_mode": "private",  # no shared-memory lateral moves
        "pid_mode": None,       # separate PID namespace (default)

        # ── Execution mode ──────────────────────────────────────────
        "detach": True,
        "remove": True,  # auto-remove on exit
        "environment": dict(_SANDBOX_ENV),

        # ── Workspace ───────────────────────────────────────────────
        "working_dir": workdir,
        "volumes": volumes,

        # ── Output capture ──────────────────────────────────────────
        "stdout": True,
        "stderr": True,
    }


class SandboxClient:
    """
    Client for running code in isolated Docker containers.
    
    Security features:
    - No network access (default) or restricted HTTPS only
    - Read-only filesystem
    - Memory limit: 128MB
    - CPU limit: 0.5 cores
    - Timeout: 10 seconds (configurable)
    - Non-root user
    - All capabilities dropped
    
    Usage:
        client = SandboxClient()
        result = await client.run_python("print('hello')")
        print(result["output"])  # "hello"
    """
    
    def __init__(
        self,
        docker_client=None,
        default_timeout: int = 10,
        default_memory_limit: str = "128m",
        default_cpu_quota: int = 50000,  # 0.5 CPU
        logger: Optional[logging.Logger] = None
    ):
        """
        Initialize sandbox client.
        
        Args:
            docker_client: Pre-initialized Docker client (optional)
            default_timeout: Default execution timeout in seconds
            default_memory_limit: Default memory limit (e.g., "128m", "256m")
            default_cpu_quota: Default CPU quota (50000 = 0.5 CPU)
            logger: Logger instance (optional)
        """
        self.logger = logger or logging.getLogger(__name__)
        self.default_timeout = default_timeout
        self.default_memory_limit = default_memory_limit
        self.default_cpu_quota = default_cpu_quota
        self._remote_url = os.environ.get("TRON_SANDBOX_URL", "").strip()

        # Remote sandbox (tron-sandbox service) — worker has no Docker socket
        if docker_client:
            self.docker_client = docker_client
        elif self._remote_url:
            self.docker_client = None
            self.logger.info(
                "SandboxClient using remote sandbox at %s", self._remote_url
            )
        elif docker:
            try:
                self.docker_client = docker.from_env()
                self.logger.info("Docker client initialized successfully")
            except Exception as e:
                self.logger.error(f"Failed to initialize Docker client: {e}")
                self.docker_client = None
        else:
            self.logger.warning("Docker SDK not installed - sandbox disabled")
            self.docker_client = None
    
    async def run_python(
        self,
        script: str,
        timeout: Optional[int] = None,
        network_mode: str = "none",
        memory_limit: Optional[str] = None,
        cpu_quota: Optional[int] = None,
        workdir: Optional[str] = None,
        volumes: Optional[Dict] = None,
    ) -> Dict:
        """
        Execute Python script in isolated sandbox container.
        
        Args:
            script: Python code to execute
            timeout: Maximum execution time in seconds (default: 10)
            network_mode: Network isolation mode
            memory_limit: Memory limit (e.g., "128m", "256m")
            cpu_quota: CPU quota (50000 = 0.5 CPU)
            workdir: Working directory inside container
            volumes: Docker volumes to mount

        Returns:
            dict with result info
        """
        # Validate BEFORE the broad try/except so a caller passing a forbidden
        # network mode gets a loud ValueError, not a silently-swallowed error
        # dict that looks like a runtime failure.
        _validate_network_mode(network_mode)

        timeout = timeout or self.default_timeout
        if self._remote_url:
            return await self._run_python_remote(
                script, timeout, network_mode, workdir=workdir, volumes=volumes
            )
        if not self.docker_client:
            return {
                "exit_code": -1,
                "output": "",
                "error": "Docker client not available",
                "duration_ms": 0
            }

        memory_limit = memory_limit or self.default_memory_limit
        cpu_quota = cpu_quota or self.default_cpu_quota

        start_time = datetime.utcnow()

        try:
            self.logger.debug(
                f"Executing Python script in sandbox "
                f"(timeout={timeout}s, network={network_mode}, workdir={workdir})"
            )
            
            # Create and run container with the full hardening kwargs.
            # See ``_hardened_run_kwargs`` for the defense-in-depth rationale.
            container = self.docker_client.containers.run(
                image="python:3.11-slim",
                command=["python", "-c", script],
                **_hardened_run_kwargs(
                    memory_limit=memory_limit,
                    cpu_quota=cpu_quota,
                    network_mode=network_mode,
                    workdir=workdir,
                    volumes=volumes,
                ),
            )
            
            # Wait for completion with timeout
            try:
                result = container.wait(timeout=timeout)
                exit_code = result["StatusCode"]
            except Exception as timeout_error:
                # Timeout or container error
                self.logger.warning(f"Container timeout/error: {timeout_error}")
                try:
                    container.kill()
                except Exception:
                    # Best-effort kill — container may already be dead.
                    pass
                
                duration = (datetime.utcnow() - start_time).total_seconds() * 1000
                return {
                    "exit_code": -1,
                    "output": "",
                    "error": f"Execution timeout after {timeout}s",
                    "duration_ms": duration
                }
            
            # Get logs (stdout + stderr combined)
            try:
                logs = container.logs(stdout=True, stderr=True)
                output = logs.decode("utf-8", errors="replace")
            except Exception as log_error:
                self.logger.warning(f"Failed to fetch logs: {log_error}")
                output = ""
            
            duration = (datetime.utcnow() - start_time).total_seconds() * 1000
            
            self.logger.debug(
                f"Sandbox execution complete: exit_code={exit_code}, "
                f"duration={duration:.0f}ms"
            )
            
            return {
                "exit_code": exit_code,
                "output": output.strip(),
                "error": None,
                "duration_ms": duration
            }
            
        except ImageNotFound:
            self.logger.error("Docker image not found: python:3.11-slim")
            return {
                "exit_code": -1,
                "output": "",
                "error": "Docker image not found (python:3.11-slim)",
                "duration_ms": 0
            }
        
        except ContainerError as e:
            self.logger.error(f"Container execution error: {e}")
            duration = (datetime.utcnow() - start_time).total_seconds() * 1000
            return {
                "exit_code": e.exit_status,
                "output": e.stderr.decode("utf-8", errors="replace") if e.stderr else "",
                "error": f"Container error: {str(e)}",
                "duration_ms": duration
            }
        
        except APIError as e:
            self.logger.error(f"Docker API error: {e}")
            return {
                "exit_code": -1,
                "output": "",
                "error": f"Docker API error: {str(e)}",
                "duration_ms": 0
            }
        
        except Exception as e:
            self.logger.error(f"Unexpected sandbox error: {e}", exc_info=True)
            return {
                "exit_code": -1,
                "output": "",
                "error": f"Unexpected error: {str(e)}",
                "duration_ms": 0
            }

    async def _run_python_remote(
        self,
        script: str,
        timeout: int,
        network_mode: str,
        workdir: Optional[str] = None,
        volumes: Optional[Dict] = None,
    ) -> Dict:
        try:
            client = await _remote_httpx_client(self._remote_url, self.default_timeout)
            r = await client.post(
                "execute",
                json={
                    "script": script,
                    "language": "python",
                    "timeout": timeout,
                    "network_mode": network_mode,
                    "workdir": workdir,
                    "volumes": volumes,
                },
                timeout=float(timeout) + 25.0,
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            self.logger.error("Remote sandbox execute failed: %s", e)
            return {
                "exit_code": -1,
                "output": "",
                "error": str(e),
                "duration_ms": 0,
            }

    async def _run_bash_remote(
        self,
        script: str,
        timeout: int,
        network_mode: str,
        workdir: Optional[str] = None,
        volumes: Optional[Dict] = None,
    ) -> Dict:
        try:
            client = await _remote_httpx_client(self._remote_url, self.default_timeout)
            r = await client.post(
                "execute",
                json={
                    "script": script,
                    "language": "bash",
                    "timeout": timeout,
                    "network_mode": network_mode,
                    "workdir": workdir,
                    "volumes": volumes,
                },
                timeout=float(timeout) + 25.0,
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            self.logger.error("Remote sandbox bash failed: %s", e)
            return {
                "exit_code": -1,
                "output": "",
                "error": str(e),
                "duration_ms": 0,
            }
    
    async def run_bash(
        self,
        script: str,
        timeout: Optional[int] = None,
        network_mode: str = "none",
        workdir: Optional[str] = None,
        volumes: Optional[Dict] = None,
    ) -> Dict:
        """
        Execute bash script in sandbox.
        
        Similar to run_python but uses bash interpreter.
        """
        # Same hoist as run_python — validation must precede the swallowing
        # try/except or the ValueError becomes an opaque error dict.
        _validate_network_mode(network_mode)

        timeout = timeout or self.default_timeout
        if self._remote_url:
            return await self._run_bash_remote(
                script, timeout, network_mode, workdir=workdir, volumes=volumes
            )
        if not self.docker_client:
            return {
                "exit_code": -1,
                "output": "",
                "error": "Docker client not available",
                "duration_ms": 0
            }
        
        start_time = datetime.utcnow()

        try:
            container = self.docker_client.containers.run(
                image="python:3.11-slim",  # Has bash
                command=["bash", "-c", script],
                **_hardened_run_kwargs(
                    memory_limit=self.default_memory_limit,
                    cpu_quota=self.default_cpu_quota,
                    network_mode=network_mode,
                    workdir=workdir,
                    volumes=volumes,
                ),
            )
            
            result = container.wait(timeout=timeout)
            logs = container.logs(stdout=True, stderr=True)
            duration = (datetime.utcnow() - start_time).total_seconds() * 1000
            
            return {
                "exit_code": result["StatusCode"],
                "output": logs.decode("utf-8", errors="replace").strip(),
                "error": None,
                "duration_ms": duration
            }
            
        except Exception as e:
            self.logger.error(f"Bash execution error: {e}")
            duration = (datetime.utcnow() - start_time).total_seconds() * 1000
            return {
                "exit_code": -1,
                "output": "",
                "error": str(e),
                "duration_ms": duration
            }
    
    def is_available(self) -> bool:
        """Check if Docker client is available and working"""
        if self._remote_url:
            try:
                r = httpx.get(
                    f"{self._remote_url.rstrip('/')}/health",
                    timeout=5.0,
                )
                r.raise_for_status()
                return bool(r.json().get("healthy"))
            except Exception:
                return False
        if not self.docker_client:
            return False
        
        try:
            self.docker_client.ping()
            return True
        except Exception:
            return False
    
    def get_info(self) -> Dict:
        """Get Docker environment info"""
        if self._remote_url:
            return {
                "available": self.is_available(),
                "mode": "remote",
                "url": self._remote_url,
            }
        if not self.docker_client:
            return {"available": False, "error": "Docker client not initialized"}
        
        try:
            info = self.docker_client.info()
            return {
                "available": True,
                "containers_running": info.get("ContainersRunning", 0),
                "images": info.get("Images", 0),
                "driver": info.get("Driver", "unknown"),
                "kernel_version": info.get("KernelVersion", "unknown")
            }
        except Exception as e:
            return {"available": False, "error": str(e)}
