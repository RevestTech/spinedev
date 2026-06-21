import pytest
from unittest.mock import MagicMock, AsyncMock
from tron.verification.execution_verifier import ExecutionVerifier, FindingSnapshot, VerificationStatus

@pytest.mark.asyncio
async def test_verify_sql_injection():
    mock_sandbox = MagicMock()
    mock_sandbox.run_python = AsyncMock(return_value={"exit_code": 0, "output": "SQL exploit executed successfully"})
    
    verifier = ExecutionVerifier(sandbox_client=mock_sandbox)
    finding = FindingSnapshot(
        category="sql_injection",
        code_snippet="db.execute('SELECT * FROM users WHERE name=' + name)"
    )
    
    result = await verifier.verify_finding(finding)
    
    assert result.status == VerificationStatus.VERIFIED
    assert "SQL" in result.reason
    mock_sandbox.run_python.assert_called_once()
    # Check if script contains expected setup
    script = mock_sandbox.run_python.call_args.kwargs['script']
    assert "import sqlite3" in script
    assert "MockDB" in script
    assert "db.execute('SELECT * FROM users WHERE name=' + name)" in script

@pytest.mark.asyncio
async def test_verify_command_injection():
    mock_sandbox = MagicMock()
    mock_sandbox.run_python = AsyncMock(return_value={"exit_code": 0, "output": "Command exploit executed successfully"})
    
    verifier = ExecutionVerifier(sandbox_client=mock_sandbox)
    finding = FindingSnapshot(
        category="command_injection",
        code_snippet="os.system('ls ' + user_input)"
    )
    
    result = await verifier.verify_finding(finding)
    
    assert result.status == VerificationStatus.VERIFIED
    assert "COMMAND" in result.reason
    mock_sandbox.run_python.assert_called_once()
    script = mock_sandbox.run_python.call_args.kwargs['script']
    assert "import os" in script
    assert "os.system('ls ' + user_input)" in script

@pytest.mark.asyncio
async def test_verify_path_traversal():
    mock_sandbox = MagicMock()
    mock_sandbox.run_python = AsyncMock(return_value={"exit_code": 0, "output": "Successfully read /etc/os-release"})
    
    verifier = ExecutionVerifier(sandbox_client=mock_sandbox)
    finding = FindingSnapshot(
        category="path_traversal",
        code_snippet="open(path)"
    )
    
    result = await verifier.verify_finding(finding)
    
    assert result.status == VerificationStatus.VERIFIED
    assert "Path traversal" in result.reason
    mock_sandbox.run_python.assert_called_once()
    script = mock_sandbox.run_python.call_args.kwargs['script']
    assert "import os" in script
    assert "/etc/os-release" in script
    assert "open(path)" in script

@pytest.mark.asyncio
async def test_verify_ssrf():
    mock_sandbox = MagicMock()
    mock_sandbox.run_python = AsyncMock(return_value={"exit_code": 0, "output": "SSRF fetch successful: 200"})
    
    verifier = ExecutionVerifier(sandbox_client=mock_sandbox)
    finding = FindingSnapshot(
        category="ssrf",
        code_snippet="requests.get(url)"
    )
    
    result = await verifier.verify_finding(finding)
    
    assert result.status == VerificationStatus.VERIFIED
    assert "SSRF" in result.reason
    mock_sandbox.run_python.assert_called_once()
    script = mock_sandbox.run_python.call_args.kwargs['script']
    assert "import requests" in script
    assert "http://localhost" in script
    assert "requests.get(url)" in script

@pytest.mark.asyncio
async def test_verify_rejected():
    mock_sandbox = MagicMock()
    mock_sandbox.run_python = AsyncMock(return_value={"exit_code": 1, "output": "Exploit failed", "error": "NameError"})
    
    verifier = ExecutionVerifier(sandbox_client=mock_sandbox)
    finding = FindingSnapshot(
        category="sql_injection",
        code_snippet="invalid snippet"
    )
    
    result = await verifier.verify_finding(finding)
    
    assert result.status == VerificationStatus.REJECTED
    assert "Failed to verify" in result.reason


# ── Regression: TypeError on str + None concat ──────────────────────────


@pytest.mark.asyncio
async def test_rejected_handles_none_output_and_error():
    """
    Regression: SandboxClient returns ``{"output": None, "error": None}`` for
    some run paths, and ``dict.get(k, "")`` does NOT substitute the default
    when the key exists with value None — only when the key is missing. The
    concatenation in the rejected branch then raised TypeError mid-Layer-3
    and killed the whole audit workflow.

    The fix uses ``(result.get(k) or "")`` on both sides. This test pins
    that contract so the regression can't return.
    """
    mock_sandbox = MagicMock()
    # The shape that broke things: keys present, values None, non-zero exit.
    mock_sandbox.run_python = AsyncMock(return_value={
        "exit_code": 1, "output": None, "error": None,
    })

    verifier = ExecutionVerifier(sandbox_client=mock_sandbox)
    finding = FindingSnapshot(
        category="sql_injection",
        code_snippet="cursor.execute('SELECT * FROM users WHERE id = ' + uid)",
    )

    # Must NOT raise TypeError — the rejection branch should produce a
    # VerificationResult with execution_output = "" (both sides normalised).
    result = await verifier.verify_finding(finding)

    assert result.status == VerificationStatus.REJECTED
    assert result.execution_output == ""


@pytest.mark.asyncio
async def test_rejected_handles_missing_output_and_error_keys():
    """Belt-and-braces: ``result`` may also be missing keys entirely."""
    mock_sandbox = MagicMock()
    mock_sandbox.run_python = AsyncMock(return_value={"exit_code": 1})

    verifier = ExecutionVerifier(sandbox_client=mock_sandbox)
    finding = FindingSnapshot(
        category="command_injection",
        code_snippet="os.system('ls ' + arg)",
    )

    result = await verifier.verify_finding(finding)

    assert result.status == VerificationStatus.REJECTED
    assert result.execution_output == ""
