#!/usr/bin/env bash
# notify.sh — default notification dispatcher.
#
# Installed to ~/.spine-development/notify.sh by install.sh.
# Daemons call this on completion / approval-needed / watchdog-restart events.
#
# Usage:
#   notify.sh "title" "body"
#
# Channels:
#   - macOS native notification (if osascript available)
#   - Slack webhook (if SLACK_WEBHOOK env var set)
#   - Append to ~/.spine-development/notifications.log (always)
#
# Customize this file freely — it lives in your home dir, not the repo.

set -uo pipefail

TITLE="${1:-Spine}"
BODY="${2:-(no message)}"

LOG_FILE="$HOME/.spine-development/notifications.log"
mkdir -p "$(dirname "$LOG_FILE")"
printf '%s | %s | %s\n' "$(date -u +%FT%TZ)" "$TITLE" "$BODY" >> "$LOG_FILE" 2>/dev/null

# macOS native notification
if command -v osascript >/dev/null 2>&1; then
  # Escape double quotes for AppleScript
  esc_title=$(printf '%s' "$TITLE" | sed 's/"/\\"/g')
  esc_body=$(printf '%s' "$BODY" | sed 's/"/\\"/g')
  osascript -e "display notification \"$esc_body\" with title \"$esc_title\"" 2>/dev/null || true
fi

# ntfy.sh push to your phone (set NTFY_TOPIC in your shell env)
# Setup: install ntfy app on phone, subscribe to your topic. No signup needed.
# Pick a hard-to-guess topic — anyone who knows it can post to your phone.
if [[ -n "${NTFY_TOPIC:-}" ]] && command -v curl >/dev/null 2>&1; then
  ntfy_server="${NTFY_SERVER:-https://ntfy.sh}"
  curl -s \
    -H "Title: $TITLE" \
    -H "Priority: ${NTFY_PRIORITY:-default}" \
    -H "Tags: ${NTFY_TAGS:-robot}" \
    -d "$BODY" \
    "$ntfy_server/$NTFY_TOPIC" >/dev/null 2>&1 || true
fi

# Pushover (set PUSHOVER_TOKEN + PUSHOVER_USER in your shell env)
if [[ -n "${PUSHOVER_TOKEN:-}" && -n "${PUSHOVER_USER:-}" ]] && command -v curl >/dev/null 2>&1; then
  curl -s \
    -F "token=$PUSHOVER_TOKEN" \
    -F "user=$PUSHOVER_USER" \
    -F "title=$TITLE" \
    -F "message=$BODY" \
    https://api.pushover.net/1/messages.json >/dev/null 2>&1 || true
fi

# Build a safe JSON payload using python's json.dumps. Title/body may
# contain quotes, backslashes, newlines, or non-ASCII; printf+sed mangled
# them and produced invalid JSON that webhook receivers silently dropped.
# Only used if curl is available AND python3 is available; otherwise the
# Slack/Discord paths are skipped silently (the local log file remains
# the source of truth).
build_chat_payload() {
  # $1: schema ('slack' or 'discord'); $2: title; $3: body
  command -v python3 >/dev/null 2>&1 || return 1
  TITLE_IN="$2" BODY_IN="$3" SCHEMA="$1" python3 - <<'PY'
import json, os, sys
title = os.environ.get('TITLE_IN', '')
body  = os.environ.get('BODY_IN', '')
schema = os.environ.get('SCHEMA', 'slack')
if schema == 'discord':
    sys.stdout.write(json.dumps({'content': f"**{title}**\n{body}"}))
else:
    sys.stdout.write(json.dumps({'text': f"*{title}*\n{body}"}))
PY
}

# Slack webhook (set SLACK_WEBHOOK in your shell env)
if [[ -n "${SLACK_WEBHOOK:-}" ]] && command -v curl >/dev/null 2>&1; then
  if payload=$(build_chat_payload slack "$TITLE" "$BODY"); then
    curl -s -X POST -H 'Content-Type: application/json' \
      -d "$payload" "$SLACK_WEBHOOK" >/dev/null 2>&1 || true
  fi
fi

# Discord webhook (set DISCORD_WEBHOOK in your shell env)
if [[ -n "${DISCORD_WEBHOOK:-}" ]] && command -v curl >/dev/null 2>&1; then
  if payload=$(build_chat_payload discord "$TITLE" "$BODY"); then
    curl -s -X POST -H 'Content-Type: application/json' \
      -d "$payload" "$DISCORD_WEBHOOK" >/dev/null 2>&1 || true
  fi
fi

# Email (set NOTIFY_EMAIL_TO; uses macOS `mail` if available)
if [[ -n "${NOTIFY_EMAIL_TO:-}" ]] && command -v mail >/dev/null 2>&1; then
  printf '%s\n' "$BODY" | mail -s "$TITLE" "$NOTIFY_EMAIL_TO" 2>/dev/null || true
fi

exit 0
