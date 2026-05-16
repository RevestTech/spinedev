# Tron — AI Agents That Never Drift, Verify Every Finding, Always Complete the Task

**Version:** 5.4  
**Status:** Implementation Ready  
**Timeline:** 8-10 weeks (AI-assisted) — Phased Production Delivery  
**Ports:** All services run on **13000+ range** (see [PORT_REFERENCE.md](docs/operations/PORT_REFERENCE.md))

---

## The Problem

AI coding tools generate plausible-looking output that nobody can fully trust. Developers spend as much time reviewing AI suggestions as they would writing code themselves. The core issue: **AI agents drift off-task, hallucinate findings that don't exist, and deliver with false confidence.**

## What Tron Does Differently

Tron is an enterprise AI QA platform built on one principle: **verify everything, trust nothing.**

Unlike tools that hand you raw LLM output and hope for the best, Tron runs a **verification pipeline** (Temporal or in-process executor) before findings are persisted:

1. **Deterministic tools scan first** — Bandit, Semgrep (and dependency scanners in BuilderISO) establish ground truth where configured
2. **Schema-enforced output** — findings are validated with Pydantic (`FindingOutput`); hallucinated structure is rejected
3. **Execution verification (Layer 3)** — critical/high items are routed through the sandbox client when Docker or `TRON_SANDBOX_URL` is available; otherwise this step is skipped with a clear log line
4. **Multi-agent cross-validation** — `AuditManager` cross-checks severe findings across LLM providers when both keys are present
5. **Blueprint-scoped tasks** — each ISO runs under a `Blueprint` (file patterns, languages, check types); stricter static “NOT_IN_SCOPE” enforcement is roadmap polish
6. **Calibrated confidence** — tool-confirmed findings keep full confidence; LLM-only findings are capped unless sandbox verification upgrades them
7. **Prompt regression testing** — not yet automated as a nightly gate; tracked for a future release

The result: **verified findings you can act on, not AI guesses you have to double-check.**

---

## How It Works

```
Your Code
    │
    ▼
┌─────────────────────────────────┐
│  Blueprint Engine               │  Structured task scope
│  "Scan *.py for SQL injection"  │  NOT_IN_SCOPE: architecture, style
└───────────┬─────────────────────┘
            │
            ▼
┌─────────────────────────────────┐
│  Deterministic Tools            │  Bandit + Semgrep + Safety
│  Ground truth baseline          │  Results: 3 confirmed vulns
└───────────┬─────────────────────┘
            │
            ▼
┌─────────────────────────────────┐
│  ISO Agent (LLM Analysis)       │  Claude Sonnet 4 / GPT-4o
│  Finds what tools miss          │  Results: 5 findings (3 confirmed + 2 new)
└───────────┬─────────────────────┘
            │
            ▼
┌─────────────────────────────────┐
│  Schema Validation              │  File exists? Code matches?
│  Hallucination filter           │  1 finding rejected (code didn't match)
└───────────┬─────────────────────┘
            │
            ▼
┌─────────────────────────────────┐
│  Cross-Validation               │  Second agent independently reviews
│  Consensus check                │  4 findings confirmed, 0 disputed
└───────────┬─────────────────────┘
            │
            ▼
┌─────────────────────────────────┐
│  Execution Sandbox              │  Apply fixes, run tests
│  Does the fix actually work?    │  3 fixes pass, 1 needs iteration
└───────────┬─────────────────────┘
            │
            ▼
  Verified Findings (with calibrated confidence)
  Ready to act on
```

---

## Quick Start

```bash
# 1. Clone and configure
git clone <repo-url> && cd tron
cp .env.example .env  # Edit with your secrets

# 2. Start infrastructure (auto-starts with Docker)
docker compose up -d

# 3. Provision Vault secrets (first time only)
docker exec -e VAULT_ADDR=http://127.0.0.1:8200 -e VAULT_TOKEN=tron-dev-token \
  tron-vault vault kv put -mount=secret tron/db/password value="your-db-pass"

# 4. Build and start API
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build -d tron-api

# 5. Verify (note: port 13000)
curl http://localhost:13000/health
open http://localhost:13000/api/docs

# All services auto-start with Docker (restart: unless-stopped)
# See docs/operations/PORT_REFERENCE.md for full port mapping (13000-13080 range)
```

### Resume work / status

- **`docs/project/MASTER_PROPOSAL_TODO.md`** — canonical checklist vs the proposal; section **“Current snapshot (where we left off)”** summarizes the last agreed delivery state and pointers into code/tests.
- **`docs/REQUIREMENTS_TRACEABILITY.md`** — strict status vocabulary and evidence index for “Done”.
- **`AGENTS.md`** (repo root) — short agent + ops context for this repository.

---

## Architecture

### Core: 7-Layer Verification Pipeline

See [docs/architecture/ZERO_DRIFT_VERIFICATION_PIPELINE.md](./docs/architecture/ZERO_DRIFT_VERIFICATION_PIPELINE.md) for the complete specification.

### ISO Agents (Specialized AI Workers)

Each agent focuses on one domain with structured Blueprint contracts:

| Agent | Focus | Model | Deterministic Tools |
|-------|-------|-------|-------------------|
| SecurityISO | Vulnerabilities | Claude Sonnet 4 | Bandit, Semgrep, Safety |
| BuilderISO | Code generation | GPT-4o | Syntax check, test runner |
| QAISO | Code quality | Claude Sonnet 4 | Ruff, mypy, complexity |
| PerformanceISO | Optimization | GPT-4o | Profiler, benchmarks |

See [docs/architecture/AI_AGENT_ARCHITECTURE.md](./docs/architecture/AI_AGENT_ARCHITECTURE.md)

### Standards Hierarchy

Three-tier enforcement that adapts to your organization:

1. **Default** — Built-in best practices (OWASP Top 10, secure coding)
2. **Company** — Organization-wide policies (SOC 2, HIPAA, internal standards)
3. **Project** — Repository-specific requirements (your team's rules)

### Technology Stack

| Layer | Technology |
|-------|------------|
| API | Python 3.11+, FastAPI |
| Database | PostgreSQL 15+ (pgvector, ltree, pgcrypto) |
| Workflows | Temporal (durable, fault-tolerant) |
| Cache | Redis 7+ with Sentinel |
| Storage | MinIO (S3-compatible) |
| Secrets | HashiCorp Vault (auto-rotation) |
| Frontend | React 18, TypeScript, shadcn/ui |
| LLMs | Claude Sonnet 4, GPT-4o, Ollama (fallback) |
| Monitoring | Prometheus, Grafana, Loki, Tempo |

---

## Project Structure

```
tron/
├── README.md                                    ← You are here
│
├── docs/
│   ├── REQUIREMENTS_TRACEABILITY.md             ← Done/Partial/Deferred + verified evidence index
│   ├── project/
│   │   ├── MASTER_PROPOSAL_TODO.md              ← Living checklist vs PROPOSAL + “where we left off”
│   │   └── IMPLEMENTATION_BLUEPRINT.md          ← Build plan (historical / deep detail)
│   ├── architecture/                            ← WHAT to build
│   │   ├── ZERO_DRIFT_VERIFICATION_PIPELINE.md  ← 7-layer verification ⭐
│   │   ├── AI_AGENT_ARCHITECTURE.md             ← ISO agent system
│   │   ├── DATABASE_SCHEMA.md                   ← Database design
│   │   ├── DATABASE_GRAPH_DESIGN.md             ← Graph queries
│   │   └── WEBSOCKET_ARCHITECTURE.md            ← Real-time updates
│   │
│   ├── implementation/                          ← HOW to build
│   │   ├── COMPLETE_P0_P1_SOLUTIONS.md          ← Security, GDPR, DR
│   │   ├── TESTING_STRATEGY.md                  ← Test suite + golden tests
│   │   ├── COST_CONTROLS.md                     ← LLM cost protection
│   │   ├── BUSINESS_MODEL.md                    ← Pricing + go-to-market
│   │   ├── RISK_REGISTER.md                     ← Known risks + mitigations
│   │   └── ADMIN_UI_PHASED.md                   ← Admin interface phases
│   │
│   ├── operations/                              ← HOW to run
│   │   ├── PORT_REFERENCE.md                    ← Port map (13000+)
│   │   ├── RUNBOOKS.md                          ← 10 production runbooks
│   │   └── SLIS_SLOS.md                         ← Monitoring + SLOs
│   │
│   └── archive/                                 ← Historical (not for implementation)
│       └── legacy-sql/                          ← Pre-Alembic SQL (reference only)
│
├── tron/                                        ← APPLICATION CODE
│   ├── schemas/verification.py                  ← Pydantic models ⭐ (implemented)
│   ├── api/                                     ← FastAPI routes
│   │   ├── routes/                              ← Endpoint handlers
│   │   └── middleware/                           ← Auth, rate limiting
│   ├── agents/                                  ← ISO agents (SecurityISO, BuilderISO, etc.)
│   ├── workflows/                               ← Temporal workflow definitions
│   ├── domain/                                  ← Business logic
│   ├── infra/                                   ← Infrastructure clients
│   │   ├── db/                                  ← PostgreSQL + pgvector
│   │   ├── redis/                               ← Cache + queue
│   │   ├── minio/                               ← Object storage
│   │   ├── sandbox/                             ← Execution sandbox gRPC client
│   │   └── llm/                                 ← LLM providers + circuit breaker
│   ├── services/                                ← Application services
│   └── parsers/                                 ← Code parsers
│
├── tests/                                       ← Test suites
│   ├── unit/                                    ← Unit tests
│   ├── integration/                             ← Integration tests
│   └── golden_suite/                            ← Known vulnerability test cases
│
├── frontend/                                    ← Main React dashboard (Vite)
├── admin-ui/                                    ← Legacy admin SPA (optional)
├── alembic/                                     ← Database migrations (Alembic)
├── config/                                      ← Service configurations
├── docker/                                      ← Dockerfiles
├── scripts/                                     ← Dev utilities, backups, scan helpers
├── docker-compose.yml                           ← Infrastructure (18 services)
├── requirements.txt                             ← Python dependencies (66 packages)
└── .env.example                                 ← Environment template
```

---

## Implementation Plan

### Phase 1: Core Platform (Weeks 1-4) — Production Foundation

| Week | Focus | Deliverable |
|------|-------|-------------|
| 1-2 | Foundation | FastAPI, PostgreSQL, pgvector, auth, deterministic tool integration, Docker sandbox service |
| 3-4 | Security ISO + Verification | Production agent with Layers 1-3 (deterministic + schema validation + execution sandbox) |

**Phase 1 production gate:** SecurityISO detects OWASP Top 10 with 98%+ verified confidence, runs in <10 min, costs <$5/audit, all findings pass schema validation and deterministic confirmation.

### Phase 2: Full Verification Pipeline (Weeks 5-8)

- Cross-validation with agent isolation (Layer 4), blueprint task contracts (Layer 5)
- Builder ISO, QA ISO, fix workflows
- Confidence calibration system (Layer 6), golden test suite (200+ cases)
- Admin UI, monitoring dashboards, 1,000+ tests, 80% coverage

### Phase 3: Enterprise Hardening (Weeks 9-10)

- Full GDPR, encryption at rest + in transit, disaster recovery
- Kubernetes deployment manifests
- Prompt regression testing (Layer 7), calibration curve fitting
- 2,000+ tests, production load testing, security penetration testing

---

## Competitive Context

Tron sits at the intersection of three approaches that no single competitor combines:

| Capability | GitHub Copilot | Snyk | Qodo | Stripe Minions | Tron |
|------------|---------------|------|------|----------------|------|
| Deterministic-first verification | — | Partial | — | Internal | Yes |
| Multi-agent cross-validation | — | — | Yes | — | Yes |
| Confidence calibration | — | — | — | — | Yes |
| Standards hierarchy | — | — | — | — | Yes |
| Agent memory/learning | — | — | — | — | Yes |
| Execution sandbox verification | — | — | Partial | Yes | Yes |
| Blueprint task contracts | — | — | — | Yes | Yes |

---

## Honest Assessment

**What this is:** A comprehensive, independently-validated architecture (design quality: 9/10) with initial implementation artifacts (Pydantic schemas, Docker Compose, Nginx config). No production code yet.

**What it isn't:** A finished product. Production readiness requires building and validating all 7 verification layers.

**Key risks:**
- LLM API dependency (mitigated by Ollama fallback + cost controls)
- Timeline optimism (mitigated by phased approach with validation checkpoints)
- Customer validation needed (3-5 design partners before full build)

**What makes us confident:** The verification pipeline architecture is based on what Stripe Minions (1,300 PRs/week), Devin (67% merge rate), and Factory AI (#1 Terminal Bench) actually do in production — not theoretical patterns.

---

## Start Building

1. Read [IMPLEMENTATION_BLUEPRINT.md](docs/project/IMPLEMENTATION_BLUEPRINT.md) — the build plan with week-by-week deliverables
2. Read [docs/architecture/ZERO_DRIFT_VERIFICATION_PIPELINE.md](./docs/architecture/ZERO_DRIFT_VERIFICATION_PIPELINE.md) — the core verification pipeline spec
3. Read [docs/architecture/AI_AGENT_ARCHITECTURE.md](./docs/architecture/AI_AGENT_ARCHITECTURE.md) — how ISO agents work
4. `cp .env.example .env` — configure your environment
5. `docker-compose up -d` — start infrastructure
6. Begin Phase 1, Week 1: FastAPI foundation + PostgreSQL + deterministic tool integration
