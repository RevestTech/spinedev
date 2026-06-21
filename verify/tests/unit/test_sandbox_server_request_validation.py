"""
Regression tests for the sandbox HTTP server's request validation.

The server duplicates the network-mode allowlist on the request edge so a
hostile/buggy caller's request dies at FastAPI with a 422 — before touching
any Docker plumbing. Belt-and-braces with ``SandboxClient._validate_network_mode``.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from tron.sandbox.server import ExecuteBody


class TestExecuteBodyNetworkMode:
    def test_defaults_to_none(self):
        body = ExecuteBody(code="print('x')")
        assert body.network_mode == "none"

    def test_bridge_is_accepted(self):
        body = ExecuteBody(code="print('x')", network_mode="bridge")
        assert body.network_mode == "bridge"

    def test_host_is_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            ExecuteBody(code="print('x')", network_mode="host")
        assert "network_mode" in str(exc_info.value)

    def test_container_mode_is_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            ExecuteBody(code="print('x')", network_mode="container:abc123")
        assert "not allowed" in str(exc_info.value)

    @pytest.mark.parametrize("bad_mode", ["", "overlay", "macvlan", "my-custom-net"])
    def test_arbitrary_modes_are_rejected(self, bad_mode):
        with pytest.raises(ValidationError):
            ExecuteBody(code="print('x')", network_mode=bad_mode)


class TestExecuteBodyCodeRequired:
    def test_code_or_script_required(self):
        with pytest.raises(ValidationError):
            ExecuteBody()

    def test_code_alone_is_enough(self):
        body = ExecuteBody(code="print('x')")
        assert body.source() == "print('x')"

    def test_script_alone_is_enough(self):
        body = ExecuteBody(script="echo hi")
        assert body.source() == "echo hi"
