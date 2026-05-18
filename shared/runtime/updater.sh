#!/usr/bin/env bash
# updater.sh — Pass L (Spine Hub Pillar 2). Periodic puller for the
# SpineDevelopment template.
#
# Big picture: SpineDevelopment is a *templating* project. Installations
# consume it. This daemon lets an admin update the template repo once,
# then every fleet member's local clone (the directory that `install.sh`
# was originally invoked from) catches up automatically.
#
# Modes:
#   off (default)  — daemon does nothing; never started by team.sh up
#   pull           — periodically `git fetch && git pull --ff-only` on the
#                    template clone
#   pull-pin       — `git fetch`, then fast-forward to the commit pinned by
#                    the hub (queried from spine_release for the configured
#                    channel). When SPINE_DB_URL is unset, gracefully falls
#                    back to plain `git pull --ff-only`.
#
# Env vars (read on every loop, so an operator can flip them via the
# environment of the parent shell without restarting):
#   SPINE_UPDATE_ENABLED=1                  enable the daemon (default 0)
#   SPINE_UPDATE_MODE=pull|pull-pin         default pull-pin
#   SPINE_UPDATE_CHANNEL=stable|beta|canary default stable
#   SPINE_UPDATE_INTERVAL_S=300             how often to check (default 5min)
#   SPINE_UPDATE_TEMPLATE_DIR=/path/to/clone
#                                           local clone of SpineDevelopment
#                                           we pull *from*. Required when
#                                           mode=pull or pull-pin. If unset
#                                           or not a git repo, the daemon
#                                           exits cleanly.
#   SPINE_DB_URL=postgresql://...           used by pull-pin to query
#                                           v_release_heads. If unset,
#                                           pull-pin falls back to plain pull.
#
# Safety:
#   * Only fast-forwards. Never `git reset --hard`, never `--force`.
#   * Only touches the template clone — does NOT replace files in the
#     consuming project's scripts/ tree.
#   * Does NOT restart running daemons. Mid-engagement restarts are risky
#     and out of scope for Pass L; that's a deliberate follow-up decision.
#
# Lifecycle: started by team.sh::cmd_up when SPINE_UPDATE_ENABLED=1, killed
# by team.sh::cmd_down via the PID file. Parent-PID watch mirrors
# heartbeat.sh so a SIGKILL'd team.sh leaves no orphan.

set -uo pipefail

INTERVAL_S="${SPINE_UPDATE_INTERVAL_S:-300}"
MODE="${SPINE_UPDATE_MODE:-pull-pin}"
CHANNEL="${SPINE_UPDATE_CHANNEL:-stable}"
TEMPLATE_DIR="${SPINE_UPDATE_TEMPLATE_DIR:-}"
PARENT_PID="${SPINE_UPDATE_PARENT_PID:-0}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
[[ -f "$SCRIPT_DIR/db-outbox.sh" ]] && source "$SCRIPT_DIR/db-outbox.sh"

UPDATER_PID_FILE=".planning/orchestration/agent-handoff/updater.pid"
mkdir -p "$(dirname "$UPDATER_PID_FILE")" 2>/dev/null || true
echo $$ > "$UPDATER_PID_FILE"
cleanup() { rm -f "$UPDATER_PID_FILE" 2>/dev/null || true; }
trap cleanup EXIT TERM INT

# Validate up front. If the operator forgot to set SPINE_UPDATE_TEMPLATE_DIR
# (or pointed it at a non-repo) we exit cleanly — team.sh up still succeeds.
if [[ -z "$TEMPLATE_DIR" || ! -d "$TEMPLATE_DIR/.git" ]]; then
  echo "updater.sh: SPINE_UPDATE_TEMPLATE_DIR not set or not a git repo — exiting" >&2
  exit 0
fi

# Best-effort outbox emit. Mirrors the contract used elsewhere — failures
# must never propagate.
emit_event() {
  local kind="$1" payload="$2"
  if declare -F spine_outbox_emit_instance_event >/dev/null 2>&1; then
    spine_outbox_emit_instance_event "$kind" "$payload" 2>/dev/null || true
  fi
}

# Query the channel head from Postgres. Prints the 40-char commit_sha on
# stdout and returns 0 on success. Returns 1 (with no stdout) when:
#   * SPINE_DB_URL is unset
#   * psycopg isn't installed
#   * the query errors
#   * no release has been promoted for the channel yet
# The caller treats any non-zero return as "no pin available" and falls
# through to a plain `git pull --ff-only`.
pin_for_channel() {
  if [[ -z "${SPINE_DB_URL:-}" ]]; then
    return 1
  fi
  python3 - <<'PY' 2>/dev/null
import os, sys
try:
    import psycopg
except ImportError:
    sys.exit(1)
channel = os.environ.get("SPINE_UPDATE_CHANNEL", "stable")
try:
    with psycopg.connect(os.environ["SPINE_DB_URL"]) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT commit_sha FROM v_release_heads WHERE channel = %s",
            (channel,),
        )
        row = cur.fetchone()
        if row and row[0]:
            print(row[0])
        else:
            sys.exit(1)
except Exception:
    sys.exit(1)
PY
}

while true; do
  # Parent-PID watch (matches heartbeat.sh). If the team.sh up shell has
  # gone away, exit cleanly so we don't leak.
  if (( PARENT_PID > 0 )) && [[ "$PARENT_PID" != "1" ]] && ! kill -0 "$PARENT_PID" 2>/dev/null; then
    exit 0
  fi

  cd "$TEMPLATE_DIR" || { sleep "$INTERVAL_S"; continue; }

  # Always fetch first so we have the latest refs even if the pin query
  # fails (operator may still want to manually inspect).
  git fetch --quiet 2>/dev/null || true

  case "$MODE" in
    pull)
      git pull --ff-only --quiet 2>/dev/null
      new_sha=$(git rev-parse HEAD 2>/dev/null)
      emit_event "SpineUpdateApplied" "{\"mode\":\"pull\",\"channel\":\"$CHANNEL\",\"commit_sha\":\"$new_sha\"}"
      ;;
    pull-pin)
      target=$(pin_for_channel)
      if [[ -z "$target" ]]; then
        # No pin → fall through to plain pull. This keeps the daemon
        # useful in dev (no DB) and on first boot before any release has
        # been promoted.
        git pull --ff-only --quiet 2>/dev/null
        new_sha=$(git rev-parse HEAD 2>/dev/null)
        emit_event "SpineUpdateApplied" "{\"mode\":\"pull-pin-fallback\",\"channel\":\"$CHANNEL\",\"commit_sha\":\"$new_sha\"}"
      else
        current=$(git rev-parse HEAD 2>/dev/null)
        if [[ "$current" != "$target" ]]; then
          # Only check out the target if it's reachable on origin —
          # protects against admins promoting commits that haven't been
          # pushed yet, or that exist on a stale local branch.
          if git merge-base --is-ancestor "$target" origin/HEAD 2>/dev/null \
             || git cat-file -e "${target}^{commit}" 2>/dev/null; then
            git -c advice.detachedHead=false checkout --quiet "$target" 2>/dev/null
            new_sha=$(git rev-parse HEAD 2>/dev/null)
            emit_event "SpineUpdateApplied" "{\"mode\":\"pull-pin\",\"channel\":\"$CHANNEL\",\"commit_sha\":\"$new_sha\",\"target\":\"$target\"}"
          else
            emit_event "SpineUpdateSkipped" "{\"reason\":\"target_not_reachable\",\"target\":\"$target\"}"
          fi
        fi
      fi
      ;;
    *)
      ;;  # off or unknown — no-op
  esac

  sleep "$INTERVAL_S"
done
