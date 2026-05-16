#!/usr/bin/env bash
# migrate_daemons.sh — STORY-7.5.{1,2,3}: move lib/ daemons + role-prompts
# into build/daemons/, build/workers/, build/roles/<role>/.
#
# Usage:
#   build/migration/migrate_daemons.sh [--dry-run] [--phase a|b|c|d|e|f|all]
#                                      [--no-shim] [--rollback <snapshot>]
#
# Phased and idempotent — re-running produces the same end-state. The actual
# move IS the deliverable (script runs operationally; story ships toolkit).
#
# Exit codes: 0 ok, 1 dirty git, 2 missing file, 3 verify fail,
# 4 already migrated (idempotent skip), 64 unknown flag.
#
# Cross-refs: docs/PRD.md REQ-INIT-7 §7.5 FR-5; docs/ARCHITECTURE.md §6
# Phase 4; docs/BACKLOG.md EPIC-7.5; migration_README.md; migrate_inventory.md.

set -euo pipefail

DRY_RUN=0; PHASE="all"; INSTALL_SHIM=1; ROLLBACK_FROM=""
for arg in "$@"; do
  case "$arg" in
    --dry-run)    DRY_RUN=1 ;;
    --no-shim)    INSTALL_SHIM=0 ;;
    --phase=*)    PHASE="${arg#--phase=}" ;;
    --phase)      shift; PHASE="${1:-all}" ;;
    --rollback=*) ROLLBACK_FROM="${arg#--rollback=}" ;;
    --rollback)   shift; ROLLBACK_FROM="${1:-}" ;;
    -h|--help)    sed -n '2,16p' "$0"; exit 0 ;;
    *)            echo "unknown flag: $arg" >&2; exit 64 ;;
  esac
done

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
LIB="$ROOT/lib"; BUILD="$ROOT/build"
DAEMONS="$BUILD/daemons"; WORKERS="$BUILD/workers"; ROLES_DIR="$BUILD/roles"
HERE="$BUILD/migration"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
SNAPSHOT="/tmp/spine-daemon-migration-$TS.tar"

# Daemon files lib/*.sh → build/daemons/*.sh. Keep synced with migrate_inventory.md §A.
DAEMON_FILES=(
  team-agent-daemon.sh file-lock.sh heartbeat.sh watchdog.sh seer-tick.sh
  executor.sh notify.sh costs-csv.sh usage-parsers.sh engagement-hook.sh
  db-outbox.sh vitals.sh preflight.sh
)
# Roster — matches lib/roles.sh SPINE_TEAM_ROLES.
ROLES=( product planner architect conductor researcher engineer
        ux qa operator datawright seer auditor memory )

say()  { printf '[migrate_daemons %s] %s\n' "$(date -u +%FT%TZ)" "$*"; }
warn() { printf '[migrate_daemons %s] WARN: %s\n' "$(date -u +%FT%TZ)" "$*" >&2; }
fail() { printf '[migrate_daemons %s] FAIL: %s\n' "$(date -u +%FT%TZ)" "$*" >&2; exit "${2:-1}"; }
run()  { if (( DRY_RUN )); then say "DRY-RUN: $*"; else eval "$@"; fi }
phase_active() { [[ "$PHASE" == "all" || "$PHASE" == "$1" ]]; }

rollback() {
  local snap="$1"
  [[ -f "$snap" ]] || fail "snapshot not found: $snap" 2
  say "rollback: restoring from $snap"
  run "tar -xf '$snap' -C '$ROOT'"
  say "rollback complete. Re-run 'git status' to inspect."
}
if [[ -n "$ROLLBACK_FROM" ]]; then rollback "$ROLLBACK_FROM"; exit 0; fi

# Phase A — preparation. Refuses dirty git in lib/. Idempotent dirs.
phase_a() {
  say "PHASE A — preparation"
  [[ -d "$LIB" && -d "$BUILD" ]] || fail "lib/ or build/ missing" 2
  if ( cd "$ROOT" && ! git diff --quiet -- lib/ ); then
    fail "lib/ has uncommitted changes — commit or stash first" 1
  fi
  if ( cd "$ROOT" && ! git diff --cached --quiet -- lib/ ); then
    fail "lib/ has staged-but-uncommitted changes — commit first" 1
  fi
  for d in "$DAEMONS" "$WORKERS" "$ROLES_DIR" "$ROLES_DIR/_archived"; do
    [[ -d "$d" ]] || run "mkdir -p '$d'"
  done
  for role in "${ROLES[@]}"; do
    [[ -d "$ROLES_DIR/$role" ]] || run "mkdir -p '$ROLES_DIR/$role'"
  done
  say "snapshot: $SNAPSHOT"
  run "tar -cf '$SNAPSHOT' -C '$ROOT' lib PROTOCOL.md INSTALL.md README.md Makefile.v2 2>/dev/null || true"
}

# Phase B — move daemon shell files via git mv.
phase_b() {
  say "PHASE B — move daemon files lib/*.sh → build/daemons/"
  local moved=0 skipped=0
  for f in "${DAEMON_FILES[@]}"; do
    local src="$LIB/$f" dst="$DAEMONS/$f"
    if [[ -L "$src" ]]; then say "skip $f: already symlink (shim)"; ((skipped++)); continue; fi
    if [[ -f "$dst" && ! -e "$src" ]]; then say "skip $f: already at $dst"; ((skipped++)); continue; fi
    if [[ ! -f "$src" ]]; then warn "missing $src — skipping"; continue; fi
    if [[ -f "$dst" ]]; then fail "conflict: $src and $dst both exist" 3; fi
    run "cd '$ROOT' && git mv 'lib/$f' 'build/daemons/$f'"
    ((moved++))
  done
  say "phase B done: $moved moved, $skipped skipped"
}

# Phase C — move role prompts (per-role + _archived/ merge).
phase_c() {
  say "PHASE C — move role prompts lib/role-prompts/*.md → build/roles/<role>/prompt.md"
  local moved=0 skipped=0
  for role in "${ROLES[@]}"; do
    local src="$LIB/role-prompts/$role.md"
    local dstdir="$ROLES_DIR/$role" dst="$ROLES_DIR/$role/prompt.md"
    [[ -d "$dstdir" ]] || run "mkdir -p '$dstdir'"
    if [[ -L "$src" ]]; then say "skip $role.md: already symlink"; ((skipped++)); continue; fi
    if [[ -f "$dst" && ! -e "$src" ]]; then say "skip $role.md: already at $dst"; ((skipped++)); continue; fi
    if [[ ! -f "$src" ]]; then warn "missing $src — skipping"; continue; fi
    run "cd '$ROOT' && git mv 'lib/role-prompts/$role.md' 'build/roles/$role/prompt.md'"
    ((moved++))
  done
  # Move _archived/ as a unit (engineering-backend / engineering-frontend per ADR-001).
  if [[ -d "$LIB/role-prompts/_archived" && ! -e "$ROLES_DIR/_archived/engineering-backend.md" ]]; then
    say "move _archived/ → build/roles/_archived/"
    run "cd '$ROOT' && git mv 'lib/role-prompts/_archived' 'build/roles/_archived_v1tmp' || true"
    if [[ -d "$ROLES_DIR/_archived_v1tmp" ]]; then
      run "cd '$ROOT' && (mv build/roles/_archived_v1tmp/* build/roles/_archived/ 2>/dev/null || true) && rmdir build/roles/_archived_v1tmp 2>/dev/null || true"
    fi
  fi
  say "phase C done: $moved moved, $skipped skipped"
}

# Phase D — update path references via update_protocol_refs.sh.
phase_d() {
  say "PHASE D — update path references"
  local updater="$HERE/update_protocol_refs.sh"
  [[ -f "$updater" ]] || fail "missing $updater" 2
  [[ -x "$updater" ]] || run "chmod +x '$updater'"
  if (( DRY_RUN )); then run "bash '$updater' --dry-run"; else run "bash '$updater'"; fi
}

# Phase E — install compat shim.
phase_e() {
  if (( ! INSTALL_SHIM )); then say "PHASE E — skipped (--no-shim)"; return; fi
  say "PHASE E — install compat shim"
  local shim="$HERE/compat_shim.sh"
  [[ -f "$shim" ]] || fail "missing $shim" 2
  if (( DRY_RUN )); then run "bash '$shim' --dry-run"; else run "bash '$shim'"; fi
}

# Phase F — verify.
phase_f() {
  say "PHASE F — verify"
  local ok=1
  for f in "${DAEMON_FILES[@]}"; do
    if [[ ! -e "$DAEMONS/$f" ]]; then
      [[ -e "$LIB/$f" ]] && { warn "verify: $f still only in lib/"; ok=0; }
    fi
  done
  for role in "${ROLES[@]}"; do
    if [[ ! -e "$ROLES_DIR/$role/prompt.md" ]]; then
      [[ -e "$LIB/role-prompts/$role.md" ]] && { warn "verify: $role.md still only in lib/"; ok=0; }
    fi
  done
  if (( INSTALL_SHIM )) && [[ ! -e "$LIB/team-agent-daemon.sh" ]]; then
    warn "verify: lib/team-agent-daemon.sh shim missing"; ok=0
  fi
  for cand in "$DAEMONS/preflight.sh" "$LIB/preflight.sh"; do
    [[ -x "$cand" ]] || continue
    say "verify: invoking $cand --version (best-effort)"
    if (( DRY_RUN )); then
      run "bash '$cand' --version || true"
    else
      bash "$cand" --version 2>/dev/null || warn "preflight --version != 0 (non-fatal)"
    fi
    break
  done
  local stale
  stale=$(grep -lE 'lib/team-agent-daemon\.sh|lib/role-prompts/' \
            "$ROOT/Makefile.v2" "$ROOT/PROTOCOL.md" "$ROOT/INSTALL.md" "$ROOT/README.md" \
            2>/dev/null || true)
  if [[ -n "$stale" ]]; then
    warn "verify: stale references still present in:"; printf '  %s\n' $stale; ok=0
  fi
  (( ok )) && say "verify OK" || fail "verify FAILED — inspect warnings above" 3
  if (( ! DRY_RUN )); then
    say "git status (unrelated changes should be empty):"
    ( cd "$ROOT" && git status --short | head -40 ) || true
  fi
}

main() {
  say "migrate_daemons start (phase=$PHASE dry-run=$DRY_RUN shim=$INSTALL_SHIM)"
  # Idempotent short-circuit when everything is already at target.
  local all_migrated=1
  for f in "${DAEMON_FILES[@]}"; do
    [[ -e "$DAEMONS/$f" ]] || { all_migrated=0; break; }
  done
  for role in "${ROLES[@]}"; do
    [[ -e "$ROLES_DIR/$role/prompt.md" ]] || { all_migrated=0; break; }
  done
  if (( all_migrated )) && [[ "$PHASE" == "all" ]]; then
    say "all daemons + role prompts already at target — idempotent skip"
    say "use --phase f to re-run verification only"
    exit 4
  fi
  phase_active a && phase_a
  phase_active b && phase_b
  phase_active c && phase_c
  phase_active d && phase_d
  phase_active e && phase_e
  phase_active f && phase_f
  say "done. Snapshot at $SNAPSHOT (rollback: $0 --rollback $SNAPSHOT)"
}

main "$@"
