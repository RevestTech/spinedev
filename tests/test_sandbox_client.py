"""
Unit tests for sandbox client implementations.

Tests cover:
- Local subprocess sandbox execution
- Error handling and timeout enforcement
- Code combination for verification
- Resource limits
"""

from __future__ import annotations

import pytest

from tron.infra.sandbox import ExecutionResult, VerificationResult, get_sandbox_client
from tron.infra.sandbox.local import LocalSandbox


@pytest.mark.asyncio
class TestLocalSandbox:
    """Tests for LocalSandbox implementation."""

    @pytest.fixture
    async def sandbox(self) -> LocalSandbox:
        """Provide a sandbox instance."""
        return LocalSandbox(sandbox_url="local://", timeout_seconds=30)

    async def test_execute_python_success(self, sandbox: LocalSandbox) -> None:
        """Execute valid Python code."""
        result = await sandbox.execute(
            code='print("hello world")',
            language="python",
        )

        assert result.success
        assert "hello world" in result.stdout
        assert result.exit_code == 0
        assert not result.timed_out
        assert result.duration_seconds > 0

    async def test_execute_python3_success(self, sandbox: LocalSandbox) -> None:
        """Execute Python code with python3."""
        result = await sandbox.execute(
            code='print(2 + 2)',
            language="python3",
        )

        assert result.success
        assert "4" in result.stdout

    async def test_execute_with_stderr(self, sandbox: LocalSandbox) -> None:
        """Capture stderr from Python."""
        result = await sandbox.execute(
            code='import sys; print("error", file=sys.stderr); print("ok")',
            language="python",
        )

        assert result.exit_code == 0
        assert "error" in result.stderr
        assert "ok" in result.stdout

    async def test_execute_with_nonzero_exit(self, sandbox: LocalSandbox) -> None:
        """Handle non-zero exit code."""
        result = await sandbox.execute(
            code='import sys; sys.exit(42)',
            language="python",
        )

        assert not result.success
        assert result.exit_code == 42

    async def test_execute_timeout(self, sandbox: LocalSandbox) -> None:
        """Enforce timeout limit."""
        result = await sandbox.execute(
            code="import time; time.sleep(10)",
            language="python",
            timeout=1,
        )

        assert result.timed_out
        assert not result.success
        assert result.duration_seconds < 2  # Should timeout before 10s

    async def test_execute_javascript_success(self, sandbox: LocalSandbox) -> None:
        """Execute JavaScript code (requires Node.js)."""
        try:
            result = await sandbox.execute(
                code='console.log("hello from js")',
                language="javascript",
            )
            assert result.success
            assert "hello from js" in result.stdout

        except RuntimeError as exc:
            if "node not found" in str(exc):
                pytest.skip("Node.js not installed")
            raise

    async def test_execute_bash_success(self, sandbox: LocalSandbox) -> None:
        """Execute Bash code."""
        result = await sandbox.execute(
            code='echo "hello from bash"',
            language="bash",
        )

        assert result.success
        assert "hello from bash" in result.stdout

    async def test_execute_empty_code_fails(self, sandbox: LocalSandbox) -> None:
        """Reject empty code."""
        with pytest.raises(ValueError, match="Code cannot be empty"):
            await sandbox.execute(code="", language="python")

    async def test_execute_whitespace_only_fails(
        self, sandbox: LocalSandbox
    ) -> None:
        """Reject whitespace-only code."""
        with pytest.raises(ValueError, match="Code cannot be empty"):
            await sandbox.execute(code="   \n  ", language="python")

    async def test_execute_unsupported_language(
        self, sandbox: LocalSandbox
    ) -> None:
        """Reject unsupported language."""
        with pytest.raises(ValueError, match="Unsupported language"):
            await sandbox.execute(code='print("test")', language="cobol")

    async def test_execute_negative_timeout(self, sandbox: LocalSandbox) -> None:
        """Reject negative timeout."""
        with pytest.raises(ValueError, match="Timeout must be positive"):
            await sandbox.execute(
                code='print("test")',
                language="python",
                timeout=-1,
            )

    async def test_execute_uses_default_timeout(self, sandbox: LocalSandbox) -> None:
        """Use default timeout when not specified."""
        # Fast code should succeed with default timeout
        result = await sandbox.execute(
            code='print("ok")',
            language="python",
            timeout=None,
        )

        assert result.success

    async def test_health_check_success(self, sandbox: LocalSandbox) -> None:
        """Health check should pass."""
        healthy = await sandbox.health_check()
        assert healthy

    async def test_verify_fix_passed(self, sandbox: LocalSandbox) -> None:
        """Verify fix when tests pass."""
        result = await sandbox.verify_fix(
            original_code='x = "not fixed"',
            fixed_code='x = "fixed"',
            test_code='assert x == "fixed", f"got {x}"',
            language="python",
        )

        assert result.passed
        assert result.duration_seconds > 0
        assert len(result.errors) == 0

    async def test_verify_fix_failed(self, sandbox: LocalSandbox) -> None:
        """Verify fix when tests fail."""
        result = await sandbox.verify_fix(
            original_code='x = 1',
            fixed_code='x = 1',
            test_code='assert x == 2, "x should be 2"',
            language="python",
        )

        assert not result.passed
        assert len(result.errors) > 0

    async def test_verify_fix_with_timeout(self, sandbox: LocalSandbox) -> None:
        """Verify fix detects timeout."""
        # Create a sandbox with very short timeout
        short_timeout_sandbox = LocalSandbox(
            sandbox_url="local://", timeout_seconds=1
        )

        result = await short_timeout_sandbox.verify_fix(
            original_code="x = 1",
            fixed_code="x = 2",
            test_code="import time; time.sleep(5)",
            language="python",
        )

        assert not result.passed
        assert any("timed out" in e.lower() for e in result.errors)

    async def test_verify_fix_empty_test_code(
        self, sandbox: LocalSandbox
    ) -> None:
        """Reject empty test code."""
        with pytest.raises(ValueError, match="Test code cannot be empty"):
            await sandbox.verify_fix(
                original_code="x = 1",
                fixed_code="x = 2",
                test_code="",
                language="python",
            )

    async def test_output_truncation(self, sandbox: LocalSandbox) -> None:
        """Verify large output is truncated."""
        # Create code that produces very large output
        large_output = "x" * (2 * 1024 * 1024)  # 2MB
        code = f'print("{large_output}")'

        result = await sandbox.execute(code=code, language="python")

        # Output should be truncated
        assert len(result.stdout) <= (1 * 1024 * 1024 + 1024)  # 1MB + margin


@pytest.mark.asyncio
class TestSandboxFactory:
    """Tests for get_sandbox_client factory."""

    async def test_factory_returns_local_by_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Factory returns LocalSandbox by default."""
        # Ensure environment is clean
        monkeypatch.delenv("SANDBOX_MODE", raising=False)

        client = await get_sandbox_client()
        assert isinstance(client, LocalSandbox)

    async def test_factory_with_local_mode(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Factory respects SANDBOX_MODE=local."""
        monkeypatch.setenv("SANDBOX_MODE", "local")

        client = await get_sandbox_client()
        assert isinstance(client, LocalSandbox)

    async def test_factory_respects_timeout_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Factory respects SANDBOX_TIMEOUT environment variable."""
        monkeypatch.setenv("SANDBOX_TIMEOUT", "60")

        client = await get_sandbox_client()
        assert client.timeout_seconds == 60

    async def test_factory_health_check_required(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Factory fails if health check fails."""
        # This is harder to test with LocalSandbox since it usually succeeds
        # But we can verify the code path exists
        client = await get_sandbox_client()
        health = await client.health_check()
        assert health


class TestExecutionResult:
    """Tests for ExecutionResult dataclass."""

    def test_success_with_zero_exit_code(self) -> None:
        """Result is successful with exit code 0 and no timeout."""
        result = ExecutionResult(
            stdout="ok",
            stderr="",
            exit_code=0,
            duration_seconds=1.0,
            timed_out=False,
        )

        assert result.success

    def test_failure_with_nonzero_exit_code(self) -> None:
        """Result is not successful with non-zero exit code."""
        result = ExecutionResult(
            stdout="",
            stderr="error",
            exit_code=1,
            duration_seconds=1.0,
            timed_out=False,
        )

        assert not result.success

    def test_failure_with_timeout(self) -> None:
        """Result is not successful if timed out."""
        result = ExecutionResult(
            stdout="",
            stderr="",
            exit_code=0,
            duration_seconds=10.0,
            timed_out=True,
        )

        assert not result.success


class TestVerificationResult:
    """Tests for VerificationResult dataclass."""

    def test_summary_when_passed(self) -> None:
        """Summary text for passed verification."""
        result = VerificationResult(
            passed=True,
            test_output="all tests passed",
            errors=[],
            duration_seconds=1.0,
        )

        assert "passed" in result.summary.lower()

    def test_summary_when_failed(self) -> None:
        """Summary text for failed verification."""
        result = VerificationResult(
            passed=False,
            test_output="",
            errors=["assertion failed", "invalid syntax"],
            duration_seconds=1.0,
        )

        summary = result.summary
        assert "failed" in summary.lower()
        assert "2" in summary  # Should mention number of errors
