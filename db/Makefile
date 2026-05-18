# Spine recording DB — developer convenience targets.
#
# All targets are thin wrappers over `docker compose`. Run `make help` for
# the list, or read README.md for the full workflow.

.PHONY: help up migrate down nuke psql info validate views \
        watch watch-down watch-logs watch-rebuild \
        snapshot watch-snapshot dashboard dashboard-stop verify \
        share-pg

# Port the live dashboard server binds to on localhost. Default is 33002 so
# it doesn't collide with the Postgres host port (33001) when running the
# default docker-compose config. Override with `DASHBOARD_PORT=NNNN make
# dashboard` if it's taken.
DASHBOARD_PORT ?= 33002

help:
	@echo "Spine DB targets:"
	@echo "  make up             - start Postgres in the background"
	@echo "  make migrate        - run Flyway migrations (one-shot)"
	@echo "  make down           - stop containers (volume persists)"
	@echo "  make nuke           - stop AND delete the data volume (asks first)"
	@echo "  make psql           - open psql in the running postgres container"
	@echo "  make info           - flyway info (migration status)"
	@echo "  make validate       - flyway validate"
	@echo "  make views          - describe the V4 reporting views (visibility check)"
	@echo "  make watch          - start the outbox -> Postgres watcher"
	@echo "  make watch-down     - stop the watcher (postgres keeps running)"
	@echo "  make watch-logs     - follow watcher logs"
	@echo "  make watch-rebuild  - rebuild the watcher image and restart it"
	@echo "  make snapshot       - write dashboard/pg-snapshot.json from live Postgres"
	@echo "  make watch-snapshot - rebuild the snapshot every 30s (loop)"
	@echo "  make dashboard      - start the live dashboard server on http://127.0.0.1:$(DASHBOARD_PORT)/"
	@echo "  make dashboard-stop - stop the live dashboard server (by port)"
	@echo "  make verify         - run every syntax/selftest check (bash -n, py_compile, pglast, selftests)"
	@echo "  make share-pg       - print copy-paste env block to onboard another machine (multi-machine hub)"

up:
	docker compose up -d postgres

migrate:
	docker compose run --rm flyway migrate

down:
	docker compose down

nuke:
	@printf "This will DELETE the spine_pgdata volume. Type 'yes' to continue: "; \
	read confirm; \
	if [ "$$confirm" = "yes" ]; then \
		docker compose down -v; \
	else \
		echo "Aborted."; \
	fi

psql:
	docker compose exec postgres psql -U spine -d spine

info:
	docker compose run --rm flyway info

validate:
	docker compose run --rm flyway validate

views:
	docker compose exec postgres psql -U $${POSTGRES_USER:-spine} -d $${POSTGRES_DB:-spine} -c "\d+ v_cost_by_role_day v_cost_by_model v_active_workers v_recent_events v_cost_by_outcome"

watch:
	docker compose up -d watcher

watch-down:
	docker compose stop watcher

watch-logs:
	docker compose logs -f watcher

watch-rebuild:
	docker compose build watcher && docker compose up -d watcher

# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
# `snapshot` writes a JSON file the static dashboard reads. The Python script
# emits a clear hint if psycopg is missing and exits non-zero on connect
# failure, so this target just runs it and lets the script handle errors.
snapshot:
	python3 dashboard/build-snapshot.py

# Keep refreshing the snapshot in the background so the dashboard stays
# fresh while you click Refresh. Stop with Ctrl-C. The redirect hides the
# per-tick output; remove `>/dev/null 2>&1` if you want to see each run.
watch-snapshot:
	@echo "refreshing dashboard/pg-snapshot.json every 30s (Ctrl-C to stop)"
	@while true; do python3 dashboard/build-snapshot.py >/dev/null 2>&1; sleep 30; done

# Live dashboard server: serves dashboard/ AND exposes /pg-snapshot.json
# backed by an on-demand call into build_snapshot(). Bound to 127.0.0.1 so
# it never leaks onto the LAN. The page auto-refreshes every 5s by default.
dashboard:
	@echo "open http://127.0.0.1:$(DASHBOARD_PORT)/"
	@DASHBOARD_PORT=$(DASHBOARD_PORT) python3 dashboard/serve.py

# Stop the running dashboard server by killing whatever process is listening
# on $(DASHBOARD_PORT). Safe to run when nothing is listening (no-op).
dashboard-stop:
	@pids="$$(lsof -t -iTCP:$(DASHBOARD_PORT) -sTCP:LISTEN 2>/dev/null)"; \
	if [ -n "$$pids" ]; then \
		echo "stopping dashboard server on :$(DASHBOARD_PORT) (pid $$pids)"; \
		echo "$$pids" | xargs kill; \
	else \
		echo "no dashboard server listening on :$(DASHBOARD_PORT)"; \
	fi

# Wave 6 Stream K: lib/verify.sh + lib/share-pg.sh retired.
# - `verify` target removed (use top-level `make lint` for syntax checks).
# - `share-pg` falls through to scripts/share-pg.sh only (the installed copy).
share-pg:
	@bash ../scripts/share-pg.sh
