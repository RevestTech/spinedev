#!/usr/bin/env bash
# install.sh — install the agent team into a target project.
#
# Usage:
#   bash install.sh <target-project-path> [--force]
#   bash install.sh <target-project-path> --pull-knowledge-only [--force]
#
# Idempotent — safe to re-run. Existing files are kept unless you pass --force
# where noted below.

set -uo pipefail

err() { printf '%s\n' "$*" >&2; }

FORCE=false
KNOWLEDGE_ONLY=false
HUB_URL=""
declare -a POSARGS=()
expect_hub_value=false
for arg in "$@"; do
  if $expect_hub_value; then
    HUB_URL="$arg"
    expect_hub_value=false
    continue
  fi
  case "$arg" in
    --force) FORCE=true ;;
    --pull-knowledge-only|--knowledge-only) KNOWLEDGE_ONLY=true ;;
    --hub) expect_hub_value=true ;;
    --hub=*) HUB_URL="${arg#--hub=}" ;;
    *) POSARGS+=("$arg") ;;
  esac
done

TARGET="${POSARGS[0]:-}"

usage() {
  cat <<'EOF'
Usage: bash install.sh <target-project-path> [options]

Options:
  --force                 Overwrite role prompts, recipes, and templates where
                          the installer would otherwise keep existing files.
  --pull-knowledge-only   Update protocol, requirements, recipes, role prompts,
                          playbook seeds, practice docs, and ADR templates only.
                          Does NOT replace scripts/*.sh, dashboard HTML, Makefile,
                          lib/tests/, makefile selftest wiring, notification hook,
                          or CLAUDE.md. Skips host preflight. (See PROTOCOL §10b.)
  --hub <url>             Mark this install as a JOINING machine (Machine B).
                          Writes the hub Postgres URL to
                          .planning/orchestration/.hub-url so a later
                          `bash scripts/spine-connect.sh` can pick it up.

Examples:
  bash install.sh ~/projects/my-new-app
  bash install.sh . --force
  bash install.sh ~/projects/existing --pull-knowledge-only
  bash install.sh ~/projects/joiner --hub "postgresql://spine:spine_dev_only@192.168.1.42:33000/spine"
EOF
}

if [[ -z "$TARGET" || "$TARGET" == -* ]]; then
  usage
  exit 1
fi

TARGET="$(cd "$TARGET" && pwd)" || { err "FATAL: target does not exist or is not a directory"; exit 1; }
SOURCE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ ! -f "$SOURCE/lib/roles.sh" ]]; then
  err "FATAL: missing $SOURCE/lib/roles.sh"
  exit 1
fi
# shellcheck source=/dev/null
source "$SOURCE/lib/roles.sh"
ROLES=("${SPINE_TEAM_ROLES[@]}")

if [[ -t 1 ]]; then
  C_BLUE='\033[0;34m'; C_GREEN='\033[0;32m'; C_YELLOW='\033[0;33m'; C_DIM='\033[2m'; C_RESET='\033[0m'
else
  C_BLUE=''; C_GREEN=''; C_YELLOW=''; C_DIM=''; C_RESET=''
fi

step() { printf "${C_BLUE}▸${C_RESET} %s\n" "$*"; }
ok()   { printf "${C_GREEN}✓${C_RESET} %s\n" "$*"; }
warn() { printf "${C_YELLOW}!${C_RESET} %s\n" "$*"; }
dim()  { printf "${C_DIM}%s${C_RESET}\n" "$*"; }

TEAM_BASE="$TARGET/.planning/orchestration/agent-handoff/teams"
ORCHESTRATION="$TARGET/.planning/orchestration"

install_orchestration_docs() {
  mkdir -p "$ORCHESTRATION"
  cp "$SOURCE/PROTOCOL.md" "$ORCHESTRATION/AGENT_TEAM_PROTOCOL.md"
  ok "  $ORCHESTRATION/AGENT_TEAM_PROTOCOL.md"
  if [[ -f "$SOURCE/REQUIREMENTS.md" ]]; then
    cp "$SOURCE/REQUIREMENTS.md" "$ORCHESTRATION/AGENT_TEAM_REQUIREMENTS.md"
    ok "  $ORCHESTRATION/AGENT_TEAM_REQUIREMENTS.md"
  fi
}

install_recipes() {
  local dest="$ORCHESTRATION/recipes"
  mkdir -p "$dest"
  if [[ ! -d "$SOURCE/recipes" ]]; then
    warn "  $SOURCE/recipes missing — skipping"
    return 0
  fi
  shopt -s nullglob
  local item
  for item in "$SOURCE/recipes"/*; do
    [[ -f "$item" ]] || continue
    local base
    base=$(basename "$item")
    if [[ -f "$dest/$base" && "$FORCE" == false ]]; then
      warn "  $dest/$base exists — keeping (pass --force to overwrite)"
    else
      cp "$item" "$dest/$base"
      ok "  $dest/$base"
    fi
  done
  shopt -u nullglob
}

install_templates() {
  local tdir="$SOURCE/templates/orchestration"
  [[ -d "$tdir" ]] || return 0
  mkdir -p "$ORCHESTRATION"
  local f
  for f in DECISIONS.md ADR_TEMPLATE.md; do
    [[ -f "$tdir/$f" ]] || continue
    local dst="$ORCHESTRATION/$f"
    if [[ -f "$dst" && "$FORCE" == false ]]; then
      warn "  $dst exists — keeping (pass --force to overwrite)"
    else
      cp "$tdir/$f" "$dst"
      ok "  $dst"
    fi
  done
}

install_practice_docs() {
  local destd="$ORCHESTRATION/docs"
  mkdir -p "$destd"
  local f
  for f in SPINE_PRACTICES.md IMPROVEMENT_CHECKLIST.md EXTENSIONS.md PROGRAM_DELIVERY.md; do
    [[ -f "$SOURCE/docs/$f" ]] || continue
    local dst="$destd/$f"
    if [[ -f "$dst" && "$FORCE" == false ]]; then
      warn "  $dst exists — keeping (pass --force to overwrite)"
    else
      cp "$SOURCE/docs/$f" "$dst"
      ok "  $dst"
    fi
  done
}

install_program_templates() {
  local pdir="$SOURCE/templates/program"
  [[ -d "$pdir" ]] || return 0
  local dest="$ORCHESTRATION/program"
  mkdir -p "$dest/ux" "$dest/qa"
  local pf
  shopt -s nullglob
  for pf in "$pdir"/*; do
    [[ -f "$pf" ]] || continue
    local bn dst
    bn=$(basename "$pf")
    dst="$dest/$bn"
    if [[ -f "$dst" && "$FORCE" == false ]]; then
      warn "  $dst exists — keeping (pass --force to overwrite)"
    else
      cp "$pf" "$dst"
      ok "  $dst"
    fi
  done
  shopt -u nullglob
}

install_role_prompts() {
  for role in "${ROLES[@]}"; do
    local src="$SOURCE/lib/role-prompts/$role.md"
    local dst="$TEAM_BASE/$role/role-prompt.md"
    if [[ ! -f "$src" ]]; then
      err "MISSING role prompt $src"
      return 1
    fi
    if [[ -f "$dst" && "$FORCE" == false ]]; then
      warn "  $dst exists — keeping (pass --force to overwrite)"
    else
      cp "$src" "$dst"
      ok "  $dst"
    fi
  done
}

team_scaffold_dirs() {
  for role in "${ROLES[@]}"; do
    mkdir -p \
      "$TEAM_BASE/$role/workers/archive" \
      "$TEAM_BASE/$role/state" \
      "$TEAM_BASE/$role/log" \
      "$TEAM_BASE/$role/scratch"
    touch "$TEAM_BASE/$role/scratch/.gitkeep"
    ok "  $TEAM_BASE/$role/{workers,state,log,scratch}/"
  done
}

init_directive_placeholders() {
  for role in "${ROLES[@]}"; do
    local dst="$TEAM_BASE/$role/directive.md"
    if [[ -f "$dst" && "$FORCE" == false ]]; then
      warn "  $dst exists — keeping"
    else
      cat > "$dst" <<EOF
# (idle — drop a # Directive here)

This file is polled by the $role manager daemon every 8 seconds. To assign work, replace this content with a directive starting with \`# Directive — <goal>\`. See PROTOCOL.md for the contract.
EOF
      ok "  $dst (placeholder)"
    fi
  done
}

seed_playbooks() {
  step "Setting up cross-project playbook"
  mkdir -p "$HOME/.spine-development/playbook"
  local role
  for role in "${ROLES[@]}" general; do
    mkdir -p "$HOME/.spine-development/playbook/$role"
  done
  ok "  ~/.spine-development/playbook/{$(IFS=,; echo "${ROLES[*]},general")}/"

  local SEEDED_COUNT=0
  for role in engineer operator datawright; do
    local src="$SOURCE/lib/playbook-defaults/$role.md"
    local dst="$HOME/.spine-development/playbook/$role/lessons.md"
    if [[ -f "$src" && ! -f "$dst" ]]; then
      cp "$src" "$dst"
      ok "  Seeded $dst (defaults)"
      SEEDED_COUNT=$((SEEDED_COUNT + 1))
    elif [[ -f "$dst" ]]; then
      dim "  $dst exists — keeping (your lessons preserved)"
    fi
  done
  if [[ $SEEDED_COUNT -gt 0 ]]; then
    dim "  Append your own with:"
    dim "    bash scripts/team.sh learn \"the lesson\" --role <role>"
  fi
  echo
}

# ── Knowledge-only install (no scripts/dashboard/makefile) ─────────────
if [[ "$KNOWLEDGE_ONLY" == true ]]; then
  step "Knowledge-only refresh into $TARGET"
  echo "  source: $SOURCE"
  dim "Skips: preflight, scripts/, dashboard, Makefile, lib/tests/, selftest wiring, notify hook, CLAUDE.md"
  echo

  step "Creating team directory scaffolding (if needed)"
  team_scaffold_dirs
  echo

  step "Installing protocol + requirements documentation"
  install_orchestration_docs
  echo

  step "Installing recipes"
  install_recipes
  echo

  step "Orchestration templates + practice docs"
  install_templates
  install_program_templates
  install_practice_docs
  echo

  step "Installing role prompts"
  install_role_prompts || exit 1
  echo

  step "Initializing idle directives (missing files only)"
  init_directive_placeholders
  echo

  seed_playbooks

  ok "Knowledge refresh complete."
  cat <<EOF

Orchestration layout:

  $ORCHESTRATION/AGENT_TEAM_PROTOCOL.md
  $ORCHESTRATION/recipes/
  $ORCHESTRATION/docs/SPINE_PRACTICES.md
  DECISIONS / ADR templates (if copied): $ORCHESTRATION/

Daemons unchanged. To refresh scripts/dashboard from this package, run a full install (without --pull-knowledge-only), or copy files manually from:

  $SOURCE/lib/
  (includes \`spine-migrate.py\` → \`scripts/spine-migrate.py\` on full install)
EOF
  exit 0
fi

# ── Full install ────────────────────────────────────────────────────────
step "Installing agent team into $TARGET"
echo "  source: $SOURCE"
echo

step "Running host preflight check"
if [[ -f "$SOURCE/lib/preflight.sh" ]]; then
  if bash "$SOURCE/lib/preflight.sh"; then
    echo
  else
    echo
    err "Preflight failed. Install the missing tools, then re-run this installer."
    err "See $SOURCE/REQUIREMENTS.md for a per-platform install guide."
    exit 1
  fi
else
  warn "  lib/preflight.sh missing — skipping host check"
fi
echo

step "Creating team directory scaffolding"
team_scaffold_dirs
echo

step "Installing role prompts"
install_role_prompts || exit 1
echo

step "Initializing idle directive placeholders"
init_directive_placeholders
echo

step "Installing scripts"
mkdir -p "$TARGET/scripts"
# Wave 3 (Squad A): nine substrate scripts migrated lib/ → shared/runtime/.
# Resolve each from shared/runtime/ first, then fall back to lib/ for
# scripts that have not yet been migrated.
RUNTIME_MIGRATED="vitals.sh heartbeat.sh watchdog.sh notify.sh executor.sh usage-parsers.sh file-lock.sh updater.sh db-outbox.sh"
for f in roles.sh team-agent-daemon.sh team.sh seer-tick.sh file-lock.sh team-clean.sh watchdog.sh executor.sh costs-csv.sh preflight.sh serve-dashboard.sh heartbeat.sh db-outbox.sh engagement-hook.sh updater.sh vitals.sh share-pg.sh spine-connect.sh spine-disconnect.sh run-standalone-watcher.sh; do
  src=""
  if [[ " $RUNTIME_MIGRATED " == *" $f "* && -f "$SOURCE/shared/runtime/$f" ]]; then
    src="$SOURCE/shared/runtime/$f"
  elif [[ -f "$SOURCE/lib/$f" ]]; then
    src="$SOURCE/lib/$f"
  else
    warn "  $f missing in both shared/runtime/ and lib/ — skipping"
    continue
  fi
  cp "$src" "$TARGET/scripts/$f"
  chmod +x "$TARGET/scripts/$f"
  ok "  $TARGET/scripts/$f"
done
if [[ -f "$SOURCE/lib/spine-migrate.py" ]]; then
  cp "$SOURCE/lib/spine-migrate.py" "$TARGET/scripts/spine-migrate.py"
  chmod +x "$TARGET/scripts/spine-migrate.py"
  ok "  $TARGET/scripts/spine-migrate.py (v1→v2 SQLite + dashboard snapshot)"
fi
mkdir -p "$TARGET/lib/tests"
for tf in "$SOURCE/lib/tests/test-"*.sh; do
  [[ -f "$tf" ]] || continue
  cp "$tf" "$TARGET/lib/tests/$(basename "$tf")"
  chmod +x "$TARGET/lib/tests/$(basename "$tf")"
  ok "  $TARGET/lib/tests/$(basename "$tf")"
done
echo

step "Installing dashboard"
mkdir -p "$TARGET/.planning/orchestration/dashboard"
cp "$SOURCE/lib/dashboard.html" "$TARGET/.planning/orchestration/dashboard/index.html"
ok "  $TARGET/.planning/orchestration/dashboard/index.html (open in browser to view)"
echo

seed_playbooks

step "Installing notification hook"
NOTIFY_DST="$HOME/.spine-development/notify.sh"
# Wave 3 (Squad A): notify.sh migrated lib/ → shared/runtime/. lib/ copy
# removed; this caller now sources from the v3 canonical location.
NOTIFY_SRC="$SOURCE/shared/runtime/notify.sh"
[[ -f "$NOTIFY_SRC" ]] || NOTIFY_SRC="$SOURCE/lib/notify.sh"   # legacy fallback
if [[ -f "$NOTIFY_DST" && "$FORCE" == false ]]; then
  warn "  $NOTIFY_DST exists — keeping (pass --force to overwrite)"
else
  cp "$NOTIFY_SRC" "$NOTIFY_DST"
  chmod +x "$NOTIFY_DST"
  ok "  $NOTIFY_DST"
  dim "  Customize freely. Set SLACK_WEBHOOK / DISCORD_WEBHOOK / NOTIFY_EMAIL_TO env vars to enable channels."
fi
echo

step "Installing protocol + requirements documentation"
install_orchestration_docs
echo

step "Installing recipes"
install_recipes
echo

step "Orchestration templates + practice docs"
install_templates
install_program_templates
install_practice_docs
echo

step "Wiring Makefile targets"
MAKEFILE="$TARGET/Makefile"
MAKE_SNIPPET=$(cat <<'EOF'

# ── Agent team (added by SpineDevelopment installer) ────────────────
TESTS := $(wildcard lib/tests/test-*.sh)

.PHONY: team-up team-down team-status team-restart team-budget team-clean team-footprint team-doctor team-rollback team-preflight dashboard selftest db-migrate db-shell db-reset db-watch dashboard-sync

team-up: ## Start agent team (all roles in scripts/roles.sh + watchdog)
	bash scripts/team.sh up

team-down: ## Stop all agent-team daemons + watchdog
	bash scripts/team.sh down

team-status: ## Show what each team manager + worker is doing
	bash scripts/team.sh status

team-restart: ## team-down + team-up
	bash scripts/team.sh restart

team-budget: ## Cost / wall-time report from costs.csv
	bash scripts/team.sh budget

team-clean: ## Cleanup scratch + logs + archive (safe — preserves directives, memory, costs)
	bash scripts/team.sh clean all

team-footprint: ## Show on-disk size of each role's working dir
	bash scripts/team.sh clean footprint

team-doctor: ## Health check: daemons alive, heartbeats fresh, cursor-agent on PATH, etc
	bash scripts/team.sh doctor

team-rollback: ## Roll back engineer changes to a prior snapshot (interactive)
	bash scripts/team.sh rollback engineer

team-preflight: ## Verify host has the tools the team needs (run before first 'team-up')
	bash scripts/team.sh preflight

dashboard: ## Serve Control Center (python http.server on .planning/orchestration)
	bash scripts/serve-dashboard.sh

dashboard-sync: ## Copy lib/dashboard.html → .planning/orchestration/dashboard/index.html (no install needed)
	cp lib/dashboard.html .planning/orchestration/dashboard/index.html
	@printf '%s\n' "synced → .planning/orchestration/dashboard/index.html ($$(wc -l < lib/dashboard.html | tr -d ' ') lines)"

selftest: ## Run all lib/tests/test-*.sh (Spine sanity checks)
	@if [ -z "$(TESTS)" ]; then printf '%s\n' 'no matching lib/tests/test-*.sh' >&2; exit 1; fi
	@for t in $(TESTS); do printf '▸ %s\n' "$$t"; bash "$$t" || exit 1; done
	@printf '%s\n' '✓ all selftests passed'

# ── v2 SQLite (see ADR-001 + .planning/orchestration/docs/V2_BACKLOG.md) ──

SPINE_DB := .planning/orchestration/state/spine.db

db-migrate: ## Build / refresh the v2 SQLite DB and dashboard snapshot from the live v1 layout
	python3 scripts/spine-migrate.py --snapshot

db-reset: ## Drop the v2 DB and re-build from scratch (destructive); also refreshes snapshot
	python3 scripts/spine-migrate.py --reset --snapshot

db-shell: ## Open an interactive sqlite3 shell against the v2 DB
	@if [ ! -f "$(SPINE_DB)" ]; then printf '%s\n' "DB not built yet — run 'make db-migrate' first." >&2; exit 1; fi
	sqlite3 "$(SPINE_DB)"

db-watch: ## Keep the v2 DB + dashboard snapshot fresh (re-migrate every 30s; Ctrl-C to stop)
	python3 scripts/spine-migrate.py --watch 30
EOF
)

if [[ ! -f "$MAKEFILE" ]]; then
  cat > "$MAKEFILE" <<EOF
.DEFAULT_GOAL := help

help: ## Show available make targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*\$\$' \$(MAKEFILE_LIST) \\
	  | awk 'BEGIN {FS = ":.*?## "} {printf "  \033[36m%-12s\033[0m %s\n", \$\$1, \$\$2}'
$MAKE_SNIPPET
EOF
  ok "  Created $MAKEFILE with team targets"
elif grep -q "team-up:" "$MAKEFILE" 2>/dev/null; then
  warn "  $MAKEFILE already has team targets — skipping"
else
  printf '%s' "$MAKE_SNIPPET" >> "$MAKEFILE"
  ok "  Appended team targets to $MAKEFILE"
fi
echo

step "Adding agent-team note to CLAUDE.md (if present)"
CLAUDE_MD="$TARGET/CLAUDE.md"
if [[ -f "$CLAUDE_MD" ]] && ! grep -q "SpineDevelopment\|AGENT_TEAM_PROTOCOL" "$CLAUDE_MD" 2>/dev/null; then
  cat >> "$CLAUDE_MD" <<'EOF'

## Agent team (parallelizable work)

This repo has the SpineDevelopment agent-team installed. Manager count and IDs are defined in **`scripts/roles.sh`** (each role uses up to **10 worker** daemons — file-based bus under `.planning/orchestration/agent-handoff/teams/`).

To assign work: replace a role's `directive.md` with `# Directive — ...`. Daemons poll about every 8 seconds.

| Need | Role directory |
|---|---|
| Requirements / PRD narrative | `teams/product/directive.md` |
| Broad multi-phase orchestration | `teams/planner/directive.md` |
| Technical architecture | `teams/architect/directive.md` |
| Approved-build coordination | `teams/conductor/directive.md` |
| Read-only investigation | `teams/researcher/directive.md` |
| Full-stack edits (small teams) | `teams/engineer/directive.md` (discipline = fullstack/backend/frontend/ml/devops) |
| UX / design-system artefacts | `teams/ux/directive.md` |
| QA narratives + verification | `teams/qa/directive.md` |
| Docker / deploy / env | `teams/operator/directive.md` |
| Inference / ML batch | `teams/datawright/directive.md` |
| Portfolio observability digest | `teams/seer/directive.md` |
| Claim verification | `teams/auditor/directive.md` |
| Spine + playbook hygiene | `teams/memory/directive.md` |

Docs: `.planning/orchestration/AGENT_TEAM_PROTOCOL.md`, `docs/SPINE_PRACTICES.md`, `docs/PROGRAM_DELIVERY.md`  
Bring up / status / stop: `make team-up`, `make team-status`, `make team-down`.  
Control Center: `make dashboard` → http://127.0.0.1:61105/dashboard/ (not your app API’s `/dashboard` route; default port avoids many Docker `*:60005` publishes — use `SPINE_DASH_PORT` if needed).
EOF
  ok "  Appended team section to $CLAUDE_MD"
else
  if [[ -f "$CLAUDE_MD" ]]; then
    warn "  $CLAUDE_MD already mentions team — skipping"
  else
    warn "  No CLAUDE.md found — skipping (consider creating one)"
  fi
fi
echo

# Pass N: --hub mode marks this checkout as a JOINING machine. Persist
# the hub URL so a later `bash scripts/spine-connect.sh` (no arg) can
# pick it up. When --hub is not passed, the file is not written and
# install behaves exactly as before — the multi-machine layer is opt-in.
if [[ -n "$HUB_URL" ]]; then
  HUB_URL_DST="$TARGET/.planning/orchestration/.hub-url"
  mkdir -p "$(dirname "$HUB_URL_DST")"
  printf '%s\n' "$HUB_URL" > "$HUB_URL_DST"
  ok "  Wrote hub URL to $HUB_URL_DST"
fi

ok "Install complete."
if [[ -n "$HUB_URL" ]]; then
  cat <<EOF

This install is configured as a JOINING machine.

Next step:

  cd $TARGET
  bash scripts/spine-connect.sh    # connect to the hub and start daemons

When you want to stop:

  bash scripts/spine-disconnect.sh
EOF
else
  cat <<EOF

Next steps:

  cd $TARGET
  make team-up          # start managers (see scripts/roles.sh) + workers + watchdog
  make team-status      # confirm everything's running

Drop your first directive at one of:
$(for r in "${ROLES[@]}"; do echo "  .planning/orchestration/agent-handoff/teams/$r/directive.md"; done)

Read:
  .planning/orchestration/AGENT_TEAM_PROTOCOL.md
  .planning/orchestration/docs/SPINE_PRACTICES.md

Recipes (installed): .planning/orchestration/recipes/
Upstream template recipes: $SOURCE/recipes/

Refresh knowledge later without touching daemons:

  bash $SOURCE/install.sh $TARGET --pull-knowledge-only
EOF
fi
