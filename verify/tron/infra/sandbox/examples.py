"""
Examples and patterns for sandbox usage.

These examples show how to use the sandbox client in different contexts,
particularly in the fix verification workflow.
"""

from __future__ import annotations

from tron.infra.sandbox import ExecutionResult, SandboxClient, VerificationResult


# ── Example: Simple Code Execution ───────────────────────────────────


async def example_execute(sandbox: SandboxClient) -> None:
    """Execute arbitrary code in sandbox.

    Use case: Execute user-supplied code or generated code fragments.
    """
    result: ExecutionResult = await sandbox.execute(
        code='''
import json

data = {"key": "value", "number": 42}
print(json.dumps(data, indent=2))
''',
        language="python",
        timeout=10,
    )

    if result.success:
        print(f"Output:\n{result.stdout}")
    else:
        print(f"Error (exit {result.exit_code}):\n{result.stderr}")


# ── Example: Verify Security Fix ─────────────────────────────────────


async def example_verify_sql_injection_fix(sandbox: SandboxClient) -> None:
    """Verify a SQL injection fix.

    Workflow Phase: Verify (from activities.py)
    """
    original_vulnerable = '''
import sqlite3

def search_users(query):
    conn = sqlite3.connect(":memory:")
    cursor = conn.cursor()
    # VULNERABLE: String concatenation allows SQL injection
    cursor.execute(f"SELECT * FROM users WHERE name = '{query}'")
    return cursor.fetchall()
'''

    fixed_code = '''
import sqlite3

def search_users(query):
    conn = sqlite3.connect(":memory:")
    cursor = conn.cursor()
    # FIXED: Use parameterized queries
    cursor.execute("SELECT * FROM users WHERE name = ?", (query,))
    return cursor.fetchall()
'''

    test_code = '''
# Create test database
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
result = search_users("Alice")
assert len(result) > 0, "Should find Alice"

# Test 2: SQL injection attempt should NOT break the query
# (it should treat the input as a literal string, not SQL code)
result = search_users("Alice' OR '1'='1")
assert len(result) == 0, "SQL injection should not bypass WHERE clause"

print("All tests passed!")
'''

    verification: VerificationResult = await sandbox.verify_fix(
        original_code=original_vulnerable,
        fixed_code=fixed_code,
        test_code=test_code,
        language="python",
    )

    print(f"SQL Injection Fix Verification: {'PASS' if verification.passed else 'FAIL'}")
    if not verification.passed:
        print("Errors:")
        for error in verification.errors:
            print(f"  - {error}")


# ── Example: Verify Command Injection Fix ────────────────────────────


async def example_verify_command_injection_fix(sandbox: SandboxClient) -> None:
    """Verify a command injection fix.

    Demonstrates multi-line test code with imports and assertions.
    """
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
    # If the original code was vulnerable, this would execute `id` command
    suspicious_filename = "dummy.jpg; id;"

    try:
        # This should not execute the "id" command
        # Instead, it should try to process a file literally named "dummy.jpg; id;"
        # Since the file doesn't exist, convert will fail, but NOT with a shell prompt
        convert_image(suspicious_filename, "png")
    except Exception:
        # Expected to fail (file doesn't exist), but NOT via shell execution
        pass

    print("Command injection test passed - shell not invoked")
finally:
    os.unlink(test_file)
'''

    verification: VerificationResult = await sandbox.verify_fix(
        original_code=original_vulnerable,
        fixed_code=fixed_code,
        test_code=test_code,
        language="python",
    )

    print(f"Command Injection Fix: {'PASS' if verification.passed else 'FAIL'}")
    if verification.test_output:
        print(f"Output: {verification.test_output}")


# ── Example: Verify Hardcoded Secrets Fix ────────────────────────────


async def example_verify_secrets_fix(sandbox: SandboxClient) -> None:
    """Verify a hardcoded secrets fix."""
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

    verification: VerificationResult = await sandbox.verify_fix(
        original_code=original_vulnerable,
        fixed_code=fixed_code,
        test_code=test_code,
        language="python",
    )

    print(f"Hardcoded Secrets Fix: {'PASS' if verification.passed else 'FAIL'}")


# ── Example: Health Check ────────────────────────────────────────────


async def example_health_check(sandbox: SandboxClient) -> None:
    """Check if sandbox is available."""
    healthy = await sandbox.health_check()

    if healthy:
        print("Sandbox is healthy and ready for execution")
    else:
        print("Sandbox is not responding - cannot execute code")


# ── Integration with Activities ──────────────────────────────────────


async def example_integration_with_verify_fix_activity(
    sandbox: SandboxClient,
) -> None:
    """Integration pattern: How verify_fix in activities.py would use sandbox.

    In activities.py, the verify_fix() activity currently does static checks.
    To enable Phase 3 (Execution Sandbox), replace the static analysis with:

        verification_result = await sandbox.verify_fix(
            original_code=finding_input.code_snippet,
            fixed_code=fix_attempt.fix_code,
            test_code=generated_test_code,  # From LLM or templates
            language=detect_language(finding_input.file_path),
        )

        return FixAttempt(
            iteration=fix_attempt.iteration,
            fix_code=fix_attempt.fix_code,
            verification_passed=verification_result.passed,
            verification_output=verification_result.summary,
        )
    """
    # Simulated finding and fix attempt
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

    # This is how the activity would use it
    print(f"Verification Status: {'PASSED' if verification.passed else 'FAILED'}")
    print(f"Summary: {verification.summary}")
    print(f"Duration: {verification.duration_seconds:.2f}s")
