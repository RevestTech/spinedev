# Tron Port Reference

All Tron services run on ports in the **13000 range** to avoid conflicts with other services.

## 🚀 Core Services

| Service | Internal Port | Host Port | URL | Description |
|---------|--------------|-----------|-----|-------------|
| **tron-api** | 8000 | **13000** | http://localhost:13000 | Main API Gateway |
| **vault** | 8200 | **13001** | http://localhost:13001 | HashiCorp Vault (secrets) |
| **postgres** | 5432 | **13002** | localhost:13002 | PostgreSQL Database |
| **redis** | 6379 | **13003** | localhost:13003 | Redis Cache & Queue |
| **minio-api** | 9000 | **13004** | https://localhost:13004 | MinIO S3 API |
| **minio-console** | 9001 | **13005** | https://localhost:13005 | MinIO Admin Console |

## 🔧 Infrastructure Services

| Service | Internal Port | Host Port | Description |
|---------|--------------|-----------|-------------|
| **pgbouncer** | 5432 | **13006** | Connection Pooler |
| **temporal** | 7233 | **13007** | Temporal Server (gRPC) |
| **temporal-ui** | 8080 | **13008** | Temporal Web UI |

## 📊 Observability Services

| Service | Internal Port | Host Port | URL | Description |
|---------|--------------|-----------|-----|-------------|
| **prometheus** | 9090 | **13009** | http://localhost:13009 | Metrics Database |
| **grafana** | 3000 | **13010** | http://localhost:13010 | Dashboards |
| **alertmanager** | 9093 | **13011** | http://localhost:13011 | Alert Management |
| **loki** | 3100 | **13012** | http://localhost:13012 | Log Aggregation |
| **tempo** | 3200 | **13013** | http://localhost:13013 | Distributed Tracing |
| **otel-collector** (gRPC) | 4317 | **13014** | localhost:13014 | OpenTelemetry gRPC |
| **otel-collector** (HTTP) | 4318 | **13015** | http://localhost:13015 | OpenTelemetry HTTP |

## 🌐 Reverse Proxy

| Service | Internal Port | Host Port | Description |
|---------|--------------|-----------|-------------|
| **nginx** | 80 | **13080** | Reverse Proxy & Load Balancer |

## 🔄 Auto-Start Configuration

All services are configured with `restart: unless-stopped`, meaning they will:
- ✅ Automatically start when Docker starts
- ✅ Restart if they crash
- ✅ Stay stopped if manually stopped with `docker stop`

## 📝 Quick Test Commands

```bash
# Test API Health
curl http://localhost:13000/health

# Test API Docs
open http://localhost:13000/api/docs

# Test Vault
curl http://localhost:13001/v1/sys/health

# Test MinIO Console
open https://localhost:13005

# Test Grafana
open http://localhost:13010

# Test Temporal UI
open http://localhost:13008
```

## 🔍 Service Status

```bash
# Check all running services
docker compose ps

# Check specific service logs
docker logs tron-api --tail 50

# View all ports
docker compose ps --format "table {{.Name}}\t{{.Ports}}"

# Verify restart policies
docker inspect tron-api --format '{{.HostConfig.RestartPolicy.Name}}'
```

## 🛑 Stop/Start Services

```bash
# Stop all services
docker compose down

# Start all services
docker compose up -d

# Restart specific service
docker compose restart tron-api

# Scale workers (multiple instances)
docker compose up --scale tron-worker=3 -d
```

## 📚 Notes

- All services bind to `127.0.0.1` (localhost only) for security
- Internal Docker network uses original ports (e.g., Postgres uses 5432 internally)
- External access uses 13000+ ports
- No port conflicts with other Docker containers or local services
