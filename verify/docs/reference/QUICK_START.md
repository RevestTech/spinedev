# Tron Quick Start Guide

Get Tron running locally in under 10 minutes.

## Prerequisites

- **Docker & Docker Compose** (v20+)
- **Python 3.11+** (for direct development)
- **Git** (to clone the repository)
- **curl** (for testing endpoints)

## Installation

### 1. Clone the Repository

```bash
git clone https://github.com/yourusername/tron.git
cd tron
```

### 2. Configure Environment

Copy the example environment file and update with your settings:

```bash
cp .env.example .env
```

Edit `.env` with:
- Database password: `POSTGRES_PASSWORD=your-secure-password`
- Redis password: `REDIS_PASSWORD=your-redis-password`
- MinIO credentials: `MINIO_USER=minioadmin`, `MINIO_PASSWORD=minioadmin`
- Grafana password: `GRAFANA_PASSWORD=admin`

### 3. Start the Stack

Start all services (PostgreSQL, Redis, MinIO, Temporal, API, monitoring):

```bash
docker compose up -d
```

This starts:
- PostgreSQL (port 13002)
- Redis (port 13003)
- MinIO (API: 13004, Console: 13005)
- PgBouncer (port 13006)
- Temporal (port 13007)
- Temporal UI (port 13008)
- Prometheus (port 13009)
- Grafana (port 13010)
- Alertmanager (port 13011)
- Loki (port 13012)
- Tempo (port 13013)
- Tron API (port 13000)
- Nginx (port 80, 443)

### 4. Initialize Secrets (First Time Only)

Set up KMac Vault secrets for API keys, database passwords, etc.:

```bash
# Create vault token file
mkdir -p ~/.config/kmac
echo "your-vault-token" > ~/.config/kmac/docker-vault-token

# Initialize via KMac Vault (or provide secrets manually)
```

### 5. Verify the System is Running

#### Check API Health

```bash
curl http://localhost:13000/health
```

Expected response:
```json
{
  "status": "ok",
  "service": "tron-api",
  "uptime_seconds": 45.2
}
```

#### Check Readiness (DB + Redis Connected)

```bash
curl http://localhost:13000/ready
```

Expected response (HTTP 200):
```json
{
  "status": "ready",
  "checks": {
    "database": "ok",
    "redis": "ok"
  }
}
```

#### View Docker Logs

```bash
docker compose logs -f tron-api
```

#### Access API Documentation

Open your browser to:
```
http://localhost:13000/api/docs
```

## Create Your First Project

### 1. Generate an API Key

API keys are configured in KMac Vault. For development, use the master key from:

```bash
curl -X GET http://localhost:13000/api/auth/keys \
  -H "X-API-Key: your-master-api-key"
```

### 2. Create a Project

```bash
curl -X POST http://localhost:13000/api/projects \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-api-key" \
  -d '{
    "name": "My First Project",
    "description": "Test project for Tron",
    "repo_url": "https://github.com/username/repo",
    "default_branch": "main"
  }'
```

Expected response (HTTP 201):
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "My First Project",
  "description": "Test project for Tron",
  "repo_url": "https://github.com/username/repo",
  "default_branch": "main",
  "created_at": "2025-01-15T10:30:00Z",
  "status": "active"
}
```

### 3. List Projects

```bash
curl http://localhost:13000/api/projects \
  -H "X-API-Key: your-api-key"
```

## Run Your First Audit

### 1. Start an Audit Run

```bash
curl -X POST http://localhost:13000/api/audits \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-api-key" \
  -d '{
    "project_id": "550e8400-e29b-41d4-a716-446655440000",
    "branch": "main",
    "trigger_type": "manual"
  }'
```

Expected response (HTTP 202 - Accepted):
```json
{
  "id": "660e8400-e29b-41d4-a716-446655440001",
  "project_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "running",
  "progress": 0,
  "started_at": "2025-01-15T10:35:00Z"
}
```

### 2. Check Audit Status

```bash
curl http://localhost:13000/api/audits/660e8400-e29b-41d4-a716-446655440001 \
  -H "X-API-Key: your-api-key"
```

Expected response (when complete):
```json
{
  "id": "660e8400-e29b-41d4-a716-446655440001",
  "project_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "completed",
  "progress": 100,
  "findings_total": 5,
  "findings_critical": 1,
  "findings_high": 2,
  "findings_medium": 2,
  "findings_low": 0,
  "completed_at": "2025-01-15T10:38:00Z"
}
```

### 3. Get Findings

```bash
curl "http://localhost:13000/api/audits/660e8400-e29b-41d4-a716-446655440001/findings?limit=10" \
  -H "X-API-Key: your-api-key"
```

Expected response:
```json
{
  "findings": [
    {
      "id": "770e8400-e29b-41d4-a716-446655440002",
      "audit_id": "660e8400-e29b-41d4-a716-446655440001",
      "title": "SQL Injection in user query",
      "severity": "critical",
      "file_path": "app/db.py",
      "line_number": 42,
      "description": "Unsanitized user input in SQL query",
      "recommendation": "Use parameterized queries",
      "confidence": 0.95
    }
  ],
  "total": 5,
  "page": 1,
  "per_page": 10
}
```

## Access the Grafana Dashboard

Tron includes observability dashboards for monitoring metrics, logs, and traces.

1. Open http://localhost:13010 (port 13010)
2. Default credentials: `admin` / your configured `GRAFANA_PASSWORD`
3. Explore pre-configured dashboards:
   - **Tron API** — Request latency, throughput, error rates
   - **Database** — Query performance, connection pool utilization
   - **Temporal** — Workflow execution, task processing
   - **Infrastructure** — CPU, memory, disk usage

## Common Troubleshooting

### Port Conflicts

If services fail to start due to port conflicts:

```bash
# Find which process is using port 13000
lsof -i :13000

# Kill the process or change port in docker-compose.yml
```

### Container Won't Start

Check container logs:

```bash
docker compose logs tron-api
docker compose logs postgres
docker compose logs redis
```

### Database Connection Error

Verify PostgreSQL is healthy:

```bash
docker compose exec postgres pg_isready -U tron
```

If the database is corrupted, reset it:

```bash
docker compose down -v  # WARNING: Deletes all data
docker compose up -d postgres
```

### Redis Connection Refused

Restart Redis:

```bash
docker compose restart redis
```

### Temporal Workflows Not Starting

Verify Temporal server is healthy:

```bash
docker compose exec temporal tctl --address localhost:7233 cluster health
```

### LLM Circuit Breaker Tripped

This means too many LLM API calls failed. Check logs:

```bash
docker compose logs tron-api | grep "circuit_breaker"
```

Reset via API (requires admin access):

```bash
curl -X POST http://localhost:13000/api/admin/reset-circuit-breaker \
  -H "X-API-Key: your-admin-key"
```

### WebSocket Connection Dropped

Check nginx logs:

```bash
docker compose logs nginx | grep websocket
```

Verify WebSocket auth headers:

```bash
curl -i -N -H "Connection: Upgrade" \
  -H "Upgrade: websocket" \
  -H "Sec-WebSocket-Version: 13" \
  -H "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==" \
  -H "X-API-Key: your-api-key" \
  http://localhost:13000/ws
```

### Metrics Not Showing in Grafana

1. Check if Prometheus is scraping metrics:
   - Open http://localhost:13009 (Prometheus)
   - Go to Status → Targets
   - Verify `tron-api` shows "UP"

2. Check OpenTelemetry collector:
   ```bash
   docker compose logs otel-collector
   ```

## Next Steps

1. **Configure CI/CD** — Run Tron audits on every PR
2. **Set up Slack notifications** — Get findings delivered to your team
3. **Integrate with your IDE** — Install the Tron VSCode extension
4. **Customize audit rules** — Modify deterministic tool configs
5. **Scale horizontally** — Run multiple API and worker instances

## Support

- **Documentation** — See `/docs` directory
- **API Reference** — http://localhost:13000/api/docs
- **Community** — Open an issue on GitHub
- **Commercial Support** — contact@tronsecurity.io
