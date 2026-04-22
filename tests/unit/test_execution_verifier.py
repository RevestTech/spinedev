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
