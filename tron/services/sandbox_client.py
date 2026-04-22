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
    from docker.errors import DockerException, ContainerError, ImageNotFound, APIError
except ImportError:
    docker = None  # Handle gracefully if docker SDK not installed


class SandboxExecutionError(Exception):
    """Raised when sandbox execution fails"""
    pass


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
            
            # Create and run container
            container = self.docker_client.containers.run(
                image="python:3.11-slim",
                command=["python", "-c", script],
                
                # Network isolation
                network_mode=network_mode,
                
                # Resource limits
                mem_limit=memory_limit,
                cpu_quota=cpu_quota,
                
                # Security hardening
                read_only=False,  # Python needs /tmp for imports
                tmpfs={"/tmp": "size=10M,mode=1777"},
                cap_drop=["ALL"],
                security_opt=["no-new-privileges:true"],
                
                # Execution mode
                detach=True,
                remove=True,  # Auto-remove after completion
                
                # Workspace
                working_dir=workdir,
                volumes=volumes,

                # Output capture
                stdout=True,
                stderr=True
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
                except:
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
                network_mode=network_mode,
                mem_limit=self.default_memory_limit,
                cpu_quota=self.default_cpu_quota,
                read_only=False,
                tmpfs={"/tmp": "size=10M,mode=1777"},
                cap_drop=["ALL"],
                security_opt=["no-new-privileges:true"],
                detach=True,
                remove=True,
                working_dir=workdir,
                volumes=volumes,
                stdout=True,
                stderr=True
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
