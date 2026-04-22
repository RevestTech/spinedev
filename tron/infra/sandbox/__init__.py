"""
Sandbox execution client for isolated code execution.

The sandbox provides a secure, isolated environment for executing arbitrary code
without compromising the host system. It currently supports HTTP-based execution
(local subprocess for development) and is designed to support gRPC migration.

Usage:
    from tron.infra.sandbox import get_sandbox_client

    sandbox = await get_sandbox_client()
    result = await sandbox.execute(
        code="print('hello')",
        language="python",
        timeout=10,
    )
    print(result.stdout)
"""

from __future__ import annotations

from tron.infra.sandbox.client import (
    ExecutionResult,
    SandboxClient,
    VerificationResult,
    get_sandbox_client,
)

__all__ = [
    "SandboxClient",
    "ExecutionResult",
    "VerificationResult",
    "get_sandbox_client",
]
