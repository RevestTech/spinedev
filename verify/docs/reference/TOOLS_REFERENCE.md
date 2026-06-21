# Tron Technology Stack - Quick Reference

**Complete tool reference for the Tron platform**  
**Version:** 5.2 | **Last Updated:** April 12, 2026

---

## Core Infrastructure

### PostgreSQL 15
**Purpose:** Primary relational database  
**Usage:** Stores projects, audits, findings, user data  
**Key Config:** 200 max connections, 512MB shared buffers, WAL archiving, pgvector for embeddings  
**Port:** 13002

### Redis 7
**Purpose:** Cache and pub/sub messaging  
**Usage:** API response caching, WebSocket event streaming, session storage  
**Key Config:** 1GB max memory, LRU eviction, AOF persistence, pool size: 50  
**Port:** 13003

### Temporal
**Purpose:** Durable workflow orchestration  
**Usage:** Fault-tolerant audit execution, survives crashes/restarts  
**Key Config:** 2 workflows, 10 activities, task queue: tron-tasks  
**Port:** 13007

### MinIO
**Purpose:** S3-compatible object storage  
**Usage:** Stores repository archives, artifacts, audit reports  
**Key Config:** Versioning enabled, lifecycle policies, multi-part uploads  
**Port:** 13004-13005

### KMac Vault
**Purpose:** Centralized secrets management  
**Usage:** Runtime secret loading (API keys, passwords, tokens)  
**Key Config:** HTTP API, prefix: tron:, token-based auth  
**Port:** 9999

### PgBouncer
**Purpose:** PostgreSQL connection pooler  
**Usage:** Reduces connection overhead, manages concurrent clients  
**Key Config:** Transaction pooling, 500 max clients, 25 pool size per DB  
**Port:** 13006

---

## Application Framework

### FastAPI
**Purpose:** Modern Python web framework  
**Usage:** Powers all HTTP endpoints, auto-generates OpenAPI docs  
**Key Config:** Async/await native, type validation via Pydantic, WebSocket support  
**Version:** 0.104.1

### SQLAlchemy 2.0
**Purpose:** Python ORM and SQL toolkit  
**Usage:** Database abstraction, all DB interactions  
**Key Config:** Async sessions, pool size: 10, max overflow: 5, Alembic migrations  
**Version:** 2.0.23

### Pydantic
**Purpose:** Data validation using type hints  
**Usage:** Validates API requests/responses, defines finding schemas  
**Key Config:** Auto validation, serialization, JSON schema generation  
**Version:** 2.5.0

### Uvicorn
**Purpose:** Lightning-fast ASGI server  
**Usage:** Runs FastAPI application  
**Key Config:** 1 worker per container, debug logging, port 13000  
**Version:** 0.24.0

---

## AI & Machine Learning

### Anthropic Claude
**Purpose:** Primary LLM for agent analysis  
**Usage:** Powers SecurityISO, BuilderISO, PerformanceISO agents  
**Model:** claude-3-haiku-20240307  
**Key Config:** 200K context window, temperature: 0.1, max tokens: 4000  
**Cost:** $0.25 input / $1.25 output per 1M tokens  
**Version:** 0.7.1

### OpenAI GPT-4o
**Purpose:** Cross-validation LLM  
**Usage:** Independent verification of critical/high severity findings  
**Model:** gpt-4o  
**Key Config:** 128K context window, JSON mode support, rate limit: 429 handling  
**Cost:** Variable pricing  
**Version:** 1.3.7

### Tiktoken
**Purpose:** BPE tokenizer for counting tokens  
**Usage:** Token budget enforcement, cost estimation before LLM calls  
**Key Config:** Model-specific encodings (cl100k_base for GPT-4, claude for Claude)  
**Version:** 0.5.2

---

## Static Analysis Tools

### Bandit
**Purpose:** Python security linter (AST-based)  
**Usage:** First-pass security scan, establishes ground truth  
**Key Config:** 100+ built-in security tests, confidence scoring, zero false negatives  
**Detects:** Hardcoded passwords, SQL injection patterns, insecure crypto  
**Version:** 1.7.5

### Semgrep
**Purpose:** Multi-language SAST tool (semantic patterns)  
**Usage:** Security scanning across 30+ languages, custom rules  
**Key Config:** OWASP Top 10 coverage, pattern-based (not regex), 500ms typical runtime  
**Detects:** Injection flaws, dangerous API usage, insecure configurations  
**Version:** 1.52.0

### Ruff
**Purpose:** Extremely fast Python linter (Rust-based)  
**Usage:** Code quality checks for Python  
**Key Config:** 700+ rules, 10-100x faster than Flake8, auto-fix support  
**Detects:** Style issues, unused imports, complexity violations  
**Version:** 0.1.7

### MyPy
**Purpose:** Static type checker for Python  
**Usage:** Type safety verification in Tron and analyzed projects  
**Key Config:** Gradual typing, plugin system, IDE integration  
**Detects:** Type errors, incorrect function signatures, None-safety issues  
**Version:** 1.7.1

---

## Resilience & Observability

### Tenacity
**Purpose:** Flexible retry logic library  
**Usage:** Wraps LLM API calls with exponential backoff  
**Key Config:** 3 attempts, exponential backoff (1s, 2s, 4s), jitter support  
**Handles:** Transient network failures, temporary rate limits  
**Version:** 8.2.3

### PyBreaker
**Purpose:** Circuit breaker pattern implementation  
**Usage:** Prevents cascading failures from LLM API outages  
**Key Config:** Failure threshold: 5, timeout: 60s, per-provider isolation  
**Behavior:** Opens after 5 failures, prevents wasted calls, auto-recovers  
**Version:** 1.0.2

### OpenTelemetry
**Purpose:** Vendor-neutral observability framework  
**Usage:** Distributed tracing for FastAPI, SQLAlchemy, Redis, HTTP clients  
**Key Config:** OTLP exporter, service name: tron-api, spans to Tempo  
**Metrics:** Request latency, error rates, database query times  
**Version:** 1.21.0

### Prometheus
**Purpose:** Time-series metrics database  
**Usage:** Application and infrastructure metrics collection  
**Key Config:** PromQL queries, alerting rules, Grafana dashboards  
**Metrics:** Request rates, LLM token usage, database pool stats  
**Version:** 0.19.0 (client)

---

## Security & Authentication

### python-jose
**Purpose:** JWT creation and verification (JOSE standard)  
**Usage:** Issues JWT tokens for user authentication  
**Key Config:** HS256 algorithm, 60min expiration, secrets from KMac Vault  
**Secrets:** tron:auth_jwt_secret  
**Version:** 3.3.0

### Passlib
**Purpose:** Password hashing library  
**Usage:** Hashes API keys and user passwords  
**Key Config:** Bcrypt with 12 rounds, constant-time comparison, auto salting  
**Backend:** [bcrypt]  
**Version:** 1.7.4

---

## HTTP & Networking

### HTTPX
**Purpose:** Modern async HTTP client  
**Usage:** External API calls (Anthropic, OpenAI, KMac Vault)  
**Key Config:** 30s timeout, automatic retries, connection pooling, HTTP/2 support  
**Features:** Async/await native, context manager support  
**Version:** 0.25.2

### Python-SocketIO
**Purpose:** Socket.IO protocol for WebSocket  
**Usage:** Real-time audit progress streaming at /ws/audits/{id}  
**Key Config:** Redis pub/sub backend, max connections: 100, heartbeat: 30s  
**Events:** audit_started, finding_discovered, audit_completed  
**Version:** 5.10.0

---

## Testing & Quality

### Pytest
**Purpose:** Python testing framework  
**Usage:** All unit and integration tests  
**Key Config:** Async support (pytest-asyncio), coverage (pytest-cov), mocking (pytest-mock)  
**Features:** Fixture system, parametrization, extensive plugin ecosystem  
**Version:** 7.4.3

### Locust
**Purpose:** Scalable load testing tool  
**Usage:** Performance testing for API endpoints, concurrent audit simulation  
**Key Config:** Distributed testing, web UI dashboard, Python test scenarios  
**Metrics:** Request rates, response times, failure rates  
**Version:** 2.19.1

### Playwright
**Purpose:** Modern browser automation framework  
**Usage:** End-to-end testing of web UI flows, WebSocket connections  
**Key Config:** Multi-browser support (Chromium, Firefox, WebKit), auto-wait, screenshots  
**Features:** Network interception, video recording, parallel execution  
**Version:** 1.40.0

---

## Development Tools

### Docker
**Purpose:** Application containerization platform  
**Usage:** All services containerized (tron-api, tron-worker, postgres, redis, etc.)  
**Key Config:** Multi-stage builds, non-root user, health checks, volume mounts  
**Containers:** 7+ services orchestrated via Docker Compose  

### Docker Compose
**Purpose:** Multi-container orchestration  
**Usage:** Defines and manages all Tron services  
**Key Config:** Health dependencies, port range 13000-13080, restart: unless-stopped  
**Services:** postgres, redis, temporal, minio, pgbouncer, tron-api, tron-worker  

### Git
**Purpose:** Version control system  
**Usage:** Clones repositories for analysis  
**Key Config:** Shallow clones (--depth 1), GIT_TERMINAL_PROMPT=0, 120s timeout  
**Features:** .gitignore respect, non-interactive mode for public repos  

### Alembic
**Purpose:** Database migration tool for SQLAlchemy  
**Usage:** Schema version control across deployments  
**Key Config:** 13 tables defined, auto-generation, rollback support  
**Features:** Forward migration, rollback, branch merging  
**Version:** 1.13.1

---

## Additional Dependencies

### asyncpg
**Purpose:** Fast PostgreSQL driver for Python asyncio  
**Version:** 0.29.0

### pgvector
**Purpose:** PostgreSQL extension for vector embeddings  
**Usage:** Stores and queries semantic embeddings for code similarity  
**Version:** 0.2.3

### hiredis
**Purpose:** High-performance Redis protocol parser  
**Usage:** Accelerates Redis client operations  
**Version:** 2.2.3

### aioredis
**Purpose:** Asyncio Redis client  
**Version:** 2.0.1

### hvac
**Purpose:** HashiCorp Vault client (legacy, now using KMac)  
**Version:** 2.1.0

### python-multipart
**Purpose:** Multipart form data parser  
**Usage:** File upload handling in FastAPI  
**Version:** 0.0.6

---

## Port Reference

| Service | Port | Purpose |
|---------|------|---------|
| tron-api | 13000 | FastAPI REST + WebSocket |
| postgres | 13002 | PostgreSQL database |
| redis | 13003 | Redis cache/pub-sub |
| minio | 13004 | MinIO API |
| minio-console | 13005 | MinIO web console |
| pgbouncer | 13006 | Connection pooler |
| temporal | 13007 | Temporal gRPC |
| temporal-ui | 13008 | Temporal web UI |

---

## Cost Analysis

### Per-Audit Costs

| Component | Cost | Basis |
|-----------|------|-------|
| Claude 3 Haiku (primary) | ~$0.0015 | ~12,200 tokens @ $0.25/$1.25 per 1M |
| OpenAI GPT-4o (cross-validation) | ~$0.0005 | Optional, critical findings only |
| Infrastructure | ~$0.0001 | Amortized compute/storage |
| **Total** | **~$0.002** | Per audit run |

### Monthly Infrastructure

| Service | Monthly Cost (estimated) |
|---------|-------------------------|
| PostgreSQL (2GB) | $15-30 |
| Redis (1GB) | $10-20 |
| MinIO Storage | $5-10 |
| Compute (4 vCPU) | $50-100 |
| Bandwidth | $10-20 |
| **Total** | **$90-180** |

---

## Environment Variables

### Database
```bash
DB_HOST=postgres
DB_PORT=5432
DB_NAME=tron
DB_POOL_SIZE=10
DB_MAX_OVERFLOW=5
```

### Temporal
```bash
TEMPORAL_HOST=temporal:7233
TEMPORAL_ENABLED=true
TEMPORAL_TASK_QUEUE=tron-tasks
TEMPORAL_MAX_CONCURRENT_ACTIVITIES=10
```

### LLM
```bash
LLM_CIRCUIT_BREAKER_THRESHOLD=5
LLM_CIRCUIT_BREAKER_TIMEOUT=60
LLM_REQUEST_TIMEOUT=30
LLM_BULKHEAD_MAX_CONCURRENT=10
```

### Redis
```bash
REDIS_HOST=redis
REDIS_PORT=6379
REDIS_DB=0
REDIS_MAX_CONNECTIONS=50
REDIS_SOCKET_TIMEOUT=5
```

### KMac Vault
```bash
VAULT_BACKEND=kmac
KMAC_VAULT_URL=http://host.docker.internal:9999
KMAC_SECRET_PREFIX=tron:
KMAC_TOKEN_PATH=/vault-token
```

---

## Key Metrics

| Metric | Target | Current |
|--------|--------|---------|
| Audit Duration | <90s | ~60s |
| Findings Accuracy | >95% | 98%+ |
| False Positive Rate | <5% | ~2% |
| API Response Time | <100ms | ~50ms (p95) |
| Database Connections | <100 | ~25 avg |
| LLM Token Budget | <20K | ~12.2K avg |
| Cost per Audit | <$0.01 | ~$0.002 |

---

## Compliance & Standards

### Security Standards
- **SOC 2 Type II** - Audit logging, encryption, access controls
- **GDPR** - Data deletion, export, anonymization
- **HIPAA Ready** - PHI handling, encryption, audit trails
- **ISO 27001** - Information security management

### Code Quality Standards
- **OWASP Top 10** - Vulnerability coverage
- **CWE Top 25** - Common weakness enumeration
- **SANS Top 25** - Most dangerous software errors
- **PCI DSS** - Payment card security (future)

---

## Quick Commands

```bash
# Start all services
docker compose up -d

# Check service status
docker compose ps

# View API logs
docker compose logs -f tron-api --tail=50

# View worker logs
docker compose logs -f tron-worker --tail=50

# View Temporal UI
open http://localhost:13008

# Access API docs
open http://localhost:13000/docs

# Run health check
curl http://localhost:13000/health

# Create project
curl -X POST http://localhost:13000/api/projects \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name": "Test", "repo_url": "https://github.com/user/repo.git"}'

# Create audit
curl -X POST http://localhost:13000/api/audits \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"project_id": "uuid"}'

# Get audit status
curl http://localhost:13000/api/audits/{id} -H "X-API-Key: $API_KEY"

# Get findings
curl http://localhost:13000/api/audits/{id}/findings -H "X-API-Key: $API_KEY"
```

---

**For detailed usage and configuration, see:**
- Full Documentation: http://localhost:8080
- Architecture Docs: `docs/architecture/`
- Documentation blueprint (canonical map): `docs/BLUEPRINT.md` — archived week-by-week plan: `docs/archive/project-journals/IMPLEMENTATION_BLUEPRINT.md`
- Deployment Guide: `docs/website/index.html#deployment`
