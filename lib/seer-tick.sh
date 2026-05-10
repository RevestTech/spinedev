#!/usr/bin/env bash
# seer-tick.sh — periodic nudge for the seer role.
#
# The seer role observes; it doesn't poll. To get a refreshed status page
# every N minutes, this script writes a tiny "refresh" directive to the
# seer's directive.md, which the seer daemon picks up within 8 seconds and
# regenerates the status page.
#
# Run as a background loop:
#   nohup bash scripts/seer-tick.sh > /dev/null 2>&1 &
#
# Or wire into a cron / launchd job. The default interval is 5 minutes.

INTERVAL_S="${SEER_INTERVAL_S:-300}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT" || exit 1

SEER_FILE=".planning/orchestration/agent-handoff/teams/seer/directive.md"

while true; do
  # Only nudge if seer is currently idle (last write was a status report,
  # not an in-flight directive). Avoid stomping work.
  if [[ -f "$SEER_FILE" ]]; then
    hdr=$(head -1 "$SEER_FILE")
    case "$hdr" in
      "# Status"*|"# (idle"*)
        cat > "$SEER_FILE.tmp" <<EOF
# Directive — Refresh team status

## Tier hint: low

Generate a fresh team status page per your role-prompt. Read all manager directive.md
files, extract state, write the status.md with a timestamp. Replace this file with
"# Status — <timestamp>" containing the table.
EOF
        mv "$SEER_FILE.tmp" "$SEER_FILE"
        ;;
    esac
  fi
  sleep "$INTERVAL_S"
done
