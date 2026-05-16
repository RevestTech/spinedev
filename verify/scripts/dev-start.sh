#!/bin/bash
# dev-start.sh — One-command development environment setup
#
# Usage: ./scripts/dev-start.sh
#
# This script:
# 1. Starts Vault and provisions secrets
# 2. Starts all infrastructure services (postgres, redis, minio, temporal)
# 3. Runs database migrations
# 4. Starts the API and worker services
# 5. Starts monitoring stack (prometheus, grafana, loki, tempo)

set -e

COMPOSE_FILES="-f docker-compose.yml -f docker-compose.dev.yml"

echo "╔══════════════════════════════════════════╗"
echo "║      Tron Development Environment        ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# Step 1: Start Vault
echo "→ Starting Vault..."
docker-compose $COMPOSE_FILES up -d vault
echo "  Waiting for Vault to be healthy..."
sleep 5

# Step 2: Run vault-init to provision secrets
echo "→ Provisioning secrets in Vault..."
docker-compose $COMPOSE_FILES up vault-init
echo ""

# Step 3: Start infrastructure
echo "→ Starting infrastructure (postgres, redis, minio, temporal)..."
docker-compose $COMPOSE_FILES up -d postgres redis minio
echo "  Waiting for infrastructure to be healthy..."
sleep 10

# Step 4: Start PgBouncer and Temporal (depend on postgres)
echo "→ Starting PgBouncer and Temporal..."
docker-compose $COMPOSE_FILES up -d pgbouncer temporal
sleep 10

# Step 5: Run migrations
echo "→ Running database migrations..."
docker-compose $COMPOSE_FILES run --rm tron-api \
    python -m alembic upgrade head
echo ""

# Step 6: Start application services
echo "→ Starting Tron API and Worker..."
docker-compose $COMPOSE_FILES up -d tron-api tron-worker
echo ""

# Step 7: Start monitoring
echo "→ Starting monitoring stack..."
docker-compose $COMPOSE_FILES up -d prometheus grafana loki tempo otel-collector alertmanager
echo ""

# Step 8: Start nginx
echo "→ Starting Nginx reverse proxy..."
docker-compose $COMPOSE_FILES up -d nginx
echo ""

echo "╔══════════════════════════════════════════╗"
echo "║           Tron is running!               ║"
echo "╠══════════════════════════════════════════╣"
echo "║  API:       http://localhost:8000        ║"
echo "║  API Docs:  http://localhost:8000/api/docs║"
echo "║  Grafana:   http://localhost:3001        ║"
echo "║  Temporal:  http://localhost:8081        ║"
echo "║  Vault:     http://localhost:8200        ║"
echo "║  MinIO:     http://localhost:9001        ║"
echo "╚══════════════════════════════════════════╝"
echo ""
echo "To view logs: docker-compose $COMPOSE_FILES logs -f tron-api"
echo "To stop:      docker-compose $COMPOSE_FILES down"
