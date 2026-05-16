"""
Abstract sandbox client interface and factory.

Provides a provider-agnostic interface for executing code in isolated environments.
Currently supports local subprocess execution; designed for gRPC migration.

The SandboxClient abstract class defines the contract for any backend
(HTTP, gRPC, subprocess, container orchestration, etc.).
"""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


# ── Data Models ───────────────────────────────────────────────────────


@dataclass
class ExecutionResult:
    """Result of executing code in the sandbox."""

    stdout: str
    stderr: str
    exit_code: int
    duration_seconds: float
    timed_out: bool

    @property
    def success(self) -> bool:
        """Code executed successfully (exit code 0, no timeout)."""
        return self.exit_code == 0 and not self.timed_out


@dataclass
class VerificationResult:
    """Result of verifying a code fix."""

    passed: bool
    test_output: str
    errors: list[str]
    duration_seconds: float

    @property
    def summary(self) -> str:
        """Human-readable summary."""
        if self.passed:
            return "All tests passed"
        return f"Tests failed with {len(self.errors)} error(s)"


# ── Abstract Client ───────────────────────────────────────────────────


class SandboxClient(ABC):
    """Abstract interface for code execution sandboxes.

    Implementations must handle:
    - Timeout enforcement
    - Resource isolation
    - Secure cleanup
    - Error handling and logging
    """

    def __init__(
        self,
        sandbox_url: str,
        timeout_seconds: int = 30,
    ) -> None:
        """Initialize the sandbox client.

        Args:
            sandbox_url: URL or connection string for the sandbox
                        (e.g., http://localhost:9999 or unix:///sandbox.sock)
            timeout_seconds: Default timeout for all operations
        """
        self.sandbox_url = sandbox_url
        self.timeout_seconds = timeout_seconds

    @abstractmethod
    async def execute(
        self,
        code: str,
        language: str,
        timeout: Optional[int] = None,
        workdir: Optional[str] = None,
    ) -> ExecutionResult:
        """Execute code in isolation.

        Args:
            code: Source code to execute
            language: Programming language (python, javascript, bash, etc.)
            timeout: Maximum execution time in seconds (uses default if None)
            workdir: Optional directory to run in (may require mounting)

        Returns:
            ExecutionResult with stdout, stderr, exit code, and duration

        Raises:
            ValueError: If language is not supported or code is invalid
            RuntimeError: If sandbox is unavailable or execution fails
        """
        pass

    async def run_bash(
        self,
        script: str,
        timeout: Optional[int] = None,
        workdir: Optional[str] = None,
    ) -> ExecutionResult:
        """Execute a bash script in the sandbox."""
        return await self.execute(script, "bash", timeout=timeout, workdir=workdir)

    @abstractmethod
    async def verify_fix(
        self,
        original_code: str,
        fixed_code: str,
        test_code: str,
        language: str,
    ) -> VerificationResult:
        """Verify a code fix by running tests.

        Args:
            original_code: Original (vulnerable) code for context
            fixed_code: Fixed/patched code to verify
            test_code: Test code to validate the fix (must be in same language)
            language: Programming language

        Returns:
            VerificationResult indicating if all tests passed

        Raises:
            ValueError: If inputs are invalid
            RuntimeError: If sandbox is unavailable
        """
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if sandbox is available.

        Returns:
            True if sandbox is healthy and responsive
        """
        pass


# ── Factory ────────────────────────────────────────────────────────


async def get_sandbox_client() -> SandboxClient:
    """Get a sandbox client (HTTP or local based on environment).

    Environment Variables:
        SANDBOX_MODE: "local" (default) or "http"
        SANDBOX_URL: URL for HTTP mode (default: http://localhost:50051)
        SANDBOX_TIMEOUT: Default timeout in seconds (default: 30)

    Returns:
        A configured SandboxClient instance

    Raises:
        RuntimeError: If configuration is invalid or health check fails
    """
    from tron.infra.sandbox.local import LocalSandbox

    mode = os.getenv("SANDBOX_MODE", "local").lower()
    sandbox_url = os.getenv("SANDBOX_URL", "http://localhost:50051")
    timeout = int(os.getenv("SANDBOX_TIMEOUT", "30"))

    if mode == "local":
        logger.debug("Using local subprocess sandbox")
        client = LocalSandbox(sandbox_url=sandbox_url, timeout_seconds=timeout)
    elif mode == "http":
        # Future: HTTP-based client
        from tron.infra.sandbox.http import HTTPSandbox

        logger.debug("Using HTTP sandbox at %s", sandbox_url)
        client = HTTPSandbox(sandbox_url=sandbox_url, timeout_seconds=timeout)
    else:
        raise ValueError(f"Unknown SANDBOX_MODE: {mode}")

    # Verify health
    if not await client.health_check():
        raise RuntimeError(f"Sandbox health check failed: {sandbox_url}")

    logger.info("Sandbox client initialized: %s (timeout=%ds)", mode, timeout)
    return client
