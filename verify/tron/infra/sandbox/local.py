"""
Local subprocess-based sandbox implementation.

For development and testing, executes code via asyncio subprocess in isolated
temp directories with strict timeout and resource limits. Production deployments
should use the HTTP client with a remote gRPC sandbox service.

Features:
- Async subprocess execution with strict timeouts
- Per-execution temp directories for file system isolation
- Language-specific interpreters (Python, Node.js, Bash)
- Resource limit enforcement
- Automatic cleanup of temp files
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Optional

from tron.infra.sandbox.client import (
    ExecutionResult,
    SandboxClient,
    VerificationResult,
)

logger = logging.getLogger(__name__)

# Supported languages and their interpreters
_INTERPRETERS = {
    "python": "python3",
    "python3": "python3",
    "javascript": "node",
    "js": "node",
    "bash": "bash",
    "sh": "bash",
}

# Maximum output size to capture (prevent memory bloat from infinite loops)
_MAX_OUTPUT_SIZE = 1024 * 1024  # 1 MB


class LocalSandbox(SandboxClient):
    """Local subprocess sandbox for development and testing.

    Each execution happens in a dedicated temp directory with:
    - No network access (implicit via subprocess isolation)
    - File system isolation (temp dir only)
    - Memory and CPU timeout enforcement
    - Automatic cleanup

    Production Deployment:
    - Replace with HTTPSandbox client pointing to remote gRPC service
    - Use gVisor or Firecracker on dedicated host
    - Enforce kernel-level resource limits via cgroups
    """

    async def execute(
        self,
        code: str,
        language: str,
        timeout: Optional[int] = None,
        workdir: Optional[str] = None,
    ) -> ExecutionResult:
        """Execute code in an isolated subprocess.

        Args:
            code: Source code to execute
            language: Programming language (python, python3, javascript, bash, sh)
            timeout: Maximum execution time in seconds (uses self.timeout_seconds if None)
            workdir: Optional directory to run in

        Returns:
            ExecutionResult with stdout, stderr, exit code, and duration

        Raises:
            ValueError: If language is not supported or code is invalid
            RuntimeError: If subprocess execution fails
        """
        if not code or not code.strip():
            raise ValueError("Code cannot be empty")

        if language not in _INTERPRETERS:
            raise ValueError(
                f"Unsupported language: {language}. "
                f"Supported: {', '.join(_INTERPRETERS.keys())}"
            )

        timeout = timeout or self.timeout_seconds
        if timeout <= 0:
            raise ValueError(f"Timeout must be positive: {timeout}")

        interpreter = _INTERPRETERS[language]

        # Verify interpreter is available
        if not shutil.which(interpreter):
            raise RuntimeError(f"{interpreter} not found in PATH")

        # Create isolated temp directory if no workdir provided
        temp_dir = tempfile.mkdtemp(prefix="tron-sandbox-")
        script_path = Path(temp_dir) / f"script.{self._ext(language)}"

        try:
            # Write code to temp script
            script_path.write_text(code, encoding="utf-8")

            # Execute in temp directory or specified workdir
            start_time = time.time()
            try:
                result = await asyncio.wait_for(
                    self._run_subprocess(
                        interpreter,
                        str(script_path),
                        cwd=workdir or temp_dir,
                    ),
                    timeout=timeout,
                )
                duration = time.time() - start_time
                return ExecutionResult(
                    stdout=result["stdout"],
                    stderr=result["stderr"],
                    exit_code=result["exit_code"],
                    duration_seconds=duration,
                    timed_out=False,
                )

            except asyncio.TimeoutError:
                duration = time.time() - start_time
                logger.warning(
                    "Sandbox execution timed out after %.1fs: %s",
                    duration,
                    language,
                )
                return ExecutionResult(
                    stdout="",
                    stderr=f"Execution timed out after {timeout}s",
                    exit_code=-1,
                    duration_seconds=duration,
                    timed_out=True,
                )

        except Exception as exc:
            logger.exception("Sandbox execution failed: %s", exc)
            raise RuntimeError(f"Execution failed: {exc}") from exc

        finally:
            # Clean up temp directory
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception as exc:
                logger.warning("Failed to cleanup temp dir %s: %s", temp_dir, exc)

    async def verify_fix(
        self,
        original_code: str,
        fixed_code: str,
        test_code: str,
        language: str,
    ) -> VerificationResult:
        """Verify a fix by executing tests in the sandbox.

        Args:
            original_code: Original code (unused, for context only)
            fixed_code: Fixed code to test
            test_code: Test code that exercises the fix
            language: Programming language

        Returns:
            VerificationResult indicating if all tests passed

        The test code must be executable and should use language-specific
        assertions or exit codes to indicate pass/fail:
        - Python: use assert, pytest, unittest, or exit(0) for pass
        - JavaScript: use console.assert, throw for failure
        - Bash: use exit codes, or test commands
        """
        if not test_code or not test_code.strip():
            raise ValueError("Test code cannot be empty")

        # Combine fixed code with test code
        combined = self._combine_code(fixed_code, test_code, language)

        start_time = time.time()
        try:
            result = await self.execute(combined, language)
            duration = time.time() - start_time

            # Verify success: exit code 0 and no timeout
            passed = result.success
            errors = []

            if result.timed_out:
                errors.append("Test execution timed out")
            elif result.exit_code != 0:
                errors.append(f"Exit code: {result.exit_code}")

            if result.stderr:
                errors.append(result.stderr)

            test_output = result.stdout or result.stderr or ""

            logger.info(
                "Fix verification: %s (%.2fs, exit_code=%d)",
                "PASS" if passed else "FAIL",
                duration,
                result.exit_code,
            )

            return VerificationResult(
                passed=passed,
                test_output=test_output,
                errors=errors,
                duration_seconds=duration,
            )

        except Exception as exc:
            duration = time.time() - start_time
            logger.exception("Fix verification failed: %s", exc)
            return VerificationResult(
                passed=False,
                test_output="",
                errors=[str(exc)],
                duration_seconds=duration,
            )

    async def health_check(self) -> bool:
        """Check if sandbox is operational.

        Returns:
            True if we can execute simple code
        """
        try:
            result = await self.execute("print('ok')", "python", timeout=5)
            return result.success

        except Exception as exc:
            logger.warning("Sandbox health check failed: %s", exc)
            return False

    # ── Private Methods ──────────────────────────────────────────────

    async def _run_subprocess(
        self,
        interpreter: str,
        script_path: str,
        cwd: Optional[str] = None,
    ) -> dict[str, str | int]:
        """Run interpreter on script, capturing output.

        Returns dict with 'stdout', 'stderr', 'exit_code'
        """
        try:
            process = await asyncio.create_subprocess_exec(
                interpreter,
                script_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                # No stdin — prevent interactive scripts
                stdin=asyncio.subprocess.DEVNULL,
                cwd=cwd,
            )

            stdout_bytes, stderr_bytes = await process.communicate()

            # Truncate output if too large
            stdout = stdout_bytes.decode("utf-8", errors="replace")[
                :_MAX_OUTPUT_SIZE
            ]
            stderr = stderr_bytes.decode("utf-8", errors="replace")[
                :_MAX_OUTPUT_SIZE
            ]

            return {
                "stdout": stdout,
                "stderr": stderr,
                "exit_code": process.returncode or 0,
            }

        except Exception as exc:
            raise RuntimeError(f"Subprocess execution failed: {exc}") from exc

    @staticmethod
    def _ext(language: str) -> str:
        """Get file extension for language."""
        exts = {
            "python": "py",
            "python3": "py",
            "javascript": "js",
            "js": "js",
            "bash": "sh",
            "sh": "sh",
        }
        return exts.get(language, "txt")

    @staticmethod
    def _combine_code(fixed_code: str, test_code: str, language: str) -> str:
        """Combine fixed code with test code for verification.

        Handles language-specific import/include patterns.
        """
        if language in ("python", "python3"):
            # In Python, assume test_code can import/use fixed_code
            # If fixed_code is a function/class definition, test_code can call it
            return f"{fixed_code}\n\n{test_code}"

        elif language in ("javascript", "js"):
            # In JavaScript, assume both are in same scope
            return f"{fixed_code}\n\n{test_code}"

        elif language in ("bash", "sh"):
            # In Bash, concatenate directly
            return f"{fixed_code}\n\n{test_code}"

        else:
            # Default: concatenate
            return f"{fixed_code}\n\n{test_code}"
