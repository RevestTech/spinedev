# State of Tron — April 2026

## What This Document Is

An honest technical reference and status assessment of the Tron platform as it exists today. Written for internal use — no sugarcoating.

---

## What Tron Is Supposed To Be

Tron is an AI-powered code security and quality platform. It scans codebases using a multi-agent system, finds vulnerabilities, and reports them through a web dashboard. The architecture is built around 4 "ISO" (Isolated Specialized Oracle) agents that each focus on a domain — security, build config, performance, and QA — and cross-validate findings using different LLM providers to reduce hallucinations.

The vision: deterministic tools (Bandit, Semgrep, pip-audit) run first, then LLMs analyze with that context, then cross-validation catches false positives. A "zero-drift verification pipeline."

---

## Architecture Overview

### Stack

| Layer | Technology | Status |
|-------|-----------|--------|
| API | FastAPI 0.104 + Uvicorn | Working |
| Database | PostgreSQL 15 + PgBouncer | Working |
| Cache/Queue | Redis 7 | Working |
| Workflow Engine | Temporal 1.22 | Configured, partially used |
| Object Storage | MinIO (S3-compatible) | Running, TLS configured |
| AI/LLM | Anthropic (Claude Haiku) + OpenAI | Working, Haiku primary |
| Sandbox | gRPC container with Docker socket | Defined, not exercised |
| Observability | Prometheus + Grafana + Tempo + Loki + OTEL | Running, mostly empty |
| Frontend | React 19 + Vite 8 + Tailwind | Working, recently improved |
| Admin UI | React 18 + Zustand + Radix | Exists, not actively used |
| Reverse Proxy | Nginx 1.25 | Running, serves admin-ui |

### Services (18 total via Docker Compose)

Infrastructure: PostgreSQL, PgBouncer, Redis, MinIO, Temporal, Temporal UI, Backup
Application: tron-api (port 13000), tron-worker, tron-sandbox (gRPC :50051)
Observability: Prometheus, Grafana, Tempo, Loki, OTEL Collector, AlertManager
Proxy: Nginx (ports 80/443)

All data services bound to 127.0.0.1 except Nginx. Port range: 13000–13015.

### Agent System

Four ISO agents inherit from `BaseISO` (670 lines):

- **SecurityISO** (488 lines) — Runs Bandit + Semgrep before LLM. Maps 50+ Bandit test IDs to vulnerability types. Tool-confirmed findings get full confidence; LLM-only capped at 0.7.
- **BuilderISO** (451 lines) — Runs pip-audit + npm-audit. Targets Dockerfiles, CI configs, dependency manifests. Looks for running-as-root, unpinned images, secrets in layers, missing health checks.
- **PerformanceISO** (312 lines) — LLM-only, no deterministic tools. Looks for N+1 queries, blocking I/O, resource leaks, unbounded queries. All findings capped at 0.7 confidence.
- **QAISO** (451 lines) — Regex-based test file detection + LLM. Finds dead tests, missing assertions, flaky patterns. **Not registered in AuditExecutor — commented out as "Phase 3."**

The `AuditManager` (479 lines) orchestrates agents: creates Blueprints, dispatches all agents concurrently via `asyncio.gather()`, merges/deduplicates findings by SHA256 fingerprint, cross-validates critical/high findings using a different LLM provider.

### How a Scan Actually Works

1. User clicks "Scan" in the frontend → `POST /api/audits`
2. API creates an `AuditRun` record (status=queued)
3. Dispatched to BackgroundTasks (Temporal is available but fallback used)
4. `AuditExecutor.run()`:
   - Loads project metadata
   - `RepoScanner` does `git clone --depth 1` (or uses demo code if no repo_url)
   - Initializes SecurityISO + BuilderISO + PerformanceISO
   - `AuditManager.run_audit()` runs all agents in parallel
   - Findings deduplicated, cross-validated, persisted to DB
   - Progress published via Redis pub/sub
5. Frontend polls `GET /api/audits/{id}` every few seconds

### Data Flow

```
POST /api/audits
  → AuditRun(queued) in PostgreSQL
  → BackgroundTask spawns AuditExecutor
    → RepoScanner: git clone → {path: content} dict
    → AuditManager:
      → SecurityISO: Bandit + Semgrep → LLM analysis → FindingOutput[]
      → BuilderISO: pip-audit + npm-audit → LLM analysis → FindingOutput[]
      → PerformanceISO: LLM analysis → FindingOutput[]
      → Merge + Dedup (fingerprint-based)
      → Cross-validate critical/high (different LLM provider)
    → Persist findings to PostgreSQL
    → Update AuditRun(completed) with counts
    → Publish to Redis pub/sub
  → Frontend polls GET /api/audits/{id}
  → GET /api/audits/{id}/findings for details
```

---

## What's Working

### Actually functional, tested in production:

1. **Core scanning pipeline** — SecurityISO and BuilderISO reliably find real vulnerabilities. FCNow was scanned successfully: 1,658 files analyzed, real findings identified and acted on.

2. **Multi-batch file scanning** — Files split into chunks to stay within token limits. Security-critical files (configs, Dockerfiles, .env files) prioritized in early batches.

3. **Git repository scanning** — `RepoScanner` (500 lines) handles real repos: shallow clone, smart filtering (skips node_modules, binaries, lock files), 512KB per-file limit, 50MB total limit, 2000 file cap.

4. **The API** — FastAPI endpoints for projects CRUD, audit creation/listing, findings retrieval, cost tracking. Auth via API key, rate limiting via Redis.

5. **The dashboard (frontend/)** — Recently rebuilt. Overview shows project names, audit status, severity charts. Projects page has clickable cards. New ProjectDetail page shows scan history, stats, run controls. AuditDetail has WebSocket live events and severity breakdowns. Findings page has expandable cards with code snippets and suggested fixes.

6. **Docker Compose infrastructure** — 18 services start cleanly. PostgreSQL, Redis, MinIO, Temporal all healthy. Observability stack (Prometheus, Grafana, Loki, Tempo) is running.

7. **Cost tracking** — Every LLM call logged to `llm_usage` table with provider, model, tokens, cost. Daily/hourly aggregation views exist.

8. **Cross-validation** — Critical/high findings from one provider validated by a different provider. Confirmed findings get +0.15 confidence, disputed get -0.2.

---

## What's Not Working or Not Real

### Honest assessment of gaps:

1. **QAISO is not registered.** The agent code exists (451 lines) but is commented out in `AuditExecutor._build_agent_manager()` with a "TODO Phase 3" comment. Only 3 of 4 agents actually run.

2. **Temporal is configured but barely used.** The workflow definitions exist (`audit_workflow.py`, `fix_workflow.py`), activities are defined, but the actual dispatch path in `audits.py` falls through to `BackgroundTasks`. The Temporal worker runs but mostly idles.

3. **The Sandbox service is defined but not exercised.** `Dockerfile.sandbox`, gRPC service definition, client code — all exist. But no code path in the current scanning pipeline actually uses it. It's infrastructure waiting for a use case.

4. **PerformanceISO has no deterministic tools.** Security has Bandit + Semgrep, Builder has pip-audit + npm-audit. Performance is pure LLM with all findings capped at 0.7 confidence. This means performance findings are inherently less reliable.

5. **The observability stack is running but mostly empty.** Prometheus scrapes metrics, but many alert rules reference metrics that don't exist yet (`pg_stat_activity_count`, `redis_memory_*`). These alerts will silently never fire. Grafana dashboards may not have meaningful data.

6. **AlertManager has no real receivers.** Routes point to `localhost:9095/alerts` — no webhook handler exists. Alerts go nowhere.

7. **Backup shipping is incomplete.** `scripts/backup.sh` creates PostgreSQL backups but the MinIO upload code is marked TODO. Backups sit in the container and are lost on container deletion.

8. **The admin-ui (port 13080) is essentially abandoned.** It uses a completely different stack (React 18, Zustand, Radix UI, React Query, Socket.IO) from the active frontend (React 19, Vite 8, plain hooks). The admin-ui has mock data in its ProjectDetail page. The user-facing frontend at port 13001 is the real dashboard.

9. **Fix workflow exists but untested end-to-end.** `fix_workflow.py` defines a Temporal workflow for generating and validating fixes, but there's no UI or API endpoint to trigger it.

10. **No end-to-end tests against live infrastructure.** Test suite is extensive (80+ files) but heavily mocked. Integration tests exist but don't test the full pipeline (API → agents → LLM → database → WebSocket).

---

## Technical Debt & Known Issues

### Critical

- **Hardcoded dev secrets in .env file** — `POSTGRES_PASSWORD=tron_dev_password_temp`, `REDIS_PASSWORD=redis_dev_password_temp`, `MINIO_PASSWORD=minioadmin_temp`. The architecture mandates KMac Vault for secrets, but the .env file has the actual passwords. This violates the project's own security policy.

- **max_tokens was wrong until recently** — `ISOConfig.max_tokens` (32000) was being passed directly to the Anthropic API as the output token limit. Haiku's max is 4096. This was causing 400 errors from Anthropic. Fixed by hardcoding `max_tokens=4096` in all 4 agent files, but the config vs API-param confusion should be refactored.

- **429 rate limiting on concurrent scans** — When all 3 agents run simultaneously with multiple batches, later batches hit Anthropic's rate limits. No inter-batch delay or retry-after handling exists.

### High

- **Two frontends, one abandoned** — `admin-ui/` (port 13080, React 18 + Zustand) and `frontend/` (port 13001, React 19 + Vite 8) coexist. The admin-ui is served by Nginx but nobody uses it. Should be deleted or consolidated.

- **NODE_ENV=production breaks npm install** — The dev environment has `NODE_ENV=production` set, which causes `npm install` to skip devDependencies. Frontend builds fail silently. Workaround: `npm install --include=dev`.

- **No retry-after handling for LLM rate limits** — The LLM client has retry with exponential backoff, but doesn't parse `Retry-After` headers from 429 responses. It just backs off generically.

- **Model names hardcoded** — `claude-3-haiku-20240307` appears in multiple files. Should be a single config value.

### Medium

- **Tool confirmation has ±5 line tolerance** — Bandit/Semgrep report findings at slightly different line numbers than LLM. The 5-line window may be too loose for dense code or too tight for multi-line vulnerabilities.

- **Demo code fallback** — If a project has no `repo_url`, the scanner uses a hardcoded vulnerable Flask app. This is fine for testing but confusing if someone misconfigures a project.

- **Nginx security headers incomplete** — HSTS commented out, CSP is basic, TLS config commented out.

- **Circuit breaker not configurable** — 5-failure threshold, 60s timeout hardcoded. No fallback if both LLM providers fail simultaneously.

### Low

- **Dead imports and unused code** — Some test files import modules that have been refactored. Cleanup needed.

- **Documentation drift** — The extensive docs/ folder (20+ documents) describes the aspirational architecture more than the current state. The "8-week implementation blueprint" was written as a plan, not a record of what was built.

---

## Project Structure

```
Tron/
├── tron/                          # Python backend (core)
│   ├── agents/                    # ISO agent system (5 files, ~2,400 LOC)
│   │   ├── base.py                # BaseISO abstract class (670 lines)
│   │   ├── manager.py             # AuditManager orchestrator (479 lines)
│   │   ├── security_iso.py        # Security agent (488 lines)
│   │   ├── builder_iso.py         # Build config agent (451 lines)
│   │   ├── performance_iso.py     # Performance agent (312 lines)
│   │   ├── qa_iso.py              # QA agent (451 lines) — NOT REGISTERED
│   │   └── memory.py              # Agent memory interface
│   ├── api/                       # FastAPI application
│   │   ├── main.py                # App entry point (135 lines)
│   │   ├── config.py              # Settings from env (86 lines)
│   │   ├── routes/                # health, projects, audits, costs, gdpr, ws
│   │   └── middleware/            # auth, rate_limit, security, metrics
│   ├── services/                  # Business logic
│   │   ├── audit_executor.py      # Scan orchestration (510 lines)
│   │   └── repo_scanner.py        # Git clone + file collection (500 lines)
│   ├── workflows/                 # Temporal workflows (partially used)
│   │   ├── audit_workflow.py      # 5-phase audit pipeline
│   │   ├── fix_workflow.py        # Fix generation (not wired)
│   │   └── activities.py          # Activity definitions
│   ├── domain/models.py           # SQLAlchemy models (487 lines, 12 tables)
│   ├── schemas/verification.py    # Pydantic models (950+ lines)
│   ├── infra/                     # Infrastructure clients
│   │   ├── db/                    # SQLAlchemy async sessions
│   │   ├── redis/                 # Redis client + pub/sub
│   │   ├── llm/client.py          # Anthropic + OpenAI unified client (372 lines)
│   │   ├── minio/                 # S3 storage client
│   │   ├── sandbox/               # gRPC sandbox client (not used)
│   │   ├── secrets/               # KMac Vault client
│   │   ├── embeddings/            # Vector embeddings (not used)
│   │   └── observability/         # Logging, metrics, tracing
│   ├── parsers/                   # Code parsers (Python, JS, TS)
│   ├── prompts/                   # LLM prompt management
│   ├── memory/                    # Agent memory system
│   ├── realtime/                  # Socket.IO server
│   └── worker.py                  # Temporal worker entry point
│
├── frontend/                      # User-facing dashboard (port 13001)
│   └── src/
│       ├── pages/                 # 8 pages (Overview, Projects, ProjectDetail,
│       │                          #   Audits, AuditDetail, Findings, Costs, Settings)
│       ├── components/            # Card, Layout, StatusBadge, SeverityBadge
│       ├── hooks/usePolling.ts    # Data polling hook
│       ├── api.ts                 # API client
│       └── App.tsx                # Routes
│
├── admin-ui/                      # ABANDONED admin dashboard (port 13080)
│   └── src/                       # React 18 + Zustand + Radix (different stack)
│
├── docker/                        # Dockerfiles (api, worker, sandbox)
├── config/                        # Service configs (nginx, prometheus, grafana,
│                                  #   loki, tempo, otel, alertmanager, minio, temporal)
├── docs/archive/legacy-sql/       # Pre-Alembic SQL snapshots (reference); use alembic/ for changes
├── tests/                         # 80+ test files (unit, integration, golden, load)
├── docs/                          # 20+ architecture & implementation docs
├── scripts/                       # dev-start, backup, restore, vault-init, preflight
├── docker-compose.yml             # 18-service composition (774 lines)
├── docker-compose.dev.yml         # Dev overrides
├── docker-compose.prod.yml        # Production overrides
├── requirements.txt               # 73 Python packages
└── .env                           # Dev secrets (SHOULD be in Vault only)
```

---

## API Endpoints

| Method | Path | Description | Status |
|--------|------|-------------|--------|
| GET | /health | Liveness check | Working |
| GET | /ready | Readiness with dependency checks | Working |
| POST | /api/projects | Create project | Working |
| GET | /api/projects | List projects (paginated) | Working |
| GET | /api/projects/{id} | Get project | Working |
| PUT | /api/projects/{id} | Update project | Working |
| DELETE | /api/projects/{id} | Soft-delete project | Working |
| POST | /api/audits | Start new scan | Working |
| GET | /api/audits | List audits (filter by project, status) | Working |
| GET | /api/audits/{id} | Get audit status + summary | Working |
| GET | /api/audits/{id}/findings | List findings (filter, paginate) | Working |
| GET | /api/costs/dashboard | Cost tracking dashboard | Working |
| DELETE | /api/gdpr/data | GDPR data deletion | Defined |
| WS | /ws/audits/{id} | WebSocket live audit events | Working |

---

## Database Tables (12)

1. **projects** — name, repo_url, branch, soft-delete
2. **audit_runs** — status, progress, findings counts, timestamps
3. **findings** — fingerprint, rule_id, file+line, severity, code_snippet, suggested_fix
4. **llm_usage** — append-only cost ledger (provider, model, tokens, cost)
5. **llm_cost_hourly** — hourly aggregation
6. **llm_cost_daily** — daily aggregation by operation type
7. **project_cost_limits** — per-project budget (daily/monthly, warn/throttle thresholds)
8. **cost_events** — threshold crossing alerts
9. **code_files** — file metadata (path, hash, language, LOC)
10. **file_dependencies** — import graph edges
11. **finding_relationships** — finding-to-finding links
12. **standards** — compliance rule hierarchy (ltree)

---

## Dependencies

### Python (73 packages)

Core: FastAPI 0.104, Uvicorn 0.24, Pydantic 2.5
Database: SQLAlchemy 2.0, asyncpg 0.29, Alembic 1.13
Workflow: Temporalio 1.4
AI: OpenAI 1.3, Anthropic 0.7, TikToken 0.5
Storage: MinIO 7.2
Auth: PyJWT 2.8, passlib 1.7
Observability: prometheus-client 0.19, opentelemetry 1.21
Testing: pytest 7.4, locust 2.19

### Frontend (port 13001)

React 19.2, React Router 7.14, Recharts 3.8, Lucide React 1.8, Tailwind 4.2, Vite 8.0

### Admin UI (port 13080, abandoned)

React 18.2, Zustand 4.4, TanStack Query 5.13, Radix UI, Socket.IO Client 4.7, Tailwind 3.3

---

## What Needs to Happen Next

### If we're keeping Tron:

1. **Delete admin-ui/** — it's a different stack, has mock data, nobody uses it. The frontend/ at port 13001 is the real dashboard.

2. **Fix the secrets situation** — Either commit to KMac Vault (remove .env passwords) or accept .env for dev and document the boundary clearly.

3. **Register QAISO** — The agent is written. Uncomment it in `AuditExecutor` and test it.

4. **Add rate limit handling** — Parse `Retry-After` from 429 responses. Add inter-batch delays when running multiple agents. This is blocking reliable multi-project scanning.

5. **Wire up Temporal properly or remove it** — Right now Temporal runs idle while BackgroundTasks does the work. Either migrate the scan pipeline to Temporal workflows or stop running the Temporal services (saves resources).

6. **Add deterministic tools to PerformanceISO** — Currently pure LLM. Consider pylint performance checks, ESLint perf rules, or custom AST analysis.

7. **Fix the backup pipeline** — Complete the MinIO upload in `backup.sh`. Backups that aren't shipped offsite aren't backups.

8. **Clean up the observability stack** — Either wire up the missing metrics (postgres_exporter, redis_exporter) so alerts actually fire, or remove the alert rules that reference nonexistent metrics.

9. **Consolidate the max_tokens confusion** — `ISOConfig.max_tokens` means "file content budget" but was being passed as LLM output limit. Rename the field or split into two distinct configs.

10. **Add real integration tests** — The test suite mocks everything. Need at least one test path that hits real PostgreSQL + real LLM (even with a small test file).

---

## Honest Summary

Tron has a solid architecture on paper — the ISO agent pattern, deterministic-first analysis, cross-validation, and cost tracking are genuinely good ideas. The infrastructure is overbuilt for what's actually being used (18 Docker services for what amounts to an API + 3 agents + a database). The codebase is well-structured Python with proper async patterns, Pydantic validation, and decent separation of concerns.

The core scanning pipeline works. It found real vulnerabilities in FCNow and the fixes were valid. The frontend was recently improved and now shows useful information.

But there's a gap between the documented architecture and what's actually running. Temporal idles, the sandbox is unused, QAISO is commented out, the observability stack collects metrics nobody looks at, alerts route to nowhere, and there are two frontends for no reason. The documentation describes a 7-layer zero-drift verification pipeline but only about 3 of those layers are actually implemented.

The platform does one thing well: scan a Git repo with 3 LLM agents and show findings in a dashboard. Everything else is scaffolding for a more ambitious system that hasn't been built yet.
