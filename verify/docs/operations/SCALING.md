# Horizontal scaling

How to run more than one of each Tron process. The default compose
file ships a single instance of every service so it boots clean on a
laptop. Production traffic needs replicas of `tron-api` and
`tron-worker`; the rest can stay singleton or scale on a different
axis (`tron-sandbox`).

## What you can scale, and how

| Service | Stateless? | How to scale | Watch out for |
|---------|-----------|--------------|---------------|
| `tron-api` | **Yes** | `docker compose up --scale tron-api=N` behind nginx, or set `replicas: N` in a deploy override | Sticky sessions for WebSocket / Socket.IO — see below |
| `tron-worker` | **Yes** (Temporal coordinates) | Run N worker containers with the same `TEMPORAL_TASK_QUEUE`. Temporal load-balances tasks. | LLM budget reservation runs on Redis; ensure Redis is reachable from every worker |
| `tron-sandbox` | **Yes** | Multiple sandbox containers can sit behind a reverse proxy at a single `TRON_SANDBOX_URL`. Each runs the docker socket itself; per-container resource limits do the rest. | Each sandbox needs its own seccomp profile mount |
| `nginx` | **Yes** but usually 1 per host | Two nginx replicas behind an LB; or skip nginx entirely and terminate TLS at your cloud LB | TLS cert rotation — see `docs/security/TLS_RUNBOOK.md` |
| `postgres` | **No** | Use managed Postgres or a primary + read replica setup. **Do not** run multi-writer. | All connections go through PgBouncer in compose; preserve that for replicas |
| `redis` | **No** (but mostly read-light) | Single instance is fine for most deployments. HA via managed Redis or a Redis Sentinel cluster. | Budget reservation depends on Redis being available — `TRON_LLM_BUDGET_REQUIRE_REDIS=true` makes that explicit |
| `temporal` | Yes (its own clustering) | Use Temporal Cloud or a clustered self-hosted deployment. Workers connect via service name; nothing in Tron pins a single Temporal node. | n/a |
| `prometheus` / `grafana` / `loki` / `tempo` / `alertmanager` | Yes | Standard observability scaling stories per project. | Alertmanager state replication if you need high-availability alerting |

## Stateless guarantees in `tron-api`

Several patterns matter for scaling safely:

- **Auth state** is per-request (the `X-API-Key` header is looked up
  on each call, the admin cookie is verified per-call). No
  in-memory session cache to invalidate across replicas.
- **Rate limit state** lives in Redis (`tron/api/middleware/rate_limit.py`).
  Counts are correct across replicas.
- **Budget reservation** lives in Redis (`tron/infra/llm/budget_reservation.py`).
  Two replicas can each call `LLMClient.complete` simultaneously
  without busting the cap.
- **API-key audit log writes** happen in a fire-and-forget background
  task (`tron/api/middleware/audit_log.py`); they never block the
  response and are bounded at 1000 in-flight per process. Across
  replicas they accumulate as expected.
- **WebSocket connection counts** are per-replica — `WS_MAX_CONNECTIONS=100`
  applies to one process. If you scale to 4 replicas and want to
  cap at 400 concurrent WS connections globally, set the per-replica
  cap to 100 and trust the math.

## WebSocket sticky sessions

`AuditWorkflow` events flow over Redis pub/sub, so any replica can
serve the WebSocket subscription for any audit. **However**,
Socket.IO has built-in handshake semantics (rooms, namespaces) that
prefer the same backend for the lifetime of one connection.

The compose `nginx.conf` uses `ip_hash` on the `tron_api` upstream:

```nginx
upstream tron_api {
    ip_hash;
    server tron-api:8000;
    # add more here when scaling
}
```

That gives sticky-by-source-IP routing. If your traffic comes through
a NAT and clients all share an IP, switch to `least_conn` and accept
the small re-handshake cost on reconnects.

## Scaling worker concurrency

Each `tron-worker` runs Temporal activities concurrently up to:

- `TEMPORAL_MAX_CONCURRENT_ACTIVITIES` (default 10) — activities like
  agent runs, sandbox calls.
- `TEMPORAL_MAX_CONCURRENT_WORKFLOWS` (default 20) — workflow
  executions.

Two ways to add capacity:

1. **More workers**: `docker compose up --scale tron-worker=4`. Each
   one polls Temporal and grabs work. No coordination needed.
2. **Bigger workers**: bump the per-worker concurrency env vars.
   Cheaper on container overhead, but each worker needs more memory
   (every concurrent activity holds an LLM request in flight).

Pick (1) when activity latency is dominated by LLM calls (most of
Tron's workload) — more processes = more parallel LLM requests
without touching `LLM_BULKHEAD_MAX_CONCURRENT`. Pick (2) when
activities are CPU-bound and you have headroom.

## What is *not* yet ready to scale

- **`tron/sandbox/server.py` shared `_local: SandboxClient`** — the
  module-level cache is per-process. Two requests to the same
  sandbox container will reuse the same `SandboxClient`; multiple
  sandbox containers each have their own. That's correct, just
  worth knowing.
- **MinIO** — when wired (it's currently used for SARIF blob
  archival only), the bucket name is shared. Scale MinIO via its
  own clustering; the Tron client doesn't need to change.
- **The legacy `admin-ui/` SPA** is single-deployment by design.
  Use `frontend/` (the active SPA) for any production scenario.

## A concrete production override

`docker-compose.scale.yml`:

```yaml
services:
  tron-api:
    deploy:
      replicas: 3
      resources:
        limits:
          cpus: '2'
          memory: 1G

  tron-worker:
    deploy:
      replicas: 4
      resources:
        limits:
          cpus: '2'
          memory: 2G
    environment:
      TEMPORAL_MAX_CONCURRENT_ACTIVITIES: 20

  nginx:
    deploy:
      replicas: 2
      placement:
        constraints: [node.labels.role == frontend]
```

Bring up with:

```bash
docker compose -f docker-compose.yml -f docker-compose.scale.yml up -d
```

For Kubernetes deployments, mirror these as a `Deployment` per
service; the same env vars and resource shapes apply. Add an
`HorizontalPodAutoscaler` keyed on CPU for `tron-api` and on
queue depth (Temporal task-queue lag) for `tron-worker`.

## Verifying it actually scaled

```bash
# Check tron-api replica count is what you expect
docker compose ps tron-api

# Confirm Temporal sees all workers
curl -s http://temporal-ui:8080/api/v1/namespaces/default/task-queues/tron-tasks | jq '.pollers | length'

# Ops verification end-to-end
make verify-observability
```
