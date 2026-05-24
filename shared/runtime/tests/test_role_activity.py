"""Tests for live role activity terminal log."""

from shared.runtime.role_activity import get_terminal_log, role_log


def test_role_log_ring_buffer() -> None:
    pid = "00000000-0000-0000-0000-00000000test"
    role_log(pid, "engineer", "first line")
    role_log(pid, "engineer", "second line")
    lines = get_terminal_log(pid)
    assert len(lines) == 2
    assert lines[0]["message"] == "first line"
    assert lines[1]["type"] == "role_log"
    assert "engineer:" in lines[1]["formatted"]
