"""Container + process auto-restart (layers 1 & 2 of #32).

Per ``docs/V3_DESIGN_DECISIONS.md`` §32:

* **Layer 1 — Container auto-recovery.** K8s does this natively (replicas
  + liveness/readiness probes); for non-K8s (laptop / single-host /
  BYOC dev shape) we use ``shared/runtime/watchdog.sh`` which already
  supervises per-role daemons + auxiliary processes via PID files and
  heartbeat mtime. This module is the Python control surface for that
  watchdog: it can READ the state, REQUEST a restart, and OBSERVE
  liveness — but it does not REPLACE the watchdog. The watchdog stays
  the single source of supervision truth.

* **Layer 2 — Process supervision.** Each role daemon supervised by
  the watchdog above. Circuit breaker on flapping is policy-tuned by
  ``MAX_RESTARTS_PER_WINDOW`` (default 5 in 10 min). When a target
  exceeds the breaker we stop restarting + page the operator (#6).

The actual sub-second restart loop lives in the watchdog shell script
because (a) it must keep running when the Python interpreter is the
process that died, and (b) consistency with #11 (the Operate
subsystem owns recovery primitives the same way it owns deploy +
incident).

This module is the *adapter* layer that:

1. Discovers supervised targets from the watchdog's state directory.
2. Computes liveness from PID files + heartbeat mtimes.
3. Calls the watchdog's documented restart entry-points (touching the
   PID file / sending SIGTERM and letting the watchdog respawn).
4. Persists circuit-breaker state in-process so a flapping target
   doesn't melt the host.
5. Feeds ``recovery_health`` MCP tool with a structured report.

The K8s path is observed via ``health.py`` (k8s liveness probe HTTP
endpoint counts as a heartbeat); this module's restart paths are no-ops
under K8s — kubelet does the actual work.
"""
from __future__ import annotations

import logging
import os
import signal
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal, Optional

logger = logging.getLogger("spine.recovery.auto_recovery")

#: Default circuit-breaker window (per-target).
MAX_RESTARTS_PER_WINDOW: int = 5
WINDOW_SECONDS: int = 600

#: How long a heartbeat file may be stale before the supervisor
#: considers the target dead. Matches the watchdog default
#: (``HEARTBEAT_TIMEOUT_S``) so the two layers agree.
DEFAULT_HEARTBEAT_TIMEOUT_S: int = 300

#: Recovery action taken by :meth:`AutoRecoveryManager.check_and_recover`.
RecoveryAction = Literal[
    "noop", "restarted", "circuit_open", "k8s_owned",
    "missing_target", "killed_zombie",
]


@dataclass(frozen=True)
class SupervisedTarget:
    """One process/container supervised by the watchdog.

    Attributes:
        name: Logical name (``"manager:engineer"`` / ``"heartbeat"`` /
            ``"hub-api"``). Must match the watchdog's identifier.
        pid_file: Path on disk; presence = live intent, absence =
            operator-stopped (per the watchdog's lifecycle contract).
        heartbeat_file: Optional; mtime is checked for liveness.
        launcher: Optional script the watchdog re-spawns. Recorded here
            for the runbook; we don't shell out ourselves.
        is_k8s_owned: True when running under K8s — restarts are
            kubelet's responsibility; we only OBSERVE.
    """

    name: str
    pid_file: Path
    heartbeat_file: Optional[Path] = None
    launcher: Optional[Path] = None
    is_k8s_owned: bool = False


@dataclass(frozen=True)
class LivenessProbe:
    """Snapshot of one supervised target at a point in time."""

    name: str
    pid: Optional[int]
    pid_alive: bool
    heartbeat_age_s: Optional[int]
    heartbeat_stale: bool
    observed_at: datetime

    @property
    def is_healthy(self) -> bool:
        if self.pid is None:
            # No PID file means operator-stopped; that's fine.
            return True
        return self.pid_alive and not self.heartbeat_stale


@dataclass(frozen=True)
class RecoveryResult:
    """Outcome of one ``check_and_recover`` pass over a target."""

    target: str
    probe: LivenessProbe
    action: RecoveryAction
    detail: str = ""
    recovered_at: Optional[datetime] = None


class AutoRecoveryManager:
    """Adapter over ``shared/runtime/watchdog.sh``.

    Production usage::

        mgr = AutoRecoveryManager.from_default_handoff()
        report = mgr.check_all()

    Test usage: pass a list of ``SupervisedTarget`` explicitly + a
    ``now_fn`` for deterministic timing.
    """

    def __init__(
        self,
        targets: list[SupervisedTarget],
        *,
        heartbeat_timeout_s: int = DEFAULT_HEARTBEAT_TIMEOUT_S,
        max_restarts_per_window: int = MAX_RESTARTS_PER_WINDOW,
        window_seconds: int = WINDOW_SECONDS,
        now_fn: Callable[[], float] = time.time,
        kill_fn: Callable[[int, int], None] = os.kill,
        runner: Optional[Callable[[list[str]], tuple[int, str, str]]] = None,
        notify_fn: Optional[Callable[[str, str], None]] = None,
    ) -> None:
        self._targets = {t.name: t for t in targets}
        self._heartbeat_timeout_s = heartbeat_timeout_s
        self._max_restarts = max_restarts_per_window
        self._window_s = window_seconds
        self._now = now_fn
        self._kill = kill_fn
        self._runner = runner or _default_runner
        self._notify = notify_fn or _default_notify
        # per-target sliding window of restart timestamps
        self._restart_log: dict[str, list[float]] = {}

    # --- discovery -------------------------------------------------

    @classmethod
    def from_default_handoff(cls) -> "AutoRecoveryManager":
        """Discover targets from the watchdog's default state dirs.

        Reads ``.planning/orchestration/agent-handoff/`` (matches
        watchdog.sh's ``HANDOFF_BASE``) and the per-role
        ``teams/<role>/state/pids/manager.pid`` convention.
        """
        base = Path(".planning/orchestration/agent-handoff")
        targets: list[SupervisedTarget] = []
        # Auxiliary supervised processes. lib/run-standalone-watcher.sh was
        # deleted in Wave 0 Pass 2 (commit e6e54d2) per V3_TRIAGE T5 DELETE
        # marking — federation join/leave moved to Wave 4 federation/ + Hub-
        # backed status MCP. Only heartbeat remains as a supervised aux.
        for aux_name, pid_filename, launcher_rel in (
            ("heartbeat", "heartbeat.pid", "shared/runtime/heartbeat.sh"),
        ):
            targets.append(SupervisedTarget(
                name=aux_name,
                pid_file=base / pid_filename,
                heartbeat_file=None,
                launcher=Path(launcher_rel),
                is_k8s_owned=_running_under_k8s(),
            ))
        # Per-role managers — only those with a state dir.
        teams_root = base / "teams"
        if teams_root.exists():
            for role_dir in sorted(teams_root.iterdir()):
                if not role_dir.is_dir():
                    continue
                role = role_dir.name
                pid_file = role_dir / "state" / "pids" / "manager.pid"
                heartbeat = role_dir / "state" / "heartbeat"
                targets.append(SupervisedTarget(
                    name=f"manager:{role}",
                    pid_file=pid_file,
                    heartbeat_file=heartbeat,
                    launcher=Path("scripts/team-agent-daemon.sh"),
                    is_k8s_owned=_running_under_k8s(),
                ))
        return cls(targets)

    # --- probing ---------------------------------------------------

    def probe(self, name: str) -> LivenessProbe:
        target = self._targets[name]
        pid: Optional[int] = None
        pid_alive = False
        if target.pid_file.exists():
            try:
                pid_raw = target.pid_file.read_text().strip()
                pid = int(pid_raw) if pid_raw else None
            except (OSError, ValueError):
                pid = None
            if pid:
                pid_alive = self._is_pid_alive(pid)
        heartbeat_age_s: Optional[int] = None
        heartbeat_stale = False
        if target.heartbeat_file and target.heartbeat_file.exists():
            try:
                mtime = target.heartbeat_file.stat().st_mtime
                heartbeat_age_s = int(self._now() - mtime)
                heartbeat_stale = heartbeat_age_s > self._heartbeat_timeout_s
            except OSError:
                heartbeat_age_s = None
        return LivenessProbe(
            name=name,
            pid=pid, pid_alive=pid_alive,
            heartbeat_age_s=heartbeat_age_s,
            heartbeat_stale=heartbeat_stale,
            observed_at=datetime.now(timezone.utc),
        )

    def probe_all(self) -> list[LivenessProbe]:
        return [self.probe(n) for n in sorted(self._targets)]

    # --- recovery --------------------------------------------------

    def check_and_recover(self, name: str) -> RecoveryResult:
        if name not in self._targets:
            return RecoveryResult(
                target=name,
                probe=LivenessProbe(
                    name=name, pid=None, pid_alive=False,
                    heartbeat_age_s=None, heartbeat_stale=False,
                    observed_at=datetime.now(timezone.utc),
                ),
                action="missing_target",
                detail=f"target {name!r} not registered",
            )
        target = self._targets[name]
        probe = self.probe(name)
        if target.is_k8s_owned:
            return RecoveryResult(
                target=name, probe=probe, action="k8s_owned",
                detail="K8s kubelet owns restart; recovery module observes only.",
            )
        if probe.pid is None:
            return RecoveryResult(
                target=name, probe=probe, action="noop",
                detail="no pid_file present — operator intent is 'stopped'",
            )
        if probe.is_healthy:
            return RecoveryResult(
                target=name, probe=probe, action="noop",
                detail="healthy",
            )
        # Unhealthy. Check breaker.
        if self._breaker_open(name):
            self._notify(
                f"[recovery] circuit breaker open for {name}",
                f"target {name!r} has failed {self._max_restarts}+ times in "
                f"{self._window_s}s window; manual intervention required.",
            )
            return RecoveryResult(
                target=name, probe=probe, action="circuit_open",
                detail=f"restarts exceeded {self._max_restarts}/{self._window_s}s",
            )
        # Kill zombie + nudge watchdog by removing stale pid file.
        killed = False
        if probe.pid and not probe.pid_alive:
            # PID is in the file but the process is gone; clear the file
            # so the watchdog (or the next probe) doesn't keep poking.
            try:
                target.pid_file.unlink(missing_ok=True)
                killed = True
            except OSError as exc:
                logger.warning("pid_file_unlink_failed",
                               extra={"name": name, "err": str(exc)})
        elif probe.pid and probe.pid_alive and probe.heartbeat_stale:
            # Heartbeat stale but PID alive — daemon hung. SIGTERM and
            # let the watchdog re-spawn it on its next poll.
            try:
                self._kill(probe.pid, signal.SIGTERM)
                killed = True
            except (ProcessLookupError, PermissionError) as exc:
                logger.warning("kill_failed",
                               extra={"name": name, "err": str(exc)})
        self._record_restart(name)
        return RecoveryResult(
            target=name, probe=probe,
            action="killed_zombie" if killed else "restarted",
            detail=(
                "watchdog will re-launch on next poll cycle"
                if killed else "no action taken (PID file alive but stale heartbeat)"
            ),
            recovered_at=datetime.now(timezone.utc),
        )

    def check_all(self) -> list[RecoveryResult]:
        return [self.check_and_recover(n) for n in sorted(self._targets)]

    def restart_log(self) -> dict[str, list[float]]:
        """Return a copy of the breaker log (read-only diagnostic)."""
        return {k: list(v) for k, v in self._restart_log.items()}

    # --- internals -------------------------------------------------

    def _is_pid_alive(self, pid: int) -> bool:
        try:
            self._kill(pid, 0)  # signal 0 = liveness check
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            # Process exists but we can't signal it — still alive.
            return True
        except OSError:
            return False

    def _breaker_open(self, name: str) -> bool:
        now = self._now()
        log = self._restart_log.setdefault(name, [])
        # Prune outside window.
        cutoff = now - self._window_s
        log[:] = [t for t in log if t >= cutoff]
        return len(log) >= self._max_restarts

    def _record_restart(self, name: str) -> None:
        self._restart_log.setdefault(name, []).append(self._now())


def _running_under_k8s() -> bool:
    """Detect K8s — the standard service-account file path."""
    return Path("/var/run/secrets/kubernetes.io/serviceaccount/token").exists()


def _default_runner(argv: list[str]) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            argv, check=False, capture_output=True, text=True, timeout=30,
        )
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except FileNotFoundError as exc:
        return 127, "", f"command not found: {argv[0]!r} — {exc}"


def _default_notify(subject: str, body: str) -> None:
    try:
        from shared.notify import NotificationEvent, Notifier
        from shared.notify.channels import StdoutChannel
        Notifier(channels=[StdoutChannel()]).notify(NotificationEvent(
            event_type="project_blocked",
            project_id="recovery", project_name="recovery",
            phase="dr", actor="recovery",
            summary=subject, severity="warning",
            metadata={"body": body},
        ))
    except Exception:  # noqa: BLE001
        logger.warning("notify_failed", extra={"subject": subject})


__all__ = [
    "AutoRecoveryManager",
    "DEFAULT_HEARTBEAT_TIMEOUT_S",
    "LivenessProbe",
    "MAX_RESTARTS_PER_WINDOW",
    "RecoveryAction",
    "RecoveryResult",
    "SupervisedTarget",
    "WINDOW_SECONDS",
]
