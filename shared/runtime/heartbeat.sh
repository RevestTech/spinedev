#!/usr/bin/env bash
# heartbeat.sh — Pass H (Spine Hub). Background loop that emits an
# InstanceHeartbeat event every $SPINE_HEARTBEAT_INTERVAL_S seconds (default
# 60). One process per `team.sh up`; team.sh down kills it via the PID
# file. Designed to stay focused — the watchdog supervises managers, this
# loop supervises only "is this Spine instance still alive?".
#
# Inherits from team.sh::cmd_up:
#   SPINE_GROUP_ID, SPINE_HOST_ID, SPINE_VERSION_SHA, SPINE_PROJECT_SLUG,
#   SPINE_PROJECT_PATH
#
# Self-protection: a tiny parent-PID watch loop. If the parent shell that
# spawned us exits (e.g., the user `kill`s team.sh without running
# `team.sh down`), we notice within INTERVAL_S and exit cleanly. The PID
# file is removed on EXIT either way.

set -uo pipefail

INTERVAL_S="${SPINE_HEARTBEAT_INTERVAL_S:-60}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck source=/dev/null
source "$SCRIPT_DIR/db-outbox.sh"

HEARTBEAT_PID_FILE=".planning/orchestration/agent-handoff/heartbeat.pid"
mkdir -p "$(dirname "$HEARTBEAT_PID_FILE")"
echo $$ > "$HEARTBEAT_PID_FILE"

# Parent PID at spawn time. team.sh up backgrounds us via `nohup ... &
# disown`, so the immediate parent is normally PID 1 once disowned. We
# still record it so that an orchestration shell that wasn't disowned
# can be tracked. If PPID is 1 we have no orphan signal to watch for and
# rely on team.sh down to clean us up.
HEARTBEAT_PARENT_PID="${SPINE_HEARTBEAT_PARENT_PID:-$PPID}"

cleanup() {
  rm -f "$HEARTBEAT_PID_FILE" 2>/dev/null || true
}
trap cleanup EXIT TERM INT

# Pass L: include the configured update channel on every heartbeat so the
# v_instance_drift view stays accurate even if the InstanceStarted event
# missed the channel (e.g., upgrade from pre-L). Default 'stable' matches
# the dashboard default.
HB_CHANNEL="${SPINE_UPDATE_CHANNEL:-stable}"

# Pass M: every heartbeat carries a vitals snapshot — total host CPU%,
# memory, disk, load avg, plus the Spine-attributed CPU%/RSS/proc count
# summed across all spine_* daemons. vitals.sh emits a one-line JSON
# object on stdout; on any failure it emits "{}" so the payload stays
# valid JSON either way. We deliberately do not let it block: a hard
# deadline lives inside vitals.sh.
_build_heartbeat_payload() {
  local vitals_json
  vitals_json="$(bash "$SCRIPT_DIR/vitals.sh" 2>/dev/null || echo '{}')"
  # Defensive: if vitals.sh somehow printed nothing, use {}.
  [[ -z "$vitals_json" ]] && vitals_json='{}'
  printf '{"vitals":%s,"channel":"%s"}' "$vitals_json" "$HB_CHANNEL"
}

# First tick is immediate so the dashboard shows the instance as alive
# without waiting a full INTERVAL_S.
spine_outbox_emit_instance_event "InstanceHeartbeat" "$(_build_heartbeat_payload)"

while true; do
  # If our parent shell vanished, exit. Skip the check if PPID is 1
  # (init / launchd reaped us) — in that case team.sh down is the
  # contract for shutdown.
  if [[ "$HEARTBEAT_PARENT_PID" != "1" ]] && ! kill -0 "$HEARTBEAT_PARENT_PID" 2>/dev/null; then
    exit 0
  fi
  sleep "$INTERVAL_S"
  spine_outbox_emit_instance_event "InstanceHeartbeat" "$(_build_heartbeat_payload)"
done
