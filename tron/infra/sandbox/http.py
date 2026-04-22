"""
HTTP-based sandbox client for remote execution.

This client communicates with a remote sandbox service via HTTP/REST.
Designed to eventually migrate to gRPC, but HTTP provides a good interim
solution with standard tooling and debugging support.

The remote service is typically deployed as a separate container
(e.g., tron-sandbox) with Docker socket access and resource isolation.

Example remote service architecture:
  Client (this module) → HTTP → Remote Sandbox Service → Docker daemon
                                      ↓
                                  Ephemeral container with:
                                  - --network none
                                  - --read-only
                                  - --memory 256m
                                  - --cpus 0.5
                                  - 30s timeout
"""

from __future__ import annotations

import json
import logging
import time
from typing import Optional

import httpx

from tron.infra.sandbox.client import (
    ExecutionResult,
    SandboxClient,
    VerificationResult,
)

logger = logging.getLogger(__name__)


class HTTPSandbox(SandboxClient):
    """HTTP client for remote sandbox execution.

    Communicates with a remote service (typically in Docker) that
    has access to Docker socket for spawning isolated containers.

    Example endpoints:
      POST /execute
        {
          "code": "...",
          "language": "python",
          "timeout": 10
        }
        → { "stdout": "...", "stderr": "...", "exit_code": 0, "duration_seconds": 0.5 }

      POST /verify
        {
          "original_code": "...",
          "fixed_code": "...",
          "test_code": "...",
          "language": "python"
        }
        → { "passed": true, "test_output": "...", "errors": [], "duration_seconds": 0.8 }

      GET /health
        → { "healthy": true, "uptime_seconds": 1234 }
    """

    def __init__(
        self,
        sandbox_url: str,
        timeout_seconds: int = 30,
    ) -> None:
        """Initialize HTTP sandbox client.

        Args:
            sandbox_url: Base URL of remote sandbox service
                        (e.g., http://tron-sandbox:50051)
            timeout_seconds: Default timeout for all HTTP operations
        """
        super().__init__(sandbox_url, timeout_seconds)
        # Remove trailing slash for consistency
        self.sandbox_url = sandbox_url.rstrip("/")
        self._http = httpx.AsyncClient(
            base_url=self.sandbox_url,
            timeout=timeout_seconds,
        )

    async def execute(
        self,
        code: str,
        language: str,
        timeout: Optional[int] = None,
        workdir: Optional[str] = None,
    ) -> ExecutionResult:
        """Execute code via remote sandbox service.

        Args:
            code: Source code to execute
            language: Programming language
            timeout: Maximum execution time in seconds
            workdir: Optional directory to run in (remote service must support mounting)

        Returns:
            ExecutionResult from remote service

        Raises:
            ValueError: If inputs are invalid
            RuntimeError: If remote service is unavailable or returns error
        """
        if not code or not code.strip():
            raise ValueError("Code cannot be empty")

        timeout = timeout or self.timeout_seconds

        payload = {
            "code": code,
            "language": language,
            "timeout": timeout,
            "workdir": workdir,
        }

        try:
            response = await self._http.post(
                "/execute",
                json=payload,
            )
            response.raise_for_status()

            data = response.json()
            return ExecutionResult(
                stdout=data.get("stdout", ""),
                stderr=data.get("stderr", ""),
                exit_code=data.get("exit_code", 0),
                duration_seconds=data.get("duration_seconds", 0.0),
                timed_out=data.get("timed_out", False),
            )

        except httpx.HTTPStatusError as exc:
            error_detail = exc.response.text
            logger.error(
                "Sandbox execution failed (HTTP %d): %s",
                exc.response.status_code,
                error_detail,
            )
            raise RuntimeError(f"Sandbox execution failed: {error_detail}") from exc

        except (httpx.RequestError, json.JSONDecodeError) as exc:
            logger.error("Sandbox request failed: %s", exc)
            raise RuntimeError(f"Sandbox unavailable: {exc}") from exc

    async def verify_fix(
        self,
        original_code: str,
        fixed_code: str,
        test_code: str,
        language: str,
    ) -> VerificationResult:
        """Verify fix via remote sandbox service.

        Args:
            original_code: Original (vulnerable) code
            fixed_code: Fixed code to verify
            test_code: Test code to execute
            language: Programming language

        Returns:
            VerificationResult from remote service

        Raises:
            ValueError: If inputs are invalid
            RuntimeError: If remote service is unavailable
        """
        payload = {
            "original_code": original_code,
            "fixed_code": fixed_code,
            "test_code": test_code,
            "language": language,
        }

        try:
            response = await self._http.post(
                "/verify",
                json=payload,
            )
            response.raise_for_status()

            data = response.json()
            return VerificationResult(
                passed=data.get("passed", False),
                test_output=data.get("test_output", ""),
                errors=data.get("errors", []),
                duration_seconds=data.get("duration_seconds", 0.0),
            )

        except httpx.HTTPStatusError as exc:
            error_detail = exc.response.text
            logger.error(
                "Fix verification failed (HTTP %d): %s",
                exc.response.status_code,
                error_detail,
            )
            raise RuntimeError(f"Fix verification failed: {error_detail}") from exc

        except (httpx.RequestError, json.JSONDecodeError) as exc:
            logger.error("Sandbox request failed: %s", exc)
            raise RuntimeError(f"Sandbox unavailable: {exc}") from exc

    async def health_check(self) -> bool:
        """Check if remote sandbox service is healthy.

        Returns:
            True if service is responsive
        """
        try:
            response = await self._http.get(
                "/health",
                timeout=5,
            )
            response.raise_for_status()

            data = response.json()
            healthy = data.get("healthy", False)

            if healthy:
                logger.debug(
                    "Sandbox health OK (uptime=%ds)",
                    data.get("uptime_seconds", 0),
                )
            else:
                logger.warning("Sandbox health check failed: unhealthy")

            return healthy

        except Exception as exc:
            logger.warning("Sandbox health check failed: %s", exc)
            return False

    async def close(self) -> None:
        """Close HTTP client connection."""
        await self._http.aclose()
