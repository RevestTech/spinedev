#!/usr/bin/env bash
# compat_shim.sh — STORY-7.5.1 / OQ-4: install (or remove) legacy lib/
# symlinks pointing at build/daemons/ + build/roles/<role>/prompt.md.
#
# Keeps v1 callers (existing installs, scripts/, the bridge in
# build/bridge/, downstream consumers using --pull-knowledge-only) working
# for one release cycle after the move per REQ-INIT-7 OQ-4 (PRD §7.8).
#
# Usage:
#   build/migration/compat_shim.sh [--dry-run] [--remove]
#
# Idempotent. Re-running produces the same result. Refuses to clobber a
# real file (only replaces existing symlinks or absent paths).
#
# Cross-refs: docs/PRD.md REQ-INIT-7 OQ-4; docs/BACKLOG.md STORY-7.5.3
# (retirement); build/migration/migrate_daemons.sh phase E.

set -euo pipefail

DRY_RUN=0
REMOVE=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --remove)  REMOVE=1 ;;
    -h|--help) sed -n '2,18p' "$0"; exit 0 ;;
    *) echo "unknown flag: $arg" >&2; exit 64 ;;
  esac
done

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
LIB="$ROOT/lib"
DAEMONS="$ROOT/build/daemons"
ROLES_DIR="$ROOT/build/roles"

DAEMON_FILES=(
  team-agent-daemon.sh file-lock.sh heartbeat.sh watchdog.sh seer-tick.sh
  executor.sh notify.sh costs-csv.sh usage-parsers.sh engagement-hook.sh
  db-outbox.sh vitals.sh preflight.sh
)

ROLES=(
  product planner architect conductor researcher engineer
  ux qa operator datawright seer auditor memory
)

say()  { printf '[compat_shim %s] %s\n' "$(date -u +%FT%TZ)" "$*"; }
warn() { printf '[compat_shim %s] WARN: %s\n' "$(date -u +%FT%TZ)" "$*" >&2; }
run()  { if (( DRY_RUN )); then say "DRY-RUN: $*"; else eval "$@"; fi }

# Place a symlink at $1 pointing to relative target $2 (relative to dir of $1).
# Refuses to overwrite a regular file. Replaces existing symlinks.
link_relative() {
  local linkpath="$1" target="$2"
  if [[ -L "$linkpath" ]]; then
    local cur; cur="$(readlink "$linkpath")"
    if [[ "$cur" == "$target" ]]; then
      say "ok: $linkpath -> $target (already)"
      return 0
    fi
    say "replace symlink: $linkpath -> $target (was $cur)"
    run "rm '$linkpath'"
  elif [[ -e "$linkpath" ]]; then
    warn "refusing to clobber regular file: $linkpath"
    return 1
  else
    say "create symlink: $linkpath -> $target"
  fi
  run "ln -s '$target' '$linkpath'"
}

remove_link() {
  local linkpath="$1"
  if [[ -L "$linkpath" ]]; then
    say "remove symlink: $linkpath"
    run "rm '$linkpath'"
  elif [[ -e "$linkpath" ]]; then
    warn "skip $linkpath: not a symlink"
  fi
}

install_shims() {
  say "install shims under $LIB → $DAEMONS / $ROLES_DIR"
  [[ -d "$LIB" ]] || { warn "lib/ missing — nothing to shim"; exit 0; }

  for f in "${DAEMON_FILES[@]}"; do
    local target="../build/daemons/$f"
    if [[ ! -e "$DAEMONS/$f" ]]; then
      warn "skip $f: target $DAEMONS/$f missing (not migrated yet)"
      continue
    fi
    link_relative "$LIB/$f" "$target" || true
  done

  [[ -d "$LIB/role-prompts" ]] || run "mkdir -p '$LIB/role-prompts'"
  for role in "${ROLES[@]}"; do
    local target="../../build/roles/$role/prompt.md"
    if [[ ! -e "$ROLES_DIR/$role/prompt.md" ]]; then
      warn "skip $role.md: target missing (not migrated yet)"
      continue
    fi
    link_relative "$LIB/role-prompts/$role.md" "$target" || true
  done

  say "shims installed (re-run safe). Retire via: $0 --remove (STORY-7.5.3)"
}

remove_shims() {
  say "remove shims under $LIB"
  for f in "${DAEMON_FILES[@]}"; do
    remove_link "$LIB/$f"
  done
  for role in "${ROLES[@]}"; do
    remove_link "$LIB/role-prompts/$role.md"
  done
  say "shims removed. Verify v1 callers have been updated."
}

main() {
  if (( REMOVE )); then remove_shims; else install_shims; fi
}

main "$@"
