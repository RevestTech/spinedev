#!/usr/bin/env bash
# update_protocol_refs.sh — STORY-7.5.2: rewrite lib/team-agent-daemon.sh
# and lib/role-prompts/ references in docs + makefiles + tests to point at
# the new build/daemons/ and build/roles/<role>/prompt.md locations.
#
# Usage:
#   build/migration/update_protocol_refs.sh [--dry-run] [--restore]
#
# Edits in-place with .bak backups (sed -i.bak). --restore reverts from .bak.
# Idempotent: re-running is a no-op once references are converted.
#
# Cross-refs: docs/PRD.md REQ-INIT-7 §7.5 FR-5; build/migration/migrate_daemons.sh
# phase D; docs/BACKLOG.md STORY-7.5.2.

set -euo pipefail

DRY_RUN=0
RESTORE=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --restore) RESTORE=1 ;;
    -h|--help) sed -n '2,15p' "$0"; exit 0 ;;
    *) echo "unknown flag: $arg" >&2; exit 64 ;;
  esac
done

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

# Files we own + edit. Anything not in this list is left alone (e.g.
# CHANGELOG, ADR text, archival history is preserved as-is per PROTOCOL §16).
TARGETS=(
  "$ROOT/PROTOCOL.md"
  "$ROOT/INSTALL.md"
  "$ROOT/README.md"
  "$ROOT/Makefile.v2"
  "$ROOT/Makefile"
  "$ROOT/docs/PRACTICES.md"
  "$ROOT/docs/IMPROVEMENT_CHECKLIST.md"
  "$ROOT/build/README.md"
  "$ROOT/build/runtime/runtime_README.md"
  "$ROOT/build/runtime/__init__.py"
  "$ROOT/build/runtime/kg_caller.py"
  "$ROOT/plan/decomposer/decomposer_README.md"
  "$ROOT/plan/swarm/swarm_README.md"
  "$ROOT/shared/eval/runner_README.md"
  "$ROOT/shared/eval/README.md"
  "$ROOT/shared/eval/runner_design.md"
  "$ROOT/shared/skills/skills_README.md"
  "$ROOT/shared/skills/skills/brainstorming/SKILL.md"
  "$ROOT/shared/skills/skills/verification-before-completion/SKILL.md"
  "$ROOT/shared/standards/install_README.md"
  "$ROOT/shared/reproducibility/manifest.py"
  "$ROOT/install.sh"
)

# Tests intentionally migrate too (they reference scripts/*.sh, but the
# role-prompt path is keyed to lib/role-prompts/).
TEST_FILES=()
if [[ -d "$ROOT/lib/tests" ]]; then
  while IFS= read -r -d '' f; do TEST_FILES+=("$f"); done < <(find "$ROOT/lib/tests" -maxdepth 1 -name 'test-*.sh' -print0 2>/dev/null)
fi

say()  { printf '[update_protocol_refs %s] %s\n' "$(date -u +%FT%TZ)" "$*"; }
warn() { printf '[update_protocol_refs %s] WARN: %s\n' "$(date -u +%FT%TZ)" "$*" >&2; }

# sed program: rewrite the path tokens. Anchored to avoid double-rewriting
# something already pointing under build/.
SED_PROG='
  s@\([^A-Za-z0-9_/]\)lib/team-agent-daemon\.sh@\1build/daemons/team-agent-daemon.sh@g
  s@^lib/team-agent-daemon\.sh@build/daemons/team-agent-daemon.sh@g
  s@\([^A-Za-z0-9_/]\)lib/role-prompts/\([a-z][a-z-]*\)\.md@\1build/roles/\2/prompt.md@g
  s@^lib/role-prompts/\([a-z][a-z-]*\)\.md@build/roles/\1/prompt.md@g
  s@\([^A-Za-z0-9_/]\)lib/role-prompts/@\1build/roles/@g
  s@^lib/role-prompts/@build/roles/@g
'

restore_one() {
  local f="$1"
  if [[ -f "$f.bak" ]]; then
    say "restore $f"
    if (( ! DRY_RUN )); then mv "$f.bak" "$f"; fi
  fi
}

rewrite_one() {
  local f="$1"
  [[ -f "$f" ]] || { say "skip (missing): $f"; return 0; }
  if ! grep -qE 'lib/team-agent-daemon\.sh|lib/role-prompts/' "$f" 2>/dev/null; then
    say "ok (no refs): $f"
    return 0
  fi
  say "rewrite: $f"
  if (( DRY_RUN )); then
    grep -nE 'lib/team-agent-daemon\.sh|lib/role-prompts/' "$f" | sed 's/^/  /'
    return 0
  fi
  # macOS + GNU sed both accept -i.bak with a positional arg.
  sed -i.bak "$SED_PROG" "$f"
  # Drop the backup if rewrite made no changes (defensive against sed no-op).
  if cmp -s "$f" "$f.bak"; then
    rm -f "$f.bak"
    say "  (no diff after sed — backup removed)"
  fi
}

main() {
  local files=( "${TARGETS[@]}" "${TEST_FILES[@]}" )
  if (( RESTORE )); then
    say "restoring from .bak files"
    for f in "${files[@]}"; do restore_one "$f"; done
    say "restore done"
    return
  fi

  for f in "${files[@]}"; do rewrite_one "$f"; done

  # Sanity report: any unconverted refs remain?
  local stale
  stale=$(grep -lE 'lib/team-agent-daemon\.sh|lib/role-prompts/' "${files[@]}" 2>/dev/null || true)
  if [[ -n "$stale" ]]; then
    warn "remaining references (intentional? CHANGELOG / archive?):"
    printf '  %s\n' $stale
  fi
  say "done."
}

main "$@"
