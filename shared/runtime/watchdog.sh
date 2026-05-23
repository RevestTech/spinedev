#!/usr/bin/env bash
# watchdog.sh — v1 file-bus manager supervisor (legacy).
#
# v3 Hub uses container lifecycle + shared/runtime/heartbeat.sh instead.
# This script no-ops when `.planning/orchestration/` is absent (normal on
# a platform-repo clone). Install the v1 template into a consumer project
# to activate — see docs/_archived/v1-PROTOCOL.md.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Wave 3 (Squad A): watchdog.sh migrated lib/ → shared/runtime/. REPO_ROOT
# now climbs two dirs (shared/runtime/.. → shared/.. → repo root).
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT" || exit 1

TEAM_BASE=".planning/orchestration/agent-handoff/teams"
HANDOFF_BASE=".planning/orchestration/agent-handoff"
if [[ ! -d "$HANDOFF_BASE" ]]; then
  echo "watchdog: v1 file-bus not present (.planning/ absent) — idle (v3 uses Hub)" >&2
  exit 0
fi

# Wave 6 Stream K: lib/ retired. roles.sh is resolved from scripts/ in
# consumer installs only.
if [[ -f "$SCRIPT_DIR/roles.sh" ]]; then
  ROLES_SH="$SCRIPT_DIR/roles.sh"
elif [[ -f "$REPO_ROOT/scripts/roles.sh" ]]; then
  ROLES_SH="$REPO_ROOT/scripts/roles.sh"
else
  echo "✗ roles.sh missing — v1 file-bus not installed (see docs/_archived/v1-PROTOCOL.md)." >&2
  exit 0
fi
# shellcheck source=/dev/null
source "$ROLES_SH"
ROLES=("${SPINE_TEAM_ROLES[@]}")

DAEMON_PATH="scripts/team-agent-daemon.sh"
WATCHDOG_LOG="$HANDOFF_BASE/watchdog.log"
WATCHDOG_PID="$HANDOFF_BASE/watchdog.pid"

# Auxiliary supervised processes beyond per-role managers.
#
# Lifecycle contract: a PID file is "live intent" — its presence means
# the launcher (team.sh up / spine-connect.sh) wants this process
# running. The owning process is responsible for removing its PID file
# on graceful shutdown (via EXIT trap or its companion `down` command).
# Therefore: PID file present + process dead = needs restart.
# PID file absent = operator stopped it, leave it alone.
SPINE_HEARTBEAT_PID_FILE="$HANDOFF_BASE/heartbeat.pid"
SPINE_WATCHER_PID_FILE="$HANDOFF_BASE/.watcher.pid"
SPINE_WATCHER_LOG="$HANDOFF_BASE/watcher.log"

POLL_INTERVAL="${WATCHDOG_POLL_S:-60}"
HEARTBEAT_TIMEOUT_S="${HEARTBEAT_TIMEOUT_S:-300}"   # 5 min default

mkdir -p "$HANDOFF_BASE"

# If another watchdog is already running, exit.
if [[ -f "$WATCHDOG_PID" ]] && kill -0 "$(cat "$WATCHDOG_PID" 2>/dev/null)" 2>/dev/null; then
  echo "watchdog already running pid=$(cat "$WATCHDOG_PID")" >&2
  exit 0
fi
echo $$ > "$WATCHDOG_PID"

log() {
  printf '%s [watchdog] %s\n' "$(date -u +%FT%TZ)" "$*" >> "$WATCHDOG_LOG" 2>/dev/null
}

manager_pid_for() {
  # Pass K: prefer the daemon-written PID file. Falls back to pgrep -f
  # for any pre-K daemon still running without one. The PID file lives
  # at <TEAM_BASE>/<role>/state/pids/manager.pid.
  local role="$1"
  local pid_file="$TEAM_BASE/$role/state/pids/manager.pid"
  if [[ -f "$pid_file" ]]; then
    local pid
    pid="$(cat "$pid_file" 2>/dev/null)"
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      echo "$pid"
      return
    fi
    # Stale PID file — clean it up so future checks don't tickle it.
    rm -f "$pid_file" 2>/dev/null
  fi
  pgrep -f "team-agent-daemon.sh $role manager$" 2>/dev/null | head -1
}

heartbeat_age_s() {
  local f="$1"
  [[ -f "$f" ]] || { echo 999999; return; }
  local now mt
  now=$(date +%s)
  if stat -f %m "$f" >/dev/null 2>&1; then
    mt=$(stat -f %m "$f")  # macOS
  else
    mt=$(stat -c %Y "$f")  # Linux
  fi
  echo $(( now - mt ))
}

restart_manager() {
  local role="$1" reason="$2"
  log "RESTART $role manager — $reason"
  # Try to kill any zombie first
  local existing
  existing=$(manager_pid_for "$role")
  if [[ -n "$existing" ]]; then
    kill "$existing" 2>/dev/null || true
    sleep 1
    kill -9 "$existing" 2>/dev/null || true
  fi
  nohup bash "$DAEMON_PATH" "$role" manager </dev/null >/dev/null 2>&1 &
  local new_pid=$!
  log "  $role manager restarted pid=$new_pid"
  notify_hook "[watchdog] $role manager auto-restarted" "Reason: $reason. New pid: $new_pid"
}

notify_hook() {
  local hook="$HOME/.spine-development/notify.sh"
  if [[ -x "$hook" ]]; then
    "$hook" "$1" "$2" </dev/null >/dev/null 2>&1 &
  fi
}

# Supervise an auxiliary process by PID-file presence.
#
# Args: <name> <pid_file> <launcher_script> [log_file]
#
# Semantics: if the PID file is absent, do nothing (operator stopped
# it). If present and the PID is alive, do nothing. If present but the
# PID is dead, relaunch via `bash <launcher_script>` and overwrite the
# PID file with the new PID. The launcher must be a script that exec's
# the long-running process (so $! is meaningful for the PID file).
supervise_aux() {
  local name="$1" pid_file="$2" launcher="$3" log_file="${4:-/dev/null}"
  [[ -f "$pid_file" ]] || return 0
  local pid
  pid="$(cat "$pid_file" 2>/dev/null | tr -d '[:space:]')"
  if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
    return 0
  fi
  if [[ ! -f "$launcher" ]]; then
    log "SKIP $name supervise — launcher missing: $launcher"
    return 0
  fi
  log "RESTART $name — pid file present but process dead (stale pid=$pid)"
  rm -f "$pid_file" 2>/dev/null || true
  if [[ "$log_file" == "/dev/null" ]]; then
    nohup bash "$launcher" </dev/null >/dev/null 2>&1 &
  else
    nohup bash "$launcher" </dev/null >>"$log_file" 2>&1 &
  fi
  local new_pid=$!
  disown 2>/dev/null || true
  echo "$new_pid" > "$pid_file"
  log "  $name restarted pid=$new_pid"
  notify_hook "[watchdog] $name auto-restarted" "Stale pid=$pid. New pid: $new_pid"
}

cleanup() {
  log "watchdog stopping (pid=$$)"
  rm -f "$WATCHDOG_PID"
  exit 0
}
trap cleanup TERM INT

log "watchdog v1.2 starting (poll=${POLL_INTERVAL}s, heartbeat_timeout=${HEARTBEAT_TIMEOUT_S}s, pid=$$)"

while true; do
  for role in "${ROLES[@]}"; do
    pid=$(manager_pid_for "$role")
    heartbeat="$TEAM_BASE/$role/state/heartbeat"

    if [[ -z "$pid" ]]; then
      restart_manager "$role" "no manager process found"
      continue
    fi

    if [[ ! -f "$heartbeat" ]]; then
      # Daemon hasn't checked in yet — give it a grace period
      continue
    fi

    age=$(heartbeat_age_s "$heartbeat")
    if (( age > HEARTBEAT_TIMEOUT_S )); then
      restart_manager "$role" "heartbeat ${age}s old (> ${HEARTBEAT_TIMEOUT_S}s)"
    fi
  done

  # Auxiliary supervised processes: heartbeat loop and standalone watcher.
  # Both follow the "pid file present + process dead = restart" contract.
  # Wave 3 (Squad A): heartbeat.sh co-located in shared/runtime/ (this
  # dir). Wave 6 Stream K: lib/ retired — run-standalone-watcher.sh is
  # now resolved from the installer-produced scripts/ directory until the
  # Wave 4 federation rebuild replaces it with a federation client.
  supervise_aux "heartbeat" \
    "$SPINE_HEARTBEAT_PID_FILE" \
    "$SCRIPT_DIR/heartbeat.sh"
  if [[ -f "$SCRIPT_DIR/run-standalone-watcher.sh" ]]; then
    WATCHER_LAUNCHER="$SCRIPT_DIR/run-standalone-watcher.sh"
  else
    WATCHER_LAUNCHER="$REPO_ROOT/scripts/run-standalone-watcher.sh"
  fi
  supervise_aux "watcher" \
    "$SPINE_WATCHER_PID_FILE" \
    "$WATCHER_LAUNCHER" \
    "$SPINE_WATCHER_LOG"

  sleep "$POLL_INTERVAL"
done
