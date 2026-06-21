# Sandbox Client Implementation

## Overview

The Tron sandbox client provides a secure, isolated execution environment for code verification. It enables Phase 3 (Execution Sandbox) of the AI Agent Architecture by allowing code fixes to be tested in isolation before approval.

### Features

- **Async/await interface** - Non-blocking code execution
- **Multiple language support** - Python, JavaScript, Bash
- **Strict timeout enforcement** - 30s default, configurable per execution
- **Resource isolation** - Temporary filesystem per execution
- **Error handling** - Comprehensive error capture and reporting
- **Health checking** - Verify sandbox availability before use
- **Development & Production modes** - Local subprocess for dev, HTTP/gRPC for production

## Architecture

```
┌─────────────────┐
│  Temporal       │
│  Activity       │
│  (verify_fix)   │
└────────┬────────┘
         │
         ▼
┌─────────────────────────┐
│  get_sandbox_client()   │  Factory function
└────────┬────────────────┘
         │
    ┌────┴─────┐
    │           │
    ▼           ▼
┌───────────┐  ┌──────────────┐
│  Local    │  │  HTTP Client │
│  Sandbox  │  │  (Remote     │
│ (Python   │  │   gRPC)      │
│subprocess)│  │              │
└───────────┘  └──────────────┘
    │               │
    └───────┬───────┘
            │
     ┌──────▼──────┐
     │  Isolated   │
     │  Execution  │
     │  Environment│
     └─────────────┘
```

## Components

### 1. `client.py` - Abstract Interface

Defines the contract for all sandbox implementations:

```python
class SandboxClient(ABC):
    async def execute(code, language, timeout) -> ExecutionResult
    async def verify_fix(original_code, fixed_code, test_code, language) -> VerificationResult
    async def health_check() -> bool
```

**ExecutionResult**: Captures stdout, stderr, exit code, duration, timeout status

**VerificationResult**: Indicates test pass/fail, includes output and error details

### 2. `local.py` - Local Subprocess Implementation

For development and testing. Executes code via `asyncio.create_subprocess_exec`:

- Creates isolated temp directory per execution
- Enforces strict timeout with `asyncio.wait_for()`
- Captures and truncates output (max 1MB)
- Automatic cleanup of temp files
- Supports Python, JavaScript, Bash

```python
sandbox = LocalSandbox(sandbox_url="local://", timeout_seconds=30)
result = await sandbox.execute("print('hello')", "python")
```

### 3. `http.py` - Remote HTTP Client

For production deployment. Communicates with remote sandbox service:

```python
sandbox = HTTPSandbox(sandbox_url="http://tron-sandbox:50051")
result = await sandbox.execute("print('hello')", "python")
```

Expected API endpoints on remote service:

- `POST /execute` - Execute code
- `POST /verify` - Verify fix with tests
- `GET /health` - Health check

### 4. `examples.py` - Usage Patterns

Real-world examples for:
- Simple code execution
- SQL injection fix verification
- Command injection fix verification
- Hardcoded secrets fix verification
- Integration with Temporal activities

## Usage

### Basic Execution

```python
from tron.infra.sandbox import get_sandbox_client

sandbox = await get_sandbox_client()
result = await sandbox.execute(
    code='print("hello")',
    language="python",
    timeout=10
)

if result.success:
    print(result.stdout)
else:
    print(f"Error: {result.stderr}")
```

### Fix Verification in Workflow

```python
# In tron/workflows/activities.py - verify_fix activity

async def verify_fix(finding_input: FindingInput, fix_attempt: FixAttempt) -> FixAttempt:
    """Verify a fix by running tests in the sandbox."""
    
    sandbox = await get_sandbox_client()
    
    # Generate test code from the fix
    test_code = await generate_test_code(finding_input, fix_attempt.fix_code)
    
    # Run verification in sandbox
    verification = await sandbox.verify_fix(
        original_code=finding_input.code_snippet,
        fixed_code=fix_attempt.fix_code,
        test_code=test_code,
        language=detect_language(finding_input.file_path),
    )
    
    return FixAttempt(
        iteration=fix_attempt.iteration,
        fix_code=fix_attempt.fix_code,
        verification_passed=verification.passed,
        verification_output=verification.summary,
    )
```

### Combining Code for Tests

The sandbox automatically handles language-specific code combination:

```python
# For Python
fixed_code = "def fix(): return 42"
test_code = "assert fix() == 42"
# Combined: "def fix(): return 42\n\nassert fix() == 42"

# Sandbox appends test_code to fixed_code and executes
```

## Configuration

### Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `SANDBOX_MODE` | `local` | Execution mode: `local` or `http` |
| `SANDBOX_URL` | `http://localhost:50051` | Service URL for HTTP mode |
| `SANDBOX_TIMEOUT` | `30` | Default timeout in seconds |

### Development Setup

```bash
# Use local subprocess sandbox (default)
export SANDBOX_MODE=local

# Or explicitly:
python -c "
import asyncio
from tron.infra.sandbox import get_sandbox_client

async def test():
    sandbox = await get_sandbox_client()
    result = await sandbox.execute('print(\"ok\")', 'python')
    print(result.stdout)

asyncio.run(test())
"
```

### Production Setup

For production, deploy the remote sandbox service in Docker:

```bash
# Start sandbox service
docker run -d \
  --name tron-sandbox \
  --volume /var/run/docker.sock:/var/run/docker.sock \
  -p 127.0.0.1:50051:50051 \
  -e SANDBOX_TIMEOUT_SECONDS=30 \
  -e SANDBOX_MEMORY_LIMIT=256m \
  -e SANDBOX_CPU_LIMIT=0.5 \
  tron:sandbox

# Configure client
export SANDBOX_MODE=http
export SANDBOX_URL=http://tron-sandbox:50051
```

## Security Considerations

### Input Validation

All inputs are validated:

```python
# Empty code rejected
await sandbox.execute("", "python")  # ValueError: Code cannot be empty

# Invalid language rejected
await sandbox.execute("print(1)", "cobol")  # ValueError: Unsupported language

# Negative timeout rejected
await sandbox.execute("print(1)", "python", timeout=-1)  # ValueError
```

### Resource Limits

**Local Sandbox:**
- Output truncated at 1MB
- Timeout enforced via `asyncio.wait_for()`
- Temp directory isolated per execution
- No network access (subprocess isolation)

**Remote Sandbox (Docker):**
- Each container: `--network none`, `--read-only`, `--memory 256m`, `--cpus 0.5`
- Global timeout: 30 seconds
- Max concurrent executions: 10
- Automatic cleanup after completion

### Code Execution Safety

The sandbox does NOT provide:
- ✗ Protection against all denial-of-service attacks
- ✗ Memory or disk exhaustion protection (use cgroups in production)
- ✗ Network isolation (use container network policies)

The sandbox DOES provide:
- ✓ Timeout enforcement
- ✓ Filesystem isolation (temp directory)
- ✓ Process isolation (subprocess/container)
- ✓ Output truncation

## Testing

Run unit tests:

```bash
pytest tests/test_sandbox_client.py -v

# Test specific functionality
pytest tests/test_sandbox_client.py::TestLocalSandbox::test_execute_python_success -v

# Test with coverage
pytest tests/test_sandbox_client.py --cov=tron.infra.sandbox
```

## Integration with Phases

### Phase 1-2: Currently Implemented
- Context gathering (repository scan)
- Parallel ISO analysis (agents)

### Phase 3: Execution Sandbox (THIS IMPLEMENTATION)
- **Current:** Static pattern matching in `verify_fix()` activity
- **With this client:** Execute actual tests in sandbox
- Workflow: `generate_fix()` → `verify_fix()` (now with execution) → iterate

### Phase 4: Pull Request Creation
- Create actual PR with verified fix (future work)

## Migration Path: Local → gRPC

### Current (Development)

```python
# Uses LocalSandbox (subprocess)
SANDBOX_MODE=local
sandbox = await get_sandbox_client()
```

### Interim (Staging)

```python
# Uses HTTPSandbox (REST API)
SANDBOX_MODE=http
SANDBOX_URL=http://tron-sandbox:50051
sandbox = await get_sandbox_client()
```

### Future (Production)

```python
# Uses gRPC client (proto-generated)
# SANDBOX_MODE=grpc  # Future
# sandbox = GRPCSandbox(host="tron-sandbox", port=50051)
```

The abstract `SandboxClient` interface makes migration transparent:

1. Implement `GRPCSandbox(SandboxClient)` with gRPC stubs
2. Update factory in `client.py`
3. No changes to activities or callers needed

## Logging and Observability

The sandbox logs all operations:

```python
import logging
logging.basicConfig(level=logging.DEBUG)

# Output:
# DEBUG: Using local subprocess sandbox
# DEBUG: Sandbox client initialized: local (timeout=30s)
# INFO: Fix verification: PASS (0.25s, exit_code=0)
```

For production observability, metrics are included:

```python
result = await sandbox.execute(...)
print(f"Duration: {result.duration_seconds}s")
print(f"Timed out: {result.timed_out}")
```

## Error Handling

### ExecutionResult

```python
result = await sandbox.execute(code, language)

if result.success:
    # exit_code == 0 and not timed_out
    print(result.stdout)
else:
    if result.timed_out:
        print("Code exceeded timeout")
    else:
        print(f"Exit code {result.exit_code}: {result.stderr}")
```

### VerificationResult

```python
verification = await sandbox.verify_fix(...)

if verification.passed:
    print("All tests passed")
else:
    for error in verification.errors:
        print(f"Error: {error}")
    print(verification.summary)
```

## Troubleshooting

### "Node.js not found in PATH"

```bash
# Install Node.js
brew install node  # macOS
apt-get install nodejs  # Ubuntu
```

### Health check fails

```python
sandbox = await get_sandbox_client()
# RuntimeError: Sandbox health check failed

# Check sandbox service is running
docker ps | grep tron-sandbox
```

### Timeout too short

```python
# Increase timeout
result = await sandbox.execute(code, language, timeout=60)

# Or configure default
export SANDBOX_TIMEOUT=60
```

## Performance Notes

- **Local sandbox:** < 100ms overhead per execution
- **HTTP sandbox:** 100-500ms round-trip overhead
- **gRPC sandbox (future):** < 50ms round-trip overhead

For workflows with many verifications, consider:
- Batching multiple tests per execution
- Caching validation results
- Pre-warming sandbox service

## Future Enhancements

1. **gRPC Migration:** Replace HTTP with proto-defined gRPC
2. **Test Templates:** Reusable test patterns for common vulnerabilities
3. **Metrics Collection:** Track execution metrics per language/type
4. **Caching:** Cache verification results for identical fixes
5. **Parallel Execution:** Support multiple concurrent code executions
6. **Custom Images:** Use specialized containers per language
