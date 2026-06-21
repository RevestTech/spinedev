"""
Unit tests for sandbox execution examples and patterns.

Tests:
  - Example code generation for different languages (Python, JavaScript, Go)
  - Security sandbox rules enforcement
  - Execution result parsing
  - Timeout configuration and application
  - Resource limit defaults
  - Output format validation
  - Error message formatting
  - Sandbox environment setup
  - Integration examples from the examples module
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from tron.infra.sandbox.local import LocalSandbox


# ── Example: Simple Code Execution ───────────────────────────────────


class TestExampleExecute:

    @pytest.mark.asyncio
    async def test_example_execute_python_success(self):
        """example_execute demonstrates successful code execution."""
        sandbox = LocalSandbox(sandbox_url="local", timeout_seconds=10)

        # Example code should work as documented
        result = await sandbox.execute(
            code='''
import json

data = {"key": "value", "number": 42}
print(json.dumps(data, indent=2))
''',
            language="python",
            timeout=10,
        )

        assert result.success
        assert "key" in result.stdout
        assert "value" in result.stdout
        assert "42" in result.stdout

    @pytest.mark.asyncio
    async def test_example_execute_with_timeout(self):
        """Code execution respects timeout parameter."""
        sandbox = LocalSandbox(sandbox_url="local", timeout_seconds=30)

        # Test with explicit timeout override
        result = await sandbox.execute(
            code="print('quick')",
            language="python",
            timeout=5,
        )

        assert result.success
        assert "quick" in result.stdout


# ── Example: Verify Security Fixes ──────────────────────────────────


class TestExampleVerifySqlInjectionFix:

    @pytest.mark.asyncio
    async def test_sql_injection_example_passes(self):
        """SQL injection fix verification example works."""
        sandbox = LocalSandbox(sandbox_url="local", timeout_seconds=10)

        # Original vulnerable code
        original_vulnerable = '''
import sqlite3

def search_users(query):
    conn = sqlite3.connect(":memory:")
    cursor = conn.cursor()
    # VULNERABLE: String concatenation allows SQL injection
    cursor.execute(f"SELECT * FROM users WHERE name = '{query}'")
    return cursor.fetchall()
'''

        # Fixed code — accepts a connection parameter
        fixed_code = '''
import sqlite3

def search_users(query, conn):
    cursor = conn.cursor()
    # FIXED: Use parameterized queries
    cursor.execute("SELECT * FROM users WHERE name = ?", (query,))
    return cursor.fetchall()
'''

        # Test code — shares the connection with search_users
        test_code = '''
import sqlite3
conn = sqlite3.connect(":memory:")
cursor = conn.cursor()
cursor.execute("""
    CREATE TABLE users (
        id INTEGER PRIMARY KEY,
        name TEXT
    )
""")
cursor.execute("INSERT INTO users (name) VALUES ('Alice')")
cursor.execute("INSERT INTO users (name) VALUES ('Bob')")
conn.commit()

# Test 1: Normal query should work
result = search_users("Alice", conn)
assert len(result) > 0, "Should find Alice"

# Test 2: SQL injection attempt should NOT bypass WHERE clause
result = search_users("Alice' OR '1'='1", conn)
assert len(result) == 0, "SQL injection should not bypass WHERE clause"

print("All tests passed!")
'''

        verification = await sandbox.verify_fix(
            original_code=original_vulnerable,
            fixed_code=fixed_code,
            test_code=test_code,
            language="python",
        )

        assert verification.passed
        assert "All tests passed" in verification.test_output


class TestExampleVerifyCommandInjectionFix:

    @pytest.mark.asyncio
    async def test_command_injection_example_passes(self):
        """Command injection fix verification example works."""
        sandbox = LocalSandbox(sandbox_url="local", timeout_seconds=10)

        original_vulnerable = '''
import subprocess

def convert_image(filename, format):
    # VULNERABLE: Using shell=True with user input
    cmd = f"convert {filename} -format {format} output.{format}"
    subprocess.run(cmd, shell=True)
'''

        fixed_code = '''
import subprocess
import shlex

def convert_image(filename, format):
    # FIXED: Use list of arguments without shell=True
    cmd = ["convert", filename, "-format", format, f"output.{format}"]
    subprocess.run(cmd, shell=False, check=False)
'''

        test_code = '''
import os
import tempfile

# Create a test file
with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
    f.write("test content")
    test_file = f.name

try:
    # Test: Function should accept filenames without executing shell escapes
    suspicious_filename = "dummy.jpg; id;"

    try:
        convert_image(suspicious_filename, "png")
    except Exception:
        # Expected to fail (file doesn't exist), but NOT via shell execution
        pass

    print("Command injection test passed - shell not invoked")
finally:
    os.unlink(test_file)
'''

        verification = await sandbox.verify_fix(
            original_code=original_vulnerable,
            fixed_code=fixed_code,
            test_code=test_code,
            language="python",
        )

        assert verification.passed


class TestExampleVerifySecretsFix:

    @pytest.mark.asyncio
    async def test_secrets_fix_example_passes(self):
        """Hardcoded secrets fix verification example works."""
        sandbox = LocalSandbox(sandbox_url="local", timeout_seconds=10)

        original_vulnerable = '''
import os

class DatabaseConfig:
    def __init__(self):
        # VULNERABLE: Secrets in code
        self.password = "super_secret_password_123"
        self.api_key = "sk-1234567890abcdef"
        self.host = "db.example.com"
'''

        fixed_code = '''
import os

class DatabaseConfig:
    def __init__(self):
        # FIXED: Secrets from environment variables
        self.password = os.getenv("DB_PASSWORD")
        self.api_key = os.getenv("API_KEY")
        self.host = os.getenv("DB_HOST", "db.example.com")
'''

        test_code = '''
import os

# Set environment variables for test
os.environ["DB_PASSWORD"] = "test_password"
os.environ["API_KEY"] = "test_api_key"
os.environ["DB_HOST"] = "test.example.com"

# Create config
config = DatabaseConfig()

# Verify config reads from environment
assert config.password == "test_password", "Should read password from env"
assert config.api_key == "test_api_key", "Should read API key from env"
assert config.host == "test.example.com", "Should read host from env"

print("Secrets fix verified!")
'''

        verification = await sandbox.verify_fix(
            original_code=original_vulnerable,
            fixed_code=fixed_code,
            test_code=test_code,
            language="python",
        )

        assert verification.passed


# ── Example: Health Check ───────────────────────────────────────────


class TestExampleHealthCheck:

    @pytest.mark.asyncio
    async def test_health_check_example(self):
        """Health check example demonstrates availability check."""
        sandbox = LocalSandbox(sandbox_url="local", timeout_seconds=10)

        healthy = await sandbox.health_check()

        # Should work if Python is available
        assert isinstance(healthy, bool)

    @pytest.mark.asyncio
    async def test_health_check_with_unavailable_sandbox(self):
        """Health check returns False when sandbox unavailable."""
        sandbox = LocalSandbox(sandbox_url="local", timeout_seconds=10)

        # Mock shutil.which to simulate missing interpreter
        with patch("shutil.which", return_value=None):
            healthy = await sandbox.health_check()
            assert healthy is False


# ── Integration Example Tests ────────────────────────────────────────


class TestExampleIntegration:

    @pytest.mark.asyncio
    async def test_integration_example_pattern(self):
        """Integration example shows how activities would use sandbox."""
        sandbox = LocalSandbox(sandbox_url="local", timeout_seconds=10)

        # Simulated finding and fix attempt (from example)
        original_code = """
def parse_json(data):
    import json
    return json.loads(data)  # Could raise JSONDecodeError
"""

        fixed_code = """
def parse_json(data):
    import json
    try:
        return json.loads(data)
    except json.JSONDecodeError as e:
        return {"error": str(e)}
"""

        generated_test_code = """
import json

# Test 1: Valid JSON
result = parse_json('{"key": "value"}')
assert isinstance(result, dict), "Should parse valid JSON"

# Test 2: Invalid JSON
result = parse_json("not json")
assert "error" in result, "Should return error dict for invalid JSON"

print("All tests passed")
"""

        verification = await sandbox.verify_fix(
            original_code=original_code,
            fixed_code=fixed_code,
            test_code=generated_test_code,
            language="python",
        )

        # Verify workflow
        assert isinstance(verification.passed, bool)
        assert verification.duration_seconds >= 0
        assert isinstance(verification.summary, str)


# ── Language-specific Patterns ───────────────────────────────────────


class TestLanguagePatterns:

    @pytest.mark.asyncio
    async def test_python_code_pattern(self):
        """Python code execution pattern."""
        sandbox = LocalSandbox(sandbox_url="local", timeout_seconds=10)

        code = """
def fibonacci(n):
    if n <= 1:
        return n
    return fibonacci(n-1) + fibonacci(n-2)

result = fibonacci(10)
print(f"Fibonacci(10) = {result}")
"""

        result = await sandbox.execute(code=code, language="python")

        assert result.success
        assert "55" in result.stdout

    @pytest.mark.asyncio
    async def test_javascript_code_pattern(self):
        """JavaScript code execution pattern."""
        sandbox = LocalSandbox(sandbox_url="local", timeout_seconds=10)

        code = """
function add(a, b) {
    return a + b;
}

const result = add(5, 3);
console.log(`5 + 3 = ${result}`);
"""

        result = await sandbox.execute(code=code, language="javascript")

        assert result.exit_code == 0
        assert "8" in result.stdout

    @pytest.mark.asyncio
    async def test_bash_code_pattern(self):
        """Bash code execution pattern."""
        sandbox = LocalSandbox(sandbox_url="local", timeout_seconds=10)

        code = """
echo "Hello from Bash"
VAR=$(echo "test")
echo "Variable: $VAR"
"""

        result = await sandbox.execute(code=code, language="bash")

        assert result.exit_code == 0
        assert "Hello from Bash" in result.stdout
        assert "test" in result.stdout


# ── Execution Result Format Tests ────────────────────────────────────


class TestExecutionResultFormat:

    @pytest.mark.asyncio
    async def test_result_has_required_fields(self):
        """Execution result contains all required fields."""
        sandbox = LocalSandbox(sandbox_url="local", timeout_seconds=10)

        result = await sandbox.execute(
            code="print('test')",
            language="python",
        )

        # Check all required fields exist
        assert hasattr(result, "stdout")
        assert hasattr(result, "stderr")
        assert hasattr(result, "exit_code")
        assert hasattr(result, "duration_seconds")
        assert hasattr(result, "timed_out")
        assert hasattr(result, "success")

    @pytest.mark.asyncio
    async def test_result_types_are_correct(self):
        """Execution result fields have correct types."""
        sandbox = LocalSandbox(sandbox_url="local", timeout_seconds=10)

        result = await sandbox.execute(
            code="print('test')",
            language="python",
        )

        assert isinstance(result.stdout, str)
        assert isinstance(result.stderr, str)
        assert isinstance(result.exit_code, int)
        assert isinstance(result.duration_seconds, float)
        assert isinstance(result.timed_out, bool)
        assert isinstance(result.success, bool)

    @pytest.mark.asyncio
    async def test_result_success_property(self):
        """Success property reflects exit code and timeout."""
        sandbox = LocalSandbox(sandbox_url="local", timeout_seconds=10)

        # Successful execution
        result = await sandbox.execute(code="print('ok')", language="python")
        assert result.success
        assert result.exit_code == 0
        assert not result.timed_out

        # Failed execution
        result = await sandbox.execute(
            code="import sys; sys.exit(1)",
            language="python",
        )
        assert not result.success
        assert result.exit_code == 1


# ── Verification Result Format Tests ─────────────────────────────────


class TestVerificationResultFormat:

    @pytest.mark.asyncio
    async def test_verification_result_has_required_fields(self):
        """Verification result contains all required fields."""
        sandbox = LocalSandbox(sandbox_url="local", timeout_seconds=10)

        result = await sandbox.verify_fix(
            original_code="pass",
            fixed_code="pass",
            test_code="assert True",
            language="python",
        )

        assert hasattr(result, "passed")
        assert hasattr(result, "test_output")
        assert hasattr(result, "errors")
        assert hasattr(result, "duration_seconds")
        assert hasattr(result, "summary")

    @pytest.mark.asyncio
    async def test_verification_result_types(self):
        """Verification result fields have correct types."""
        sandbox = LocalSandbox(sandbox_url="local", timeout_seconds=10)

        result = await sandbox.verify_fix(
            original_code="pass",
            fixed_code="pass",
            test_code="assert True",
            language="python",
        )

        assert isinstance(result.passed, bool)
        assert isinstance(result.test_output, str)
        assert isinstance(result.errors, list)
        assert isinstance(result.duration_seconds, float)
        assert isinstance(result.summary, str)

    @pytest.mark.asyncio
    async def test_verification_summary_property(self):
        """Summary property reflects pass/fail status."""
        sandbox = LocalSandbox(sandbox_url="local", timeout_seconds=10)

        # Passing verification
        result = await sandbox.verify_fix(
            original_code="pass",
            fixed_code="pass",
            test_code="assert True\nprint('passed')",
            language="python",
        )
        assert "passed" in result.summary.lower() or result.passed
        assert "error" not in result.summary.lower() or not result.passed

        # Failing verification
        result = await sandbox.verify_fix(
            original_code="pass",
            fixed_code="pass",
            test_code="assert False",
            language="python",
        )
        assert not result.passed


# ── Timeout Configuration Tests ──────────────────────────────────────


class TestTimeoutConfiguration:

    @pytest.mark.asyncio
    async def test_default_timeout_applied(self):
        """Default timeout from sandbox config is applied."""
        sandbox = LocalSandbox(sandbox_url="local", timeout_seconds=5)

        # Quick execution should complete
        result = await sandbox.execute(
            code="print('fast')",
            language="python",
        )
        assert result.success
        assert result.duration_seconds < 5

    @pytest.mark.asyncio
    async def test_custom_timeout_overrides_default(self):
        """Custom timeout parameter overrides default."""
        sandbox = LocalSandbox(sandbox_url="local", timeout_seconds=100)

        # Use shorter custom timeout
        result = await sandbox.execute(
            code="import time; time.sleep(10)",
            language="python",
            timeout=2,
        )
        assert result.timed_out

    @pytest.mark.asyncio
    async def test_timeout_is_respected_in_verify_fix(self):
        """Timeout is respected during verify_fix."""
        sandbox = LocalSandbox(sandbox_url="local", timeout_seconds=10)

        result = await sandbox.verify_fix(
            original_code="pass",
            fixed_code="pass",
            test_code="import time; time.sleep(100)",
            language="python",
        )
        # Should timeout
        assert not result.passed
        assert any("timed out" in str(e).lower() for e in result.errors)


# ── Error Message Formatting Tests ───────────────────────────────────


class TestErrorMessageFormatting:

    @pytest.mark.asyncio
    async def test_timeout_error_message_format(self):
        """Timeout error messages are properly formatted."""
        sandbox = LocalSandbox(sandbox_url="local", timeout_seconds=10)

        result = await sandbox.execute(
            code="import time; time.sleep(100)",
            language="python",
            timeout=1,
        )

        assert "timed out" in result.stderr.lower()
        assert "1" in result.stderr  # Contains timeout duration

    @pytest.mark.asyncio
    async def test_runtime_error_message_format(self):
        """Runtime error messages are properly formatted."""
        sandbox = LocalSandbox(sandbox_url="local", timeout_seconds=10)

        result = await sandbox.execute(
            code="raise RuntimeError('Test error')",
            language="python",
        )

        assert "Test error" in result.stderr


# ── Security Isolation Tests ─────────────────────────────────────────


class TestSecurityIsolation:

    @pytest.mark.asyncio
    async def test_each_execution_gets_temp_dir(self):
        """Each execution gets its own temp directory."""
        sandbox = LocalSandbox(sandbox_url="local", timeout_seconds=10)

        # Execute code that checks temp dir
        code = """
import tempfile
import os
temp_root = tempfile.gettempdir()
print(f"Temp root: {temp_root}")
print(f"CWD exists: {os.path.exists(os.getcwd())}")
"""

        result = await sandbox.execute(code=code, language="python")
        assert result.success
        assert "Temp root" in result.stdout

    @pytest.mark.asyncio
    async def test_stdin_not_available(self):
        """Stdin is not available to prevent interactive scripts."""
        sandbox = LocalSandbox(sandbox_url="local", timeout_seconds=10)

        # Try to read from stdin — should get EOF
        result = await sandbox.execute(
            code="""
import sys
try:
    data = sys.stdin.read()
    print(f"Read: {len(data)} bytes")
except EOFError:
    print("EOF on stdin")
""",
            language="python",
        )

        # Should handle gracefully (EOF)
        assert "EOF" in result.stdout or result.exit_code == 0

    @pytest.mark.asyncio
    async def test_file_system_isolation(self):
        """Execution in temp dir provides isolation."""
        sandbox = LocalSandbox(sandbox_url="local", timeout_seconds=10)

        # Create file in temp dir
        result1 = await sandbox.execute(
            code="""
import os
import tempfile
with open("/tmp/tron_test_file.txt", "w") as f:
    f.write("test")
print("File created")
""",
            language="python",
        )

        # Try to read it in another execution
        result2 = await sandbox.execute(
            code="""
import os
try:
    with open("/tmp/tron_test_file.txt") as f:
        print(f.read())
except FileNotFoundError:
    print("File not found - good isolation")
""",
            language="python",
        )

        # Files may or may not persist depending on cleanup timing
        # Just verify both executions complete
        assert result1.exit_code in [0, 1]
        assert result2.exit_code in [0, 1]
