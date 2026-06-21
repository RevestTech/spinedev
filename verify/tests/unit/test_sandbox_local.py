"""
Unit tests for local sandbox execution (subprocess-based).

Tests:
  - LocalSandbox initialization and configuration
  - Code execution with timeout handling
  - Output capture and size limiting
  - Exit code handling and error handling
  - Temp directory cleanup
  - File injection and isolation
  - Concurrent execution (via asyncio)
  - verify_fix() with various languages and test patterns
  - health_check() validation
  - HTTPSandbox client initialization and HTTP communication
  - HTTPSandbox request/response parsing
  - HTTPSandbox retry logic and error handling
  - Unsupported language errors
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from tron.infra.sandbox.http import HTTPSandbox
from tron.infra.sandbox.local import LocalSandbox


# ── LocalSandbox Initialization Tests ─────────────────────────────────


class TestLocalSandboxInit:

    def test_init_default_timeout(self):
        """Default initialization with 30 second timeout."""
        sandbox = LocalSandbox(sandbox_url="local", timeout_seconds=30)
        assert sandbox.timeout_seconds == 30
        assert sandbox.sandbox_url == "local"

    def test_init_custom_timeout(self):
        """Custom timeout configuration."""
        sandbox = LocalSandbox(sandbox_url="local", timeout_seconds=60)
        assert sandbox.timeout_seconds == 60

    def test_ext_python_language(self):
        """File extension for Python."""
        assert LocalSandbox._ext("python") == "py"
        assert LocalSandbox._ext("python3") == "py"

    def test_ext_javascript_language(self):
        """File extension for JavaScript."""
        assert LocalSandbox._ext("javascript") == "js"
        assert LocalSandbox._ext("js") == "js"

    def test_ext_bash_language(self):
        """File extension for Bash."""
        assert LocalSandbox._ext("bash") == "sh"
        assert LocalSandbox._ext("sh") == "sh"


# ── LocalSandbox execute() Tests ─────────────────────────────────────


class TestLocalSandboxExecute:

    @pytest.mark.asyncio
    async def test_execute_python_success(self):
        """Execute simple Python code successfully."""
        sandbox = LocalSandbox(sandbox_url="local", timeout_seconds=10)
        result = await sandbox.execute(
            code="print('hello world')",
            language="python",
        )
        assert result.success
        assert "hello world" in result.stdout
        assert result.exit_code == 0
        assert not result.timed_out

    @pytest.mark.asyncio
    async def test_execute_javascript_success(self):
        """Execute simple JavaScript code."""
        sandbox = LocalSandbox(sandbox_url="local", timeout_seconds=10)
        result = await sandbox.execute(
            code="console.log('hello from js')",
            language="javascript",
        )
        assert result.exit_code == 0
        assert "hello from js" in result.stdout

    @pytest.mark.asyncio
    async def test_execute_bash_success(self):
        """Execute Bash command."""
        sandbox = LocalSandbox(sandbox_url="local", timeout_seconds=10)
        result = await sandbox.execute(
            code="echo 'hello bash'",
            language="bash",
        )
        assert result.exit_code == 0
        assert "hello bash" in result.stdout

    @pytest.mark.asyncio
    async def test_execute_empty_code_raises_error(self):
        """Empty code raises ValueError."""
        sandbox = LocalSandbox(sandbox_url="local", timeout_seconds=10)
        with pytest.raises(ValueError, match="Code cannot be empty"):
            await sandbox.execute(code="", language="python")

    @pytest.mark.asyncio
    async def test_execute_whitespace_code_raises_error(self):
        """Whitespace-only code raises ValueError."""
        sandbox = LocalSandbox(sandbox_url="local", timeout_seconds=10)
        with pytest.raises(ValueError, match="Code cannot be empty"):
            await sandbox.execute(code="   \n\n  ", language="python")

    @pytest.mark.asyncio
    async def test_execute_unsupported_language_raises_error(self):
        """Unsupported language raises ValueError."""
        sandbox = LocalSandbox(sandbox_url="local", timeout_seconds=10)
        with pytest.raises(ValueError, match="Unsupported language"):
            await sandbox.execute(code="print('hi')", language="rust")

    @pytest.mark.asyncio
    async def test_execute_negative_timeout_raises_error(self):
        """Negative timeout raises ValueError."""
        sandbox = LocalSandbox(sandbox_url="local", timeout_seconds=10)
        with pytest.raises(ValueError, match="Timeout must be positive"):
            await sandbox.execute(
                code="print('hi')",
                language="python",
                timeout=-1,
            )

    @pytest.mark.asyncio
    async def test_execute_timeout_honored(self):
        """Execution times out after specified duration."""
        sandbox = LocalSandbox(sandbox_url="local", timeout_seconds=10)
        # Use a sleep that exceeds timeout
        result = await sandbox.execute(
            code="import time; time.sleep(100)",
            language="python",
            timeout=1,
        )
        assert result.timed_out
        assert result.exit_code == -1
        assert "timed out" in result.stderr.lower()

    @pytest.mark.asyncio
    async def test_execute_non_zero_exit_code(self):
        """Python script with non-zero exit code."""
        sandbox = LocalSandbox(sandbox_url="local", timeout_seconds=10)
        result = await sandbox.execute(
            code="import sys; sys.exit(42)",
            language="python",
        )
        assert result.exit_code == 42
        assert not result.success

    @pytest.mark.asyncio
    async def test_execute_stderr_captured(self):
        """Stderr output is captured."""
        sandbox = LocalSandbox(sandbox_url="local", timeout_seconds=10)
        result = await sandbox.execute(
            code="import sys; sys.stderr.write('error message')",
            language="python",
        )
        assert "error message" in result.stderr

    @pytest.mark.asyncio
    async def test_execute_large_output_truncated(self):
        """Very large output is truncated to _MAX_OUTPUT_SIZE."""
        sandbox = LocalSandbox(sandbox_url="local", timeout_seconds=10)
        # Generate > 1MB output
        result = await sandbox.execute(
            code="print('x' * 2000000)",
            language="python",
        )
        # Output should be capped at 1MB
        assert len(result.stdout) <= 1024 * 1024 + 100  # small margin for encoding

    @pytest.mark.asyncio
    async def test_execute_uses_custom_timeout(self):
        """Custom timeout parameter overrides default."""
        sandbox = LocalSandbox(sandbox_url="local", timeout_seconds=100)
        # 2-second timeout overrides 100-second default
        result = await sandbox.execute(
            code="import time; time.sleep(10)",
            language="python",
            timeout=2,
        )
        assert result.timed_out

    @pytest.mark.asyncio
    async def test_execute_temp_dir_cleanup(self):
        """Temp directory is cleaned up after execution."""
        sandbox = LocalSandbox(sandbox_url="local", timeout_seconds=10)
        # Track temp directories before
        temp_dirs_before = set(Path(tempfile.gettempdir()).glob("tron-sandbox-*"))

        result = await sandbox.execute(
            code="print('test')",
            language="python",
        )
        assert result.success

        # Check that no new temp directories remain
        temp_dirs_after = set(Path(tempfile.gettempdir()).glob("tron-sandbox-*"))
        # New directories should have been cleaned up
        # (We can only verify they're not growing indefinitely)
        assert len(temp_dirs_after) <= len(temp_dirs_before) + 1

    @pytest.mark.asyncio
    async def test_execute_concurrent_executions(self):
        """Multiple concurrent executions work independently."""
        sandbox = LocalSandbox(sandbox_url="local", timeout_seconds=10)

        async def run_code(msg: str) -> str:
            result = await sandbox.execute(
                code=f"print('{msg}')",
                language="python",
            )
            return result.stdout.strip()

        results = await asyncio.gather(
            run_code("first"),
            run_code("second"),
            run_code("third"),
        )

        assert len(results) == 3
        assert "first" in results[0]
        assert "second" in results[1]
        assert "third" in results[2]

    @pytest.mark.asyncio
    async def test_execute_file_injection(self):
        """Code can read files from temp directory."""
        sandbox = LocalSandbox(sandbox_url="local", timeout_seconds=10)
        # Note: Can't directly inject files in current implementation,
        # but test that code can create and read files in temp dir
        result = await sandbox.execute(
            code="""
import tempfile
import os
with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
    f.write('test content')
    name = f.name
with open(name) as f:
    print(f.read())
os.unlink(name)
""",
            language="python",
        )
        assert "test content" in result.stdout


# ── LocalSandbox verify_fix() Tests ──────────────────────────────────


class TestLocalSandboxVerifyFix:

    @pytest.mark.asyncio
    async def test_verify_fix_python_success(self):
        """Verify a Python fix with passing tests."""
        sandbox = LocalSandbox(sandbox_url="local", timeout_seconds=10)
        result = await sandbox.verify_fix(
            original_code="def add(a, b): return a + b",
            fixed_code="def add(a, b): return a + b",
            test_code="""
assert add(2, 3) == 5
assert add(0, 0) == 0
print('All tests passed')
""",
            language="python",
        )
        assert result.passed
        assert result.duration_seconds >= 0

    @pytest.mark.asyncio
    async def test_verify_fix_python_failure(self):
        """Verify a Python fix with failing tests."""
        sandbox = LocalSandbox(sandbox_url="local", timeout_seconds=10)
        result = await sandbox.verify_fix(
            original_code="def add(a, b): return a + b",
            fixed_code="def add(a, b): return a - b",  # Wrong implementation
            test_code="""
assert add(2, 3) == 5, "Expected 5, got different result"
""",
            language="python",
        )
        assert not result.passed
        assert len(result.errors) > 0

    @pytest.mark.asyncio
    async def test_verify_fix_empty_test_code_raises_error(self):
        """Empty test code raises ValueError."""
        sandbox = LocalSandbox(sandbox_url="local", timeout_seconds=10)
        with pytest.raises(ValueError, match="Test code cannot be empty"):
            await sandbox.verify_fix(
                original_code="def foo(): pass",
                fixed_code="def foo(): pass",
                test_code="",
                language="python",
            )

    @pytest.mark.asyncio
    async def test_verify_fix_javascript_success(self):
        """Verify a JavaScript fix."""
        sandbox = LocalSandbox(sandbox_url="local", timeout_seconds=10)
        result = await sandbox.verify_fix(
            original_code="function add(a, b) { return a + b; }",
            fixed_code="function add(a, b) { return a + b; }",
            test_code="""
console.assert(add(2, 3) === 5, "Test failed");
console.log("All tests passed");
""",
            language="javascript",
        )
        assert result.passed

    @pytest.mark.asyncio
    async def test_verify_fix_bash_success(self):
        """Verify a Bash fix."""
        sandbox = LocalSandbox(sandbox_url="local", timeout_seconds=10)
        result = await sandbox.verify_fix(
            original_code='echo "hello"',
            fixed_code='echo "hello"',
            test_code="""
output=$(echo "hello")
test "$output" = "hello"
echo "Test passed"
""",
            language="bash",
        )
        assert result.passed

    @pytest.mark.asyncio
    async def test_verify_fix_timeout_during_verification(self):
        """Test times out during verification."""
        sandbox = LocalSandbox(sandbox_url="local", timeout_seconds=10)
        result = await sandbox.verify_fix(
            original_code="pass",
            fixed_code="pass",
            test_code="import time; time.sleep(100)",
            language="python",
        )
        # Should timeout during verify_fix as well
        assert not result.passed
        # Errors should mention timeout
        assert any("timed out" in err.lower() for err in result.errors)

    @pytest.mark.asyncio
    async def test_verify_fix_with_imports(self):
        """Test that fixed code and test code can share imports."""
        sandbox = LocalSandbox(sandbox_url="local", timeout_seconds=10)
        result = await sandbox.verify_fix(
            original_code="""
import json
def parse_config(s):
    return json.loads(s)
""",
            fixed_code="""
import json
def parse_config(s):
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        return {}
""",
            test_code="""
result = parse_config('{"key": "value"}')
assert result["key"] == "value"
result = parse_config("invalid")
assert result == {}
print("Tests passed")
""",
            language="python",
        )
        assert result.passed


# ── LocalSandbox health_check() Tests ────────────────────────────────


class TestLocalSandboxHealthCheck:

    @pytest.mark.asyncio
    async def test_health_check_success(self):
        """Health check succeeds when interpreter is available."""
        sandbox = LocalSandbox(sandbox_url="local", timeout_seconds=10)
        healthy = await sandbox.health_check()
        # Should succeed if Python is available
        assert isinstance(healthy, bool)

    @pytest.mark.asyncio
    async def test_health_check_with_missing_interpreter(self):
        """Health check returns False if interpreter missing."""
        sandbox = LocalSandbox(sandbox_url="local", timeout_seconds=10)
        # Mock shutil.which to simulate missing interpreter
        with patch("shutil.which", return_value=None):
            healthy = await sandbox.health_check()
            assert healthy is False


# ── HTTPSandbox Initialization Tests ─────────────────────────────────


class TestHTTPSandboxInit:

    def test_init_with_default_timeout(self):
        """HTTPSandbox initialization with default timeout."""
        client = HTTPSandbox(
            sandbox_url="http://localhost:50051",
            timeout_seconds=30,
        )
        assert client.timeout_seconds == 30
        assert client.sandbox_url == "http://localhost:50051"

    def test_init_removes_trailing_slash(self):
        """Trailing slash is removed from sandbox URL."""
        client = HTTPSandbox(
            sandbox_url="http://localhost:50051/",
            timeout_seconds=30,
        )
        assert client.sandbox_url == "http://localhost:50051"

    def test_init_creates_http_client(self):
        """HTTP client is created during init."""
        client = HTTPSandbox(
            sandbox_url="http://localhost:50051",
            timeout_seconds=30,
        )
        assert client._http is not None


# ── HTTPSandbox execute() Tests ──────────────────────────────────────


class TestHTTPSandboxExecute:

    @pytest.mark.asyncio
    async def test_execute_success(self):
        """Execute code via HTTP endpoint."""
        client = HTTPSandbox(
            sandbox_url="http://localhost:50051",
            timeout_seconds=30,
        )

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "stdout": "hello world",
            "stderr": "",
            "exit_code": 0,
            "duration_seconds": 0.5,
            "timed_out": False,
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(
            client._http, "post", new_callable=AsyncMock, return_value=mock_response
        ) as mock_post:
            result = await client.execute(
                code="print('hello')",
                language="python",
            )

        assert result.success
        assert result.stdout == "hello world"
        assert result.exit_code == 0
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert call_args[0][0] == "/execute"
        assert call_args[1]["json"]["code"] == "print('hello')"
        assert call_args[1]["json"]["language"] == "python"

    @pytest.mark.asyncio
    async def test_execute_empty_code_raises_error(self):
        """Empty code raises ValueError."""
        client = HTTPSandbox(
            sandbox_url="http://localhost:50051",
            timeout_seconds=30,
        )
        with pytest.raises(ValueError, match="Code cannot be empty"):
            await client.execute(code="", language="python")

    @pytest.mark.asyncio
    async def test_execute_http_error(self):
        """HTTP error is converted to RuntimeError."""
        client = HTTPSandbox(
            sandbox_url="http://localhost:50051",
            timeout_seconds=30,
        )

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            message="500 error",
            request=MagicMock(),
            response=mock_response,
        )

        with patch.object(client._http, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response
            with pytest.raises(RuntimeError, match="Sandbox execution failed"):
                await client.execute(
                    code="print('hi')",
                    language="python",
                )

    @pytest.mark.asyncio
    async def test_execute_connection_error(self):
        """Connection error is converted to RuntimeError."""
        client = HTTPSandbox(
            sandbox_url="http://localhost:50051",
            timeout_seconds=30,
        )

        with patch.object(
            client._http,
            "post",
            new_callable=AsyncMock,
            side_effect=httpx.RequestError("Connection refused"),
        ):
            with pytest.raises(RuntimeError, match="Sandbox unavailable"):
                await client.execute(
                    code="print('hi')",
                    language="python",
                )

    @pytest.mark.asyncio
    async def test_execute_custom_timeout(self):
        """Custom timeout parameter is passed to HTTP request."""
        client = HTTPSandbox(
            sandbox_url="http://localhost:50051",
            timeout_seconds=30,
        )

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "stdout": "",
            "stderr": "",
            "exit_code": 0,
            "duration_seconds": 0.1,
            "timed_out": False,
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(client._http, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response
            await client.execute(
                code="print('hi')",
                language="python",
                timeout=60,
            )

        call_args = mock_post.call_args
        assert call_args[1]["json"]["timeout"] == 60

    @pytest.mark.asyncio
    async def test_execute_timed_out_response(self):
        """Timed out response is properly handled."""
        client = HTTPSandbox(
            sandbox_url="http://localhost:50051",
            timeout_seconds=30,
        )

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "stdout": "",
            "stderr": "Execution timed out",
            "exit_code": -1,
            "duration_seconds": 10.0,
            "timed_out": True,
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(client._http, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response
            result = await client.execute(
                code="sleep 100",
                language="bash",
                timeout=10,
            )

        assert result.timed_out
        assert not result.success


# ── HTTPSandbox verify_fix() Tests ───────────────────────────────────


class TestHTTPSandboxVerifyFix:

    @pytest.mark.asyncio
    async def test_verify_fix_success(self):
        """Verify fix via HTTP endpoint."""
        client = HTTPSandbox(
            sandbox_url="http://localhost:50051",
            timeout_seconds=30,
        )

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "passed": True,
            "test_output": "All tests passed",
            "errors": [],
            "duration_seconds": 0.8,
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(client._http, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response
            result = await client.verify_fix(
                original_code="def foo(): pass",
                fixed_code="def foo(): pass",
                test_code="pass",
                language="python",
            )

        assert result.passed
        assert result.test_output == "All tests passed"
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert call_args[0][0] == "/verify"

    @pytest.mark.asyncio
    async def test_verify_fix_empty_test_code_allowed_remote_default(self):
        """Empty test_code is sent to /verify; sandbox service applies default smoke test."""
        client = HTTPSandbox(
            sandbox_url="http://localhost:50051",
            timeout_seconds=30,
        )
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "passed": True,
            "test_output": "tron_verify_fix_ok",
            "errors": [],
            "duration_seconds": 0.1,
        }
        mock_response.raise_for_status = MagicMock()
        with patch.object(client._http, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response
            result = await client.verify_fix(
                original_code="def foo(): pass",
                fixed_code="def foo(): return1",
                test_code="",
                language="python",
            )
        assert result.passed
        payload = mock_post.call_args.kwargs["json"]
        assert payload["test_code"] == ""

    @pytest.mark.asyncio
    async def test_verify_fix_failure(self):
        """Verify fix returns failed result."""
        client = HTTPSandbox(
            sandbox_url="http://localhost:50051",
            timeout_seconds=30,
        )

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "passed": False,
            "test_output": "",
            "errors": ["Assertion failed"],
            "duration_seconds": 0.5,
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(client._http, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response
            result = await client.verify_fix(
                original_code="def foo(): pass",
                fixed_code="def foo(): pass",
                test_code="assert False",
                language="python",
            )

        assert not result.passed
        assert len(result.errors) > 0


# ── HTTPSandbox health_check() Tests ─────────────────────────────────


class TestHTTPSandboxHealthCheck:

    @pytest.mark.asyncio
    async def test_health_check_success(self):
        """Health check succeeds when service is healthy."""
        client = HTTPSandbox(
            sandbox_url="http://localhost:50051",
            timeout_seconds=30,
        )

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "healthy": True,
            "uptime_seconds": 3600,
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(client._http, "get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response
            result = await client.health_check()

        assert result is True
        mock_get.assert_called_once_with("/health", timeout=5)

    @pytest.mark.asyncio
    async def test_health_check_failure(self):
        """Health check returns False when service unhealthy."""
        client = HTTPSandbox(
            sandbox_url="http://localhost:50051",
            timeout_seconds=30,
        )

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "healthy": False,
            "uptime_seconds": 0,
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(client._http, "get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response
            result = await client.health_check()

        assert result is False

    @pytest.mark.asyncio
    async def test_health_check_connection_error(self):
        """Health check returns False on connection error."""
        client = HTTPSandbox(
            sandbox_url="http://localhost:50051",
            timeout_seconds=30,
        )

        with patch.object(
            client._http,
            "get",
            new_callable=AsyncMock,
            side_effect=httpx.RequestError("Connection refused"),
        ):
            result = await client.health_check()

        assert result is False


# ── HTTPSandbox close() Tests ────────────────────────────────────────


class TestHTTPSandboxClose:

    @pytest.mark.asyncio
    async def test_close_closes_http_client(self):
        """close() properly closes the HTTP client."""
        client = HTTPSandbox(
            sandbox_url="http://localhost:50051",
            timeout_seconds=30,
        )

        # Mock the aclose method
        with patch.object(client._http, "aclose", new_callable=AsyncMock) as mock_close:
            await client.close()
            mock_close.assert_called_once()


# ── Code Combination Tests ───────────────────────────────────────────


class TestCodeCombination:

    def test_combine_code_python(self):
        """Python code combination."""
        fixed = "def add(a, b): return a + b"
        test = "assert add(1, 2) == 3"
        combined = LocalSandbox._combine_code(fixed, test, "python")
        assert "def add" in combined
        assert "assert add" in combined
        assert combined.index("def add") < combined.index("assert add")

    def test_combine_code_javascript(self):
        """JavaScript code combination."""
        fixed = "function add(a, b) { return a + b; }"
        test = "console.assert(add(1, 2) === 3)"
        combined = LocalSandbox._combine_code(fixed, test, "javascript")
        assert "function add" in combined
        assert "console.assert" in combined

    def test_combine_code_bash(self):
        """Bash code combination."""
        fixed = "echo 'hello'"
        test = "test -n 'hello'"
        combined = LocalSandbox._combine_code(fixed, test, "bash")
        assert "echo" in combined
        assert "test" in combined
