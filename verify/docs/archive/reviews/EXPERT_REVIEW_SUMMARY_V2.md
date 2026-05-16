# Tron Proposal - Expert Review Summary (10 Agents)

**Review Date:** April 11, 2026  
**Document Reviewed:** `/Users/khashsarrafi/Projects/Tron/TRON_PROPOSAL.md`  
**Reviewers:** 10 expert agents across DevOps, Frontend, Security, FinOps, Data Engineering, Product, UX, SRE, Architecture, and Performance

---

## Executive Summary

All 10 experts agree the **Tron concept is strong** and addresses real problems (AI code quality inconsistency, runaway LLM costs, standards enforcement). However, the current proposal has **significant gaps between design intent and implementation reality**, particularly around:

- **Deployment configuration** (Docker Compose is internally contradictory)
- **Real-time architecture** (WebSocket implementation is incoherent)
- **Security boundaries** (Docker socket, WebSocket auth, cache privacy)
- **Performance math** (PostgreSQL connections don't add up)
- **Observability** (claimed tools not deployed, no SLOs)
- **Scope for single user/company** (Admin UI may be over-engineered)

**Critical Finding:** All reviewers noted the document version is inconsistent (header says "1.0 Draft", footer says "2.0 Final", no "2.1" label exists).

**Overall Ratings:**
- DevOps: 5.5/10
- Frontend: 6.5/10
- Security: C+ (dangerous gaps)
- FinOps: 6/10 (concept), 4/10 (quantitative credibility)
- Data Engineering: 6/10
- Product: 6.5/10
- UX: 6.5/10
- SRE: 5/10
- Software Architecture: 7/10 (vision), 5.5/10 (implementation-ready)
- Performance: 6/10

---

## Cross-Cutting Critical Issues

### 1. Docker Compose Configuration is Broken

**All technical reviewers flagged this:**

- `deploy.replicas: 3` on `tron-worker` **does not work** in standard Docker Compose (Swarm-only)
- PostgreSQL `max_connections: 50` vs. advertised pools:
  - API: 20+10 per process
  - 3 Temporal workers
  - Temporal server itself
  - **Total needed: 120+ connections** vs. 50 available → **immediate failure**
- Admin UI `VITE_*` environment variables are **build-time only**; runtime Docker env vars do nothing
- `VITE_API_URL=http://tron-api:8000` is **not browser-resolvable** (internal Docker network name)

**Fix Required:** Complete rewrite of connection budgeting, remove or qualify `deploy.replicas`, fix frontend env var strategy.

---

### 2. WebSocket / Socket.IO Implementation is Incoherent

**6 of 10 reviewers called this out explicitly:**

The proposal mixes three contradictory patterns:
1. `@app.websocket("/ws/admin")` (FastAPI raw WebSocket)
2. `socketio.AsyncServer` with `sio.emit()`
3. Client code using `io('ws://localhost:8000/ws/admin')` (Socket.IO client)

**Problems:**
- Socket.IO is **not raw WebSocket**; requires its own handshake and path (usually `/socket.io/`)
- No authentication on WebSocket connections shown
- Horizontal scaling with multiple API instances needs **Redis adapter + sticky sessions** (not mentioned)
- Mixing with Temporal workflows risks **duplicate/missed events** without idempotent event IDs

**Fix Required:** Pick **one** technology stack (FastAPI + python-socketio with ASGI mount), document auth, scaling, and event delivery semantics.

---

### 3. Security Architecture Has Dangerous Gaps

**Security Engineer: "C+ rating - promising checklist, dangerous gaps"**

#### Critical Issues:

1. **Docker Socket on API/Worker** (`/var/run/docker.sock` mounted):
   - Grants **effective root on host** if API/worker compromised
   - ADR-002 calls this "Docker-in-Docker" but it's actually **Docker-outside-of-Docker** (different threat model)
   - No mention of rootless Docker, gVisor, Sysbox, or dedicated sandbox hosts

2. **WebSocket has No Authentication**:
   - Sample code shows `accept()` then stream events
   - Full surveillance of workflows, costs, sensitive metadata for **anyone who can reach the port**
   - `ws://` in examples (cleartext) vs. production need for `wss://`

3. **LLM Cache is a High-Sensitivity Datastore**:
   - Prompts often contain **source code, credentials, PII**
   - No encryption-at-rest for Redis/MinIO cache
   - No TTL policy per sensitivity
   - No purge on secret rotation

4. **Admin Authentication Undefined**:
   - ADR-006 says "API keys for v1"
   - Browser SPAs need **cookies + CSRF** or **OIDC**, not Bearer tokens in localStorage
   - "Separate admin API keys" is underspecified

5. **Audit Logs Not Actually Immutable**:
   - Stored in PostgreSQL without WORM, tamper-evident chaining, or separate log account
   - DBA/compromised app can UPDATE/DELETE

**Fix Required:** Sandbox isolation redesign, WebSocket auth, LLM cache encryption, OIDC for admin humans, audit log immutability.

---

### 4. Cost Model Claims are Optimistic and Unverifiable

**FinOps Engineer: "60-80% savings is stretch goal, not default"**

#### Issues:

1. **Pricing Table:**
   - No date, region, or tier (Batch vs standard)
   - "AUDIT = $0" conflicts with narrative about Compliance ISOs using LLMs

2. **Cache Hit Rate Claims:**
   - "67% hit rate" implies 67% of all LLM spend disappears
   - But BUILD (largest bucket) is "mostly not cached"
   - Cache keys are `sha256(prompt|model)` → **exact string** identity
   - Real repos change constantly → **churned cache keys**
   - **Realistic expectation: single-digit to low-teens percent** for interactive BUILD-heavy work

3. **Hidden Costs:**
   - Ollama "local fallback" is **not free** (GPU/CPU, RAM, power, human rework time)
   - Platform TCO: Temporal, Postgres, Redis, MinIO, worker replicas, Docker pools, observability
   - Retry amplification: PLAN → BUILD → AUDIT → FIX loops multiply calls

4. **Dashboard Gaps:**
   - No forecasting, waste metrics, or provider invoice reconciliation

**Fix Required:** Source pricing with dates, align cache scope with workload reality, show platform TCO, add "cost per successful quality gate pass" metrics.

---

### 5. Database Design Needs Hardening

**Data Engineer: "Connection math is the most likely first breakage"**

#### Critical Issues:

1. **Connection Pool Math:**
   - Single Postgres `max_connections=50`
   - API: 20+10 per process (if 4 Uvicorn workers = 120)
   - 3 Temporal workers
   - Temporal server/history
   - **Total can approach 150+ vs. 50** → **connection refused**

2. **Schema Issues:**
   - `ProjectCostLimit` with `daily_spent_usd`/`monthly_spent_usd` on same row is **update-heavy under concurrency**
   - `LLMUsage` at per-call granularity will grow quickly; no partitioning, archival, or aggregation tables
   - No indexes specified
   - Standards content (large YAML) vs. hashes unclear

3. **Scaling Problems:**
   - No time-based partitioning for LLMUsage/findings
   - MinIO with no lifecycle policy → unbounded disk growth
   - Dashboard "real-time" queries can create sustained read load

**Fix Required:** PgBouncer or explicit per-service connection budgets, partitioning strategy, indexes, aggregation tables for dashboards.

---

### 6. Admin UI Scope vs. Single User/Company Use Case

**Product Manager: "6.5/10 - ambitious and somewhat internally duplicative"**

#### Concerns:

1. **Overlap with Existing Tools:**
   - Workflows page vs. **Temporal Web UI** (already at port 8081)
   - System monitoring vs. **Grafana** (mentioned in stack)
   - Cost monitoring vs. **provider dashboards**

2. **Six Dashboard Pages for One User:**
   - Main Dashboard
   - Projects
   - Workflows
   - System
   - Costs
   - Settings
   - **Is this over-engineering for single user/company?**

3. **Feature Prioritization:**
   - Real-time WebSocket for one user is **complexity for marginal gain**
   - Customizable widgets without usage proof
   - Six product commitments each requiring APIs, auth, real-time channels

**UX Designer adds:** "6.5/10 - overlapping concerns across Main/Workflows/System/Costs"

**Recommendation:** Phase 1 should be **Projects + Findings + Costs** (core value), defer or slim System health (link to Grafana), Workflow detail (link to Temporal UI), customizable widgets.

---

### 7. Observability Stack Not Actually Deployed

**SRE: "5/10 - observability backends are not in deployment sketch"**

#### Gaps:

1. **Claimed but Not Deployed:**
   - Prometheus (not in docker-compose)
   - Grafana (not in docker-compose)
   - OpenTelemetry collector (not in docker-compose)
   - Log aggregation (Loki/ELK) (not mentioned)

2. **No SLIs/SLOs Defined:**
   - "Success Metrics" are product KPIs, not service SLIs
   - No targets for API availability, latency percentiles, workflow success rate
   - No error budgets

3. **Missing:**
   - Alerting rules and on-call model
   - Synthetic/black-box monitoring
   - Backup/restore automation and testing
   - Runbooks

**Fix Required:** Add Prometheus, Alertmanager, Grafana, OTel collector to compose OR document hosted alternative; define SLOs before building more UI.

---

### 8. Real-Time Architecture Lacks Event Pipeline

**Software Architect: "7/10 vision, 5.5/10 implementation-ready"**

#### Problems:

1. **Temporal + Live UI Integration:**
   - Pushing "workflow progress" from **activities directly** to Socket.IO couples **durable workers** to **ephemeral connection state**
   - Retries, worker restarts, multi-replica workers → **duplicate or missed events**
   - No idempotent event IDs, at-least-once handling, or single writer model

2. **Consistency Model Undefined:**
   - Multiple TTLs (metrics 5s, projects 30s, standards 5m, audits 1m)
   - No rule for **read-your-writes** after mutations
   - "Duplicate paths for truth": WebSocket + Redis cache + Prometheus

3. **GraphQL (future):**
   - Adds **third API style** (REST + WS + GraphQL) → client complexity

**Fix Required:** Define event pipeline: workflow → append-only domain_events → broadcaster → Socket.IO. Workers stay dumb publishers.

---

### 9. Performance Bottlenecks Identified

**Performance Engineer: "6/10 - several numbers are placeholders"**

#### First to Break Under Load:

1. **PostgreSQL connections** (immediate)
2. **Docker sandbox pool (10)** when audits parallelize
3. **LLM HTTP client (100)** and provider rate limits
4. **Single Redis** (CPU single-threaded, 512MB cap)
5. **WebSocket broadcast** on one API instance

#### Missing Optimizations:

- PgBouncer for connection pooling
- Indexes on hot paths
- Cache stampede protection
- Temporal activity timeouts and concurrency limits
- Separate "sandbox-heavy" vs "metadata" task queues

**Fix Required:** Connection budget table, load testing strategy, pool sizing with justification.

---

### 10. Frontend Architecture Needs Boundaries

**Frontend Engineer: "6.5/10 - strong stack, weak on coherent data/real-time"**

#### Issues:

1. **State Management:**
   - Zustand + React Query + WebSocket → risk of **triple sources of truth**
   - No rules for where workflow/metrics live after WS push

2. **Performance:**
   - Simultaneous "1-5s auto-refresh" + WebSocket → double renders
   - Recharts + live data → frequent SVG reconciliation
   - No mention of downsampling, pause when tab hidden, or disconnecting WS on inactive routes

3. **Missing:**
   - SPA authentication strategy (session cookies vs. Bearer)
   - Accessibility as engineering process (live regions, keyboard flows, focus management)
   - Error boundaries, offline/reconnect messaging, empty/loading states
   - Component/E2E testing (Playwright/Cypress)

**Fix Required:** Explicit rules for React Query vs Zustand vs WebSocket merges; auth strategy; a11y testing; chart/update performance plan.

---

## What's Better (vs Earlier Versions)

Multiple reviewers noted improvements:

1. **ADR Set (12 items)** improves traceability
2. **Healthchecks** on core datastores
3. **Cost management** (budgets, tiers, caching) addresses runaway spend
4. **API key model** with scopes, rate limits, expiry
5. **Docker sandbox** security parameters (no network, read-only, resource limits)
6. **Admin visibility** for workflows, costs, projects

---

## Recommendations by Priority

### P0 (Blocking - Fix Before Implementation)

1. **Fix PostgreSQL connection math**
   - Add PgBouncer OR
   - Separate DBs for Temporal vs app OR
   - Explicit per-service connection budgets aligned with `max_connections`

2. **Fix Docker Compose worker replicas**
   - Remove `deploy.replicas: 3` OR
   - Document `docker compose up --scale tron-worker=3` OR
   - Use Swarm mode explicitly

3. **Fix WebSocket/Socket.IO confusion**
   - Pick **one** stack (python-socketio with ASGI mount)
   - Document auth, path, and horizontal scaling (Redis adapter)

4. **Fix Admin UI environment variables**
   - Use runtime config.json OR envsubst in Nginx OR relative URLs
   - Fix `tron-api` internal name not resolvable by browser

5. **Fix document versioning**
   - Align header/footer/narrative to one version (2.1 or correct)

---

### P1 (High Priority - Before Production)

6. **Security hardening:**
   - Remove Docker socket OR document rootless Docker/gVisor/dedicated hosts
   - Add WebSocket authentication (signed short-lived tokens)
   - Encrypt LLM cache at rest
   - Define admin authentication (OIDC for humans)
   - Implement tamper-evident audit logs (WORM storage or hash-chaining)

7. **Define event pipeline for real-time:**
   - Workflow → domain_events table → broadcaster → Socket.IO
   - Idempotent event IDs, at-least-once handling

8. **Database schema:**
   - Add indexes (project_id, created_at, status, etc.)
   - Cost tracking as ledger + aggregation tables (not denormalized counters)
   - Partitioning strategy for LLMUsage and findings

9. **Deploy observability stack:**
   - Add Prometheus, Alertmanager, Grafana, OTel collector to compose
   - OR document hosted alternative explicitly

10. **Define SLIs/SLOs:**
    - API availability, latency p95, workflow success rate
    - Error budgets tied to release decisions

---

### P2 (Important - Before Scale)

11. **Cost model:**
    - Source pricing with dates
    - Realistic cache hit rate (10-20% for interactive work, not 60-80%)
    - Show platform TCO (not just LLM costs)
    - Add forecasting and waste metrics to dashboard

12. **Admin UI scope:**
    - Phase 1: Projects + Findings + Costs only
    - Defer: System monitoring (link to Grafana), Workflow detail (link to Temporal UI)
    - Make WebSocket optional (start with REST + polling)

13. **Performance:**
    - Load test connection pool saturation, sandbox pool, WebSocket fan-out
    - Document pool sizes with justification
    - Add cache stampede protection

14. **Frontend:**
    - Define React Query vs Zustand vs WebSocket merge rules
    - Add a11y testing to CI
    - Document auth strategy (cookies vs Bearer)

---

### P3 (Nice to Have - Future)

15. **Backup/restore:**
    - Automated Postgres PITR
    - MinIO replication/versioning
    - Documented RPO/RTO

16. **Alerting:**
    - Versioned alert rules for Alertmanager
    - On-call rotations and runbooks

17. **Semantic LLM cache:**
    - Embedding-based near-duplicate detection
    - OR provider-native prompt caching

18. **GraphQL:**
    - If added, define migration boundary and BFF strategy

---

## Summary by Expert

### DevOps (5.5/10)
"Compose should not be labeled 'complete production-ready' without fixing replica semantics, browser-safe admin URLs, realtime multi-instance strategy, Temporal readiness, Docker socket risk, and actually wiring metrics/logs/traces."

### Frontend (6.5/10)
"Strong stack choices, weaker on coherent data/real-time architecture, internal consistency of WebSocket examples, information architecture overlap, and accessibility/compliance as engineering process."

### Security (C+)
"Promising checklist, dangerous gaps in execution plane. Docker socket + warm pool + LLM cache + unauthenticated WebSocket + 'immutable logs' in Postgres combine into high-impact story if exposed beyond localhost."

### FinOps (6/10 concept, 4/10 quantitative)
"Framework is sound for governance. Headline savings (60-80%) need workload-specific evidence and engineering design; without that, they read as marketing-grade, not FinOps-grade."

### Data Engineering (6/10)
"Clear Postgres vs MinIO split. Connection math vs max_connections is not reconciled; cost/usage modeling mixes denormalized counters with append-only facts without concurrency-safe aggregation."

### Product (6.5/10)
"Ambitious and internally duplicative (Temporal UI + Grafana + Admin). Cost management and project/findings strengthen story; six fully featured dashboards for single-tenant is more scope than value."

### UX (6.5/10)
"Strong on high-level buckets, weak on overlapping concerns, underspecified visualization semantics, high default cognitive load from live updates, missing cross-project triage."

### SRE (5/10)
"Solid baseline awareness. Observability backends not in deployment, SLOs absent, alerting vague, WebSocket needs scalability story, single-node dependencies unchecked."

### Software Architect (7/10 vision, 5.5/10 implementation)
"Better as product architecture, more complex as systems architecture. WebSocket/Temporal integration, compose accuracy, multi-layer caching consistency, admin auth need hardening before buildable."

### Performance (6/10)
"Sensible building blocks but several numbers are placeholders. Postgres connection accounting contradicts compose in way that fails early. Pre-warmed Docker pools not harmonized with singleton bottleneck."

---

## Action Items for User

1. **Acknowledge version confusion** - Align document labels
2. **Fix P0 blockers** - Connection math, Docker compose, WebSocket stack, admin env vars
3. **Review security recommendations** - Especially Docker socket and WebSocket auth
4. **Revise cost claims** - Lower cache hit rate expectations, add platform TCO
5. **Re-scope Admin UI** - Consider phased approach (core features first)
6. **Add observability to deployment** - Or document hosted alternative
7. **Define SLOs** before building more features

---

**Next Steps:** Would you like me to:
1. Create a **P0 Blocker Fix Plan** with specific code/config changes?
2. Generate a **revised docker-compose.yml** that actually works?
3. Design a **coherent WebSocket + Temporal event pipeline**?
4. Create a **connection budget spreadsheet** for all services?
5. Draft a **revised Phase 1 scope** for Admin UI?

All 10 experts agree: **The vision is solid, but the devil is in the details that need fixing.**
