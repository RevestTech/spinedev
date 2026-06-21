# Tron — AI Agents That Never Drift, Verify Every Finding, Always Complete the Task

**Version:** 5.4  
**Status:** Implementation Ready  
**Timeline:** 8-10 weeks (AI-assisted) — Phased Production Delivery  
**Ports:** All services run on **13000+ range** (see [PORT_REFERENCE.md](docs/operations/PORT_REFERENCE.md))

**Delivered scope:** **[Documentation blueprint](docs/BLUEPRINT.md)** · [BRD.md](docs/project/BRD.md) · [TRD.md](docs/project/TRD.md) · [REQUIREMENTS_TRACEABILITY.md](docs/project/REQUIREMENTS_TRACEABILITY.md) · **Open backlog vs proposal:** [MASTER_PROPOSAL_TODO.md](docs/project/MASTER_PROPOSAL_TODO.md) · **Hardening / ops** (TLS, CORS prod, sandbox options, etc.): [HARDENING_REVIEW_TODO.md](docs/project/HARDENING_REVIEW_TODO.md).

**Recently landed (April 2026):** real Layer 5 NOT_IN_SCOPE enforcement · Layer 7 prompt-regression CI gate · Platt-scaled Layer 6 calibration with `sklearn` (banded fallback otherwise) · pre-PR diff-mode audits via `POST /api/audits/diff` plus a sample [GitHub Action](docs/integrations/github-action-pr-gate.yml) · outbound audit webhooks (HMAC-signed, JSON Schema published at `/api/integrations/audit-webhook/schema`) · per-audit cost ledger surfaced in admin UI · ESLint+plugin-security baseline for JS/TS · sandbox seccomp profile + client wiring (**mount `config/sandbox/seccomp.json` into `tron-sandbox` at `/etc/tron/sandbox/seccomp.json` for compose defaults to pick it up**) · API-key audit log (background-task writes, bounded queue) · MinIO SARIF blob archival · synthetic-CVE benchmark harness with Snyk adapter · observability E2E verification script (`make verify-observability`) · horizontal-scaling docs at [docs/operations/SCALING.md](docs/operations/SCALING.md).

---

## The Problem

AI coding tools generate plausible-looking output that nobody can fully trust. Developers spend as much time reviewing AI suggestions as they would writing code themselves. The core issue: **AI agents drift off-task, hallucinate findings that don't exist, and deliver with false confidence.**

## What Tron Does Differently

Tron is an enterprise AI QA platform built on one principle: **verify everything, trust nothing.**

Unlike tools that hand you raw LLM output and hope for the best, Tron runs a
**verification pipeline** (Temporal or in-process executor) before findings
are persisted. The pipeline is **layered, with several layers gated on
configuration** — the README is honest about which is which:

1. **Deterministic tools scan first** — Bandit + Semgrep + Safety on Python and ESLint+plugin-security on JS/TS (SecurityISO), Ruff on Python with optional mypy (QAISO), OSV / advisory keyword scan on dependencies (BuilderISO). Compliance and Documentation ISOs remain LLM-only.
2. **Schema-enforced output** — findings are validated with Pydantic (`FindingOutput`); hallucinated structure is rejected. *Always on.*
3. **Execution verification (Layer 3)** — critical/high items are routed through the sandbox client **when Docker or `TRON_SANDBOX_URL` is available**; otherwise this step is skipped with a clear log line. Ephemeral sandbox containers use **`sandbox_client`** hardening (caps, read-only rootfs, network isolation). **Custom seccomp** (**`config/sandbox/seccomp.json`**) applies when that file is visible inside the **`tron-sandbox`** container at **`TRON_SANDBOX_SECCOMP`** (default **`/etc/tron/sandbox/seccomp.json`**); the stock **`docker-compose.yml`** omits that bind mount, so compose defaults fall back to Docker’s built-in seccomp until you mount it — details in **`docs/security/SANDBOX_THREAT_MODEL.md`**.
4. **Multi-agent cross-validation** — `AuditManager` cross-checks severe findings across LLM providers **when both Anthropic and OpenAI keys are present**. Single-key deployments don't get this layer.
5. **Blueprint-scoped tasks** — each ISO runs under a `Blueprint` (file patterns, check types) that shapes prompts AND statically enforces scope: a post-process filter in `AuditManager` drops findings whose file path or vulnerability type violates the issuing Blueprint's declared scope.
6. **Confidence cap + Platt calibration when corpus available** — schema enforces a 0.7 cap on LLM-only findings (lifted by deterministic confirmation or sandbox repro). The calibration engine fits a logistic Platt mapping over labeled outcomes when N≥500 and scikit-learn is available; falls back to per-band TP rate otherwise. Operators can inspect the active mode at `GET /api/admin/calibration/status`.
7. **Prompt regression testing** — `tests/golden_suite/` holds the labeled cases; `.github/workflows/prompt-regression.yml` runs them on a daily cron and on every PR touching `tron/agents/**` or `tron/schemas/**`.
8. **Parallel ISO swarm** — every registered specialist agent (security, builder, QA, performance, compliance, documentation) runs **concurrently** under `AuditManager`; results are merged and deduplicated, then critical/high items can be cross-validated across providers and Layer 3-verified where sandbox is configured. This is orchestrated breadth with a supervisor merge — not a single chat reviewer.
9. **Layered assurance for dependencies and hostile code** — Tron does **not** certify "no backdoor anywhere." It raises the bar with **layers**: OSV-backed dependency checks and advisory keyword surfacing (`ThreatIntelService` → audit-run alerts via BuilderISO), deterministic scanners, SecurityISO trained to flag insider-style risks when visible in source (obfuscation, covert egress, persistence), optional sandbox verification for severe findings. Novel malware without advisory footprint or purely runtime behavior still needs human judgment and prod controls.

The result: **verified findings with explicit provenance** (which tools confirmed, whether the sandbox reproduced, what the calibration band was). Not "AI guesses you have to double-check," and not "magic perfect answers" either — every finding tells you exactly which layers vouched for it.

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

- **`docs/AGENT_NAV.md`** — AI-assisted work: task → minimal docs (save tokens).
- **`docs/README.md`** — folder tree for **`docs/`** and suggested reading order.
- **`docs/BLUEPRINT.md`** — canonical map of governance, architecture, operations, security, reference, archives, and CI workflows.
- **`docs/project/BRD.md`** — business requirements; what shipped vs **`docs/archive/PROPOSAL.md`**.
- **`docs/project/TRD.md`** — technical requirements and module/route pointers.
- **`docs/project/MASTER_PROPOSAL_TODO.md`** — **remaining open backlog** vs proposal (empty while proposal-aligned items are cleared).
- **`docs/project/REQUIREMENTS_TRACEABILITY.md`** — Done / Partial / Deferred vocabulary and verified-deliveries evidence table.
- **`AGENTS.md`** (repo root) — short agent + ops context for this repository.

---

## Architecture

### Core: 7-Layer Verification Pipeline

See [docs/architecture/ZERO_DRIFT_VERIFICATION_PIPELINE.md](./docs/architecture/ZERO_DRIFT_VERIFICATION_PIPELINE.md) for the complete specification.

### ISO Agents (Specialized AI Workers)

Each agent focuses on one domain with structured Blueprint contracts. Six
specialists run in parallel under `AuditManager`; results are merged and
deduped, then critical/high items are cross-validated when both Anthropic
and OpenAI keys are present, and Layer 3 sandbox-verified when
`TRON_SANDBOX_URL` is configured.

| Agent | Focus | Default Model | Deterministic Pre-Pass |
|-------|-------|--------------|------------------------|
| SecurityISO | Vulnerabilities | Claude Sonnet 4 | Bandit + Semgrep on Python; Safety on Python deps (`requirements*.txt`); ESLint+plugin-security on JS/TS. |
| BuilderISO | Dockerfiles, CI/CD, deps | GPT-4o | OSV-backed dependency check + advisory keyword surfacing via `ThreatIntelService`. |
| QAISO | Test coverage / quality | Claude Sonnet 4 | Ruff lint pass on Python files; mypy opt-in via `Blueprint.tools_required = ["mypy"]`. Test-file metadata (function counts, skip decorators, pytest config detection). |
| PerformanceISO | Optimization | GPT-4o | LLM-only — static profiling isn't practical. Findings are confidence-capped at 0.7. |
| ComplianceISO | SOC 2 / ISO 27001 / HIPAA reference | Claude Sonnet 4 | LLM-only against built-in reference packs (not certified — see ADR-002). Confidence capped at 0.65. |
| DocumentationISO | API/docs drift | Claude Sonnet 4 | LLM-only. |

See [docs/architecture/AI_AGENT_ARCHITECTURE.md](./docs/architecture/AI_AGENT_ARCHITECTURE.md)

### Standards Hierarchy

Three-tier enforcement that adapts to your organization:

1. **Default** — Built-in best practices (OWASP Top 10, secure coding)
2. **Company** — Organization-wide policies (SOC 2, HIPAA, internal standards)
3. **Project** — Repository-specific requirements (your team's rules)

### Technology Stack

| Layer | Technology | Notes |
|-------|------------|-------|
| API | Python 3.11+, FastAPI | |
| Database | PostgreSQL 15+ (pgvector, ltree, pgcrypto) | Source of truth for projects, audits, findings, ledger. |
| Workflows | Temporal | Durable PLAN/BUILD/AUDIT/EVOLVE/FIX workflows, fault-tolerant retries, activity-level idempotency. |
| Cache / queue | Redis 7+ | Plain Redis client (no Sentinel/HA wired today; managed-Redis recommended for prod). |
| Object storage | MinIO (S3-compatible) | Best-effort SARIF blob archival and artifact paths (`tron/infra/minio/`); optional depending on deployment. |
| Secrets | HashiCorp Vault / KMac | Read at runtime via `tron.infra.secrets`; **rotation policies are defined, automatic rotation against the vault backend is not yet implemented** (see `tron/infra/secrets/rotation.py`). |
| Frontend | React 18, TypeScript, shadcn/ui | `frontend/` is the active SPA; `admin-ui/` is a legacy second SPA scheduled for removal. |
| LLMs | Anthropic (Claude family), OpenAI (GPT-4 family), Ollama | Cross-validation requires both Anthropic and OpenAI keys; without them, severe LLM-only findings stay capped at 0.7 confidence. |
| Monitoring | Prometheus, Grafana, Loki, Tempo, Alertmanager | Instrumentation is wired in code; the stack is defined in `docker-compose.yml` and is opt-in (some teams run only the core services). Slack alert receiver is wired (`tron/api/routes/alerts.py`). |

---

## Project Structure

```
tron/
├── README.md                                    ← You are here
│
├── docs/
│   ├── AGENT_NAV.md                         ← AI: task-based doc routing (read first)
│   ├── README.md                             ← docs/ tree + human reading order
│   ├── BLUEPRINT.md                           ← Canonical documentation index ⭐
│   ├── project/                               ← BRD, TRD, REQUIREMENTS_TRACEABILITY, MASTER todo, HARDENING, ADRs
│   ├── architecture/
│   ├── implementation/
│   ├── operations/                            ← Ports, scaling, runbooks, HOW_TO_RUN_AUDIT, SCAN_LOCAL_FOLDER
│   ├── security/
│   ├── reference/                           ← API_REFERENCE, TOOLS_REFERENCE, QUICK_START, TROUBLESHOOTING
│   ├── guides/sandbox/                       ← Sandbox client + integration guides
│   ├── integrations/                         ← Sample GitHub Action YAML + README
│   ├── website/                              ← Static documentation site
│   └── archive/                              ← PROPOSAL, journals, audit-reports HTML, reviews, legacy-sql
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

## Scope & honesty

**Source of truth for what shipped:** **`docs/project/BRD.md`**, **`docs/project/TRD.md`**, **`docs/project/REQUIREMENTS_TRACEABILITY.md`**, and **`docs/project/MASTER_PROPOSAL_TODO.md`**. Narrative copy in this README can fall behind; when in doubt, follow those files.

**Operational security and production readiness** (TLS, CORS prod, Grafana proof, sandbox hardening follow-ups): **`docs/project/HARDENING_REVIEW_TODO.md`**.

**Historical / journal markdown** (session notes, dated assessments, phased build plans): **`docs/archive/project-journals/`** — indexed in that folder’s **`README.md`**; not used to judge current delivery.

---

## Start here (contributors)

1. Read **[`docs/AGENT_NAV.md`](docs/AGENT_NAV.md)** — pick the minimal doc set for your task.
2. Read **[`docs/BLUEPRINT.md`](docs/BLUEPRINT.md)** — only as a TOC if you need paths (don’t load every linked file).
3. Read [`docs/architecture/ZERO_DRIFT_VERIFICATION_PIPELINE.md`](./docs/architecture/ZERO_DRIFT_VERIFICATION_PIPELINE.md) — core verification pipeline spec.
4. Read [`docs/project/TRD.md`](./docs/project/TRD.md) — modules and runtime paths in the codebase today.
5. `cp .env.example .env` — configure your environment.
6. `docker compose up -d` — start infrastructure (see [`docs/operations/PORT_REFERENCE.md`](./docs/operations/PORT_REFERENCE.md)).
7. Optional phased build narrative (historical detail): [`docs/archive/project-journals/IMPLEMENTATION_BLUEPRINT.md`](./docs/archive/project-journals/IMPLEMENTATION_BLUEPRINT.md).
