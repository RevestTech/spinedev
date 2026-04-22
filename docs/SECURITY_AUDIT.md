# Tron Security Audit Checklist

Pre-production security review. Each item maps to a specific code module or configuration.

## Encryption at Rest

- [x] Field-level encryption via Fernet (AES-128-CBC + HMAC) — `tron/infra/encryption.py`
- [x] Encryption key loaded from keyvault, never in env vars — `get_encryptor()`
- [x] Key rotation support via `FieldEncryptor.rotate_key()` — tested
- [x] PII fields encrypted before DB write — finding descriptions, code snippets

## Secrets Management

- [x] All secrets loaded from KMac Vault at startup — `tron/infra/secrets/kmac_client.py`
- [x] No secrets in environment variables or config files — `tron/api/config.py` only has non-secret settings
- [x] Secrets cached with TTL, not persisted to disk — `CACHE_TTL_SECONDS = 300`
- [x] Rotation policies defined for all secrets — `tron/infra/secrets/rotation.py`
- [x] Rotation intervals: DB/Redis 90d, Auth keys 180d, Master keys 365d

## Authentication & Authorization

- [x] JWT-based auth with configurable algorithm and expiration — `tron/api/config.py`
- [x] WebSocket auth via query param token — `tron/api/routes/ws.py`
- [x] Socket.IO auth via auth dict JWT — `tron/realtime/socket_server.py`
- [x] API key validation with constant-time comparison (HMAC) — `_authenticate_ws()`
- [x] Rate limiting: 60/min, 1000/hour — `RateLimitMiddleware`

## GDPR Compliance

- [x] Data export endpoint — `GET /api/gdpr/export/{subject_id}`
- [x] Data deletion endpoint — `DELETE /api/gdpr/delete/{subject_id}`
- [x] Retention policy endpoint — `GET /api/gdpr/retention-policy`
- [x] Configurable retention periods (audit data, findings, logs)
- [x] Routes tested with unit tests — `tests/unit/test_routes_health.py`

## Network Security

- [x] Security headers middleware (X-Content-Type-Options, X-Frame-Options, CSP) — `SecurityHeadersMiddleware`
- [x] CORS restricted to localhost:3000, localhost:3001 — `main.py`
- [x] WebSocket max connections guard — `ws.py` `_active_connections`
- [x] Nginx config with rate limiting and SSL termination — `config/nginx/`

## Container Security

- [x] Trivy vulnerability scanning configured — `trivy.yaml`
- [x] CVE ignore list with justifications — `.trivyignore`
- [x] Multi-stage Docker builds (minimal runtime image) — `docker/Dockerfile.api`
- [x] Non-root user in containers
- [x] Resource limits in production compose — `docker-compose.prod.yml`

## Observability & Alerting

- [x] Prometheus metrics collection — `tron/infra/observability/metrics.py`
- [x] SLO-based alerting (availability, latency burn rates) — `config/prometheus/alert_rules.yml`
- [x] LLM cost spike alerts — `LLMCostSpike` rule
- [x] Circuit breaker monitoring — `LLMCircuitBreakerOpen` rule
- [x] Grafana dashboards: overview, SLOs, LLM costs — `config/grafana/dashboards/`

## Testing

- [x] 2,600+ unit/integration tests passing
- [x] Load testing with Locust (multiple user profiles) — `tests/load/locustfile.py`
- [x] Sandbox execution tests — `tests/unit/test_sandbox_*.py`
- [x] Cross-validation golden tests — `tests/golden_suite/`

## Deployment

- [x] Pre-flight checklist script — `scripts/preflight.sh`
- [x] Backup scripts (PostgreSQL, pg_basebackup) — `scripts/backup.sh`
- [x] Restore procedures — `scripts/restore.sh`
- [x] Production docker-compose with replicas — `docker-compose.prod.yml`
