.DEFAULT_GOAL := help

help: ## Show available make targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "} {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

# ── Agent team (added by SpineDevelopment installer) ────────────────
TESTS := $(wildcard lib/tests/test-*.sh)

.PHONY: team-up team-down team-status team-restart team-budget team-clean team-footprint team-doctor team-rollback team-preflight dashboard selftest db-migrate db-shell db-reset db-watch dashboard-sync verify lint lint-shell lint-py lint-html lint-sql lint-md lint-fix

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

verify: ## Run every syntax + selftest check (bash -n, py_compile, pglast, selftests)
	@bash lib/verify.sh

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

# ── Lint targets ────────────────────────────────────────────────────
# Required tools (install on macOS via `brew install shellcheck tidy-html5 ruff sqlfluff`;
# markdownlint runs via `npx -y markdownlint-cli`).
# Config files: .markdownlint.json, .tidyconfig, db/flyway/sql/.sqlfluff.

PY_LINT_FILES := lib/spine-migrate.py scripts/spine-migrate.py db/watcher/spine_watcher.py db/dashboard/build-snapshot.py db/dashboard/serve.py db/dashboard/tests/test_approval.py
HTML_LINT_FILES := lib/dashboard.html db/dashboard/index.html db/dashboard/about.html db/dashboard/versions.html db/dashboard/tech.html db/dashboard/engagement.html db/dashboard/machines.html
MD_LINT_FILES := CHANGELOG.md INSTALL.md PROTOCOL.md README.md REQUIREMENTS.md docs/EXTENSIONS.md docs/IMPROVEMENT_CHECKLIST.md docs/PROGRAM_DELIVERY.md docs/SPINE_PRACTICES.md

lint: lint-shell lint-py lint-html lint-sql lint-md ## Run all linters (shell, python, html, sql, markdown)
	@printf '%s\n' '✓ all linters passed'

lint-shell: ## shellcheck on lib/*.sh
	@command -v shellcheck >/dev/null || { printf '%s\n' "shellcheck not installed (brew install shellcheck)" >&2; exit 1; }
	shellcheck -x -s bash lib/*.sh

lint-py: ## ruff (default ruleset) on the project's Python files
	@command -v ruff >/dev/null || { printf '%s\n' "ruff not installed (brew install ruff)" >&2; exit 1; }
	ruff check --no-fix $(PY_LINT_FILES)

lint-html: ## tidy-html5 on dashboard HTML (uses .tidyconfig)
	@command -v tidy >/dev/null || { printf '%s\n' "tidy not installed (brew install tidy-html5)" >&2; exit 1; }
	@fail=0; for f in $(HTML_LINT_FILES); do \
	  out=$$(tidy -config .tidyconfig -e -q "$$f" 2>&1 | grep -vE '^Info:|^$$' || true); \
	  if [ -n "$$out" ]; then printf '=== %s ===\n%s\n' "$$f" "$$out"; fail=1; fi; \
	done; exit $$fail

lint-sql: ## sqlfluff on db/flyway/sql/ (uses db/flyway/sql/.sqlfluff)
	@command -v sqlfluff >/dev/null || { printf '%s\n' "sqlfluff not installed (brew install sqlfluff)" >&2; exit 1; }
	sqlfluff lint --dialect postgres db/flyway/sql/

lint-md: ## markdownlint on root + docs markdown (uses .markdownlint.json)
	@command -v npx >/dev/null || { printf '%s\n' "npx not installed (install Node.js)" >&2; exit 1; }
	npx -y markdownlint-cli $(MD_LINT_FILES)

lint-fix: ## Auto-fix what each linter can (sqlfluff fix, markdownlint --fix, ruff --fix)
	@command -v sqlfluff >/dev/null && sqlfluff fix --dialect postgres db/flyway/sql/ || true
	@command -v ruff >/dev/null && ruff check --fix $(PY_LINT_FILES) || true
	@command -v npx >/dev/null && npx -y markdownlint-cli --fix $(MD_LINT_FILES) || true
	@printf '%s\n' '✓ auto-fix pass complete (review diff before committing)'
