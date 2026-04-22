# Tron Production Runbooks

Production emergency response procedures for Tron infrastructure. Each runbook includes severity classification, symptom detection, diagnosis steps, resolution procedures, verification steps, and prevention guidance.

**Quick Reference**: [PostgreSQL Failover](#postgresql-failover--recovery) | [Redis Eviction & OOM](#redis-eviction--oom) | [Sandbox Explosion](#sandbox-container-explosion) | [Stuck Temporal Workflows](#temporal-workflow-stuck) | [LLM Circuit Breaker](#llm-api-circuit-breaker-open) | [Secret Rotation](#secret-rotation) | [Full Backup & Restore](#full-backup--restore) | [Nginx Failure](#nginx--load-balancer-failure) | [Disk Space](#disk-space-exhaustion) | [Zero-Downtime Deploy](#zero-downtime-deployment)

---

## PostgreSQL Failover & Recovery

**Severity**: P1 (Critical - Data loss possible)

### Symptoms
- PostgreSQL container health check failing: `docker-compose ps | grep tron-postgres`
- PgBouncer connection errors: `FATAL: sorry, too many clients already`
- Application errors: "database connection refused" in logs
- WAL archiving falling behind (disk fill risk)
- Queries timing out consistently (query backlog)

### Diagnosis

Run these commands to assess the situation:

```bash
# Check PostgreSQL service status
docker-compose logs tron-postgres | tail -50

# Check if postgres process is alive
docker exec tron-postgres pg_isready -U tron

# Check connection count
docker exec tron-postgres psql -U tron -d tron -c "SELECT datname, count(*) FROM pg_stat_activity GROUP BY datname;"

# Check disk usage (WAL archive may be growing)
docker exec tron-postgres df -h /var/lib/postgresql

# Check for stuck transactions
docker exec tron-postgres psql -U tron -d tron -c "SELECT pid, usename, state, query FROM pg_stat_activity WHERE state != 'idle' ORDER BY query_start;"

# Check WAL position (replication lag indicator)
docker exec tron-postgres psql -U tron -d tron -c "SELECT pg_wal_lsn_diff(pg_current_wal_lsn(), '0/0');"

# Check PgBouncer stats
docker exec tron-pgbouncer psql -h localhost -U tron -d pgbouncer -c "SHOW POOLS;"
```

### Resolution - Healthy Database Recovery

**Case 1: PostgreSQL is hung/unresponsive (process dead or query storm)**

1. Drain connections gracefully:
```bash
# Set max_connections to 0 to prevent new connections
docker exec tron-postgres psql -U tron -d tron -c "ALTER SYSTEM SET max_connections = 0;" || true

# Kill long-running queries (>5 minutes)
docker exec tron-postgres psql -U tron -d tron -c \
  "SELECT pg_terminate_backend(pid) FROM pg_stat_activity 
   WHERE query_start < now() - interval '5 minutes' AND state != 'idle';"

# Wait 30 seconds for connections to drain
sleep 30
```

2. Restart PostgreSQL gracefully:
```bash
# Stop the container
docker-compose stop tron-postgres

# Ensure full shutdown (allow 15s)
sleep 15

# Restart
docker-compose up -d tron-postgres

# Wait for health check to pass (monitor logs)
docker-compose logs -f tron-postgres | grep "database system is ready"
```

3. Restore max_connections:
```bash
docker exec tron-postgres psql -U tron -d tron -c "ALTER SYSTEM RESET max_connections;"
docker-compose restart tron-postgres
```

**Case 2: WAL Archive is Full (Disk Exhaustion)**

1. Check WAL archive size:
```bash
docker exec tron-postgres ls -lah /var/lib/postgresql/wal-archive/ | tail -20
du -sh /var/lib/postgresql/wal-archive/
```

2. Verify WAL files are being archived:
```bash
docker exec tron-postgres psql -U tron -d tron -c "SHOW archive_status;" 
```

3. Manual WAL cleanup (ONLY after verifying backups are current):
```bash
# List all WAL files in archive
docker exec tron-postgres find /var/lib/postgresql/wal-archive -name "*.ready" -exec rm {} \;

# Force checkpoint and archiving
docker exec tron-postgres psql -U tron -d tron -c "CHECKPOINT;"

# This will clear .ready files, allowing WAL cleanup
docker exec tron-postgres psql -U tron -d tron -c "SELECT pg_switch_wal();"
```

**Case 3: Replication Lag (if in replicated setup)**

```bash
# Check replication slots
docker exec tron-postgres psql -U tron -d tron -c "SELECT * FROM pg_replication_slots;"

# If slot is inactive, drop it and restart replicas
docker exec tron-postgres psql -U tron -d tron -c "SELECT pg_drop_replication_slot('slot_name');"
```

### Verification

```bash
# 1. Verify PostgreSQL is healthy
docker-compose ps tron-postgres  # Should show "healthy"
docker exec tron-postgres pg_isready -U tron  # Should output "accepting connections"

# 2. Verify connectivity from PgBouncer
docker exec tron-pgbouncer psql -h localhost -U tron -d tron -c "SELECT 1;"

# 3. Verify connectivity from application
docker-compose logs tron-api | grep -i "database" | tail -5

# 4. Verify data integrity (run with --all-databases)
docker exec tron-postgres pg_dump -U tron -d tron --schema-only | grep -c "CREATE TABLE"

# 5. Verify WAL archiving is functioning
docker exec tron-postgres psql -U tron -d tron -c "SELECT last_archived_wal FROM pg_stat_archiver;"
```

### Prevention

1. **Monitor connection count** - Set up alerts when connections exceed 80% of max_connections:
   ```bash
   # In Prometheus config, add alert:
   # active_connections / max_connections > 0.8 for 5m
   ```

2. **Monitor WAL archive growth**:
   ```bash
   # Daily: Check WAL archive size isn't growing unexpectedly
   du -h /var/lib/postgresql/wal-archive/
   
   # Alert if daily growth > 10GB
   ```

3. **Configure WAL cleanup**:
   ```bash
   # In docker-compose.yml, ensure these are set:
   # wal_level=replica
   # archive_mode=on
   # archive_command=... (copies to /var/lib/postgresql/wal-archive)
   ```

4. **Enable PgBouncer health checks** - Already configured in docker-compose.yml with `DEFAULT_POOL_SIZE: 25`

5. **Run regular backups** - See [Full Backup & Restore](#full-backup--restore) runbook

---

## Redis Eviction & OOM

**Severity**: P1 (Cache loss, queue loss)

### Symptoms
- Redis connection errors: `OOM command not allowed when used memory > maxmemory`
- High memory utilization in metrics: `redis_memory_used_bytes` near `1073741824` (1GB)
- Cache misses spiking (keys not found when they should exist)
- Queue processing stalling (jobs stuck in Redis)
- Redis health check failing intermittently
- Application errors: "WRONGTYPE Operation against a key holding the wrong kind of value"

### Diagnosis

```bash
# Check Redis memory status
docker exec tron-redis redis-cli -a ${REDIS_PASSWORD} INFO memory

# Get current memory usage (bytes)
docker exec tron-redis redis-cli -a ${REDIS_PASSWORD} INFO memory | grep used_memory:

# Check eviction policy
docker exec tron-redis redis-cli -a ${REDIS_PASSWORD} CONFIG GET maxmemory-policy

# Check number of keys (high count = many small keys or unsharded data)
docker exec tron-redis redis-cli -a ${REDIS_PASSWORD} DBSIZE

# Check key space usage
docker exec tron-redis redis-cli -a ${REDIS_PASSWORD} INFO keyspace

# List largest keys (memory hogs)
docker exec tron-redis redis-cli -a ${REDIS_PASSWORD} --bigkeys

# Check for expired keys not being cleaned
docker exec tron-redis redis-cli -a ${REDIS_PASSWORD} LASTSAVE  # Last save time
docker exec tron-redis redis-cli -a ${REDIS_PASSWORD} BGSAVE   # Current savepoint
```

### Resolution

**Case 1: Memory near limit but eviction enabled (LRU working)**

1. Monitor eviction in real time:
```bash
docker exec tron-redis redis-cli -a ${REDIS_PASSWORD} INFO stats | grep evicted
```

2. If eviction rate is high (>1000 evictions/sec), emergency scale options:
   ```bash
   # Option A: Increase Redis memory limit (temporary, requires restart)
   # Edit docker-compose.yml: --maxmemory 2gb
   docker-compose up -d tron-redis
   
   # Option B: Flush non-critical cache
   # See "Emergency Cache Flush" below
   
   # Option C: Scale to separate Redis for sessions vs queues
   # (Long-term solution, see Prevention)
   ```

**Case 2: Emergency Cache Flush (OOM condition, cannot accept writes)**

```bash
# Step 1: Verify which databases to flush
docker exec tron-redis redis-cli -a ${REDIS_PASSWORD} INFO keyspace

# Step 2: Select non-critical database (e.g., cache DB 0, keep queue DB 1)
# This assumes application uses DB 0 for cache, DB 1 for queues

# Step 3: Flush ONLY cache database (careful: verify your DB mapping!)
docker exec tron-redis redis-cli -a ${REDIS_PASSWORD} -n 0 FLUSHDB

# Step 4: Verify eviction stopped
docker exec tron-redis redis-cli -a ${REDIS_PASSWORD} INFO stats | grep evicted_keys

# Step 5: Monitor memory recovery
docker exec tron-redis redis-cli -a ${REDIS_PASSWORD} INFO memory | grep used_memory
```

**Case 3: Memory leak (steady growth, eviction can't keep up)**

1. Check for keys with very long TTLs or no TTL:
```bash
# Find keys without expiration
docker exec tron-redis redis-cli -a ${REDIS_PASSWORD} \
  --scan --pattern '*' | while read key; do 
    ttl=$(docker exec tron-redis redis-cli -a ${REDIS_PASSWORD} TTL "$key")
    [ "$ttl" = "-1" ] && echo "$key: NO EXPIRATION"
  done | head -20
```

2. Clean up keys manually:
```bash
# Delete specific key pattern (dangerous - test first!)
docker exec tron-redis redis-cli -a ${REDIS_PASSWORD} --scan --pattern 'old:*' | \
  xargs -L 100 docker exec tron-redis redis-cli -a ${REDIS_PASSWORD} DEL

# Or delete by age (requires custom Lua script - contact dev team)
```

3. Restart Redis to force clean state:
```bash
docker-compose stop tron-redis
# This persists to disk (appendonly=yes), so restart will rehydrate 

docker-compose up -d tron-redis
docker-compose logs -f tron-redis | grep "ready to accept"
```

### Verification

```bash
# 1. Verify memory usage is below threshold
docker exec tron-redis redis-cli -a ${REDIS_PASSWORD} INFO memory | grep -E "used_memory:|maxmemory:"

# 2. Verify eviction has stopped
docker exec tron-redis redis-cli -a ${REDIS_PASSWORD} INFO stats | grep evicted_keys_total

# 3. Verify key operations are working
docker exec tron-redis redis-cli -a ${REDIS_PASSWORD} SET test-key "test-value"
docker exec tron-redis redis-cli -a ${REDIS_PASSWORD} GET test-key
docker exec tron-redis redis-cli -a ${REDIS_PASSWORD} DEL test-key

# 4. Verify queue/cache still functioning
docker-compose logs tron-api | grep -i redis | tail -5
```

### Prevention

1. **Set Redis memory alerts**:
   ```yaml
   # In Prometheus alerting rules:
   - alert: RedisMemoryNearLimit
     expr: redis_memory_used_bytes / redis_memory_max_bytes > 0.8
     for: 5m
     annotations:
       summary: "Redis memory {{ $value | humanizePercentage }} of max"
   ```

2. **Monitor eviction rate**:
   ```yaml
   - alert: RedisHighEvictionRate
     expr: rate(redis_evicted_keys_total[5m]) > 100
     annotations:
       summary: "{{ $value | humanize }} keys evicted per second"
   ```

3. **Set appropriate TTLs** - Ensure application sets TTL on all temporary keys:
   ```bash
   # Verify all keys have expiration
   docker exec tron-redis redis-cli -a ${REDIS_PASSWORD} --bigkeys
   
   # Should see mostly keys with TTL > 0
   ```

4. **Database separation** - In production, consider separate Redis instances:
   - DB 0-1: Cache (volatile, OK to evict)
   - DB 2-3: Sessions (persist, requires backup)
   - DB 4: Queues (task jobs, critical, requires backup)

5. **Enable AOF rewriting**:
   ```bash
   # Already enabled in docker-compose.yml (appendonly=yes)
   # Monitor AOF file size
   ls -lh /var/lib/redis/appendonly.aof
   ```

---

## Sandbox Container Explosion

**Severity**: P1 (Resource exhaustion, denial of service)

### Symptoms
- Host OOM killer activating (processes being killed)
- Docker daemon responding slowly or crashing
- Ephemeral container processes accumulating: `docker ps -a | wc -l` shows 100+
- tron-sandbox service becoming unresponsive
- Requests to sandbox hanging indefinitely
- High CPU/memory usage from many small containers
- Errors: "Cannot create container: memory limit"

### Diagnosis

```bash
# Check ephemeral containers
docker ps -a | grep -E "tron|sandbox" | wc -l

# Check which containers are running
docker ps --format "table {{.ID}}\t{{.Names}}\t{{.Status}}\t{{.RunningFor}}"

# Check tron-sandbox service status
docker-compose ps tron-sandbox

# Check tron-sandbox logs for errors
docker-compose logs tron-sandbox | tail -100

# Check Docker daemon resource usage
docker stats --no-stream | grep -E "CONTAINER|tron"

# Check host OOM pressure
docker exec tron-sandbox free -h
docker exec tron-sandbox ps aux | head -20

# Check if there are zombie containers (exited but not cleaned)
docker ps -a --filter "status=exited" | wc -l

# Check sandbox container limits
docker exec tron-sandbox env | grep SANDBOX_
```

### Resolution

**Case 1: Many exited containers accumulating**

```bash
# Step 1: Clean up exited containers
docker container prune -f --filter "until=1h"

# Step 2: Remove dangling images (if sandbox builds ephemerals)
docker image prune -a -f --filter "until=24h"

# Step 3: Clean up volumes not in use
docker volume prune -f --filter "until=24h"

# Step 4: Verify cleanup
docker ps -a | wc -l  # Should be much lower
```

**Case 2: Sandbox service spawning too many concurrent containers**

```bash
# Step 1: Reduce concurrent sandbox limit immediately
docker-compose exec tron-sandbox env | grep SANDBOX_MAX_CONCURRENT

# Step 2: Stop accepting new sandbox requests (graceful drain)
# Comment out or reduce SANDBOX_MAX_CONCURRENT temporarily:
# docker-compose stop tron-sandbox

# Step 3: Wait for existing containers to complete (30s timeout)
sleep 35

# Step 4: Clean running sandbox containers
docker ps -a -q | xargs docker inspect --format '{{.Id}} {{.Name}}' | \
  grep -E "sandbox_run_|execution_" | awk '{print $1}' | xargs docker rm -f

# Step 5: Restart with reduced concurrency
docker-compose up -d tron-sandbox
```

**Case 3: Memory exhaustion cascade**

```bash
# Step 1: Identify top memory consumers
docker stats --no-stream --format "table {{.Container}}\t{{.MemUsage}}" | sort -k2 -hr | head -10

# Step 2: Kill sandboxed containers to free memory
docker ps -a --filter "label!=no-kill" -q | head -20 | xargs docker kill

# Step 3: Check OOM killer log
dmesg | tail -50 | grep -i "oom"

# Step 4: Restart Docker daemon if hung
# WARNING: This will restart all containers
# docker restart docker.service  # or on Mac: restart Docker app

# Step 5: Re-scale sandbox
docker-compose up -d tron-sandbox --scale tron-sandbox=1
```

**Case 4: Long-running sandbox containers not timing out**

```bash
# Step 1: Check SANDBOX_TIMEOUT_SECONDS setting
docker-compose config | grep -A 5 "tron-sandbox" | grep TIMEOUT

# Step 2: List containers older than timeout (should be none)
docker ps -a --format "{{.RunningFor}}\t{{.ID}}\t{{.Names}}" | \
  awk '$1 ~ /[5-9]m|[1-9]h/ {print}'

# Step 3: Kill stuck containers manually
# docker kill <container_id>

# Step 4: Verify timeout enforcement in code
# Check tron/sandbox/executor.py for timeout enforcement
```

### Verification

```bash
# 1. Verify sandbox is responsive
docker exec tron-sandbox grpc_health_probe -addr=:50051

# 2. Verify sandbox concurrency is limited
docker exec tron-sandbox ps aux | grep -c "python\|sandbox"

# 3. Verify no old containers are running
docker ps -a --format "{{.RunningFor}}\t{{.Names}}" | grep -v "second\|minute" | wc -l

# 4. Test sandbox with small execution
# (request from tron-api to execute: echo "hello")

# 5. Verify memory usage is stable
watch -n 5 'docker stats tron-sandbox --no-stream'
```

### Prevention

1. **Set sandbox concurrency limits**:
   ```yaml
   # In docker-compose.yml (already set):
   SANDBOX_MAX_CONCURRENT: 10        # Limit concurrent executions
   SANDBOX_TIMEOUT_SECONDS: 30       # Kill after 30s
   SANDBOX_MEMORY_LIMIT: 256m        # Per-container memory limit
   SANDBOX_CPU_LIMIT: "0.5"          # Per-container CPU limit
   ```

2. **Monitor sandbox resource usage**:
   ```bash
   # Add Prometheus metric:
   # container_count{service="tron-sandbox"} (running + exited)
   # memory_usage{service="tron-sandbox"}
   ```

3. **Enable container cleanup**:
   ```bash
   # Weekly cleanup job (add to cron):
   0 3 * * 0 docker container prune -f --filter "until=30d"
   ```

4. **Implement request queuing**:
   ```bash
   # In tron-api, implement queue depth monitoring
   # If queue > 100, return HTTP 429 (Too Many Requests)
   ```

5. **Use resource quotas** (production):
   ```bash
   # On host, limit Docker daemon memory
   # /etc/docker/daemon.json:
   # {
   #   "storage-driver": "overlay2",
   #   "log-driver": "json-file",
   #   "memory": "8g",
   #   "memswap": "8g"
   # }
   ```

---

## Temporal Workflow Stuck

**Severity**: P2 (Workflows not processing, business logic halted)

### Symptoms
- Workflow execution metrics not advancing (Temporal UI shows no progress)
- Temporal worker logs show "context deadline exceeded" or "worker not picking up tasks"
- Workflow tasks queued but not being executed (queue depth growing)
- Schema migration hanging during startup
- Worker health check failing
- High latency on workflow decisions (>30s)
- Errors in Temporal UI: "Workflow execution timed out"

### Diagnosis

```bash
# Check Temporal cluster health
docker exec tron-temporal tctl --address localhost:7233 cluster health

# List active workflows
docker exec tron-temporal tctl --address localhost:7233 workflow list

# Check specific workflow status (get ID from UI or logs)
docker exec tron-temporal tctl --address localhost:7233 workflow describe \
  -w <workflow_id> -r <run_id>

# Check workflow history
docker exec tron-temporal tctl --address localhost:7233 workflow show \
  -w <workflow_id> -r <run_id>

# List activity tasks pending
docker exec tron-temporal tctl --address localhost:7233 task-queue list

# Check task queue status
docker exec tron-temporal tctl --address localhost:7233 task-queue describe \
  -t tron-tasks

# Check worker process status
docker-compose ps tron-worker

# Check worker logs
docker-compose logs tron-worker | tail -100

# Check Temporal database connections
docker exec tron-postgres psql -U tron -d tron -c \
  "SELECT datname, count(*) FROM pg_stat_activity WHERE datname LIKE '%temporal%' GROUP BY datname;"

# Check Temporal visibility schema
docker exec tron-postgres psql -U tron -d tron -c \
  "SELECT table_name FROM information_schema.tables WHERE table_schema = 'temporal_visibility' LIMIT 10;"
```

### Resolution

**Case 1: Worker is healthy but workflow not advancing (deadlock/hang)**

```bash
# Step 1: Check if activities are being scheduled
docker exec tron-temporal tctl --address localhost:7233 task-queue describe -t tron-tasks

# Step 2: Check for failed activities in workflow history
docker exec tron-temporal tctl --address localhost:7233 workflow show \
  -w <workflow_id> | grep -i "failed\|timeout\|error"

# Step 3: If activities are stuck, increase activity timeout
# (In code: activity_options.start_to_close_timeout = timedelta(minutes=10))
# No runtime fix; requires code change and restart

# Step 4: If workflow in "running" state but no progress for >5m, terminate and retry
docker exec tron-temporal tctl --address localhost:7233 workflow terminate \
  -w <workflow_id> -r <run_id> -r "Terminated due to timeout; manual requeue required"
```

**Case 2: Worker not picking up tasks (process dead or connection lost)**

```bash
# Step 1: Verify worker is running
docker-compose ps tron-worker

# Step 2: Restart worker
docker-compose restart tron-worker

# Step 3: Verify Temporal connectivity
docker-compose logs tron-worker | grep -i "temporal\|connecting" | tail -20

# Step 4: Verify database connectivity
docker exec tron-worker python -c "import asyncpg; print('asyncpg OK')"

# Step 5: Check if stuck transactions are blocking
docker exec tron-postgres psql -U tron -d tron -c \
  "SELECT pid, usename, state, query FROM pg_stat_activity WHERE state = 'idle in transaction';"
```

**Case 3: Schema migration hanging during Temporal startup**

```bash
# Step 1: Check Temporal logs
docker-compose logs tron-temporal | grep -i "migration\|schema" | tail -50

# Step 2: Verify PostgreSQL is healthy
docker exec tron-postgres pg_isready -U tron

# Step 3: Check for stuck migration locks
docker exec tron-postgres psql -U tron -d tron -c \
  "SELECT * FROM pg_locks WHERE NOT granted;"

# Step 4: If locks exist, kill blocking transaction
docker exec tron-postgres psql -U tron -d tron -c \
  "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE state = 'idle in transaction';"

# Step 5: Force Temporal restart (will retry migration)
docker-compose stop tron-temporal
docker-compose up -d tron-temporal
docker-compose logs -f tron-temporal | grep -E "Schema|Initialized|ready"
```

**Case 4: High latency (decisions taking >30s)**

```bash
# Step 1: Check query performance on workflow tables
docker exec tron-postgres psql -U tron -d tron -c \
  "SELECT query, calls, mean_exec_time FROM pg_stat_statements \
   WHERE query ILIKE '%workflows%' ORDER BY mean_exec_time DESC LIMIT 10;"

# Step 2: Check table sizes
docker exec tron-postgres psql -U tron -d tron -c \
  "SELECT schemaname, tablename, pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) 
   FROM pg_tables WHERE schemaname = 'public' ORDER BY pg_total_relation_size DESC LIMIT 10;"

# Step 3: Reindex if tables are large
docker exec tron-postgres psql -U tron -d tron -c "REINDEX TABLE workflow_execution VERBOSE;"

# Step 4: Vacuum if fragmented
docker exec tron-postgres psql -U tron -d tron -c "VACUUM ANALYZE workflow_execution;"

# Step 5: Check Temporal server resource constraints
docker stats tron-temporal --no-stream
```

### Verification

```bash
# 1. Verify Temporal cluster is healthy
docker exec tron-temporal tctl --address localhost:7233 cluster health

# 2. Verify worker is running and connected
docker exec tron-temporal tctl --address localhost:7233 task-queue list | grep tron-tasks

# 3. Start a test workflow and verify it executes
# (Use tron API to start simple workflow like "echo hello")

# 4. Verify workflow completes within expected time (<10s for simple ones)
docker exec tron-temporal tctl --address localhost:7233 workflow describe \
  -w <test_workflow_id> | grep -E "ExecutionStatus|CloseTime"

# 5. Verify no stuck workflows remain
docker exec tron-temporal tctl --address localhost:7233 workflow list \
  | grep -i "running" | wc -l  # Should be reasonable number, not 1000+
```

### Prevention

1. **Monitor workflow queue depth**:
   ```bash
   # Add metric: temporal_task_queue_depth{queue="tron-tasks"}
   # Alert if depth > 100 for >5m
   ```

2. **Set workflow timeouts**:
   ```python
   # In tron/workflows/your_workflow.py:
   @workflow.defn
   class YourWorkflow:
       @workflow.run
       async def run(self, ...):
           # Set workflow execution timeout
           # execution_timeout = timedelta(hours=1)
           pass
   ```

3. **Monitor worker availability**:
   ```bash
   # Ensure at least 2-3 workers are always running
   docker-compose up -d --scale tron-worker=3
   ```

4. **Enable Temporal metrics**:
   ```yaml
   # In temporal config, enable Prometheus metrics
   # prometheus_endpoint: ":8088"
   ```

5. **Regular schema migration testing**:
   ```bash
   # Before major Temporal upgrades, test migration
   docker-compose exec tron-postgres pg_dump -s tron > /tmp/schema_backup.sql
   ```

---

## LLM API Circuit Breaker Open

**Severity**: P2 (LLM features unavailable, core API still functional)

### Symptoms
- Requests with `llm_mode: true` returning 503 "Circuit breaker open"
- LLM request errors spike in logs: "OpenAI API rate limited" or "Anthropic API unavailable"
- Circuit breaker metrics showing: `circuit_breaker_state{service="llm"} = 1` (open)
- All LLM-dependent features fail (code generation, analysis, summarization)
- Error: "Bulkhead rejected: max concurrent LLM requests exceeded"
- LLM API availability check failing in health endpoint

### Diagnosis

```bash
# Check circuit breaker state in logs
docker-compose logs tron-api | grep -i "circuit\|breaker" | tail -20

# Check LLM request failures
docker-compose logs tron-api | grep -i "llm.*error\|openai.*error\|anthropic.*error" | tail -30

# Check current LLM configuration
docker-compose exec tron-api env | grep LLM_

# Test OpenAI API connectivity
docker-compose exec tron-api curl -s https://api.openai.com/v1/models \
  -H "Authorization: Bearer $OPENAI_API_KEY" | jq '.error' 2>/dev/null || echo "API unreachable"

# Test Anthropic API connectivity
docker-compose exec tron-api curl -s https://api.anthropic.com/v1/status \
  -H "x-api-key: $ANTHROPIC_API_KEY" | jq '.status' 2>/dev/null || echo "API unreachable"

# Check concurrent LLM request count
docker-compose logs tron-api | grep -i "bulkhead\|concurrent" | tail -10

# Check circuit breaker failure count
docker-compose logs tron-api | grep "circuit_breaker.*failures" | tail -5

# Monitor real-time metric
docker exec tron-prometheus curl -s http://localhost:9090/api/v1/query \
  'circuit_breaker_failures_total{service="llm"}' | jq '.data.result'
```

### Resolution

**Case 1: Circuit breaker is open due to API failures (transient)**

```bash
# Step 1: Verify which API is failing
docker-compose logs tron-api | grep -E "OpenAI|Anthropic" | grep -i "error\|rate_limit" | tail -5

# Step 2: Check API status
# OpenAI: https://status.openai.com
# Anthropic: https://status.anthropic.com
# (Check via browser or curl)

# Step 3: Wait for circuit breaker to half-open (LLM_CIRCUIT_BREAKER_TIMEOUT = 60s)
echo "Waiting 60 seconds for circuit breaker half-open state..."
sleep 60

# Step 4: Send a test request to allow circuit breaker to retry
docker-compose exec tron-api python -c \
  "import requests; requests.post('http://localhost:8000/api/llm/test', json={'prompt': 'hello'})"

# Step 5: Check if circuit breaker closed
docker-compose logs tron-api | tail -5 | grep -i "circuit"
```

**Case 2: Permanent API failure or quota exceeded**

```bash
# Step 1: Verify API credentials are correct
docker-compose exec tron-api env | grep -E "OPENAI_API_KEY|ANTHROPIC_API_KEY"

# Step 2: Test API keys directly
# For OpenAI:
curl -s https://api.openai.com/v1/models \
  -H "Authorization: Bearer ${OPENAI_API_KEY}" | jq '.error'

# For Anthropic:
curl -s https://api.anthropic.com/v1/messages \
  -H "x-api-key: ${ANTHROPIC_API_KEY}" \
  -H "anthropic-version: 2023-06-01" \
  -d '{"model":"claude-3-sonnet","max_tokens":100,"messages":[{"role":"user","content":"test"}]}' | jq '.error'

# Step 3: Check account status / billing
# OpenAI: https://platform.openai.com/account/billing/overview
# Anthropic: Contact support

# Step 4: Rotate credentials if needed (see Secret Rotation runbook)
```

**Case 3: Too many concurrent LLM requests (bulkhead limit hit)**

```bash
# Step 1: Check bulkhead settings
docker-compose config | grep -A 2 "LLM_BULKHEAD"

# Step 2: Check current concurrent requests
docker-compose logs tron-worker | grep -i "llm.*concurrent\|bulkhead" | tail -10

# Step 3: Increase bulkhead limit (temporary, requires restart)
# Edit docker-compose.yml:
# LLM_BULKHEAD_MAX_CONCURRENT: 20  # From 10

docker-compose up -d tron-api tron-worker

# Step 4: Monitor concurrent request rate
watch -n 2 'docker-compose logs --tail=20 tron-worker | grep -i concurrent'
```

**Case 4: Manual circuit breaker override (emergency)**

```bash
# Step 1: Reset circuit breaker state via environment variable
# (Requires code change - this is for reference)
# Option A: Redeploy with circuit breaker disabled:
docker-compose exec tron-api env -u LLM_CIRCUIT_BREAKER_THRESHOLD python -m tron.api

# Option B: Restart the API service to reset in-memory state
docker-compose restart tron-api

# Step 2: Verify circuit is closed
docker-compose logs tron-api | grep -i "circuit.*closed"

# Step 3: Test LLM functionality
curl -s http://localhost:8000/api/health | jq '.llm_available'
```

### Verification

```bash
# 1. Verify circuit breaker is closed
docker-compose logs tron-api | tail -20 | grep -i "circuit"

# 2. Send test LLM request
curl -X POST http://localhost:8000/api/llm/prompt \
  -H "Content-Type: application/json" \
  -d '{"prompt":"What is 2+2?"}' | jq '.response'

# 3. Verify no bulkhead rejections
docker-compose logs tron-worker | grep -i "bulkhead" | wc -l

# 4. Verify concurrent requests are being processed
docker-compose logs tron-worker | grep -i "llm.*start" | tail -5

# 5. Check circuit breaker metrics
docker exec tron-prometheus curl -s 'http://localhost:9090/api/v1/query' \
  --data-urlencode 'query=circuit_breaker_state{service="llm"}' | jq '.data.result[].value'
```

### Prevention

1. **Monitor LLM API errors**:
   ```yaml
   - alert: LLMAPIFailureRate
     expr: rate(llm_api_failures_total[5m]) > 0.1
     for: 5m
     annotations:
       summary: "{{ $value | humanizePercentage }} LLM API failures"
   ```

2. **Monitor circuit breaker state**:
   ```yaml
   - alert: LLMCircuitBreakerOpen
     expr: circuit_breaker_state{service="llm"} == 1
     for: 1m
     annotations:
       summary: "LLM circuit breaker is open"
   ```

3. **Graceful degradation in UI**:
   ```python
   # In API endpoint, catch circuit breaker exceptions:
   try:
       result = await llm_service.generate(prompt)
   except CircuitBreakerOpen:
       result = {"error": "LLM temporarily unavailable, please retry in 60s"}
       return 503, result
   ```

4. **API quota management**:
   ```bash
   # Monitor OpenAI usage
   # curl https://api.openai.com/v1/usage/gpt-4 \
   #   -H "Authorization: Bearer $OPENAI_API_KEY"
   
   # Set up budget alerts in OpenAI dashboard
   ```

5. **Fallback LLM provider**:
   ```python
   # In production, implement fallback:
   # Try OpenAI first, fall back to Anthropic if circuit open
   # Requires implementation in tron/llm/client.py
   ```

---

## Secret Rotation

**Severity**: P2 (Credentials aging, compliance requirement)

### Symptoms
- Credentials approaching expiration (security audit)
- Compliance requirement: "rotate secrets every 90 days"
- New team member needing API keys
- Suspected credential compromise
- Key rotation deadline approaching

### Resolution - PostgreSQL Password Rotation

```bash
# Step 1: Generate new password
NEW_POSTGRES_PASSWORD=$(openssl rand -hex 32)
echo "New password: $NEW_POSTGRES_PASSWORD"

# Step 2: Update .env file
sed -i "" "s/POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=$NEW_POSTGRES_PASSWORD/" .env

# Step 3: Update password in PostgreSQL (WHILE RUNNING)
docker exec tron-postgres psql -U tron -d tron \
  -c "ALTER ROLE tron WITH PASSWORD '$NEW_POSTGRES_PASSWORD';"

# Step 4: Test new password from PgBouncer
docker exec tron-pgbouncer psql -h localhost -U tron -d tron \
  -c "SELECT 1;" \
  -v PGPASSWORD=$NEW_POSTGRES_PASSWORD

# Step 5: Restart dependent services to use new password
docker-compose restart tron-pgbouncer
docker-compose restart tron-api
docker-compose restart tron-worker
docker-compose restart tron-temporal
docker-compose restart tron-backup

# Step 6: Verify all services are healthy
sleep 30
docker-compose ps | grep -E "tron-|postgres|pgbouncer"
```

### Resolution - Redis Password Rotation

```bash
# Step 1: Generate new password
NEW_REDIS_PASSWORD=$(openssl rand -hex 32)
echo "New password: $NEW_REDIS_PASSWORD"

# Step 2: Update .env file
sed -i "" "s/REDIS_PASSWORD=.*/REDIS_PASSWORD=$NEW_REDIS_PASSWORD/" .env

# Step 3: Update password in Redis (WHILE RUNNING)
docker exec tron-redis redis-cli \
  -a $(grep REDIS_PASSWORD .env | cut -d= -f2) \
  CONFIG SET requirepass "$NEW_REDIS_PASSWORD"

# Step 4: Verify new password works
docker exec tron-redis redis-cli -a "$NEW_REDIS_PASSWORD" PING

# Step 5: Persist to disk
docker exec tron-redis redis-cli -a "$NEW_REDIS_PASSWORD" BGSAVE

# Step 6: Restart dependent services
docker-compose restart tron-api
docker-compose restart tron-worker

# Step 7: Verify cache is still working
curl http://localhost:8000/api/health | jq '.redis'
```

### Resolution - MinIO Credentials Rotation

```bash
# Step 1: Generate new credentials
NEW_MINIO_USER="minio-admin"
NEW_MINIO_PASSWORD=$(openssl rand -hex 32)

# Step 2: Update .env file
sed -i "" "s/MINIO_USER=.*/MINIO_USER=$NEW_MINIO_USER/" .env
sed -i "" "s/MINIO_PASSWORD=.*/MINIO_PASSWORD=$NEW_MINIO_PASSWORD/" .env

# Step 3: Stop MinIO (will cause brief S3 downtime)
docker-compose stop tron-minio

# Step 4: Update credentials (requires stopping and restarting)
# Note: MinIO stores credentials in metadata, restart will pick up new env vars
docker-compose up -d tron-minio

# Step 5: Wait for MinIO to be ready
sleep 10
docker-compose logs tron-minio | grep "API"

# Step 6: Verify new credentials
docker exec tron-minio mc ls minio \
  --access-key $NEW_MINIO_USER \
  --secret-key $NEW_MINIO_PASSWORD

# Step 7: Restart services using MinIO
docker-compose restart tron-api
docker-compose restart tron-worker
docker-compose restart tron-backup
```

### Resolution - LLM API Keys Rotation

```bash
# Step 1: Generate/obtain new API keys
# OpenAI: https://platform.openai.com/account/api-keys
# Anthropic: https://console.anthropic.com/

NEW_OPENAI_API_KEY="sk-..."  # Paste new key
NEW_ANTHROPIC_API_KEY="sk-ant-..."  # Paste new key

# Step 2: Update .env file
sed -i "" "s/OPENAI_API_KEY=.*/OPENAI_API_KEY=$NEW_OPENAI_API_KEY/" .env
sed -i "" "s/ANTHROPIC_API_KEY=.*/ANTHROPIC_API_KEY=$NEW_ANTHROPIC_API_KEY/" .env

# Step 3: Test new keys before rolling out
docker-compose exec tron-api python -c \
  "import os; from openai import OpenAI; c=OpenAI(api_key=os.getenv('OPENAI_API_KEY')); print(c.models.list())"

# Step 4: Restart services
docker-compose restart tron-api tron-worker

# Step 5: Verify LLM functionality
curl http://localhost:8000/api/llm/test

# Step 6: Deactivate old keys in cloud console
# OpenAI: Delete old key from platform.openai.com
# Anthropic: Deactivate in console.anthropic.com
```

### Resolution - JWT Secret Rotation

```bash
# Step 1: Generate new JWT secret
NEW_JWT_SECRET=$(openssl rand -hex 32)
echo "New JWT secret: $NEW_JWT_SECRET"

# Step 2: Update .env file
sed -i "" "s/JWT_SECRET_KEY=.*/JWT_SECRET_KEY=$NEW_JWT_SECRET/" .env

# Step 3: Restart API (will start issuing new JWTs with new secret)
docker-compose restart tron-api

# Step 4: OLD JWTs still valid until they expire (check exp claim)
# Users will be logged out when token expires and will re-authenticate with new secret

# Step 5: Verify new JWTs are being issued
curl -s http://localhost:8000/api/auth/token | jq '.token' | cut -d. -f2 | base64 -D | jq '.'

# Step 6: Monitor for auth failures (users with old tokens)
docker-compose logs tron-api | grep -i "jwt\|auth" | tail -20
```

### Verification

```bash
# 1. Verify all services are healthy after rotation
docker-compose ps
docker-compose exec tron-postgres pg_isready -U tron
docker-compose exec tron-redis redis-cli ping
docker-compose exec tron-minio mc ls minio

# 2. Verify application connectivity
curl http://localhost:8000/health

# 3. Run application smoke tests
# (e.g., create task, execute workflow, store file)

# 4. Verify no errors in logs
docker-compose logs --tail=100 | grep -i "error\|failed\|invalid" | wc -l

# 5. Commit updated .env (ensure it's in .gitignore!)
# NEVER commit .env with actual secrets
```

### Prevention

1. **Automate secret rotation**:
   ```bash
   # Create daily rotation check (cron job):
   0 9 * * MON /usr/local/bin/check-secret-expiry.sh
   
   # check-secret-expiry.sh:
   # - Read secret creation date from encrypted vault
   # - If >90 days old, alert on-call SRE
   # - Generate rotation runbook
   ```

2. **Store secrets in Vault** (production):
   ```bash
   # Migrate from .env to HashiCorp Vault
   # docker-compose.yml pulls from Vault at startup:
   # command: vault kv get -field=postgres_password secret/tron
   ```

3. **Document rotation schedule**:
   ```
   PostgreSQL password: Every 90 days (Q1, Q2, Q3, Q4)
   Redis password: Every 90 days
   MinIO credentials: Every 90 days
   LLM API keys: Rotate if compromised, or annually
   JWT secret: Rotate if key is compromised, or annually
   ```

4. **Monitor secret usage**:
   ```bash
   # Alert if secret is used outside expected location:
   # - POSTGRES_PASSWORD should only be in PostgreSQL/PgBouncer config
   # - LLM keys should only be in API/Worker environment
   ```

---

## Full Backup & Restore

**Severity**: P1 (Disaster recovery)

### Symptoms
- Unplanned data loss
- Ransomware/corruption event
- Major application bug caused data corruption
- Need to test disaster recovery procedures
- Compliance requirement: "annual backup restore test"

### Resolution - Full Backup Procedure

```bash
# Step 1: Trigger full backup manually (outside regular schedule)
docker-compose exec tron-backup bash /usr/local/bin/backup.sh

# Step 2: Wait for backup to complete (may take 5-30 minutes)
docker-compose logs -f tron-backup | grep -E "Backup|complete|error"

# Step 3: Verify backup was created in MinIO
docker exec tron-minio mc ls minio/tron-backups/ --recursive | head -20

# Step 4: Verify base backup size (should be >100MB for non-empty DB)
docker exec tron-minio mc du minio/tron-backups/

# Step 5: Verify WAL files are being archived
ls -lh /var/lib/postgresql/wal-archive/ | tail -10

# Step 6: Create snapshot of backup metadata for restore
docker-compose exec tron-postgres pg_dump -U tron -d tron --schema-only > /tmp/schema_snapshot.sql
```

### Resolution - Full Restore Procedure (Disaster Scenario)

**DESTRUCTIVE OPERATION**: This procedure DELETES current data and restores from backup.

```bash
# Step 1: Stop all applications accessing database
docker-compose stop tron-api tron-worker tron-backup

# Step 2: Verify database is stopped
docker-compose stop tron-postgres
sleep 10

# Step 3: Download latest base backup from MinIO
# (Backup tool stores as: tron-backups/pg_basebackup_YYYY-MM-DD_HH-MM-SS.tar.gz)
LATEST_BACKUP=$(docker exec tron-minio mc ls --json minio/tron-backups/ | \
  jq -r '.name' | grep 'pg_basebackup' | sort -r | head -1)

echo "Restoring from backup: $LATEST_BACKUP"

docker exec tron-minio mc cp minio/tron-backups/$LATEST_BACKUP /tmp/backup.tar.gz

# Step 4: Extract backup
cd /tmp
tar -xzf backup.tar.gz -C backup/

# Step 5: Remove old data directory and restore
docker exec tron-postgres bash -c "rm -rf /var/lib/postgresql/data/*"
docker exec tron-postgres bash -c "cp -r /tmp/backup/* /var/lib/postgresql/data/"

# Step 6: Restore WAL files for point-in-time recovery
# (Optional: if you need to recover to a specific point in time)
# Requires: recovery.conf with restore_command pointing to WAL archive

# Step 7: Start PostgreSQL
docker-compose up -d tron-postgres

# Step 8: Wait for recovery to complete
docker-compose logs -f tron-postgres | grep -E "Database|recovery|ready"

# Step 9: Verify data integrity
docker exec tron-postgres psql -U tron -d tron -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public';"

# Step 10: Restart applications
docker-compose up -d tron-api tron-worker tron-backup
```

### Resolution - Point-in-Time Recovery (PITR)

```bash
# Use case: Restore database to specific time (e.g., before accidental delete)

# Step 1: Determine target recovery time
TARGET_TIME="2024-03-15 14:30:00 UTC"
echo "Recovering to: $TARGET_TIME"

# Step 2: Stop applications
docker-compose stop tron-api tron-worker

# Step 3: Download base backup (as above)
# ...

# Step 4: Create recovery.conf to enable PITR
cat > /tmp/recovery.conf <<EOF
restore_command = 'cp /var/lib/postgresql/wal-archive/%f %p'
recovery_target_timeline = 'latest'
recovery_target_time = '$TARGET_TIME'
recovery_target_inclusive = false
EOF

# Step 5: Place recovery.conf in data directory
docker cp /tmp/recovery.conf tron-postgres:/var/lib/postgresql/data/recovery.conf

# Step 6: Start PostgreSQL (it will recover to target time)
docker-compose up -d tron-postgres

# Step 7: Monitor recovery progress
docker-compose logs -f tron-postgres | grep -E "recovery complete|redo complete"

# Step 8: Verify target time was reached
docker exec tron-postgres psql -U tron -d tron -c "SELECT now();"

# Step 9: Promote database to standby (if applicable)
# docker exec tron-postgres psql -U tron -d tron -c "SELECT pg_promote();"
```

### Resolution - MinIO Backup Restore (S3-compatible storage)

```bash
# Use case: Restore all application files from MinIO backup

# Step 1: List backups in MinIO
docker exec tron-minio mc ls minio/tron-backups/ --recursive

# Step 2: Stop application
docker-compose stop tron-api tron-worker

# Step 3: Download backup manifest
docker exec tron-minio mc cp minio/tron-backups/manifest.json /tmp/manifest.json

# Step 4: Verify backup contents
jq '.buckets | keys' /tmp/manifest.json

# Step 5: Restore specific bucket (e.g., user-uploads)
docker exec tron-minio mc mirror --overwrite \
  minio/tron-backups/user-uploads_20240315 \
  minio/user-uploads

# Step 6: Verify restoration
docker exec tron-minio mc ls minio/user-uploads/ | head -20

# Step 7: Restart application
docker-compose up -d tron-api tron-worker
```

### Verification

```bash
# 1. Verify PostgreSQL backup completeness
docker exec tron-postgres psql -U tron -d tron -c \
  "SELECT schemaname, tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename;" | wc -l

# 2. Verify row counts match pre-backup
# (Save this before backup: SELECT COUNT(*) FROM each_table)
docker exec tron-postgres psql -U tron -d tron -c \
  "SELECT COUNT(*) as total_rows FROM (
    SELECT COUNT(*) FROM workflows
    UNION ALL SELECT COUNT(*) FROM executions
    UNION ALL SELECT COUNT(*) FROM tasks
   ) t;"

# 3. Verify MinIO backup exists and is recent
docker exec tron-minio mc ls minio/tron-backups/ --recursive | tail -5

# 4. Test backup integrity (optional, requires separate PostgreSQL)
# docker run -d postgres:15-alpine
# # Restore to test container
# # Verify data
# docker rm test-postgres

# 5. Verify WAL archive is sequential
ls /var/lib/postgresql/wal-archive/ | sort | tail -20

# 6. Run application smoke tests
curl http://localhost:8000/health
```

### Prevention

1. **Automate daily backups**:
   ```yaml
   # In docker-compose.yml (already configured):
   tron-backup:
     environment:
       BACKUP_SCHEDULE: "0 2 * * *"  # Daily at 2 AM UTC
       BACKUP_RETENTION_DAYS: 30
   ```

2. **Test restore monthly**:
   ```bash
   # Schedule monthly restore test on non-prod environment:
   0 3 1 * * /usr/local/bin/test-restore.sh
   
   # test-restore.sh:
   # - Download latest backup
   # - Restore to temporary PostgreSQL container
   # - Run integrity checks
   # - Alert if any failures
   ```

3. **Monitor backup success**:
   ```yaml
   - alert: BackupFailed
     expr: time() - backup_last_successful_timestamp > 86400
     annotations:
       summary: "No successful backup in last 24 hours"
   ```

4. **Implement off-site backups**:
   ```bash
   # Copy MinIO backups to S3 / cloud storage weekly:
   # 0 4 * * SUN aws s3 sync minio-backup-volume s3://company-tron-backups/
   ```

---

## Nginx / Load Balancer Failure

**Severity**: P1 (All requests blocked, API unreachable)

### Symptoms
- Cannot access http://localhost or http://yourdomain.com
- `curl http://localhost` returns "Connection refused"
- Nginx container is exited or unhealthy
- 502 Bad Gateway errors (upstream unreachable)
- SSL certificate errors when using HTTPS
- WebSocket connections failing (ws:// or wss://)

### Diagnosis

```bash
# Check Nginx container status
docker-compose ps tron-nginx

# Check Nginx logs for errors
docker-compose logs tron-nginx | tail -100

# Check Nginx configuration syntax
docker exec tron-nginx nginx -t

# Check Nginx process
docker exec tron-nginx ps aux | grep nginx

# Test local connectivity to upstream API
docker exec tron-nginx curl -v http://tron-api:8000/health

# Check DNS resolution (tron-api hostname)
docker exec tron-nginx nslookup tron-api

# Check if upstream is listening
docker exec tron-api netstat -tlnp | grep 8000

# Verify TLS certificates
docker exec tron-nginx ls -lah /etc/nginx/ssl/

# Check certificate expiration
docker exec tron-nginx openssl x509 -in /etc/nginx/ssl/cert.pem -noout -dates

# Monitor port 80/443
docker exec tron-nginx netstat -tlnp | grep -E ":80|:443"
```

### Resolution

**Case 1: Nginx container exited/crashed**

```bash
# Step 1: Restart Nginx
docker-compose restart tron-nginx

# Step 2: Wait for startup
sleep 5

# Step 3: Check if it's running
docker-compose ps tron-nginx

# Step 4: If still down, check logs for startup errors
docker-compose logs tron-nginx | grep -i "error\|fail" | tail -20

# Step 5: Verify configuration is valid
docker-compose exec tron-nginx nginx -t

# Step 6: If config error, fix and restart
# (Check /config/nginx/nginx.conf for syntax errors)
docker-compose up -d tron-nginx
```

**Case 2: Upstream API unreachable (502 Bad Gateway)**

```bash
# Step 1: Verify API is running
docker-compose ps tron-api

# Step 2: Test API directly
curl http://tron-api:8000/health

# Step 3: Check API health
docker-compose logs tron-api | grep -i "error\|listening" | tail -10

# Step 4: Restart API if hung
docker-compose restart tron-api

# Step 5: Check DNS resolution
docker exec tron-nginx nslookup tron-api

# Step 6: If DNS fails, restart Docker daemon
# (Last resort - this restarts all containers)
# docker restart docker  # or on Mac: restart Docker app

# Step 7: Wait for all services to come up
docker-compose logs -f | grep -E "healthy|ready"
```

**Case 3: SSL certificate expired or invalid**

```bash
# Step 1: Check certificate expiration
docker exec tron-nginx openssl x509 -in /etc/nginx/ssl/cert.pem -noout -dates

# Step 2: If expired, generate new self-signed certificate (development only)
docker exec tron-nginx openssl req -x509 -nodes -days 365 \
  -newkey rsa:2048 \
  -keyout /etc/nginx/ssl/key.pem \
  -out /etc/nginx/ssl/cert.pem \
  -subj "/CN=localhost"

# Step 3: For production, obtain certificate from Let's Encrypt
# Requires: acme.sh or certbot integration with docker-compose

# Step 4: Reload Nginx to pick up new certificate
docker exec tron-nginx nginx -s reload

# Step 5: Test HTTPS
curl -k https://localhost/health  # -k ignores cert validation for testing
```

**Case 4: WebSocket connection failing**

```bash
# Step 1: Verify WebSocket upgrade is configured in nginx.conf
docker exec tron-nginx grep -A 5 "Upgrade\|upgrade" /etc/nginx/nginx.conf

# Step 2: Check for session stickiness (ip_hash) configuration
docker exec tron-nginx grep -A 5 "upstream tron-api" /etc/nginx/nginx.conf

# Step 3: Test WebSocket endpoint
# (Requires client-side testing, e.g., JavaScript WebSocket client)

# Step 4: Check for proxy protocol issues
# Verify: proxy_set_header Upgrade $http_upgrade;
#         proxy_set_header Connection "Upgrade";
#         proxy_read_timeout 86400;

# Step 5: Reload Nginx
docker exec tron-nginx nginx -s reload
```

**Case 5: High latency / Slow responses (not down, just slow)**

```bash
# Step 1: Check Nginx worker processes
docker exec tron-nginx ps aux | grep "nginx: worker"

# Step 2: Check Nginx error log for timeouts
docker-compose logs tron-nginx | grep -i "timeout"

# Step 3: Increase upstream timeout if API is slow
# In docker-compose.yml volumes mount nginx.conf:
# proxy_connect_timeout 60s;
# proxy_send_timeout 60s;
# proxy_read_timeout 60s;

# Step 4: Check upstream server response time
docker-compose logs tron-api | grep -i "response\|duration" | tail -10

# Step 5: If API is slow, see [PostgreSQL](#postgresql-failover--recovery) or [Redis](#redis-eviction--oom) runbooks
```

### Verification

```bash
# 1. Verify Nginx is running and healthy
docker-compose ps tron-nginx

# 2. Test HTTP connectivity
curl -v http://localhost/health

# 3. Test HTTPS connectivity (if configured)
curl -vk https://localhost/health

# 4. Test reverse proxy to API
curl http://localhost/api/health

# 5. Test static file serving (admin UI)
curl http://localhost/index.html

# 6. Test WebSocket upgrade (advanced)
# wscat -c ws://localhost/ws  # requires wscat tool

# 7. Check response headers
curl -i http://localhost/health | head -20
```

### Prevention

1. **Monitor Nginx uptime**:
   ```yaml
   - alert: NginxDown
     expr: up{job="nginx"} == 0
     for: 1m
     annotations:
       summary: "Nginx is down"
   ```

2. **Monitor upstream health**:
   ```yaml
   - alert: UpstreamUnhealthy
     expr: nginx_upstream_requests_total{state="down"} > 0
     for: 5m
     annotations:
       summary: "Nginx upstream server is unhealthy"
   ```

3. **Enable Nginx metrics**:
   ```bash
   # Add to docker-compose.yml:
   # ports: ["127.0.0.1:8888:8888"]  # Prometheus metrics
   ```

4. **Use health checks**:
   ```bash
   # Already configured in docker-compose.yml:
   healthcheck:
     test: ["CMD", "curl", "-f", "http://localhost/health"]
     interval: 30s
     timeout: 10s
     retries: 3
   ```

5. **Set up multiple Nginx replicas** (production):
   ```bash
   # docker-compose up --scale tron-nginx=3
   # Plus external load balancer (AWS ELB, HAProxy, etc.)
   ```

---

## Disk Space Exhaustion

**Severity**: P1 (Database writes fail, services crash)

### Symptoms
- PostgreSQL disk full error: "ERROR: could not extend relation"
- MinIO unable to store objects: "The disk space is full"
- Docker container unable to write logs
- Application crashes with "No space left on device"
- WAL archiving stopped (archive directory full)
- Metrics: `node_filesystem_avail_bytes{mountpoint="/"}` near 0

### Diagnosis

```bash
# Check overall disk usage
df -h /

# Check PostgreSQL data directory size
du -sh /var/lib/postgresql/data/

# Check PostgreSQL WAL archive size
du -sh /var/lib/postgresql/wal-archive/

# Check MinIO data size
du -sh /minio-data/

# Check Docker volumes
docker volume ls -q | xargs -I {} docker volume inspect {} | grep Mountpoint | head -10

# Check database size
docker exec tron-postgres psql -U tron -d tron -c \
  "SELECT datname, pg_size_pretty(pg_database_size(datname)) FROM pg_database ORDER BY pg_database_size(datname) DESC;"

# Check largest tables
docker exec tron-postgres psql -U tron -d tron -c \
  "SELECT schemaname, tablename, pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) 
   FROM pg_tables ORDER BY pg_total_relation_size DESC LIMIT 20;"

# Check largest indexes
docker exec tron-postgres psql -U tron -d tron -c \
  "SELECT schemaname, indexname, pg_size_pretty(pg_relation_size(schemaname||'.'||indexname))
   FROM pg_indexes ORDER BY pg_relation_size DESC LIMIT 10;"

# Check WAL file count
ls -1 /var/lib/postgresql/wal-archive/ | wc -l

# Check Docker image sizes
docker images --format "table {{.Repository}}\t{{.Size}}" | sort -k3 -hr | head -20

# Check container log sizes
docker ps -q | xargs -I {} bash -c \
  'echo "{}"; du -sh /var/lib/docker/containers/{}/  2>/dev/null' | grep -B1 "G$" | head -20
```

### Resolution

**Case 1: PostgreSQL WAL archive is consuming space**

```bash
# Step 1: Verify archiving is working
docker exec tron-postgres psql -U tron -d tron -c "SHOW archive_status;"

# Step 2: Check for .ready files (not yet archived)
ls /var/lib/postgresql/wal-archive/ | grep -c "\.ready"

# Step 3: Force archiving immediately
docker exec tron-postgres psql -U tron -d tron -c "SELECT pg_switch_wal();"

# Step 4: Check if archiving is running properly (may be stuck)
docker-compose logs tron-backup | tail -50

# Step 5: If archiving is hung, clean up old WAL files
# WARNING: Only do this if backup is up-to-date and WAL is 7+ days old
find /var/lib/postgresql/wal-archive/ -name "*.ready" -delete

# Step 6: Re-run pg_switch_wal() to create new segment
docker exec tron-postgres psql -U tron -d tron -c "SELECT pg_switch_wal();"

# Step 7: Monitor free space
watch -n 5 "df -h / | tail -1; du -sh /var/lib/postgresql/wal-archive/"
```

**Case 2: PostgreSQL bloat (dead tuples, table/index bloat)**

```bash
# Step 1: Identify bloated tables
docker exec tron-postgres psql -U tron -d tron -c \
  "SELECT schemaname, tablename, 
     ROUND(100*((CASE WHEN otta > 0 THEN sml.relpages - otta::int ELSE 0 END)::float / sml.relpages), 2) bloat_pct
   FROM pg_class
   WHERE relpages > 1000 AND bloat_pct > 10 ORDER BY bloat_pct DESC LIMIT 10;"

# Step 2: VACUUM to reclaim dead tuples
docker exec tron-postgres psql -U tron -d tron -c "VACUUM ANALYZE;"

# Step 3: Full VACUUM (requires exclusive lock - will block writes!)
# docker exec tron-postgres psql -U tron -d tron -c "VACUUM FULL;" 
# WARNING: Only run during maintenance window

# Step 4: Reindex bloated indexes
docker exec tron-postgres psql -U tron -d tron -c \
  "REINDEX INDEX CONCURRENTLY index_name;"  # Replace index_name

# Step 5: Check freed space
docker exec tron-postgres psql -U tron -d tron -c \
  "SELECT pg_size_pretty(pg_database_size('tron'));"
```

**Case 3: MinIO storage is full**

```bash
# Step 1: Check MinIO quota
docker exec tron-minio du -sh /data

# Step 2: List largest buckets
docker exec tron-minio mc du minio/ --recursive | sort -h | tail -10

# Step 3: List oldest objects in bucket (for cleanup)
docker exec tron-minio mc ls minio/user-uploads/ --recursive | sort | head -20

# Step 4: Delete old/temporary uploads
# (Requires application-level policy, e.g., "delete uploads >30 days old")

# Step 5: Check if incomplete uploads exist (failed uploads taking space)
docker exec tron-minio mc find minio/ --incomplete

# Step 6: Remove incomplete uploads
docker exec tron-minio mc rm minio/ --incomplete --force --recursive
```

**Case 4: Docker image/container bloat**

```bash
# Step 1: Remove unused images
docker image prune -a --force --filter "until=24h"

# Step 2: Remove unused volumes
docker volume prune --force --filter "until=24h"

# Step 3: Remove unused networks
docker network prune --force

# Step 4: Clean Docker cache
docker builder prune --all --force

# Step 5: Check freed space
df -h /var/lib/docker

# Step 6: Restart Docker daemon (optional, forces cleanup)
# docker restart docker  # or on Mac: restart Docker app
```

**Case 5: Container logs are too large**

```bash
# Step 1: Find large log files
du -sh /var/lib/docker/containers/*/

# Step 2: Truncate logs safely (container still running)
docker exec tron-api bash -c "cat /dev/null > /proc/self/fd/1"

# Step 3: Or restart container to rotate logs
docker-compose restart tron-api

# Step 4: Configure log rotation in docker-compose.yml:
# logging:
#   driver: "json-file"
#   options:
#     max-size: "10m"
#     max-file: "3"
```

### Verification

```bash
# 1. Verify disk space is freed
df -h / | tail -1

# 2. Verify PostgreSQL is healthy after cleanup
docker exec tron-postgres pg_isready -U tron

# 3. Verify MinIO is healthy
docker exec tron-minio mc ls minio/

# 4. Verify application can still write
curl -X POST http://localhost:8000/api/data -d '{"test":"data"}'

# 5. Check metrics for space availability
docker exec tron-prometheus curl -s 'http://localhost:9090/api/v1/query' \
  --data-urlencode 'query=node_filesystem_avail_bytes{mountpoint="/"}' | jq '.data.result[].value'
```

### Prevention

1. **Set up disk space alerts**:
   ```yaml
   - alert: DiskSpaceLow
     expr: node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"} < 0.15
     for: 10m
     annotations:
       summary: "Disk space < 15% ({{ $value | humanizePercentage }})"
   
   - alert: DiskSpaceCritical
     expr: node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"} < 0.05
     for: 1m
     annotations:
       summary: "Disk space critical < 5% - IMMEDIATE ACTION REQUIRED"
   ```

2. **Monitor PostgreSQL growth**:
   ```bash
   # Daily: Check database size growth rate
   0 6 * * * psql -c "SELECT pg_size_pretty(pg_database_size('tron'))" >> /var/log/tron/pg_size.log
   ```

3. **Automate WAL cleanup**:
   ```bash
   # Backup service should clean old WAL files (>7 days)
   # docker-compose.yml backup script:
   # find /var/lib/postgresql/wal-archive -mtime +7 -delete
   ```

4. **Set MinIO quota**:
   ```bash
   # In docker-compose.yml, add:
   # MINIO_STORAGE_CLASS_STANDARD=EC:3,DRV:4  # For quotas
   ```

5. **Enable autovacuum** (already enabled):
   ```bash
   # docker-compose.yml already has autovacuum enabled
   # Monitor autovacuum runs:
   docker exec tron-postgres psql -U tron -d tron -c "SELECT * FROM pg_stat_user_tables WHERE last_autovacuum IS NOT NULL LIMIT 10;"
   ```

---

## Zero-Downtime Deployment

**Severity**: P2 (Required for updates, business continuity)

### Symptoms
- Planning an update/release
- Need to deploy without interrupting users
- Temporal workflows should continue processing
- WebSocket connections should remain active
- Long-running requests should complete gracefully

### Resolution

**Pre-deployment Checklist**

```bash
# 1. Ensure all tests pass
docker-compose run tron-api pytest

# 2. Build new images
docker-compose build tron-api tron-worker

# 3. Verify new images are built
docker images | grep tron-

# 4. Tag images for release
docker tag tron:latest tron:v2.0.0
docker push <registry>/tron:v2.0.0

# 5. Verify Temporal workflow compatibility
# (See "Temporal Workflow Versioning" below)

# 6. Verify database migrations are backward-compatible
# (Old code must still work with new schema)

# 7. Get deployment approval
echo "Deployment planned for 2024-03-20 02:00 UTC during maintenance window"
```

**Rolling Update - API (No Downtime)**

```bash
# Step 1: Update docker-compose.yml with new image version
sed -i "" 's/image: tron:.*$/image: tron:v2.0.0/' docker-compose.yml

# Step 2: Start new API instance (scale up)
docker-compose up -d --scale tron-api=2

# Step 3: Wait for new instance to be healthy
sleep 30
docker-compose ps tron-api | grep "healthy"

# Step 4: Remove one old instance (old requests complete)
docker-compose up -d --scale tron-api=1

# Step 5: Verify no traffic loss (watch metrics)
curl http://localhost:8000/health | jq '.uptime'

# Step 6: Verify WebSocket connections are stable
# (Real-time features should work)
```

**Rolling Update - Worker (Graceful Drain)**

```bash
# Step 1: Scale up workers with new version
sed -i "" 's/image: tron-worker:.*$/image: tron-worker:v2.0.0/' docker-compose.yml
docker-compose up -d --scale tron-worker=4  # Add one extra

# Step 2: Wait for new workers to join Temporal task queue
sleep 10
docker exec tron-temporal tctl --address localhost:7233 task-queue describe -t tron-tasks

# Step 3: Stop accepting new tasks on old workers (graceful drain)
# Set environment variable: ACCEPT_NEW_TASKS=false
docker-compose exec tron-worker env | grep ACCEPT_NEW_TASKS

# Step 4: Wait for old workers to finish current tasks (max 5 minutes)
# Monitor: docker-compose logs tron-worker | grep "task completed"
sleep 300

# Step 5: Remove old workers
docker-compose up -d --scale tron-worker=3

# Step 6: Verify all tasks are being processed by new workers
docker exec tron-temporal tctl --address localhost:7233 task-queue describe -t tron-tasks
```

**Temporal Workflow Versioning (Critical for ZDT)**

```python
# File: tron/workflows/example.py
from datetime import timedelta
from temporalio import workflow

@workflow.defn
class MyWorkflow:
    @workflow.run
    async def run(self, name: str) -> str:
        # Use versioning to support old code during rollout
        
        # Old behavior (version 1)
        if await workflow.get_version("my-change-id", workflow.DEFAULT_VERSION, 1) <= 1:
            result = await workflow.execute_activity(
                old_activity,
                name,
                start_to_close_timeout=timedelta(seconds=60)
            )
        
        # New behavior (version 2+)
        else:
            result = await workflow.execute_activity(
                new_activity,
                name,
                timeout=timedelta(seconds=120)
            )
        
        return result

# Version numbering: OLD code runs with DEFAULT_VERSION (-1)
#                    NEW code runs with latest version (1, 2, etc.)
# During rollout: Both old and new can process workflows safely
```

**Database Migration - Zero-Downtime Pattern**

```bash
# Pattern: Expand schema (new code optional), then contract

# Step 1: Add new database column (no-op for old code)
docker exec tron-postgres psql -U tron -d tron -c \
  "ALTER TABLE workflows ADD COLUMN new_field TEXT DEFAULT NULL;"

# Step 2: Deploy new code that writes to new_field
docker-compose up -d tron-api  # Pulls version v2.0.0

# Step 3: Wait for all old code to drain (all rows have new_field)
sleep 60

# Step 4: Make column NOT NULL (optional, when fully migrated)
docker exec tron-postgres psql -U tron -d tron -c \
  "ALTER TABLE workflows ALTER COLUMN new_field SET NOT NULL;"

# Step 5: Drop old column if no longer needed (remove old code first)
# docker exec tron-postgres psql -U tron -d tron -c \
#   "ALTER TABLE workflows DROP COLUMN old_field;"
```

**Rollback Procedure (If Something Goes Wrong)**

```bash
# Step 1: Immediately scale down new version
docker-compose up -d --scale tron-api=0 --scale tron-worker=0

# Step 2: Scale up old version
sed -i "" 's/image: tron:v2.0.0$/image: tron:v1.9.9/' docker-compose.yml
docker-compose up -d --scale tron-api=2 --scale tron-worker=3

# Step 3: Monitor for errors
docker-compose logs -f tron-api | grep -i "error"

# Step 4: If database schema was changed, need to revert
# (Requires downtime if schema is incompatible)

# Step 5: Notify team of rollback
echo "Rolled back to v1.9.9 due to error: [error description]"
```

### Verification

```bash
# 1. Verify no requests are dropped during update
# Check request metrics: count should remain steady
curl http://localhost:8000/metrics | grep "http_requests_total" | tail -3

# 2. Verify WebSocket connections remain active
# (Use real-time feature and verify no disconnects in logs)

# 3. Verify Temporal workflows continue processing
docker exec tron-temporal tctl --address localhost:7233 workflow list | head -5

# 4. Verify no new errors in logs
docker-compose logs --tail=100 | grep -i "error" | wc -l

# 5. Verify application health
curl http://localhost:8000/health | jq '.status'

# 6. Verify data integrity (no corruption during migration)
docker exec tron-postgres psql -U tron -d tron -c \
  "SELECT COUNT(*) FROM workflows WHERE new_field IS NOT NULL;"
```

### Prevention

1. **Implement feature flags**:
   ```python
   # In application code:
   if feature_flag("new-endpoint"):
       # New behavior
   else:
       # Old behavior
   
   # Deploy code with flag OFF
   # Deploy code with flag ON after monitoring
   ```

2. **Set up canary deployments**:
   ```bash
   # Send 5% of traffic to new version
   # docker-compose up --scale tron-api=19 --scale tron-api-v2=1
   ```

3. **Automated smoke tests**:
   ```bash
   # After each deployment, run:
   # - Health check
   # - Workflow execution test
   # - API endpoint tests
   # - WebSocket connectivity test
   ```

4. **Monitor deployment health**:
   ```yaml
   - alert: HighErrorRateAfterDeployment
     expr: rate(http_requests_total{status=~"5.."}[5m]) > 0.05
     for: 5m
     annotations:
       summary: "Error rate > 5% after deployment"
   ```

5. **Automated rollback**:
   ```bash
   # If error rate > threshold for 10 minutes, auto-rollback:
   # 0 * * * * /usr/local/bin/check-deployment-health.sh
   ```

---

## Quick Reference - Common Commands

```bash
# Get overall system status
docker-compose ps

# View logs for specific service
docker-compose logs -f tron-api
docker-compose logs --tail=50 tron-postgres

# Execute command in running container
docker exec tron-postgres psql -U tron -d tron -c "SELECT 1;"

# Restart service
docker-compose restart tron-api

# Scale service
docker-compose up -d --scale tron-worker=5

# Clean up old containers/images
docker container prune -f
docker image prune -a -f

# Check metrics
docker stats tron-api --no-stream
df -h /

# Tail all logs
docker-compose logs -f

# Stop all services
docker-compose down

# Stop specific service (graceful shutdown, 10s timeout)
docker-compose stop tron-api
```

---

## Incident Response Checklists

### Data Loss Incident

1. **Immediate (0-5 min)**
   - [ ] Stop all write operations: `docker-compose stop tron-api tron-worker`
   - [ ] Preserve evidence: `docker-compose logs > /tmp/incident_logs.txt`
   - [ ] Assess scope: Which data was affected? How much?

2. **Short-term (5-30 min)**
   - [ ] Activate restore procedures (see [Full Backup & Restore](#full-backup--restore))
   - [ ] Notify stakeholders of potential recovery time
   - [ ] Determine if restoration is possible (verify backup integrity)

3. **Recovery (30 min - hours)**
   - [ ] Execute restore from backup
   - [ ] Verify data integrity
   - [ ] Restart services
   - [ ] Validate with stakeholders

### Performance Degradation Incident

1. **Immediate (0-5 min)**
   - [ ] Check metrics: `docker stats --no-stream`
   - [ ] Check disk: `df -h /`
   - [ ] Check database: `docker exec tron-postgres pg_isready -U tron`

2. **Diagnosis (5-15 min)**
   - [ ] Use appropriate runbook:
     - High memory → [Redis Eviction & OOM](#redis-eviction--oom)
     - Slow queries → [PostgreSQL Failover](#postgresql-failover--recovery)
     - Container explosion → [Sandbox Explosion](#sandbox-container-explosion)

3. **Resolution (15-60 min)**
   - [ ] Execute runbook procedures
   - [ ] Monitor metrics during recovery
   - [ ] Verify services return to health

### Deployment Issue

1. **Immediate (0-5 min)**
   - [ ] Assess impact: Are new deployments working?
   - [ ] Stop new deployments: Pause CI/CD
   - [ ] Check error logs: `docker-compose logs tron-api | grep -i error`

2. **Short-term (5-15 min)**
   - [ ] Decide: Rollback or debug?
   - [ ] If rollback needed: See [Zero-Downtime Deployment](#zero-downtime-deployment) → Rollback Procedure
   - [ ] If debugging: Check [Temporal Workflow Stuck](#temporal-workflow-stuck) or other relevant runbooks

3. **Recovery**
   - [ ] Execute rollback if needed
   - [ ] Re-run deployment with fix
   - [ ] Post-mortem analysis

---

**Last updated**: 2024-03-15  
**Maintained by**: SRE Team  
**Version**: 5.1 (Production Ready)
