#!/usr/bin/env bash
# watchdog.sh — supervises the 8 manager daemons.
#
# Reads each manager's state/heartbeat file. If mtime > HEARTBEAT_TIMEOUT_S
# old, presumes daemon dead and re-launches it. Workers are not directly
# supervised — managers re-spawn workers as needed via the file bus.
#
# Idempotent: starts once on `team up`. Safe to kill and restart.
#
# Logs to .planning/orchestration/agent-handoff/watchdog.log
# State at .planning/orchestration/agent-handoff/watchdog.pid

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT" || exit 1

if [[ -f "$SCRIPT_DIR/roles.sh" ]]; then
  # shellcheck source=/dev/null
  source "$SCRIPT_DIR/roles.sh"
  ROLES=("${SPINE_TEAM_ROLES[@]}")
else
  echo "✗ scripts/roles.sh missing — re-run SpineDevelopment installer." >&2
  exit 1
fi

TEAM_BASE=".planning/orchestration/agent-handoff/teams"
HANDOFF_BASE=".planning/orchestration/agent-handoff"
DAEMON_PATH="scripts/team-agent-daemon.sh"
WATCHDOG_LOG="$HANDOFF_BASE/watchdog.log"
WATCHDOG_PID="$HANDOFF_BASE/watchdog.pid"

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
  pgrep -f "team-agent-daemon.sh $1 manager$" 2>/dev/null | head -1
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
  sleep "$POLL_INTERVAL"
done
