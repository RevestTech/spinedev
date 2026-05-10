.DEFAULT_GOAL := help

help: ## Show available make targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "} {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

# ── Agent team (added by SpineDevelopment installer) ────────────────
.PHONY: team-up team-down team-status team-restart team-budget team-clean team-footprint team-doctor team-rollback team-preflight dashboard

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
