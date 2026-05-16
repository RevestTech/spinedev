#!/usr/bin/env bash
# migrate-to-shared.sh — STORY-8.3.3: relocate db/ → shared/db/.
#
# Usage: db/migrate-to-shared.sh [--dry-run] [--verify-only] [--leave-symlink]
#
# Moves db/ (Postgres + Flyway + dashboard + watcher) under shared/db/, then
# rewrites internal path references in Makefile, Makefile.v2,
# docker-compose.yml. Safe to re-run; verification is idempotent.
#
# Run AFTER stopping spine_postgres / spine_watcher / spine_dashboard
# containers. Refuses to run if any are detected.
#
# Cross-refs: docs/ARCHITECTURE.md §6 Phase 2; db/multi-schema-layout.md;
# docs/BACKLOG.md STORY-8.3.3; db/migrate-to-shared_README.md.

set -euo pipefail

DRY_RUN=0; VERIFY_ONLY=0; LEAVE_SYMLINK=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --verify-only) VERIFY_ONLY=1 ;;
    --leave-symlink) LEAVE_SYMLINK=1 ;;
    -h|--help) sed -n '2,15p' "$0"; exit 0 ;;
    *) echo "unknown flag: $arg" >&2; exit 2 ;;
  esac
done

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/db"; DST="$ROOT/shared/db"

say() { printf '[migrate-to-shared] %s\n' "$*"; }
run() { if (( DRY_RUN )); then say "DRY-RUN: $*"; else eval "$@"; fi }

preflight() {
  say "pre-flight: checking repo state"
  [[ -d "$SRC" ]] || { say "source db/ missing — nothing to do"; exit 0; }
  [[ -d "$ROOT/shared" ]] || { say "shared/ missing"; exit 1; }
  if [[ -e "$DST" && ! -L "$DST" ]]; then
    say "destination $DST exists — refusing to overwrite"; exit 1
  fi
  if command -v docker >/dev/null 2>&1; then
    local running
    running=$(docker ps --format '{{.Names}}' 2>/dev/null \
              | grep -E '^(spine_postgres|spine_watcher|spine_dashboard)$' || true)
    [[ -z "$running" ]] || { say "ERROR: containers running: $running — stop them first"; exit 1; }
  fi
  ( cd "$ROOT" && git diff --quiet -- db/ ) \
    || say "WARN: uncommitted changes in db/ — they will be moved as-is"
}

verify() {
  say "verify: checking path references"
  local check_dir
  check_dir="$([[ -e "$DST" ]] && echo "$DST" || echo "$SRC")"
  local ok=1
  [[ -f "$check_dir/flyway/sql/V1__init_core_schema.sql" ]] \
    || { say "MISSING: V1 SQL not found under $check_dir"; ok=0; }
  [[ -f "$check_dir/docker-compose.yml" ]] \
    || { say "MISSING: docker-compose.yml under $check_dir"; ok=0; }
  if [[ -e "$DST" ]]; then
    local stale
    stale=$(grep -rEn '(^|[^/])db/flyway|cd db\b|\./db\b' \
              "$ROOT/Makefile" "$ROOT/Makefile.v2" 2>/dev/null \
              | grep -v 'shared/db' || true)
    [[ -z "$stale" ]] || { say "STALE refs still point at db/:"; printf '  %s\n' $stale; ok=0; }
  fi
  (( ok )) && say "verify OK" || { say "verify FAILED"; exit 3; }
}

rewrite_paths() {
  say "rewrite: db/ → shared/db/ in build files"
  local files=( "$ROOT/Makefile" "$ROOT/Makefile.v2" "$ROOT/docker-compose.yml" )
  for f in "${files[@]}"; do
    [[ -f "$f" ]] || continue
    if (( DRY_RUN )); then
      say "DRY-RUN: would rewrite $f"
      grep -nE '(^|[^/])db/(flyway|dashboard|watcher|Makefile|README|docker-compose)|cd db\b' "$f" || true
    else
      sed -i.bak -E \
        -e 's@(^|[^/a-zA-Z0-9_])db/flyway@\1shared/db/flyway@g' \
        -e 's@(^|[^/a-zA-Z0-9_])db/dashboard@\1shared/db/dashboard@g' \
        -e 's@(^|[^/a-zA-Z0-9_])db/watcher@\1shared/db/watcher@g' \
        -e 's@(^|[^/a-zA-Z0-9_])db/docker-compose@\1shared/db/docker-compose@g' \
        -e 's@(^|[^/a-zA-Z0-9_])db/Makefile@\1shared/db/Makefile@g' \
        -e 's@(^|[^/a-zA-Z0-9_])db/README@\1shared/db/README@g' \
        -e 's@\bcd db\b@cd shared/db@g' "$f"
      rm -f "$f.bak"
    fi
  done
}

move_dir() {
  say "move: git mv db shared/db"
  run "cd '$ROOT' && git mv db shared/db"
  if (( LEAVE_SYMLINK )); then
    say "symlink: db -> shared/db for legacy callers"
    run "cd '$ROOT' && ln -s shared/db db"
  fi
}

main() {
  if (( VERIFY_ONLY )); then verify; exit 0; fi
  preflight
  move_dir
  rewrite_paths
  verify
  say "done. Run 'make migrate' from repo root to confirm Flyway sees V1..V21."
}

main "$@"
