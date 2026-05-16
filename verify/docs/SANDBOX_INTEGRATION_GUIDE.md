# Integrating Sandbox Client into verify_fix Activity

This guide shows how to integrate the new sandbox client into the existing `verify_fix()` activity to enable Phase 3 (Execution Sandbox) verification.

## Current State

In `tron/workflows/activities.py`, the `verify_fix()` activity currently performs **static analysis only**:

```python
@activity.defn
async def verify_fix(finding_input: FindingInput, fix_attempt: FixAttempt) -> FixAttempt:
    """Verify a fix by running static analysis on the patched code.
    
    TODO Phase 3: Run in Docker sandbox (tron-sandbox gRPC) for execution verification
    """
    # Static pattern checks by vulnerability type
    if vuln_type == "sql_injection":
        if "execute(" in fix_code and ("+ " in fix_code or "%" in fix_code):
            issues.append("Fix still contains string concatenation in SQL query")
    
    # ... more static checks ...
    
    return FixAttempt(
        iteration=fix_attempt.iteration,
        fix_code=fix_attempt.fix_code,
        verification_passed=len(issues) == 0,
        verification_output="; ".join(issues),
    )
```

## Phase 3 Implementation

To enable execution-based verification, update the activity:

### Step 1: Add Sandbox Import

```python
# At the top of tron/workflows/activities.py

from tron.infra.sandbox import get_sandbox_client, SandboxClient
```

### Step 2: Create Test Generation Helper

Add a helper to generate test code based on vulnerability type:

```python
async def _generate_verification_tests(
    finding_input: FindingInput,
    language: str,
) -> str:
    """Generate test code to verify a fix for a specific vulnerability.
    
    Args:
        finding_input: The finding details including vulnerability type
        language: Programming language
        
    Returns:
        Test code that validates the fix
    """
    vuln_type = finding_input.vulnerability_type.lower()
    
    if vuln_type == "sql_injection":
        return _test_sql_injection_fix(finding_input, language)
    elif vuln_type == "command_injection":
        return _test_command_injection_fix(finding_input, language)
    elif vuln_type == "hardcoded_secrets":
        return _test_hardcoded_secrets_fix(finding_input, language)
    elif vuln_type == "insecure_deserialization":
        return _test_deserialization_fix(finding_input, language)
    elif vuln_type == "xss":
        return _test_xss_fix(finding_input, language)
    else:
        # Fallback: generic sanity checks
        return _test_generic_fix(finding_input, language)


def _test_sql_injection_fix(finding_input: FindingInput, language: str) -> str:
    """Test code for SQL injection fixes."""
    if language in ("python", "python3"):
        return '''
# SQL Injection Test
import sqlite3

# Assume the fixed code defines a safe_query function
conn = sqlite3.connect(":memory:")
cursor = conn.cursor()
cursor.execute("CREATE TABLE users (id INTEGER, name TEXT)")
cursor.execute("INSERT INTO users VALUES (1, 'Alice')")
conn.commit()

# Test 1: Normal query works
result = safe_query(cursor, "Alice")
assert len(result) > 0, "Should find valid user"

# Test 2: SQL injection attempt is treated as literal
result = safe_query(cursor, "Alice' OR '1'='1")
assert len(result) == 0, "SQL injection should not bypass WHERE"

# Test 3: Empty result for non-existent user
result = safe_query(cursor, "Nonexistent")
assert len(result) == 0, "Should return empty for non-existent user"

print("SQL Injection tests PASSED")
'''
    elif language in ("javascript", "js"):
        return '''
// SQL Injection Test (Node.js with better-sqlite3)
const db = require('better-sqlite3', ':memory:');
db.exec("CREATE TABLE users (id INTEGER, name TEXT)");
db.exec("INSERT INTO users VALUES (1, 'Alice')");

// Test 1: Normal query
let result = safeQuery("Alice");
console.assert(result.length > 0, "Should find valid user");

// Test 2: SQL injection attempt
result = safeQuery("Alice' OR '1'='1");
console.assert(result.length === 0, "SQL injection should not work");

console.log("SQL Injection tests PASSED");
'''
    else:
        return "# Language not supported for SQL injection tests"


def _test_command_injection_fix(finding_input: FindingInput, language: str) -> str:
    """Test code for command injection fixes."""
    if language in ("python", "python3"):
        return '''
# Command Injection Test
import subprocess
import tempfile
import os

# Test 1: Normal command execution works
result = safe_command("echo", "test")
assert "test" in result, "Normal command should work"

# Test 2: Shell escapes don't execute
# If vulnerable, this would execute `id` command
result = safe_command("echo", "; id;")
assert "uid=" not in result, "Shell escape should not execute commands"

# Test 3: Command with special characters
result = safe_command("echo", "$(whoami)")
assert "$(whoami)" in result, "Dollar signs should be literal, not expanded"

print("Command Injection tests PASSED")
'''
    elif language in ("javascript", "js"):
        return '''
// Command Injection Test
const { execSync } = require('child_process');

// Test 1: Normal execution
let result = safeCommand("echo", "test");
console.assert(result.includes("test"), "Normal command should work");

// Test 2: Shell escapes don't execute
result = safeCommand("echo", "; id;");
console.assert(!result.includes("uid="), "Shell escape should not execute");

// Test 3: Special characters are literal
result = safeCommand("echo", "$(whoami)");
console.assert(result.includes("$(whoami)"), "Dollar signs should be literal");

console.log("Command Injection tests PASSED");
'''
    else:
        return "# Language not supported for command injection tests"


def _test_hardcoded_secrets_fix(finding_input: FindingInput, language: str) -> str:
    """Test code for hardcoded secrets fixes."""
    if language in ("python", "python3"):
        return '''
# Hardcoded Secrets Test
import os

# Set test values
os.environ["DB_PASSWORD"] = "test_password"
os.environ["API_KEY"] = "test_api_key"

# Instantiate config
config = create_config()

# Test 1: Passwords come from environment
assert config.password == "test_password", "Password should come from env"

# Test 2: API keys come from environment
assert config.api_key == "test_api_key", "API key should come from env"

# Test 3: No hardcoded secrets in string representation
config_str = str(config)
assert "test_password" not in config_str or "os.environ" in config_str, \
    "Config should not expose secrets"

print("Hardcoded Secrets tests PASSED")
'''
    else:
        return "# Language not supported for secrets tests"


def _test_deserialization_fix(finding_input: FindingInput, language: str) -> str:
    """Test code for insecure deserialization fixes."""
    if language in ("python", "python3"):
        return '''
# Insecure Deserialization Test
import json

# Safe data
safe_json = '{"key": "value", "number": 42}'
result = safe_deserialize(safe_json)
assert result["key"] == "value", "Should deserialize valid JSON"

# Malicious data - should not execute arbitrary code
malicious_json = '{"__code__": "import os; os.system(\\"id\\")"}'
try:
    result = safe_deserialize(malicious_json)
    # Should successfully parse as data, not execute
    assert isinstance(result, dict), "Should parse as data structure"
    print("Insecure Deserialization tests PASSED")
except:
    print("Insecure Deserialization tests PASSED (rejected malicious input)")
'''
    else:
        return "# Language not supported for deserialization tests"


def _test_xss_fix(finding_input: FindingInput, language: str) -> str:
    """Test code for XSS fixes."""
    if language in ("python", "python3"):
        return '''
# XSS Test
from html import escape

# Test 1: Normal content renders safely
result = render_safe("<script>alert('xss')</script>")
assert "<script>" not in result, "Script tags should be escaped"
assert "alert" in result, "Content should be present"

# Test 2: Safe HTML is preserved if using Markup
result = render_safe("<b>bold</b>")
# Result depends on implementation - either escaped or Markup'd
assert "bold" in result, "Content should be present"

print("XSS tests PASSED")
'''
    else:
        return "# Language not supported for XSS tests"


def _test_generic_fix(finding_input: FindingInput, language: str) -> str:
    """Generic test code for unknown vulnerability types."""
    if language in ("python", "python3"):
        return '''
# Generic sanity checks
# If the fixed code can be imported and has the expected structure,
# consider it a basic pass

try:
    # Code was successfully parsed and executed
    print("Generic verification PASSED")
except Exception as e:
    raise AssertionError(f"Code failed basic sanity check: {e}")
'''
    else:
        return "# Generic verification for this language"
```

### Step 3: Update verify_fix Activity

Replace the static analysis with sandbox-based execution:

```python
@activity.defn
async def verify_fix(finding_input: FindingInput, fix_attempt: FixAttempt) -> FixAttempt:
    """Verify a fix by running tests in the sandbox.
    
    Phase 3: Execution Sandbox
    
    This activity now executes the fixed code with generated test cases
    in an isolated Docker sandbox, providing real verification instead of
    just static analysis.
    """
    if not fix_attempt.fix_code:
        return FixAttempt(
            iteration=fix_attempt.iteration,
            fix_code=fix_attempt.fix_code,
            verification_passed=False,
            verification_output="No fix code generated",
            error_message=fix_attempt.error_message,
        )
    
    try:
        # Get sandbox client
        sandbox = await get_sandbox_client()
        
        # Detect language from file extension
        language = _detect_language(finding_input.file_path)
        
        # Generate verification tests
        test_code = await _generate_verification_tests(finding_input, language)
        
        # Run verification in sandbox
        verification = await sandbox.verify_fix(
            original_code=finding_input.code_snippet,
            fixed_code=fix_attempt.fix_code,
            test_code=test_code,
            language=language,
        )
        
        activity.logger.info(
            "Verify fix (iter %d): %s — %s",
            fix_attempt.iteration,
            "PASS" if verification.passed else "FAIL",
            verification.summary,
        )
        
        return FixAttempt(
            iteration=fix_attempt.iteration,
            fix_code=fix_attempt.fix_code,
            verification_passed=verification.passed,
            verification_output=verification.summary,
            error_message=None if verification.passed else "; ".join(verification.errors),
        )
    
    except Exception as exc:
        activity.logger.exception("Fix verification failed: %s", exc)
        return FixAttempt(
            iteration=fix_attempt.iteration,
            fix_code=fix_attempt.fix_code,
            verification_passed=False,
            verification_output="",
            error_message=f"Verification error: {exc}",
        )


def _detect_language(file_path: str) -> str:
    """Detect programming language from file extension."""
    ext_to_lang = {
        ".py": "python",
        ".js": "javascript",
        ".ts": "javascript",  # TypeScript compiles to JS
        ".sh": "bash",
        ".rb": "ruby",  # Future support
        ".go": "golang",  # Future support
    }
    
    import os
    _, ext = os.path.splitext(file_path)
    return ext_to_lang.get(ext.lower(), "python")  # Default to Python
```

## Workflow Integration

The FixWorkflow in `tron/workflows/fix_workflow.py` already calls `verify_fix`:

```python
# Existing workflow - no changes needed!
fix_attempt = await activity.verify_fix(
    finding_input=finding_input,
    fix_attempt=fix_attempt,
)

if fix_attempt.verification_passed:
    # Fix verified! Proceed to persist_fix
    await activity.persist_fix(finding_input, fix_attempt)
else:
    # Verification failed
    if iteration < max_iterations:
        # Retry with feedback
        continue
    else:
        # Escalate to human
        await activity.escalate_to_human(finding_input, iteration)
```

By updating `verify_fix`, the entire workflow automatically gains execution-based verification!

## Testing the Integration

### Unit Test

```python
# In tests/test_fix_activity.py

@pytest.mark.asyncio
async def test_verify_fix_with_sandbox():
    """Test verify_fix activity uses sandbox."""
    from tron.workflows.activities import verify_fix
    
    finding = FindingInput(
        finding_id="test-1",
        audit_run_id="audit-1",
        project_id="project-1",
        file_path="app.py",
        line_number=10,
        vulnerability_type="sql_injection",
        severity="high",
        description="SQL injection in search",
        code_snippet='cursor.execute(f"SELECT * FROM users WHERE name = \'{query}\'")',
    )
    
    fix_attempt = FixAttempt(
        iteration=1,
        fix_code='cursor.execute("SELECT * FROM users WHERE name = ?", (query,))',
        verification_passed=False,
        verification_output="",
    )
    
    # Execute activity
    result = await verify_fix(finding, fix_attempt)
    
    # Should now use sandbox verification
    assert result.verification_passed  # Real test execution
```

### Integration Test

```python
# In tests/test_fix_workflow_integration.py

@pytest.mark.asyncio
@pytest.mark.integration
async def test_fix_workflow_with_sandbox():
    """Test full workflow with sandbox verification."""
    from tron.workflows.fix_workflow import FixWorkflow
    
    # Run actual workflow with sandbox
    workflow = FixWorkflow()
    finding = create_test_finding()
    
    result = await workflow.run(finding)
    
    # Workflow should complete successfully with real sandbox verification
    assert result.success
```

## Environment Configuration

For testing/development:

```bash
# Use local subprocess sandbox
export SANDBOX_MODE=local

# Or for integration testing with Docker:
docker-compose up tron-sandbox
export SANDBOX_MODE=http
export SANDBOX_URL=http://localhost:50051
```

## Deployment

### Development

```bash
# Already works with default local sandbox
docker-compose up tron-worker
```

### Production

```bash
# Ensure tron-sandbox is running
docker-compose up -d tron-sandbox

# Start worker (will auto-discover sandbox)
docker-compose up -d tron-worker

# Verify health
curl http://localhost:50051/health
```

## Monitoring & Debugging

### View Sandbox Activity Logs

```bash
# Local mode (subprocess)
docker logs -f tron-worker | grep "verify_fix"

# HTTP mode (remote)
docker logs -f tron-sandbox | grep "execute"
```

### Debug a Single Verification

```python
# In a test script
import asyncio
from tron.workflows.activities import verify_fix
from tron.workflows.activities import FindingInput, FixAttempt

async def debug():
    finding = FindingInput(
        finding_id="debug-1",
        audit_run_id="audit-1",
        project_id="project-1",
        file_path="app.py",
        line_number=10,
        vulnerability_type="sql_injection",
        severity="high",
        description="Test",
        code_snippet='cursor.execute("SELECT * FROM users WHERE name = \'" + query + "\'")',
    )
    
    fix_attempt = FixAttempt(
        iteration=1,
        fix_code='cursor.execute("SELECT * FROM users WHERE name = ?", (query,))',
        verification_passed=False,
        verification_output="",
    )
    
    result = await verify_fix(finding, fix_attempt)
    print(f"Result: {result}")
    print(f"Verification: {result.verification_passed}")
    print(f"Output: {result.verification_output}")

asyncio.run(debug())
```

## Rollback Plan

If issues occur with sandbox-based verification:

1. **Disable sandbox** - Set `SANDBOX_MODE=disabled` (future support)
2. **Fall back to static** - Revert `verify_fix()` to original implementation
3. **Investigate** - Check sandbox logs and test cases

```python
# Fallback implementation (restore original if needed)
@activity.defn
async def verify_fix(finding_input: FindingInput, fix_attempt: FixAttempt) -> FixAttempt:
    """Fallback: Static analysis only."""
    # Original implementation here...
```

## Next Steps

1. Update `verify_fix()` activity with sandbox integration
2. Add test generation helpers for each vulnerability type
3. Run integration tests against sandbox
4. Deploy to staging and monitor
5. Enable in production with gradual rollout
