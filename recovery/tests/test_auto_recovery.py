"""Tests for ``recovery.auto_recovery``."""
from __future__ import annotations

import signal
import time
from pathlib import Path
from typing import Optional

import pytest

from recovery.auto_recovery import (
    AutoRecoveryManager,
    LivenessProbe,
    SupervisedTarget,
)


def _make_target(
    tmp_path: Path, name: str = "test-target", *,
    pid: Optional[int] = None,
    heartbeat_age_s: Optional[int] = None,
    is_k8s: bool = False,
) -> SupervisedTarget:
    pid_file = tmp_path / f"{name}.pid"
    if pid is not None:
        pid_file.write_text(str(pid))
    hb_file = None
    if heartbeat_age_s is not None:
        hb_file = tmp_path / f"{name}.heartbeat"
        hb_file.write_text("ok")
        # backdate mtime
        new_mtime = time.time() - heartbeat_age_s
        import os
        os.utime(hb_file, (new_mtime, new_mtime))
    return SupervisedTarget(
        name=name, pid_file=pid_file,
        heartbeat_file=hb_file,
        launcher=Path("/dev/null"),
        is_k8s_owned=is_k8s,
    )


def _kill_alive_fn(pid: int, sig: int) -> None:
    """Pretend every PID is alive (signal 0 returns no error)."""
    return None


def _kill_dead_fn(pid: int, sig: int) -> None:
    raise ProcessLookupError(f"no such pid {pid}")


# ---------------------------------------------------------------------------
# LivenessProbe.is_healthy
# ---------------------------------------------------------------------------


class TestLivenessProbe:

    def test_no_pid_is_healthy(self) -> None:
        from datetime import datetime, timezone
        p = LivenessProbe(name="x", pid=None, pid_alive=False,
                          heartbeat_age_s=None, heartbeat_stale=False,
                          observed_at=datetime.now(timezone.utc))
        assert p.is_healthy

    def test_pid_alive_heartbeat_fresh_is_healthy(self) -> None:
        from datetime import datetime, timezone
        p = LivenessProbe(name="x", pid=123, pid_alive=True,
                          heartbeat_age_s=10, heartbeat_stale=False,
                          observed_at=datetime.now(timezone.utc))
        assert p.is_healthy

    def test_pid_alive_heartbeat_stale_is_unhealthy(self) -> None:
        from datetime import datetime, timezone
        p = LivenessProbe(name="x", pid=123, pid_alive=True,
                          heartbeat_age_s=999, heartbeat_stale=True,
                          observed_at=datetime.now(timezone.utc))
        assert not p.is_healthy


# ---------------------------------------------------------------------------
# AutoRecoveryManager probing
# ---------------------------------------------------------------------------


class TestProbe:

    def test_probe_alive(self, tmp_path) -> None:
        t = _make_target(tmp_path, pid=123, heartbeat_age_s=10)
        mgr = AutoRecoveryManager(targets=[t], kill_fn=_kill_alive_fn)
        probe = mgr.probe(t.name)
        assert probe.pid == 123
        assert probe.pid_alive
        assert not probe.heartbeat_stale

    def test_probe_stale_heartbeat(self, tmp_path) -> None:
        t = _make_target(tmp_path, pid=123, heartbeat_age_s=99999)
        mgr = AutoRecoveryManager(targets=[t], kill_fn=_kill_alive_fn)
        probe = mgr.probe(t.name)
        assert probe.heartbeat_stale

    def test_probe_dead_pid(self, tmp_path) -> None:
        t = _make_target(tmp_path, pid=123, heartbeat_age_s=10)
        mgr = AutoRecoveryManager(targets=[t], kill_fn=_kill_dead_fn)
        probe = mgr.probe(t.name)
        assert not probe.pid_alive

    def test_probe_no_pid_file(self, tmp_path) -> None:
        t = _make_target(tmp_path, pid=None)
        mgr = AutoRecoveryManager(targets=[t], kill_fn=_kill_alive_fn)
        probe = mgr.probe(t.name)
        assert probe.pid is None
        assert not probe.pid_alive


# ---------------------------------------------------------------------------
# check_and_recover
# ---------------------------------------------------------------------------


class TestCheckAndRecover:

    def test_k8s_owned_noop(self, tmp_path) -> None:
        t = _make_target(tmp_path, pid=123, heartbeat_age_s=99999, is_k8s=True)
        mgr = AutoRecoveryManager(targets=[t], kill_fn=_kill_dead_fn)
        result = mgr.check_and_recover(t.name)
        assert result.action == "k8s_owned"

    def test_missing_target(self) -> None:
        mgr = AutoRecoveryManager(targets=[], kill_fn=_kill_alive_fn)
        result = mgr.check_and_recover("not-real")
        assert result.action == "missing_target"

    def test_no_pid_file_noop(self, tmp_path) -> None:
        t = _make_target(tmp_path, pid=None)
        mgr = AutoRecoveryManager(targets=[t], kill_fn=_kill_alive_fn)
        result = mgr.check_and_recover(t.name)
        assert result.action == "noop"

    def test_healthy_noop(self, tmp_path) -> None:
        t = _make_target(tmp_path, pid=123, heartbeat_age_s=5)
        mgr = AutoRecoveryManager(targets=[t], kill_fn=_kill_alive_fn)
        result = mgr.check_and_recover(t.name)
        assert result.action == "noop"

    def test_dead_pid_clears_pid_file(self, tmp_path) -> None:
        t = _make_target(tmp_path, pid=123, heartbeat_age_s=5)
        mgr = AutoRecoveryManager(targets=[t], kill_fn=_kill_dead_fn)
        result = mgr.check_and_recover(t.name)
        assert result.action == "killed_zombie"
        assert not t.pid_file.exists()

    def test_stale_heartbeat_kills_pid(self, tmp_path) -> None:
        killed: list[tuple[int, int]] = []

        def killer(pid: int, sig: int) -> None:
            killed.append((pid, sig))
            return None  # alive

        t = _make_target(tmp_path, pid=123, heartbeat_age_s=99999)
        mgr = AutoRecoveryManager(targets=[t], kill_fn=killer)
        result = mgr.check_and_recover(t.name)
        assert result.action == "killed_zombie"
        # Must have been SIGTERM'd
        assert (123, signal.SIGTERM) in killed

    def test_circuit_breaker_opens(self, tmp_path) -> None:
        notifies: list[tuple[str, str]] = []
        # Always-dead target → every check is a restart.
        t = _make_target(tmp_path, pid=123, heartbeat_age_s=5)
        mgr = AutoRecoveryManager(
            targets=[t], kill_fn=_kill_dead_fn,
            max_restarts_per_window=3, window_seconds=600,
            notify_fn=lambda s, b: notifies.append((s, b)),
        )
        # Drive the breaker open: first 3 hits = killed_zombie,
        # 4th = circuit_open. Recreate pid_file each loop so the
        # "no pid file" branch isn't hit.
        for i in range(3):
            t.pid_file.write_text("123")
            result = mgr.check_and_recover(t.name)
            assert result.action == "killed_zombie", f"iter {i}: {result.action}"
        t.pid_file.write_text("123")
        result = mgr.check_and_recover(t.name)
        assert result.action == "circuit_open"
        assert notifies, "operator should have been notified"


# ---------------------------------------------------------------------------
# check_all
# ---------------------------------------------------------------------------


class TestCheckAll:

    def test_check_all_visits_every_target(self, tmp_path) -> None:
        t1 = _make_target(tmp_path, name="a", pid=None)
        t2 = _make_target(tmp_path, name="b", pid=123, heartbeat_age_s=5)
        mgr = AutoRecoveryManager(targets=[t1, t2], kill_fn=_kill_alive_fn)
        results = mgr.check_all()
        assert len(results) == 2
        assert {r.target for r in results} == {"a", "b"}

    def test_restart_log_records_attempts(self, tmp_path) -> None:
        t = _make_target(tmp_path, pid=123, heartbeat_age_s=5)
        mgr = AutoRecoveryManager(targets=[t], kill_fn=_kill_dead_fn)
        mgr.check_and_recover(t.name)
        log = mgr.restart_log()
        assert t.name in log
        assert len(log[t.name]) == 1
