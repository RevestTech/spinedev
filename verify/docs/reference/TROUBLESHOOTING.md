# Tron Troubleshooting Guide

Solutions for common issues when running Tron.

## Container Won't Start

### Check Container Logs

```bash
# View logs for a specific service
docker compose logs tron-api

# View last 100 lines with timestamps
docker compose logs --tail 100 -t tron-api

# Follow logs in real-time
docker compose logs -f tron-api
```

### Port Conflict Error

If you see "bind: address already in use":

```bash
# Find which process is using the port (e.g., 13000)
lsof -i :13000

# Kill the process
kill -9 <PID>

# Or change the port in docker-compose.yml
# ports:
#   - "127.0.0.1:13001:8000"  # Changed from 13000
```

### Resource Limits Exceeded

If containers are killed with no error:

```bash
# Check Docker resource allocation
docker stats

# Increase Docker Desktop memory:
# 1. Docker > Preferences > Resources
# 2. Set Memory to at least 8GB
# 3. Set Swap to 4GB
```

### Container Crashes Immediately

Check the health status:

```bash
docker ps -a | grep tron

# If status shows "Exited", check logs
docker compose logs postgres
docker compose logs redis
```

## Database Connection Errors

### PostgreSQL Won't Start

```bash
# Check if postgres data volume is corrupt
docker volume ls | grep postgres

# If corrupt, remove and recreate
docker volume rm tron_postgres-data

# Restart
docker compose up -d postgres
docker compose logs -f postgres
```

### "Connection refused" or "No such file or directory"

The API can't connect to the database. Verify:

```bash
# 1. Check if postgres is healthy
docker compose exec postgres pg_isready -U tron

# 2. Verify environment variables in tron-api
docker compose exec tron-api env | grep DB_

# 3. Check the connection string
# Should be: postgres://tron:password@postgres:5432/tron
```

### PgBouncer Connection Pool Exhausted

Error: `Sorry, too many clients already`

```bash
# Check PgBouncer status
docker compose exec pgbouncer psql -U tron -d pgbouncer -c "SHOW CLIENTS;"

# View pool configuration
docker compose exec pgbouncer psql -U tron -d pgbouncer -c "SHOW POOLS;"

# Increase max_client_conn in docker-compose.yml
# environment:
#   MAX_CLIENT_CONN: 1000  # Increased from 500
```

### Database Migration Failed

If migrations fail on startup:

```bash
# Check migration status
docker compose exec tron-api alembic current

# View available migrations
docker compose exec tron-api alembic history

# Rollback to previous version
docker compose exec tron-api alembic downgrade -1

# Re-run migrations
docker compose exec tron-api alembic upgrade head
```

### CRITICAL: Database Corruption

If the database is corrupted beyond repair:

```bash
# WARNING: This deletes all data
docker compose down -v

# Remove postgres volume
docker volume rm tron_postgres-data

# Start fresh
docker compose up -d postgres

# Re-run migrations
docker compose exec tron-api alembic upgrade head
```

## Redis Connection Issues

### Redis Won't Connect

```bash
# Check if Redis is running
docker compose ps redis

# Test Redis connectivity
docker compose exec redis redis-cli ping

# If password is required
docker compose exec redis redis-cli -a your-redis-password ping
```

### Redis Memory Full

Error: `OOM command not allowed when used memory > 'maxmemory'.`

```bash
# Check Redis memory usage
docker compose exec redis redis-cli INFO memory

# Clear expired keys
docker compose exec redis redis-cli EVICT KEYS

# Increase max memory in docker-compose.yml
# command: redis-server --maxmemory 2gb
```

### Redis Persists Old Data

If you want a fresh Redis:

```bash
docker compose down
docker volume rm tron_redis-data
docker compose up -d redis
```

## Temporal Workflow Failures

### Temporal Server Won't Start

```bash
# Check Temporal logs
docker compose logs temporal

# Verify Temporal is healthy
docker compose exec temporal tctl --address localhost:7233 cluster health
```

### Workflow Execution Timeout

Workflows taking too long can be interrupted:

```bash
# Check active workflows
docker compose exec temporal tctl workflow list

# Describe a workflow
docker compose exec temporal tctl workflow describe --workflow-id YOUR_WORKFLOW_ID

# Terminate a stuck workflow
docker compose exec temporal tctl workflow terminate --workflow-id YOUR_WORKFLOW_ID
```

### Task Queue Not Found

Error: `Task queue 'tron-tasks' not found`

This means the worker hasn't registered the queue yet:

```bash
# Check if tron-worker is running
docker compose ps tron-worker

# Restart the worker
docker compose restart tron-worker

# Wait 5-10 seconds for queue registration
sleep 10

# Try workflow again
```

### Activity Execution Failed

```bash
# Check worker logs
docker compose logs tron-worker

# Verify worker can connect to Temporal
docker compose exec tron-worker python -c \
  "import temporalio.client; print('Temporal OK')"
```

## LLM Circuit Breaker Tripped

Error: `Circuit breaker is open - refusing requests`

This happens when too many LLM API calls fail:

```bash
# Check circuit breaker status in logs
docker compose logs tron-api | grep "circuit_breaker"

# Verify API keys are configured
docker compose exec tron-api env | grep LLM_

# Check OpenAI/Anthropic API status
# OpenAI: https://status.openai.com
# Anthropic: Check your account dashboard

# Reset circuit breaker (admin API)
curl -X POST http://localhost:13000/api/admin/reset-circuit-breaker \
  -H "X-API-Key: your-admin-key"
```

### Circuit Breaker Config

Adjust thresholds in docker-compose.yml:

```yaml
environment:
  LLM_CIRCUIT_BREAKER_THRESHOLD: 5        # Failures before opening
  LLM_CIRCUIT_BREAKER_TIMEOUT: 60         # Seconds before retry
  LLM_REQUEST_TIMEOUT: 30                 # Per-request timeout
  LLM_BULKHEAD_MAX_CONCURRENT: 10         # Max concurrent calls
```

## Rate Limit Errors (429 Responses)

### Too Many Requests

Error: `HTTP 429 - Too Many Requests`

```bash
# Check rate limit headers
curl -i http://localhost:13000/api/projects \
  -H "X-API-Key: your-api-key" | grep -i "rate-limit"

# Wait before retrying
sleep 60

# Increase rate limit (if admin)
curl -X POST http://localhost:13000/api/admin/rate-limits \
  -H "X-API-Key: your-admin-key" \
  -d '{"requests_per_minute": 100}'
```

### Per-API-Key Rate Limits

Each API key has its own bucket:

```bash
# Check current limits
curl http://localhost:13000/api/auth/rate-limits \
  -H "X-API-Key: your-api-key"

# Generate new API key with higher limits
curl -X POST http://localhost:13000/api/auth/keys \
  -H "X-API-Key: your-master-key" \
  -d '{"requests_per_minute": 500, "daily_limit": 50000}'
```

## WebSocket Connection Issues

### Connection Refused

```bash
# Verify WebSocket is listening
curl -i -N \
  -H "Connection: Upgrade" \
  -H "Upgrade: websocket" \
  -H "Sec-WebSocket-Version: 13" \
  -H "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==" \
  http://localhost:13000/ws

# Check nginx configuration
docker compose exec nginx nginx -t

# View nginx logs
docker compose logs nginx
```

### Authentication Failed

Error: `WebSocket connection unauthorized`

```bash
# Verify API key is valid
curl http://localhost:13000/health

# Include API key in WebSocket handshake
curl -i -N \
  -H "Connection: Upgrade" \
  -H "Upgrade: websocket" \
  -H "Sec-WebSocket-Version: 13" \
  -H "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==" \
  -H "X-API-Key: your-api-key" \
  http://localhost:13000/ws
```

### Connection Drops After Inactivity

WebSocket connections are closed after idle timeout:

```bash
# Check idle timeout setting
docker compose exec tron-api env | grep WS_

# Adjust in docker-compose.yml
# environment:
#   WS_IDLE_TIMEOUT: 3600  # 1 hour
```

## Observability Stack Issues

### Prometheus Not Scraping Metrics

```bash
# Check Prometheus targets
curl http://localhost:13009/api/v1/targets | jq '.data.activeTargets'

# Verify tron-api endpoint is alive
curl http://tron-api:8000/metrics

# Check Prometheus config
docker compose exec prometheus cat /etc/prometheus/prometheus.yml

# Restart Prometheus
docker compose restart prometheus
```

### Grafana Shows No Data

```bash
# Verify Prometheus is the data source
curl http://localhost:13009/api/v1/query?query=up

# Check if metrics are being collected
curl http://localhost:13009/api/v1/query?query=up{job="tron-api"}

# Restart Grafana
docker compose restart grafana

# Re-login (admin password may have changed)
```

### Tempo Traces Not Showing

```bash
# Check if otel-collector is running
docker compose ps otel-collector

# Verify span export configuration
docker compose logs otel-collector | grep "exporting"

# Check Tempo storage
docker volume ls | grep tempo

# Restart the observability stack
docker compose restart otel-collector tempo grafana
```

### Loki Logs Not Aggregating

```bash
# Verify Loki is healthy
curl http://localhost:13012/ready

# Check log ingestion
curl http://localhost:13012/loki/api/v1/label

# View Loki config
docker compose exec loki cat /etc/loki/loki.yml

# Restart Loki
docker compose restart loki
```

## Reset the Development Environment

### Soft Reset (Keep Database)

```bash
# Stop all containers but keep volumes
docker compose down

# Start fresh
docker compose up -d

# Re-run migrations
docker compose exec tron-api alembic upgrade head
```

### Hard Reset (Delete Everything)

WARNING: This deletes all data, including databases and cache.

```bash
# Stop containers and remove volumes
docker compose down -v

# Remove any dangling volumes
docker volume prune -f

# Start from scratch
docker compose up -d

# Wait for services to initialize
sleep 30

# Re-run migrations
docker compose exec tron-api alembic upgrade head
```

### Clean Up Docker Resources

```bash
# Remove stopped containers
docker container prune -f

# Remove unused images
docker image prune -f

# Remove unused networks
docker network prune -f

# Show total disk usage
docker system df
```

## Performance Debugging

### High CPU Usage

```bash
# Check which service is consuming CPU
docker stats

# For tron-api specifically
docker stats tron-api --no-stream

# Enable profiling (if available)
export PROFILE=1
docker compose restart tron-api
```

### High Memory Usage

```bash
# Check memory usage
docker stats

# Identify memory leaks
docker compose logs tron-api | grep -i "memory\|leak"

# Reduce pool sizes in docker-compose.yml
# DB_POOL_SIZE: 5  # Reduced from 10
```

### Slow Queries

```bash
# Enable PostgreSQL slow query log
docker compose exec postgres \
  psql -U tron -d tron -c \
  "ALTER SYSTEM SET log_min_duration_statement = 1000;"

# Reload configuration
docker compose exec postgres \
  psql -U tron -d tron -c "SELECT pg_reload_conf();"

# View slow queries
docker compose exec postgres \
  tail -f /var/log/postgresql/postgresql.log
```

## Get Help

1. **Check logs first** — 90% of issues are in the logs
2. **Review environment variables** — Verify all secrets are configured
3. **Verify connectivity** — Test each service independently
4. **Check resource limits** — Ensure Docker has enough memory/disk
5. **Search documentation** — Check `/docs` directory for solutions

For persistent issues, collect diagnostics:

```bash
# Generate diagnostic bundle
docker compose exec tron-api curl http://localhost:8000/health > /tmp/health.json
docker compose logs --tail 1000 > /tmp/docker-logs.txt
docker ps -a > /tmp/containers.txt
docker stats --no-stream > /tmp/stats.txt

# Provide these files when reporting issues
```
