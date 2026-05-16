#!/usr/bin/env bash
# install-lite.sh — Spine **lite** installer.
#
# Ships role prompts, skills, intake templates, and (optionally) recipes into
# ~/.spine-lite/ for use inside Claude Code. No Postgres, no Docker, no
# daemons, no MCP server. Upgrade to full later via `upgrade-to-full.sh`.
#
# Implements STORY-4.3.1 (docs/BACKLOG.md, EPIC-4.3).
#
# Exit codes:
#   0   success
#   1   generic failure (missing source files, copy error)
#   2   bad usage / unknown subcommand
#   3   user aborted (e.g. uninstall confirmation declined)
#  64   environment problem (no HOME, unwritable target, etc.)

set -euo pipefail

# ── Constants ──────────────────────────────────────────────────────────
SOURCE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEFAULT_TARGET="${HOME:-}/.spine-lite"
SPINE_LITE_VERSION="v2-lite-1"

# ── Logging (ISO-8601 timestamps) ──────────────────────────────────────
log()  { printf '%s  %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }
ok()   { log "OK    $*"; }
warn() { log "WARN  $*" >&2; }
err()  { log "ERROR $*" >&2; }
step() { log "STEP  $*"; }

# ── Helpers ────────────────────────────────────────────────────────────
require_home() {
  if [[ -z "${HOME:-}" ]]; then
    err "HOME is not set; cannot determine install target"
    exit 64
  fi
}

usage() {
  cat <<'EOF'
Usage: bash install-lite.sh <subcommand> [options]

Subcommands:
  install [--target-dir PATH] [--with-skills] [--with-templates] [--with-recipes]
                          Install Spine lite. Role prompts always installed.
                          Skills + intake templates ship by default; pass the
                          --with-* flags to be explicit (they have no negative
                          form here — use manifest.yaml to disable).
  update [--target-dir PATH]
                          Refresh contents from this source tree. Preserves
                          any files the user has modified (mtime newer than
                          source) — diffed, not clobbered.
  status [--target-dir PATH]
                          Print which components are installed and the
                          recorded version.
  uninstall [--target-dir PATH] [--yes]
                          Remove the lite install dir. Prompts unless --yes.
  as-claude-code-plugin   Register Spine lite as a Claude Code plugin at
                          ~/.claude/plugins/spine/. Detects Claude Code in
                          common locations; symlinks the bundle.

Examples:
  bash lite/install-lite.sh install
  bash lite/install-lite.sh install --with-recipes
  bash lite/install-lite.sh install --target-dir /opt/spine-lite
  bash lite/install-lite.sh as-claude-code-plugin
  bash lite/install-lite.sh uninstall --yes
EOF
}

# ── Argument parsing ───────────────────────────────────────────────────
SUBCMD="${1:-}"
[[ -z "$SUBCMD" ]] && { usage; exit 2; }
shift || true

TARGET="$DEFAULT_TARGET"
WITH_SKILLS=true
WITH_TEMPLATES=true
WITH_RECIPES=false
ASSUME_YES=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --target-dir)    TARGET="$2"; shift 2 ;;
    --target-dir=*)  TARGET="${1#--target-dir=}"; shift ;;
    --with-skills)   WITH_SKILLS=true; shift ;;
    --with-templates) WITH_TEMPLATES=true; shift ;;
    --with-recipes)  WITH_RECIPES=true; shift ;;
    --yes|-y)        ASSUME_YES=true; shift ;;
    -h|--help)       usage; exit 0 ;;
    *)               err "Unknown option: $1"; usage; exit 2 ;;
  esac
done

# ── Source-tree resolution (lib/role-prompts vs build/roles post-migration) ─
resolve_role_prompts_src() {
  if [[ -d "$SOURCE/build/roles" ]]; then
    printf '%s\n' "$SOURCE/build/roles"
  elif [[ -d "$SOURCE/lib/role-prompts" ]]; then
    printf '%s\n' "$SOURCE/lib/role-prompts"
  else
    err "No role-prompts source found (looked in build/roles, lib/role-prompts)"
    exit 1
  fi
}

# ── Copy helpers (idempotent; never clobbers user-modified files) ──────
safe_copy_file() {
  local src="$1" dst="$2"
  if [[ ! -f "$src" ]]; then warn "missing: $src"; return 0; fi
  if [[ -f "$dst" ]] && [[ "$dst" -nt "$src" ]]; then
    warn "kept (user-modified, newer than source): $dst"
    return 0
  fi
  mkdir -p "$(dirname "$dst")"
  cp "$src" "$dst" && ok "  $dst"
}

safe_copy_tree() {
  local src="$1" dst="$2"
  [[ -d "$src" ]] || { warn "missing tree: $src"; return 0; }
  mkdir -p "$dst"
  local f rel
  while IFS= read -r -d '' f; do
    rel="${f#$src/}"
    safe_copy_file "$f" "$dst/$rel"
  done < <(find "$src" -type f -print0)
}

# ── Component installers ───────────────────────────────────────────────
install_role_prompts() {
  step "Installing role prompts"
  local rp_src; rp_src="$(resolve_role_prompts_src)"
  local rp_dst="$TARGET/role-prompts"
  mkdir -p "$rp_dst"
  shopt -s nullglob
  if [[ "$rp_src" == */build/roles ]]; then
    # post-migration layout: build/roles/<role>/prompt.md
    local d role
    for d in "$rp_src"/*/; do
      role="$(basename "$d")"
      [[ "$role" == _* ]] && continue
      [[ -f "$d/prompt.md" ]] && safe_copy_file "$d/prompt.md" "$rp_dst/$role.md"
    done
  else
    # legacy layout: lib/role-prompts/<role>.md
    local f base
    for f in "$rp_src"/*.md; do
      base="$(basename "$f")"
      [[ "$base" == _* ]] && continue
      safe_copy_file "$f" "$rp_dst/$base"
    done
  fi
  shopt -u nullglob
}

install_skills() {
  $WITH_SKILLS || { warn "skipping skills (--with-skills not set)"; return 0; }
  step "Installing skills"
  safe_copy_tree "$SOURCE/shared/skills/skills" "$TARGET/skills"
}

install_templates() {
  $WITH_TEMPLATES || { warn "skipping templates"; return 0; }
  step "Installing intake templates"
  safe_copy_tree "$SOURCE/plan/templates/intake" "$TARGET/templates/intake"
}

install_recipes() {
  $WITH_RECIPES || return 0
  step "Installing recipes (opt-in)"
  safe_copy_tree "$SOURCE/recipes" "$TARGET/recipes"
}

install_artifacts_docs() {
  step "Installing artifact schemas (documentation reference only)"
  safe_copy_tree "$SOURCE/plan/artifacts" "$TARGET/artifacts"
  cat > "$TARGET/artifacts/README-lite.md" <<'EOF'
# Pydantic artifact schemas — documentation only in lite mode

These schemas describe PRD/TRD/Roadmap shape. In **lite** mode they are not
runnable (no validator daemon). In **full** mode the same files are loaded
by the SDLC pipeline. Useful as a reference when hand-rolling artifacts in
Claude Code chat.
EOF
}

write_spine_md() {
  step "Writing $TARGET/SPINE.md (master doc loaded by Claude Code)"
  mkdir -p "$TARGET"
  cat > "$TARGET/SPINE.md" <<EOF
# Spine — lite mode

Installed: $(date -u +%Y-%m-%dT%H:%M:%SZ)
Version:   $SPINE_LITE_VERSION
Source:    $SOURCE
Target:    $TARGET

## What you have

- Role prompts in \`role-prompts/\` — invoke via @-mention in Claude Code.
- Skills in \`skills/\` — auto-trigger on matching contexts.
- Intake templates in \`templates/intake/\` — PRD/TRD scaffolds.
- Artifact schemas in \`artifacts/\` — documentation reference (lite mode).
$( $WITH_RECIPES && echo "- Recipes in \`recipes/\` — runnable narratives." )

## What you do NOT have (lite mode)

No daemons, no Postgres, no MCP server, no audit log, no cost router, no
knowledge graph. See \`feature_matrix.md\` for the full lite-vs-full table.

## Upgrade to full

Run \`bash lite/upgrade-to-full.sh\` — your customizations are preserved.
EOF
  ok "  $TARGET/SPINE.md"
}

write_install_receipt() {
  cat > "$TARGET/.install-receipt" <<EOF
spine_lite_version=$SPINE_LITE_VERSION
installed_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
source=$SOURCE
with_skills=$WITH_SKILLS
with_templates=$WITH_TEMPLATES
with_recipes=$WITH_RECIPES
EOF
}

# ── Subcommands ────────────────────────────────────────────────────────
do_install() {
  require_home
  step "Installing Spine lite ($SPINE_LITE_VERSION) → $TARGET"
  mkdir -p "$TARGET" || { err "cannot create $TARGET"; exit 64; }
  install_role_prompts
  install_skills
  install_templates
  install_recipes
  install_artifacts_docs
  write_spine_md
  write_install_receipt
  ok "Lite install complete at $TARGET"
  log "Next: open Claude Code in any project — role prompts available via @-mention; skills auto-trigger."
}

do_update() {
  require_home
  [[ -d "$TARGET" ]] || { err "no existing install at $TARGET — run 'install' first"; exit 1; }
  step "Updating Spine lite at $TARGET (preserves user-modified files)"
  do_install
}

do_status() {
  require_home
  if [[ ! -d "$TARGET" ]]; then
    log "Not installed at $TARGET"
    exit 0
  fi
  log "Lite install at $TARGET"
  if [[ -f "$TARGET/.install-receipt" ]]; then
    while IFS= read -r line; do log "  $line"; done < "$TARGET/.install-receipt"
  fi
  for sub in role-prompts skills templates/intake recipes artifacts; do
    if [[ -d "$TARGET/$sub" ]]; then
      log "  $sub/ : $(find "$TARGET/$sub" -type f | wc -l | tr -d ' ') files"
    fi
  done
}

do_uninstall() {
  require_home
  [[ -d "$TARGET" ]] || { log "Nothing to remove at $TARGET"; exit 0; }
  if ! $ASSUME_YES; then
    printf 'Remove %s? [y/N] ' "$TARGET"
    read -r reply
    [[ "$reply" =~ ^[Yy]$ ]] || { warn "Aborted"; exit 3; }
  fi
  rm -rf "$TARGET"
  ok "Removed $TARGET"
}

do_as_plugin() {
  require_home
  [[ -d "$TARGET" ]] || { err "lite install not found at $TARGET — run 'install' first"; exit 1; }
  local cc_root="" candidate
  for candidate in "$HOME/.claude" "$HOME/.config/claude" "$HOME/Library/Application Support/Claude"; do
    [[ -d "$candidate" ]] && { cc_root="$candidate"; break; }
  done
  [[ -n "$cc_root" ]] || { err "Claude Code config dir not found (looked in ~/.claude, ~/.config/claude, ~/Library/Application Support/Claude)"; exit 1; }
  local plugin_dir="$cc_root/plugins/spine"
  step "Registering Spine lite as Claude Code plugin at $plugin_dir"
  mkdir -p "$(dirname "$plugin_dir")"
  rm -rf "$plugin_dir"
  ln -s "$TARGET" "$plugin_dir"
  cp "$SOURCE/lite/claude-code-plugin/spine.json" "$TARGET/spine.json" 2>/dev/null || true
  ok "Linked $plugin_dir → $TARGET"
  log "Restart Claude Code to load the plugin."
}

case "$SUBCMD" in
  install)              do_install ;;
  update)               do_update ;;
  status)               do_status ;;
  uninstall)            do_uninstall ;;
  as-claude-code-plugin) do_as_plugin ;;
  -h|--help|help)       usage; exit 0 ;;
  *)                    err "Unknown subcommand: $SUBCMD"; usage; exit 2 ;;
esac
