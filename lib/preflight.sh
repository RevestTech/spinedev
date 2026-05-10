#!/usr/bin/env bash
# preflight.sh — verify the host has the tools the team needs.
#
# Usage:
#   bash preflight.sh           # human-readable report, exit 0 if all REQUIRED present
#   bash preflight.sh --strict  # exit 1 if ANY (required or recommended) missing
#   bash preflight.sh --quiet   # one-line summary only
#
# Categories:
#   REQUIRED — the team will not function without these
#   RECOMMENDED — degraded experience without these (no timeouts, no notifications, etc)
#   AGENT CLI — at least ONE of these must be present
#   PLATFORM — current OS detection + caveats

set -uo pipefail

STRICT=false
QUIET=false
for arg in "$@"; do
  case "$arg" in
    --strict) STRICT=true ;;
    --quiet)  QUIET=true ;;
  esac
done

if [[ -t 1 ]] && ! $QUIET; then
  C_GREEN='\033[0;32m'; C_YELLOW='\033[0;33m'; C_RED='\033[0;31m'
  C_DIM='\033[2m'; C_BLUE='\033[0;34m'; C_RESET='\033[0m'
else
  C_GREEN=''; C_YELLOW=''; C_RED=''; C_DIM=''; C_BLUE=''; C_RESET=''
fi

ok()    { $QUIET || printf "  ${C_GREEN}✓${C_RESET} %s\n" "$*"; }
warn()  { $QUIET || printf "  ${C_YELLOW}!${C_RESET} %s\n" "$*"; }
miss()  { $QUIET || printf "  ${C_RED}✗${C_RESET} %s\n" "$*"; }
hint()  { $QUIET || printf "    ${C_DIM}%s${C_RESET}\n" "$*"; }
step()  { $QUIET || printf "${C_BLUE}▸${C_RESET} %s\n" "$*"; }

REQUIRED_MISSING=0
OPTIONAL_MISSING=0
AGENT_FOUND=""

# --- platform detection ---
$QUIET || step "Platform"
UNAME="$(uname -s 2>/dev/null || echo unknown)"
case "$UNAME" in
  Darwin)  PLATFORM="macOS"     ;;
  Linux)
    if grep -qi microsoft /proc/version 2>/dev/null || [[ -n "${WSL_DISTRO_NAME:-}" ]]; then
      PLATFORM="Linux (WSL)"
    else
      PLATFORM="Linux"
    fi
    ;;
  CYGWIN*|MINGW*|MSYS*) PLATFORM="Windows (Git Bash / MSYS — partial support, see REQUIREMENTS.md)" ;;
  *) PLATFORM="$UNAME (untested)" ;;
esac
ok "$PLATFORM"

# Bash version
$QUIET || echo
$QUIET || step "Required: shell + core utilities"
BASH_MAJOR=${BASH_VERSINFO[0]:-0}
if (( BASH_MAJOR >= 4 )); then
  ok "bash $BASH_VERSION (>= 4 is fine)"
elif (( BASH_MAJOR == 3 )); then
  warn "bash $BASH_VERSION — works, but macOS default is 3.2; some features (esp. associative arrays) need bash 4+"
  hint "macOS upgrade: brew install bash"
else
  miss "bash version too old: $BASH_VERSION"
  hint "Need bash 3.2+. Current shell may not be bash."
  REQUIRED_MISSING=$((REQUIRED_MISSING + 1))
fi

check_required() {
  local name="$1" hint_macos="$2" hint_linux="$3"
  if command -v "$name" >/dev/null 2>&1; then
    ok "$name → $(command -v "$name")"
  else
    miss "$name (REQUIRED)"
    case "$PLATFORM" in
      macOS*)        hint "macOS: $hint_macos" ;;
      Linux*)        hint "Linux: $hint_linux" ;;
      Windows*)      hint "Windows: install via WSL2 (recommended) or Git Bash" ;;
    esac
    REQUIRED_MISSING=$((REQUIRED_MISSING + 1))
  fi
}

check_optional() {
  local name="$1" why="$2" hint_macos="$3" hint_linux="$4"
  if command -v "$name" >/dev/null 2>&1; then
    ok "$name → $(command -v "$name")"
  else
    warn "$name not found — $why"
    case "$PLATFORM" in
      macOS*)        hint "macOS: $hint_macos" ;;
      Linux*)        hint "Linux: $hint_linux" ;;
    esac
    OPTIONAL_MISSING=$((OPTIONAL_MISSING + 1))
  fi
}

check_required "git"     "preinstalled or: brew install git"          "apt install git"
check_required "curl"    "preinstalled"                                "apt install curl"
check_required "tar"     "preinstalled"                                "apt install tar"
check_required "find"    "preinstalled"                                "apt install findutils"
check_required "awk"     "preinstalled"                                "apt install gawk"
check_required "sed"     "preinstalled"                                "apt install sed"
check_required "grep"    "preinstalled"                                "apt install grep"
check_required "pgrep"   "preinstalled"                                "apt install procps"
check_required "ln"      "preinstalled"                                "apt install coreutils"

# shasum or sha256sum
if command -v shasum >/dev/null 2>&1 || command -v sha256sum >/dev/null 2>&1; then
  if command -v shasum >/dev/null 2>&1; then
    ok "shasum → $(command -v shasum)"
  else
    ok "sha256sum → $(command -v sha256sum)  (template currently uses shasum — works fine on Linux distros that have sha256sum but not shasum, but the daemon prefers shasum)"
  fi
else
  miss "neither shasum nor sha256sum found (REQUIRED for hash-based change detection)"
  REQUIRED_MISSING=$((REQUIRED_MISSING + 1))
fi

# --- recommended ---
$QUIET || echo
$QUIET || step "Recommended (degraded behavior without these)"

# timeout / gtimeout
if command -v gtimeout >/dev/null 2>&1; then
  ok "gtimeout (GNU coreutils) → $(command -v gtimeout)"
elif command -v timeout >/dev/null 2>&1; then
  ok "timeout → $(command -v timeout)"
else
  warn "no timeout/gtimeout found — daemon will run agents without a hard timeout"
  case "$PLATFORM" in
    macOS*) hint "macOS: brew install coreutils  (provides gtimeout)" ;;
    Linux*) hint "Linux: apt install coreutils" ;;
  esac
  OPTIONAL_MISSING=$((OPTIONAL_MISSING + 1))
fi

# stat (BSD or GNU is fine — daemon already detects)
if command -v stat >/dev/null 2>&1; then
  ok "stat → $(command -v stat)"
else
  warn "stat not found — heartbeat freshness checks will fail"
  OPTIONAL_MISSING=$((OPTIONAL_MISSING + 1))
fi

# du, wc — pretty universal but check anyway
for util in du wc; do
  command -v "$util" >/dev/null 2>&1 && ok "$util" || { warn "$util not found — footprint reports degraded"; OPTIONAL_MISSING=$((OPTIONAL_MISSING+1)); }
done

# Notifications
$QUIET || echo
$QUIET || step "Notifications (optional, set env vars to enable)"

case "$PLATFORM" in
  macOS*)
    if command -v osascript >/dev/null 2>&1; then
      ok "osascript → macOS Notification Center available (auto)"
    else
      warn "osascript not found — macOS notifications disabled"
    fi
    ;;
  Linux*)
    if command -v notify-send >/dev/null 2>&1; then
      ok "notify-send → desktop notifications available (you may need to wire this into ~/.spine-development/notify.sh manually)"
    else
      warn "notify-send not found (install: apt install libnotify-bin) — desktop notifications via notify.sh need a webhook channel"
    fi
    ;;
  Windows*)
    warn "no native Windows toaster — use webhook channels (ntfy.sh / Slack / Discord)"
    ;;
esac

if [[ -n "${NTFY_TOPIC:-}" ]];      then ok "NTFY_TOPIC set ($NTFY_TOPIC) → ntfy.sh push armed"; else hint "NTFY_TOPIC not set — phone push via ntfy.sh disabled"; fi
if [[ -n "${SLACK_WEBHOOK:-}" ]];   then ok "SLACK_WEBHOOK set → Slack channel armed";          else hint "SLACK_WEBHOOK not set — Slack disabled"; fi
if [[ -n "${DISCORD_WEBHOOK:-}" ]]; then ok "DISCORD_WEBHOOK set → Discord channel armed";      else hint "DISCORD_WEBHOOK not set — Discord disabled"; fi
if [[ -n "${PUSHOVER_USER:-}" && -n "${PUSHOVER_TOKEN:-}" ]]; then ok "Pushover armed";          else hint "PUSHOVER_USER+PUSHOVER_TOKEN not set — Pushover disabled"; fi

# --- agent CLI ---
$QUIET || echo
$QUIET || step "AI CLI (need at least one)"

for bin in cursor-agent cursor claude aider opencode codex; do
  if command -v "$bin" >/dev/null 2>&1; then
    ok "$bin → $(command -v "$bin")"
    [[ -z "$AGENT_FOUND" ]] && AGENT_FOUND="$bin"
  fi
done
if [[ -n "${EXECUTOR_CMD:-}" ]]; then
  ok "EXECUTOR_CMD set → $EXECUTOR_CMD (will be used directly)"
  AGENT_FOUND="${AGENT_FOUND:-$EXECUTOR_CMD}"
fi

if [[ -z "$AGENT_FOUND" ]]; then
  miss "no AI CLI found on PATH"
  hint "Install at least one of:"
  hint "  - Cursor Agent (cursor-agent) — https://cursor.com — recommended"
  hint "  - Claude Code (claude) — npm i -g @anthropic-ai/claude-code"
  hint "  - Aider (aider) — pip install aider-chat"
  hint "  - OpenCode (opencode) — https://opencode.ai"
  hint "Or set EXECUTOR_CMD=/path/to/your-cli in your shell"
  REQUIRED_MISSING=$((REQUIRED_MISSING + 1))
fi

# --- summary ---
$QUIET || echo
if (( REQUIRED_MISSING == 0 && OPTIONAL_MISSING == 0 )); then
  $QUIET && echo "PREFLIGHT: OK ($PLATFORM, agent=$AGENT_FOUND)" || ok "All checks passed. Platform: $PLATFORM. Agent CLI: $AGENT_FOUND"
  exit 0
elif (( REQUIRED_MISSING == 0 )); then
  if $QUIET; then
    echo "PREFLIGHT: OK with warnings ($PLATFORM, agent=$AGENT_FOUND, $OPTIONAL_MISSING optional missing)"
  else
    warn "$OPTIONAL_MISSING recommended dependencies missing — team will run with degraded features."
  fi
  $STRICT && exit 1 || exit 0
else
  if $QUIET; then
    echo "PREFLIGHT: FAIL ($REQUIRED_MISSING required missing, $OPTIONAL_MISSING optional missing)"
  else
    miss "$REQUIRED_MISSING required dependencies missing — team CANNOT run."
    hint "See $(dirname "${BASH_SOURCE[0]}")/../REQUIREMENTS.md for the full list."
  fi
  exit 1
fi
