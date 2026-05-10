#!/usr/bin/env bash
# team-clean.sh — cleanup for the agent team file footprint.
#
# Usage:
#   bash scripts/team-clean.sh scratch    # wipe per-role scratch dirs (safe)
#   bash scripts/team-clean.sh logs       # rotate logs older than 7 days, drop > 5MB
#   bash scripts/team-clean.sh archive    # prune workers/archive to last 50 batches
#   bash scripts/team-clean.sh all        # scratch + logs + archive (safe — preserves
#                                         # directives, memory, role-prompts, costs.csv)
#   bash scripts/team-clean.sh nuclear    # all + costs.csv + memory.md (DESTRUCTIVE)
#   bash scripts/team-clean.sh dry-run <mode>   # show what would be deleted
#
# What this script will NEVER delete:
#   - directive.md files (current task state)
#   - role-prompt.md files (system prompts)
#   - PROTOCOL files
#   - In safe modes: memory.md and costs.csv
#
# What gets cleaned:
#   - teams/<role>/scratch/         (entire dir contents)
#   - teams/<role>/log/*.log        (rotated/truncated)
#   - teams/<role>/workers/archive/ (oldest batches beyond keep limit)
#   - /tmp/spine-<role>-*/          (OS-level temp dirs created by agents)

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT" || exit 1

TEAM_ROLES=(planner researcher engineer operator datawright seer auditor memory)
TEAM_BASE=".planning/orchestration/agent-handoff/teams"

LOG_MAX_BYTES="${LOG_MAX_BYTES:-5242880}"     # 5 MB per log
ARCHIVE_KEEP="${ARCHIVE_KEEP:-50}"            # keep last 50 worker-archive batches per role

DRY_RUN=false

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

run() {
  if $DRY_RUN; then
    dim "  [dry-run] $*"
  else
    "$@"
  fi
}

clean_scratch() {
  step "Wiping per-role scratch dirs"
  local total_freed=0
  for role in "${TEAM_ROLES[@]}"; do
    local d="$TEAM_BASE/$role/scratch"
    if [[ -d "$d" ]]; then
      local sz
      sz=$(du -sk "$d" 2>/dev/null | awk '{print $1}')
      total_freed=$((total_freed + sz))
      run rm -rf "$d"
      run mkdir -p "$d"
      run touch "$d/.gitkeep"
      ok "  $role/scratch/  (${sz} KB freed)"
    fi
  done
  # OS-level temp dirs
  for d in /tmp/spine-*; do
    [[ -e "$d" ]] || continue
    local sz
    sz=$(du -sk "$d" 2>/dev/null | awk '{print $1}')
    total_freed=$((total_freed + sz))
    run rm -rf "$d"
    ok "  $(basename "$d")/  (${sz} KB freed)"
  done
  ok "Scratch cleanup: ${total_freed} KB freed."
}

clean_logs() {
  step "Rotating / truncating role logs (> ${LOG_MAX_BYTES} bytes)"
  for role in "${TEAM_ROLES[@]}"; do
    local logdir="$TEAM_BASE/$role/log"
    [[ -d "$logdir" ]] || continue
    shopt -s nullglob
    for f in "$logdir"/*.log; do
      local sz
      sz=$(wc -c < "$f" 2>/dev/null || echo 0)
      if (( sz > LOG_MAX_BYTES )); then
        # Keep last ~5MB worth of lines, dump the rest.
        run bash -c "tail -c $LOG_MAX_BYTES '$f' > '$f.rotated' && mv '$f.rotated' '$f'"
        ok "  $(basename "$f")  (was ${sz} B, truncated to ~${LOG_MAX_BYTES} B)"
      fi
    done
    shopt -u nullglob
  done
}

clean_archive() {
  step "Pruning workers/archive (keep last $ARCHIVE_KEEP batches per role)"
  for role in "${TEAM_ROLES[@]}"; do
    local archive_dir="$TEAM_BASE/$role/workers/archive"
    [[ -d "$archive_dir" ]] || continue
    local n
    n=$(find "$archive_dir" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l | tr -d ' ')
    if (( n > ARCHIVE_KEEP )); then
      local n_drop=$((n - ARCHIVE_KEEP))
      # Drop the oldest n_drop dirs by name (timestamps so lexical sort = chronological)
      local to_drop
      to_drop=$(find "$archive_dir" -mindepth 1 -maxdepth 1 -type d 2>/dev/null \
        | sort | head -n "$n_drop")
      while IFS= read -r d; do
        [[ -z "$d" ]] && continue
        run rm -rf "$d"
      done <<< "$to_drop"
      ok "  $role/workers/archive: dropped $n_drop oldest, kept $ARCHIVE_KEEP"
    else
      dim "  $role/workers/archive: $n batches (under keep limit)"
    fi
  done
}

clean_costs() {
  step "Wiping per-role costs.csv (DESTRUCTIVE — loses cost history)"
  for role in "${TEAM_ROLES[@]}"; do
    local f="$TEAM_BASE/$role/state/costs.csv"
    if [[ -f "$f" ]]; then
      run rm -f "$f"
      ok "  $role/state/costs.csv removed"
    fi
  done
}

clean_memory() {
  step "Wiping per-role memory.md (DESTRUCTIVE — loses learned lessons)"
  for role in "${TEAM_ROLES[@]}"; do
    local f="$TEAM_BASE/$role/memory.md"
    if [[ -f "$f" ]]; then
      run rm -f "$f"
      ok "  $role/memory.md removed"
    fi
  done
}

show_footprint() {
  step "Current team footprint on disk"
  echo
  for role in "${TEAM_ROLES[@]}"; do
    local d="$TEAM_BASE/$role"
    [[ -d "$d" ]] || continue
    local sz
    sz=$(du -sh "$d" 2>/dev/null | awk '{print $1}')
    printf "  %-12s  %s\n" "$role" "$sz"
  done
  echo
  if compgen -G "/tmp/spine-*" >/dev/null; then
    step "OS-level temp dirs"
    for d in /tmp/spine-*; do
      local sz
      sz=$(du -sh "$d" 2>/dev/null | awk '{print $1}')
      printf "  %-30s  %s\n" "$(basename "$d")" "$sz"
    done
  fi
}

usage() {
  cat <<EOF
team-clean.sh — agent team cleanup

Usage: bash scripts/team-clean.sh <mode>

Safe modes (preserve directives, role-prompts, memory, costs):
  scratch        Wipe per-role scratch/ dirs and /tmp/spine-* dirs
  logs           Truncate .log files larger than ${LOG_MAX_BYTES} bytes
  archive        Prune workers/archive/ to last $ARCHIVE_KEEP batches per role
  all            scratch + logs + archive (recommended periodic cleanup)

Destructive modes:
  costs          Remove all costs.csv (loses cost history)
  memory         Remove all memory.md (loses per-role learned lessons)
  nuclear        all + costs + memory (full reset minus current directives)

Inspection:
  footprint      Show disk usage per role
  dry-run <mode> Print what would be deleted without doing it

Tunables (env vars):
  LOG_MAX_BYTES  default $LOG_MAX_BYTES (5 MB)
  ARCHIVE_KEEP   default $ARCHIVE_KEEP batches per role
EOF
}

# --- arg dispatch ---
MODE="${1:-help}"

if [[ "$MODE" == "dry-run" ]]; then
  DRY_RUN=true
  MODE="${2:-help}"
  warn "DRY RUN — no changes will be made"
  echo
fi

case "$MODE" in
  scratch)   clean_scratch ;;
  logs)      clean_logs ;;
  archive)   clean_archive ;;
  all)
    clean_scratch
    echo
    clean_logs
    echo
    clean_archive
    ;;
  costs)     clean_costs ;;
  memory)    clean_memory ;;
  nuclear)
    warn "Nuclear mode — destroying scratch, logs, archive, costs, AND memory"
    warn "Current directive.md files are PRESERVED so in-flight work isn't lost."
    if ! $DRY_RUN; then
      read -r -p "Type 'yes' to proceed: " ans
      [[ "$ans" == "yes" ]] || { err "Aborted"; exit 1; }
    fi
    clean_scratch; echo
    clean_logs; echo
    clean_archive; echo
    clean_costs; echo
    clean_memory
    ;;
  footprint) show_footprint ;;
  help|-h|--help|"") usage ;;
  *)
    err "Unknown mode: $MODE"
    usage
    exit 1
    ;;
esac
