#!/usr/bin/env bash
# team.sh — single entry point for the file-based agent team.
#
# Usage:
#   bash scripts/team.sh up          # start 5 manager daemons + 50 worker slots
#   bash scripts/team.sh down        # clean shutdown
#   bash scripts/team.sh status      # what's each manager + worker doing
#   bash scripts/team.sh restart
#   bash scripts/team.sh help
#
# The daemon itself is at scripts/team-agent-daemon.sh — this script just
# spawns/kills the right number of those processes.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT" || exit 1

if [[ -f "$SCRIPT_DIR/roles.sh" ]]; then
  # shellcheck source=/dev/null
  source "$SCRIPT_DIR/roles.sh"
  TEAM_ROLES=("${SPINE_TEAM_ROLES[@]}")
else
  echo "✗ scripts/roles.sh missing — re-run SpineDevelopment installer." >&2
  exit 1
fi

TEAM_DAEMON="scripts/team-agent-daemon.sh"
TEAM_BASE=".planning/orchestration/agent-handoff/teams"

if [[ -t 1 ]]; then
  C_BLUE='\033[0;34m'; C_GREEN='\033[0;32m'; C_YELLOW='\033[0;33m'
  C_RED='\033[0;31m'; C_DIM='\033[2m'; C_RESET='\033[0m'
else
  C_BLUE=''; C_GREEN=''; C_YELLOW=''; C_RED=''; C_DIM=''; C_RESET=''
fi

step()  { printf "${C_BLUE}▸${C_RESET} %s\n" "$*"; }
ok()    { printf "${C_GREEN}✓${C_RESET} %s\n" "$*"; }
warn()  { printf "${C_YELLOW}!${C_RESET} %s\n" "$*"; }
err()   { printf "${C_RED}✗${C_RESET} %s\n" "$*" >&2; }
dim()   { printf "${C_DIM}%s${C_RESET}\n" "$*"; }

team_pids_for() {
  # Args: role mode [slot]
  local role="$1" mode="$2" slot="${3:-}"
  if [[ "$mode" == "manager" ]]; then
    pgrep -f "team-agent-daemon.sh $role manager$" 2>/dev/null || true
  else
    pgrep -f "team-agent-daemon.sh $role worker $slot" 2>/dev/null || true
  fi
}

start_manager() {
  local role="$1"
  local existing
  existing=$(team_pids_for "$role" manager)
  if [[ -n "$existing" ]]; then
    dim "  $role manager already running (pid: $existing)"
    return
  fi
  nohup bash "$TEAM_DAEMON" "$role" manager </dev/null >/dev/null 2>&1 &
  ok "  $role manager started (pid: $!)"
}

start_workers() {
  local role="$1" n_started=0
  for i in $(seq -f '%02g' 1 10); do
    local existing
    existing=$(team_pids_for "$role" worker "$i")
    if [[ -n "$existing" ]]; then continue; fi
    nohup bash "$TEAM_DAEMON" "$role" worker "$i" </dev/null >/dev/null 2>&1 &
    n_started=$((n_started + 1))
  done
  if (( n_started > 0 )); then
    ok "  $role workers: $n_started new daemons started"
  else
    dim "  $role workers: all 10 already running"
  fi
}

stop_role() {
  local role="$1"
  local pids
  pids=$(pgrep -f "team-agent-daemon.sh $role" 2>/dev/null || true)
  if [[ -z "$pids" ]]; then
    dim "  $role daemons: none running"
    return
  fi
  # shellcheck disable=SC2086
  kill $pids 2>/dev/null || true
  ok "  $role daemons stopped"
}

ensure_scaffold() {
  for role in "${TEAM_ROLES[@]}"; do
    mkdir -p "$TEAM_BASE/$role/workers/archive" "$TEAM_BASE/$role/state" "$TEAM_BASE/$role/log"
    if [[ ! -f "$TEAM_BASE/$role/role-prompt.md" ]]; then
      warn "  $role/role-prompt.md missing — re-run installer or copy from agent-team-template/lib/role-prompts/"
    fi
    if [[ ! -f "$TEAM_BASE/$role/directive.md" ]]; then
      printf '%s\n' "# (idle — drop a directive here)" > "$TEAM_BASE/$role/directive.md"
    fi
  done
}

cmd_up() {
  if [[ ! -x "$TEAM_DAEMON" ]]; then
    err "Missing $TEAM_DAEMON — run installer or chmod +x"
    return 1
  fi
  ensure_scaffold
  local nm=${#TEAM_ROLES[@]}
  local nw=$((nm * 10))
  step "Starting agent team (${nm} managers + ${nw} worker slots + watchdog)"
  for role in "${TEAM_ROLES[@]}"; do
    echo
    dim "  $role:"
    start_manager "$role"
    start_workers "$role"
  done
  echo
  start_watchdog
  echo
  ok "Team up. Drop a directive into:"
  for role in "${TEAM_ROLES[@]}"; do
    dim "  $TEAM_BASE/$role/directive.md"
  done
  echo
  dim "  Status:    bash scripts/team.sh status"
  dim "  Health:    bash scripts/team.sh doctor"
  dim "  Stop:      bash scripts/team.sh down"
}

start_watchdog() {
  if [[ ! -f "scripts/watchdog.sh" ]]; then
    warn "  watchdog: scripts/watchdog.sh missing — skipping (re-run installer)"
    return
  fi
  local pidfile=".planning/orchestration/agent-handoff/watchdog.pid"
  if [[ -f "$pidfile" ]] && kill -0 "$(cat "$pidfile" 2>/dev/null)" 2>/dev/null; then
    dim "  watchdog: already running (pid $(cat "$pidfile"))"
    return
  fi
  nohup bash scripts/watchdog.sh </dev/null >/dev/null 2>&1 &
  ok "  watchdog: started (will auto-restart dead managers)"
}

stop_watchdog() {
  local pidfile=".planning/orchestration/agent-handoff/watchdog.pid"
  if [[ -f "$pidfile" ]]; then
    local pid
    pid=$(cat "$pidfile" 2>/dev/null)
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      ok "  watchdog stopped (pid $pid)"
    fi
    rm -f "$pidfile"
  fi
}

cmd_down() {
  step "Stopping agent team"
  stop_watchdog
  for role in "${TEAM_ROLES[@]}"; do
    stop_role "$role"
  done
  ok "Team stopped."
}

cmd_doctor() {
  step "Team health check"
  echo
  local issues=0

  # 1. cursor-agent on PATH
  if command -v cursor-agent >/dev/null 2>&1; then
    ok "  cursor-agent on PATH ($(command -v cursor-agent))"
  elif command -v cursor >/dev/null 2>&1; then
    warn "  cursor on PATH (cursor-agent not found — daemon will use cursor)"
  else
    err "  no cursor-agent or cursor on PATH — daemons cannot invoke agents"
    issues=$((issues + 1))
  fi

  # 2. Each manager: process alive + heartbeat fresh
  echo
  for role in "${TEAM_ROLES[@]}"; do
    local pid hb_age
    pid=$(team_pids_for "$role" manager)
    local hb_file="$TEAM_BASE/$role/state/heartbeat"
    if [[ -z "$pid" ]]; then
      err "  $role manager: NOT RUNNING"
      issues=$((issues + 1))
      continue
    fi
    if [[ ! -f "$hb_file" ]]; then
      warn "  $role manager: pid=$pid but no heartbeat file yet (daemon may be starting)"
      continue
    fi
    if stat -f %m "$hb_file" >/dev/null 2>&1; then
      hb_age=$(( $(date +%s) - $(stat -f %m "$hb_file") ))
    else
      hb_age=$(( $(date +%s) - $(stat -c %Y "$hb_file") ))
    fi
    if (( hb_age > 300 )); then
      err "  $role manager: pid=$pid but heartbeat ${hb_age}s stale (>300s — watchdog should restart)"
      issues=$((issues + 1))
    elif (( hb_age > 30 )); then
      warn "  $role manager: pid=$pid · heartbeat ${hb_age}s old"
    else
      ok "  $role manager: pid=$pid · heartbeat ${hb_age}s old"
    fi
  done

  # 3. Watchdog
  echo
  local wpid_file=".planning/orchestration/agent-handoff/watchdog.pid"
  if [[ -f "$wpid_file" ]] && kill -0 "$(cat "$wpid_file" 2>/dev/null)" 2>/dev/null; then
    ok "  watchdog: pid=$(cat "$wpid_file")"
  else
    err "  watchdog: NOT RUNNING — managers will not auto-recover"
    issues=$((issues + 1))
  fi

  # 4. Notification hook
  echo
  if [[ -x "$HOME/.spine-development/notify.sh" ]]; then
    ok "  notify hook: $HOME/.spine-development/notify.sh"
  else
    warn "  notify hook: not installed at $HOME/.spine-development/notify.sh — completion notifications disabled"
  fi

  # 5. Zombie cursor-agent processes
  local zombies
  zombies=$(pgrep -f 'cursor-agent' 2>/dev/null | wc -l | tr -d ' ')
  if (( zombies > 16 )); then
    warn "  $zombies cursor-agent processes running (>16 — possible runaway)"
  else
    dim "  $zombies cursor-agent processes running"
  fi

  # 6. Disk footprint check
  local total_kb=0
  for role in "${TEAM_ROLES[@]}"; do
    [[ -d "$TEAM_BASE/$role" ]] || continue
    local kb
    kb=$(du -sk "$TEAM_BASE/$role" 2>/dev/null | awk '{print $1}')
    total_kb=$((total_kb + kb))
  done
  echo
  if (( total_kb > 102400 )); then  # > 100 MB
    warn "  team disk footprint: ${total_kb} KB ($((total_kb/1024)) MB) — consider 'team.sh clean all'"
  else
    ok "  team disk footprint: ${total_kb} KB ($((total_kb/1024)) MB)"
  fi

  echo
  if (( issues == 0 )); then
    ok "All checks passed."
  else
    err "$issues issue(s) detected. Try: bash scripts/team.sh restart"
    return 1
  fi
}

cmd_rollback() {
  shift  # consume "rollback"
  local role="${1:-engineer}"
  local stack="$TEAM_BASE/$role/state/rollback-stack.csv"
  if [[ "$role" != "engineer" && "$role" != "engineering-backend" && "$role" != "engineering-frontend" ]]; then
    err "Rollback targets code squads only: engineer | engineering-backend | engineering-frontend"
    return 1
  fi
  if [[ ! -f "$stack" ]]; then
    warn "No rollback history at $stack"
    return 1
  fi
  if ! command -v git >/dev/null 2>&1; then
    err "git not on PATH"
    return 1
  fi
  if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    err "Not inside a git work tree"
    return 1
  fi

  step "Engineer rollback history (most recent first)"
  echo
  printf "  %-3s  %-22s  %-20s  %-12s  %-12s  %s\n" "#" "timestamp" "directive" "head" "tracked" "restored"
  echo "  ---  ----------------------  --------------------  ------------  ------------  --------"
  local lines=()
  while IFS= read -r line; do
    [[ "$line" == timestamp* ]] && continue
    lines+=("$line")
  done < "$stack"
  local n=${#lines[@]}
  if (( n == 0 )); then
    warn "  (no entries)"
    return 0
  fi
  local i
  for (( i=n-1; i>=0; i-- )); do
    IFS=',' read -r ts identity dh head_sha tracked_sha untracked_arch restored <<< "${lines[i]}"
    local idx=$((n - i))
    printf "  %-3s  %-22s  %-20s  %-12s  %-12s  %s\n" "$idx" "${ts:0:19}" "${dh:0:18}" "${head_sha:0:10}" "${tracked_sha:0:10}" "${restored:-no}"
  done

  echo
  read -r -p "Roll back to which # (1=most recent, q=quit)? " pick
  [[ "$pick" == "q" ]] && return 0
  if ! [[ "$pick" =~ ^[0-9]+$ ]] || (( pick < 1 || pick > n )); then
    err "Invalid selection"
    return 1
  fi
  local target_idx=$((n - pick))
  IFS=',' read -r ts identity dh head_sha tracked_sha untracked_arch restored <<< "${lines[target_idx]}"

  step "Rolling back to snapshot from $ts (head=${head_sha:0:10})"
  warn "This will run: git reset --hard $head_sha && git stash apply $tracked_sha"
  read -r -p "Type 'yes' to proceed (your current changes will be lost): " confirm
  [[ "$confirm" == "yes" ]] || { err "Aborted"; return 1; }

  git reset --hard "$head_sha" || { err "git reset failed"; return 1; }
  if [[ -n "$tracked_sha" ]]; then
    git stash apply "$tracked_sha" 2>/dev/null || warn "stash apply had conflicts — review with git status"
  fi
  if [[ -n "$untracked_arch" ]]; then
    local ua="$TEAM_BASE/$role/state/rollback-snapshots/$untracked_arch"
    if [[ -f "$ua" ]]; then
      tar -xzf "$ua" -C . 2>/dev/null && ok "  untracked files restored from $untracked_arch"
    fi
  fi
  ok "Rollback complete. Review with: git status && git diff"
  # Mark the entry as restored (rebuild file)
  local tmp
  tmp=$(mktemp)
  head -1 "$stack" > "$tmp"
  for (( i=0; i<n; i++ )); do
    if (( i == target_idx )); then
      IFS=',' read -r a b c d e f g <<< "${lines[i]}"
      echo "$a,$b,$c,$d,$e,$f,$ts" >> "$tmp"
    else
      echo "${lines[i]}" >> "$tmp"
    fi
  done
  mv "$tmp" "$stack"
}

cmd_status() {
  step "Agent team status"
  echo
  for role in "${TEAM_ROLES[@]}"; do
    local mgr_pid worker_pids n_workers
    mgr_pid=$(team_pids_for "$role" manager)
    worker_pids=$(pgrep -f "team-agent-daemon.sh $role worker" 2>/dev/null || true)
    n_workers=$(echo -n "$worker_pids" | grep -c '^' 2>/dev/null || echo 0)
    [[ -z "$worker_pids" ]] && n_workers=0

    local dir="$TEAM_BASE/$role"
    local state="?"
    if [[ -f "$dir/directive.md" ]]; then
      state=$(head -1 "$dir/directive.md" 2>/dev/null | head -c 80)
    fi
    if [[ -n "$mgr_pid" ]]; then
      ok "  $role  manager pid=$mgr_pid · workers=$n_workers/10"
    else
      warn "  $role  manager NOT running · workers=$n_workers"
    fi
    dim "         current: $state"
  done
}

cmd_restart() {
  cmd_down
  echo
  cmd_up
}

cmd_budget() {
  step "Cost report (from teams/*/state/costs.csv)"
  echo
  local total_invs=0 total_wall_s=0
  declare -A by_tier_n by_tier_s
  for role in "${TEAM_ROLES[@]}"; do
    local f="$TEAM_BASE/$role/state/costs.csv"
    [[ -f "$f" ]] || continue
    local n_role wall_role
    n_role=$(tail -n +2 "$f" | wc -l | tr -d ' ')
    wall_role=$(tail -n +2 "$f" | awk -F, '{s+=$7} END {print s+0}')
    if [[ "$n_role" -gt 0 ]]; then
      printf "  %-12s  invocations=%-5s  wall=%6ss\n" "$role" "$n_role" "$wall_role"
      total_invs=$((total_invs + n_role))
      total_wall_s=$((total_wall_s + wall_role))
      while IFS=',' read -r ts r mode slot phase tier wall rc; do
        [[ "$tier" == "tier" ]] && continue
        by_tier_n[$tier]=$(( ${by_tier_n[$tier]:-0} + 1 ))
        by_tier_s[$tier]=$(( ${by_tier_s[$tier]:-0} + wall ))
      done < <(tail -n +2 "$f")
    fi
  done
  echo
  ok "  TOTAL invocations: $total_invs"
  ok "  TOTAL wall time:   ${total_wall_s}s ($((total_wall_s / 60))m)"
  echo
  step "By tier"
  for t in low medium high; do
    local n=${by_tier_n[$t]:-0} s=${by_tier_s[$t]:-0}
    printf "  %-7s  invocations=%-5s  wall=%6ss\n" "$t" "$n" "$s"
  done
  echo
  dim "  Detailed CSVs at: $TEAM_BASE/<role>/state/costs.csv"
}

cmd_learn() {
  shift  # consume "learn" command name
  local lesson="$*"
  if [[ -z "$lesson" ]]; then
    err "Usage: bash scripts/team.sh learn \"the lesson text\" [--role <role>]"
    return 1
  fi
  local role="general"
  # crude --role flag parse
  if [[ "$lesson" == *"--role "* ]]; then
    role="${lesson##*--role }"; role="${role%% *}"
    lesson="${lesson%% --role*}"
  fi
  local target
  if [[ "$role" == "general" ]]; then
    mkdir -p "$HOME/.spine-development/playbook/general"
    target="$HOME/.spine-development/playbook/general/lessons.md"
  else
    mkdir -p "$HOME/.spine-development/playbook/$role"
    target="$HOME/.spine-development/playbook/$role/lessons.md"
  fi
  printf -- '- %s — %s\n' "$(date -u +%Y-%m-%d)" "$lesson" >> "$target"
  ok "Lesson saved to $target"
  dim "  Will be loaded into future $role agent invocations across all projects."
}

cmd_clean() {
  shift  # consume "clean"
  local mode="${1:-all}"
  if [[ ! -x "scripts/team-clean.sh" ]] && [[ ! -f "scripts/team-clean.sh" ]]; then
    err "scripts/team-clean.sh missing — re-run installer"
    return 1
  fi
  bash scripts/team-clean.sh "$mode"
}

cmd_notify_test() {
  local hook="$HOME/.spine-development/notify.sh"
  if [[ ! -x "$hook" ]]; then
    err "Notify hook not installed at $hook — re-run installer"
    return 1
  fi
  step "Firing a test notification through every configured channel"
  echo
  dim "  Channels:"
  if command -v osascript >/dev/null 2>&1; then dim "    [auto] macOS Notification Center"; fi
  if [[ -n "${NTFY_TOPIC:-}" ]];      then dim "    [✓] ntfy.sh — topic: $NTFY_TOPIC (server: ${NTFY_SERVER:-https://ntfy.sh})"; else dim "    [ ] ntfy.sh — set NTFY_TOPIC env var to enable"; fi
  if [[ -n "${PUSHOVER_TOKEN:-}" && -n "${PUSHOVER_USER:-}" ]]; then dim "    [✓] Pushover"; else dim "    [ ] Pushover — set PUSHOVER_TOKEN + PUSHOVER_USER to enable"; fi
  if [[ -n "${SLACK_WEBHOOK:-}" ]];   then dim "    [✓] Slack webhook"; else dim "    [ ] Slack — set SLACK_WEBHOOK to enable"; fi
  if [[ -n "${DISCORD_WEBHOOK:-}" ]]; then dim "    [✓] Discord webhook"; else dim "    [ ] Discord — set DISCORD_WEBHOOK to enable"; fi
  if [[ -n "${NOTIFY_EMAIL_TO:-}" ]] && command -v mail >/dev/null 2>&1; then dim "    [✓] Email — to: $NOTIFY_EMAIL_TO"; else dim "    [ ] Email — set NOTIFY_EMAIL_TO and ensure 'mail' CLI works"; fi
  echo
  "$hook" "[spine] notify test" "If you see this, notifications are working. $(date -u +%FT%TZ)"
  ok "Test fired."
  dim "  Always-on log: tail $HOME/.spine-development/notifications.log"
}

case "${1:-help}" in
  up|start)    cmd_up ;;
  down|stop)   cmd_down ;;
  status|ps)   cmd_status ;;
  restart)     cmd_restart ;;
  budget|cost) cmd_budget ;;
  learn)       cmd_learn "$@" ;;
  clean)       cmd_clean "$@" ;;
  doctor|health) cmd_doctor ;;
  rollback)    cmd_rollback "$@" ;;
  notify-test) cmd_notify_test ;;
  preflight)
    if [[ -f "scripts/preflight.sh" ]]; then
      shift; bash scripts/preflight.sh "$@"
    else
      err "scripts/preflight.sh missing — re-run installer"; exit 1
    fi
    ;;
  help|-h|--help)
    cat <<EOF
Usage: bash scripts/team.sh <command>

  up         Start manager daemons + worker slots (see scripts/roles.sh) + watchdog
  down       Stop all team daemons
  status     Show what each manager + worker is doing
  restart    down + up
  budget     Show cost / wall-time report from cost CSVs
  learn      Append a lesson to ~/.spine-development/playbook/<role>/lessons.md
             Usage: team.sh learn "lesson text" [--role engineer]
  clean      Cleanup the team's file footprint. Modes:
               clean scratch    — wipe per-role scratch dirs (safe)
               clean logs       — truncate logs > 5MB
               clean archive    — prune workers/archive to last 50 batches
               clean all        — scratch + logs + archive (recommended)
               clean footprint  — show disk usage per role
               clean nuclear    — destroy everything except current directives
  doctor     Health check: cursor-agent on PATH, daemons alive, heartbeats fresh, watchdog up
  rollback   Roll back code-squad changes (git snapshot)
             Usage: team.sh rollback engineer|engineering-backend|engineering-frontend
  notify-test Fire a test notification through every configured channel.
             Channels are env-var driven — see "How am I going to get pinged?" below.

How am I going to get pinged?
  By default: macOS notification banner + line in ~/.spine-development/notifications.log
  For phone pings, set ONE of these env vars in your shell (~/.zshrc or ~/.bashrc):
    NTFY_TOPIC=<your-secret-topic>     # ntfy.sh — easiest, no signup, install ntfy app
    PUSHOVER_TOKEN=... PUSHOVER_USER=... # Pushover (\$5 one-time)
    SLACK_WEBHOOK=https://hooks.slack.com/services/...
    DISCORD_WEBHOOK=https://discord.com/api/webhooks/...
    NOTIFY_EMAIL_TO=khash@khash.com
  Then verify: bash scripts/team.sh notify-test

Drop directives at:
  See scripts/roles.sh (`SPINE_TEAM_ROLES`)
  Paths: .planning/orchestration/agent-handoff/teams/<role>/directive.md
EOF
    ;;
  *)
    err "Unknown command: $1"
    exit 1
    ;;
esac
