.PHONY: prod-static prod-images prod-up e2e

# In-process audit pipeline E2E (mocked LLM) + live HTTP smoke (health/ready; API if TRON_E2E_API_KEY set).
e2e:
	./.venv312/bin/python -m pytest tests/integration/test_e2e_audit.py -q --tb=short
	./.venv312/bin/python scripts/e2e_live_smoke.py

# Build primary UI for nginx (`docker-compose.yml` mounts `./frontend/dist`).
prod-static:
	cd frontend && npm ci && npm run build

# Rebuild API image after code changes.
prod-images:
	docker compose build tron-api

prod-up: prod-static
	docker compose up -d nginx tron-api
