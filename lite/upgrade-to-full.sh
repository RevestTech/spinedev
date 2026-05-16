#!/usr/bin/env bash
# upgrade-to-full.sh — migrate from Spine **lite** to a full install while
# preserving any role-prompt / skill / template edits the user made
# locally in ~/.spine-lite/.
#
# Flow:
#   1. Detect ~/.spine-lite/.
#   2. Stage user-modified files (mtime newer than the source ship) to a
#      tempdir.
#   3. Run install.sh (full) against the target project.
#   4. Merge staged customizations back over the full install paths.
#   5. Archive ~/.spine-lite/ → ~/.spine-lite.archive-<ts>/ (or remove,
#      per flag).
#   6. Print verification + rollback instructions.
#
# Implements STORY-4.3.3 (docs/BACKLOG.md, EPIC-4.3).
#
# Exit codes:
#   0  success
#   1  generic failure
#   2  bad usage
#   3  user aborted
#  64  environment problem (no HOME, no lite install, no install.sh found)

set -euo pipefail

SOURCE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LITE_DIR="${HOME:-}/.spine-lite"

log()  { printf '%s  %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }
ok()   { log "OK    $*"; }
warn() { log "WARN  $*" >&2; }
err()  { log "ERROR $*" >&2; }
step() { log "STEP  $*"; }

usage() {
  cat <<'EOF'
Usage: bash upgrade-to-full.sh [options] <target-project-path>

Options:
  --preserve-archive   Keep ~/.spine-lite.archive-<ts>/ after upgrade (default).
  --remove-lite        Remove ~/.spine-lite/ instead of archiving (destructive).
  --dry-run            Show what would happen; do not modify anything.
  -y, --yes            Skip the interactive confirmation prompt.
  -h, --help           Show this help.

The <target-project-path> argument is the project where the full install
will be placed (forwarded to install.sh). Use "." for the current dir.

Examples:
  bash lite/upgrade-to-full.sh ~/projects/my-app
  bash lite/upgrade-to-full.sh --remove-lite ~/projects/my-app
  bash lite/upgrade-to-full.sh --dry-run .
EOF
}

# ── Argument parsing ───────────────────────────────────────────────────
PRESERVE_ARCHIVE=true
DRY_RUN=false
ASSUME_YES=false
TARGET_PROJECT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --preserve-archive) PRESERVE_ARCHIVE=true; shift ;;
    --remove-lite)      PRESERVE_ARCHIVE=false; shift ;;
    --dry-run)          DRY_RUN=true; shift ;;
    -y|--yes)           ASSUME_YES=true; shift ;;
    -h|--help)          usage; exit 0 ;;
    -*)                 err "Unknown option: $1"; usage; exit 2 ;;
    *)                  TARGET_PROJECT="$1"; shift ;;
  esac
done

[[ -z "${HOME:-}" ]] && { err "HOME not set"; exit 64; }
[[ -z "$TARGET_PROJECT" ]] && { err "target project path required"; usage; exit 2; }
[[ -d "$LITE_DIR" ]] || { err "no lite install at $LITE_DIR — nothing to upgrade"; exit 64; }
[[ -f "$SOURCE/install.sh" ]] || { err "full install.sh not found at $SOURCE/install.sh"; exit 64; }
TARGET_PROJECT="$(cd "$TARGET_PROJECT" 2>/dev/null && pwd)" || { err "target project missing: $TARGET_PROJECT"; exit 64; }

# ── Confirmation ───────────────────────────────────────────────────────
log "Plan:"
log "  lite source       : $LITE_DIR"
log "  full source tree  : $SOURCE"
log "  target project    : $TARGET_PROJECT"
log "  preserve archive  : $PRESERVE_ARCHIVE"
log "  dry-run           : $DRY_RUN"
if ! $ASSUME_YES; then
  printf 'Proceed? [y/N] '
  read -r reply
  [[ "$reply" =~ ^[Yy]$ ]] || { warn "Aborted by user"; exit 3; }
fi

# ── Stage user-modified files ──────────────────────────────────────────
STAGE_DIR="$(mktemp -d -t spine-lite-stage-XXXXXX)"
trap 'rm -rf "$STAGE_DIR"' EXIT

stage_modified() {
  local lite_sub="$1" src_sub="$2"
  local lite_path="$LITE_DIR/$lite_sub"
  local src_path="$SOURCE/$src_sub"
  [[ -d "$lite_path" ]] || return 0
  local f rel src_file
  while IFS= read -r -d '' f; do
    rel="${f#$lite_path/}"
    src_file="$src_path/$rel"
    if [[ ! -f "$src_file" ]] || [[ "$f" -nt "$src_file" ]]; then
      mkdir -p "$STAGE_DIR/$lite_sub/$(dirname "$rel")"
      cp "$f" "$STAGE_DIR/$lite_sub/$rel"
      log "  staged: $lite_sub/$rel"
    fi
  done < <(find "$lite_path" -type f -print0)
}

step "Staging user-modified files from $LITE_DIR"
stage_modified "role-prompts" "lib/role-prompts"
stage_modified "skills"       "shared/skills/skills"
stage_modified "templates/intake" "plan/templates/intake"
stage_modified "recipes"      "recipes"

STAGED_COUNT=$(find "$STAGE_DIR" -type f 2>/dev/null | wc -l | tr -d ' ')
log "Staged $STAGED_COUNT modified file(s) total."

# ── Run full install ───────────────────────────────────────────────────
step "Running full install.sh against $TARGET_PROJECT"
if $DRY_RUN; then
  warn "  (dry-run) would run: bash $SOURCE/install.sh $TARGET_PROJECT"
else
  bash "$SOURCE/install.sh" "$TARGET_PROJECT" || { err "full install failed"; exit 1; }
fi

# ── Merge staged customizations back over the full install ─────────────
merge_back() {
  local lite_sub="$1" full_sub="$2" rename_to_role_prompt="${3:-false}"
  local stage_path="$STAGE_DIR/$lite_sub"
  [[ -d "$stage_path" ]] || return 0
  local f rel dst
  while IFS= read -r -d '' f; do
    rel="${f#$stage_path/}"
    if [[ "$rename_to_role_prompt" == "true" ]]; then
      local role="${rel%.md}"
      dst="$TARGET_PROJECT/$full_sub/$role/role-prompt.md"
    else
      dst="$TARGET_PROJECT/$full_sub/$rel"
    fi
    if $DRY_RUN; then
      warn "  (dry-run) would merge: $rel → $dst"
    else
      mkdir -p "$(dirname "$dst")"
      cp "$f" "$dst" && ok "  merged: $rel → $dst"
    fi
  done < <(find "$stage_path" -type f -print0)
}

step "Merging staged customizations into full install"
merge_back "role-prompts" ".planning/orchestration/agent-handoff/teams" true
merge_back "skills" "shared/skills/skills" false
merge_back "templates/intake" "plan/templates/intake" false
merge_back "recipes" ".planning/orchestration/recipes" false

# ── Archive or remove lite ─────────────────────────────────────────────
TS="$(date -u +%Y%m%dT%H%M%SZ)"
ARCHIVE_DIR="$HOME/.spine-lite.archive-$TS"
step "Finalizing lite directory"
if $DRY_RUN; then
  warn "  (dry-run) would $( $PRESERVE_ARCHIVE && echo archive || echo remove ) $LITE_DIR"
elif $PRESERVE_ARCHIVE; then
  mv "$LITE_DIR" "$ARCHIVE_DIR"
  ok "  Archived: $ARCHIVE_DIR (remove when you've confirmed everything works)"
else
  rm -rf "$LITE_DIR"
  ok "  Removed:  $LITE_DIR"
fi

# ── Verify ─────────────────────────────────────────────────────────────
step "Verifying full install"
if $DRY_RUN; then
  warn "  (dry-run) skipping verification"
else
  local_ok=true
  for role in engineer product architect planner; do
    p="$TARGET_PROJECT/.planning/orchestration/agent-handoff/teams/$role/role-prompt.md"
    if [[ -f "$p" ]]; then
      ok "  $p"
    else
      err "  MISSING $p"
      local_ok=false
    fi
  done
  $local_ok && ok "Verification passed" || warn "Verification incomplete — review missing paths above"
fi

# ── Done ───────────────────────────────────────────────────────────────
ok "Upgrade complete."
cat <<EOF

Next steps:

  cd $TARGET_PROJECT
  make team-up          # start manager + worker daemons
  make team-status      # confirm everything's running

EOF
if $PRESERVE_ARCHIVE && ! $DRY_RUN; then
  echo "Once you've confirmed daemons start and your customizations carried over:"
  echo "  rm -rf $ARCHIVE_DIR"
  echo ""
fi
