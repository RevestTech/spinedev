.PHONY: prod-static prod-images prod-up e2e dev-cert verify-observability

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

# Generate a self-signed TLS cert for local development. Nginx won't start
# without config/nginx/ssl/{cert,key}.pem — this creates them. Safe to re-run;
# refuses to overwrite an existing cert unless TRON_DEV_CERT_FORCE=1 is set.
# Production uses a real cert (see docs/security/TLS_RUNBOOK.md); do not ship.
dev-cert:
	./config/nginx/ssl/generate-dev-cert.sh

# End-to-end verification that the observability stack actually flows.
# Probes Prometheus targets, Grafana dashboards, Alertmanager → Slack
# round-trip via the tron-api receiver. Run after a deploy or whenever
# you suspect the dashboards have been empty for reasons nobody investigated.
verify-observability:
	./.venv312/bin/python scripts/verify_observability.py
