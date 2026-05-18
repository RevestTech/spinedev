#!/usr/bin/env bash
# vitals.sh — Pass M. Capture host vitals + Spine-attributed totals as
# a flat one-line JSON object printed to stdout. Called by heartbeat.sh
# every SPINE_HEARTBEAT_INTERVAL_S seconds.
#
# Output shape (all fields optional — missing ones are simply absent):
#   {"cpu_pct":12.3,"mem_used_mb":4096,"mem_total_mb":16384,
#    "disk_used_gb":120.5,"disk_total_gb":500.0,
#    "load_avg_1m":1.23,"load_avg_5m":1.10,"load_avg_15m":0.95,
#    "spine_cpu_pct":2.5,"spine_mem_mb":520,"spine_proc_count":143}
#
# Contract:
#   * Must be fast (well under a second; target <300ms).
#   * Must never crash the heartbeat. On ANY error, emit '{}' and exit 0.
#   * The "spine_*" totals are summed across processes whose cmdline
#     contains team-agent-daemon.sh OR heartbeat.sh OR updater.sh OR
#     watchdog.sh OR serve.py.
#
# Implementation:
#   We dispatch to an inline Python helper. Python first tries `psutil`
#   for clean cross-platform metrics; on ImportError it falls through to
#   platform-specific CLI parsing (vm_stat/top/df/uptime on macOS, /proc
#   on Linux).
#
# psutil install behavior:
#   By default we do NOT attempt to install psutil — modifying the
#   system Python environment without consent is invasive and breaks in
#   locked-down/CI hosts. The CLI fallback is fully sufficient for the
#   metrics we emit; psutil is a performance/cleanliness optimization.
#   To opt in, set SPINE_VITALS_INSTALL=1 (one-shot best-effort
#   `pip3 install --break-system-packages -q psutil`).
#   SPINE_VITALS_NO_INSTALL=1 is still honored as a hard veto.

set -uo pipefail

# Single-shot pip install marker: once we've tried and failed, never try
# again in this process tree. The heartbeat respawns vitals.sh each tick
# so the marker is per-tick — that's fine: the cost is one stat() per
# minute. To persist across ticks we'd need a real on-disk marker; the
# spend isn't worth the complexity here.

# Cap total runtime defensively. macOS bash 3.2 doesn't have native
# timeout; we use a subshell with a background watchdog.
_VITALS_DEADLINE_S="${SPINE_VITALS_DEADLINE_S:-3}"

_emit_empty() {
  printf '%s\n' '{}'
  exit 0
}

# If python3 isn't on PATH, we can't do anything. Best-effort: emit {}.
if ! command -v python3 >/dev/null 2>&1; then
  _emit_empty
fi

# Opt-in psutil install. Only runs when SPINE_VITALS_INSTALL=1 AND
# SPINE_VITALS_NO_INSTALL is not set. The CLI fallback path covers all
# emitted metrics, so installing is purely an optimization.
_try_install_psutil() {
  if [[ "${SPINE_VITALS_NO_INSTALL:-0}" == "1" ]]; then
    return 0
  fi
  if [[ "${SPINE_VITALS_INSTALL:-0}" != "1" ]]; then
    return 0
  fi
  if python3 -c 'import psutil' >/dev/null 2>&1; then
    return 0
  fi
  if ! command -v pip3 >/dev/null 2>&1; then
    return 0
  fi
  pip3 install --break-system-packages -q psutil >/dev/null 2>&1 || true
}

# Kick off the install only if the operator has opted in. Otherwise we
# fall straight to the CLI path on every tick (psutil import simply
# fails inside the helper) — no background process, no orphan risk.
if [[ "${SPINE_VITALS_INSTALL:-0}" == "1" ]] \
   && [[ "${SPINE_VITALS_NO_INSTALL:-0}" != "1" ]] \
   && ! python3 -c 'import psutil' >/dev/null 2>&1; then
  _try_install_psutil &
  _INSTALL_PID=$!
  disown "$_INSTALL_PID" 2>/dev/null || true
fi

# Run the Python helper with a hard wall-clock cap. We use a subshell +
# background + wait loop because macOS lacks coreutils `timeout` by
# default. If the helper takes longer than _VITALS_DEADLINE_S, we kill
# it and emit '{}'.
_PYHELPER='
import json, os, re, subprocess, sys

# Process-attribution markers. A process is "spine_*" if any of these
# substrings appears in its cmdline. team-agent-daemon.sh is the worker
# daemon; heartbeat.sh / updater.sh / watchdog.sh are the per-instance
# supervisors; serve.py is the dashboard backend (when running locally).
SPINE_MARKERS = (
    "team-agent-daemon.sh",
    "heartbeat.sh",
    "updater.sh",
    "watchdog.sh",
    "serve.py",
)

def _is_spine_cmdline(cmd):
    if not cmd:
        return False
    for m in SPINE_MARKERS:
        if m in cmd:
            return True
    return False


def _emit(data):
    # Drop None values so the JSON stays tidy; the watcher tolerates
    # missing fields and uses NULL semantics.
    out = {k: v for k, v in data.items() if v is not None}
    sys.stdout.write(json.dumps(out))
    sys.stdout.write("\n")


def _try_psutil():
    try:
        import psutil  # type: ignore
    except Exception:
        return None
    try:
        out = {}

        # Total CPU across all cores. interval=None reads the cached
        # snapshot from the previous call; first call after import
        # returns 0.0, so we prime then sleep ~100ms and read again.
        psutil.cpu_percent(interval=None)
        # Brief sleep so the second sample is meaningful. Keep tight
        # so the whole helper stays under our budget.
        try:
            import time
            time.sleep(0.10)
        except Exception:
            pass
        cpu = psutil.cpu_percent(interval=None)
        if cpu is not None:
            out["cpu_pct"] = round(float(cpu), 2)

        vm = psutil.virtual_memory()
        out["mem_used_mb"] = int(vm.used / (1024 * 1024))
        out["mem_total_mb"] = int(vm.total / (1024 * 1024))

        try:
            du = psutil.disk_usage("/")
            out["disk_used_gb"] = round(du.used / (1024 ** 3), 2)
            out["disk_total_gb"] = round(du.total / (1024 ** 3), 2)
        except Exception:
            pass

        try:
            la = psutil.getloadavg()
            out["load_avg_1m"] = round(float(la[0]), 2)
            out["load_avg_5m"] = round(float(la[1]), 2)
            out["load_avg_15m"] = round(float(la[2]), 2)
        except Exception:
            pass

        # Spine-attributed totals. Walk every process once. CPU% is
        # already a percent of one core; we sum across procs and let
        # the dashboard normalize against cpu_pct.
        spine_cpu = 0.0
        spine_mem = 0
        spine_n = 0
        ncpu = max(1, psutil.cpu_count(logical=True) or 1)
        for p in psutil.process_iter(attrs=["cmdline", "cpu_percent", "memory_info"]):
            try:
                cmd = " ".join(p.info.get("cmdline") or [])
                if not _is_spine_cmdline(cmd):
                    continue
                cp = p.info.get("cpu_percent") or 0.0
                spine_cpu += float(cp)
                mi = p.info.get("memory_info")
                if mi is not None:
                    spine_mem += int(getattr(mi, "rss", 0) or 0)
                spine_n += 1
            except Exception:
                continue
        # cpu_percent reports per-core %; normalize to host % by dividing
        # by core count so spine_cpu_pct is comparable to cpu_pct.
        out["spine_cpu_pct"] = round(spine_cpu / ncpu, 2)
        out["spine_mem_mb"] = int(spine_mem / (1024 * 1024))
        out["spine_proc_count"] = spine_n
        return out
    except Exception:
        return None


def _run(cmd, timeout=2):
    try:
        cp = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return cp.stdout or ""
    except Exception:
        return ""


def _try_cli_linux():
    out = {}
    # CPU% from /proc/stat. We take two samples ~100ms apart.
    def _read_stat():
        try:
            with open("/proc/stat", "r") as f:
                for line in f:
                    if line.startswith("cpu "):
                        parts = [int(x) for x in line.split()[1:]]
                        idle = parts[3] + (parts[4] if len(parts) > 4 else 0)
                        total = sum(parts)
                        return idle, total
        except Exception:
            return None, None
        return None, None
    try:
        i1, t1 = _read_stat()
        import time
        time.sleep(0.10)
        i2, t2 = _read_stat()
        if None not in (i1, t1, i2, t2) and (t2 - t1) > 0:
            out["cpu_pct"] = round(100.0 * (1.0 - (i2 - i1) / (t2 - t1)), 2)
    except Exception:
        pass
    # Memory from /proc/meminfo.
    try:
        with open("/proc/meminfo", "r") as f:
            mi = {}
            for line in f:
                k, _, rest = line.partition(":")
                if not rest:
                    continue
                v = rest.strip().split()[0]
                try:
                    mi[k.strip()] = int(v)  # kB
                except ValueError:
                    pass
        total_kb = mi.get("MemTotal", 0)
        avail_kb = mi.get("MemAvailable", mi.get("MemFree", 0))
        used_kb = max(0, total_kb - avail_kb)
        if total_kb > 0:
            out["mem_total_mb"] = int(total_kb / 1024)
            out["mem_used_mb"] = int(used_kb / 1024)
    except Exception:
        pass
    # Load average.
    try:
        with open("/proc/loadavg", "r") as f:
            la = f.read().split()
            out["load_avg_1m"] = round(float(la[0]), 2)
            out["load_avg_5m"] = round(float(la[1]), 2)
            out["load_avg_15m"] = round(float(la[2]), 2)
    except Exception:
        pass
    # Disk via df.
    try:
        txt = _run(["df", "-kP", "/"], timeout=2)
        lines = [l for l in txt.splitlines() if l.strip()]
        if len(lines) >= 2:
            parts = lines[-1].split()
            # parts: Filesystem 1024-blocks Used Available Capacity Mounted-on
            if len(parts) >= 4:
                total_k = int(parts[1])
                used_k = int(parts[2])
                out["disk_total_gb"] = round(total_k / (1024 * 1024), 2)
                out["disk_used_gb"] = round(used_k / (1024 * 1024), 2)
    except Exception:
        pass
    # Spine totals via ps.
    try:
        txt = _run(["ps", "-eo", "pid,pcpu,rss,args"], timeout=2)
        spine_cpu = 0.0
        spine_mem_kb = 0
        spine_n = 0
        for line in txt.splitlines()[1:]:
            line = line.strip()
            if not line:
                continue
            parts = line.split(None, 3)
            if len(parts) < 4:
                continue
            _, pcpu, rss, args = parts
            if not _is_spine_cmdline(args):
                continue
            try:
                spine_cpu += float(pcpu)
                spine_mem_kb += int(rss)
                spine_n += 1
            except ValueError:
                continue
        # ps pcpu is per-core; normalize.
        try:
            ncpu = os.cpu_count() or 1
        except Exception:
            ncpu = 1
        out["spine_cpu_pct"] = round(spine_cpu / max(1, ncpu), 2)
        out["spine_mem_mb"] = int(spine_mem_kb / 1024)
        out["spine_proc_count"] = spine_n
    except Exception:
        pass
    return out


def _try_cli_macos():
    out = {}
    # CPU% from top -l 1 -n 0 (one sample, header only).
    try:
        txt = _run(["top", "-l", "1", "-n", "0"], timeout=2)
        # Line looks like: "CPU usage: 5.12% user, 3.41% sys, 91.46% idle"
        m = re.search(r"CPU usage:\s+([0-9.]+)%\s+user,\s+([0-9.]+)%\s+sys,\s+([0-9.]+)%\s+idle", txt)
        if m:
            idle = float(m.group(3))
            out["cpu_pct"] = round(max(0.0, 100.0 - idle), 2)
    except Exception:
        pass
    # Memory: prefer sysctl + vm_stat for clean numbers.
    try:
        total_b = 0
        sct = _run(["sysctl", "-n", "hw.memsize"], timeout=2).strip()
        if sct.isdigit():
            total_b = int(sct)
        # vm_stat reports pages; page size from sysctl.
        psz = _run(["sysctl", "-n", "hw.pagesize"], timeout=2).strip()
        page = int(psz) if psz.isdigit() else 4096
        vm = _run(["vm_stat"], timeout=2)
        # Active + Wired + Compressed is a reasonable "used" proxy.
        def _pages(label):
            m = re.search(r"Pages " + label + r"[^:]*:\s+([0-9]+)", vm)
            return int(m.group(1)) if m else 0
        active = _pages("active")
        wired = _pages("wired down")
        # "Pages occupied by compressor" on newer macOS.
        compressed = 0
        m = re.search(r"Pages occupied by compressor[^:]*:\s+([0-9]+)", vm)
        if m:
            compressed = int(m.group(1))
        used_b = (active + wired + compressed) * page
        if total_b > 0:
            out["mem_total_mb"] = int(total_b / (1024 * 1024))
            out["mem_used_mb"] = int(used_b / (1024 * 1024))
    except Exception:
        pass
    # Load avg via uptime: "... load averages: 1.23 1.10 0.95"
    try:
        txt = _run(["uptime"], timeout=2)
        m = re.search(r"load averages?:\s+([0-9.]+)[ ,]+([0-9.]+)[ ,]+([0-9.]+)", txt)
        if m:
            out["load_avg_1m"] = round(float(m.group(1)), 2)
            out["load_avg_5m"] = round(float(m.group(2)), 2)
            out["load_avg_15m"] = round(float(m.group(3)), 2)
    except Exception:
        pass
    # Disk via df -k /
    try:
        txt = _run(["df", "-k", "/"], timeout=2)
        lines = [l for l in txt.splitlines() if l.strip()]
        if len(lines) >= 2:
            parts = lines[-1].split()
            if len(parts) >= 4:
                total_k = int(parts[1])
                used_k = int(parts[2])
                out["disk_total_gb"] = round(total_k / (1024 * 1024), 2)
                out["disk_used_gb"] = round(used_k / (1024 * 1024), 2)
    except Exception:
        pass
    # Spine totals via ps -axo pid,pcpu,rss,command
    try:
        txt = _run(["ps", "-axo", "pid,pcpu,rss,command"], timeout=2)
        spine_cpu = 0.0
        spine_mem_kb = 0
        spine_n = 0
        for line in txt.splitlines()[1:]:
            line = line.strip()
            if not line:
                continue
            parts = line.split(None, 3)
            if len(parts) < 4:
                continue
            _, pcpu, rss, args = parts
            if not _is_spine_cmdline(args):
                continue
            try:
                spine_cpu += float(pcpu)
                spine_mem_kb += int(rss)
                spine_n += 1
            except ValueError:
                continue
        try:
            ncpu = os.cpu_count() or 1
        except Exception:
            ncpu = 1
        out["spine_cpu_pct"] = round(spine_cpu / max(1, ncpu), 2)
        out["spine_mem_mb"] = int(spine_mem_kb / 1024)
        out["spine_proc_count"] = spine_n
    except Exception:
        pass
    return out


def main():
    try:
        result = _try_psutil()
        if not result:
            if sys.platform == "darwin":
                result = _try_cli_macos()
            else:
                result = _try_cli_linux()
        if not result:
            result = {}
        _emit(result)
    except Exception:
        # Belt-and-braces: if everything blows up, still print {} so the
        # heartbeat payload is valid JSON.
        sys.stdout.write("{}\n")


if __name__ == "__main__":
    main()
'

# Run the helper with a hard deadline. We capture its single line of
# output and print it. On any error, fall back to '{}'.
(
  python3 -c "$_PYHELPER" 2>/dev/null &
  PYPID=$!
  # Watchdog: kill the helper if it overruns.
  (
    sleep "$_VITALS_DEADLINE_S"
    kill -9 "$PYPID" 2>/dev/null
  ) &
  WPID=$!
  if wait "$PYPID" 2>/dev/null; then
    kill -9 "$WPID" 2>/dev/null || true
    exit 0
  fi
  kill -9 "$WPID" 2>/dev/null || true
  exit 1
) || _emit_empty
