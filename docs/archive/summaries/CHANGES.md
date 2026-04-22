# Tron Proposal Updates

**Date:** April 11, 2026  
**Version:** 1.0 → 2.0  
**Status:** Finalized and ready for implementation

---

## Summary of Changes

The proposal has been updated based on expert feedback and refined design decisions. All "v1 vs later" hedging has been removed. This is now a **build-it-right-the-first-time** architecture.

---

## Major Changes

### 1. Workflow Engine: Celery → Temporal

**Before:**
- Celery for task queue
- "Fine for v1, migrate to Temporal later"

**After:**
- Temporal from day one
- Supports multi-step workflows (PLAN, BUILD, FIX modes)
- Durable state, error recovery, human-in-the-loop
- No need to rewrite later

**Why:** PLAN and BUILD modes require complex workflows. Building with Celery would require a costly rewrite.

---

### 2. Multi-Tenancy: Simplified to Project Isolation

**Before:**
- Multi-tenant architecture
- Row-level security
- Per-tenant quotas
- Complex isolation

**After:**
- Single user/company with multiple projects
- Simple `project_id` foreign keys
- Application-level filtering
- No tenant overhead

**Why:** Use case is single user/company, not SaaS platform. Removed unnecessary complexity.

---

### 3. Security Architecture: Added (Was Missing)

**Before:**
- No security section
- Authentication mentioned briefly

**After:**
- Complete security architecture
- Three access methods (MCP, REST API, CLI)
- API key model with scopes
- Docker sandbox hardening
- Secrets management (AES-256)
- Rate limiting
- Audit logging

**Components Added:**
- API key authentication with scopes (`audit:read`, `audit:write`)
- Docker sandbox security:
  - No network access
  - Read-only root filesystem
  - CPU/memory limits (0.5 CPU, 512MB RAM)
  - 5-minute timeout
  - All capabilities dropped
- Secrets encryption (AES-256)
- Rate limiting (100 req/hour default per key)
- Audit logging for all API calls

---

### 4. Connection Pooling: Added for Scaling

**Before:**
- Not addressed

**After:**
- PostgreSQL: 20 connections + 10 overflow
- Redis: 50 connections
- Docker containers: 10 pre-warmed
- HTTP client: 100 connections (for LLM APIs)

**Why:** Prevent resource exhaustion, enable horizontal scaling, faster execution.

---

### 5. Redis Topology: Two Instances → One

**Before:**
- Separate Redis for cache and queue

**After:**
- Single Redis with multiple DBs
- DB 0: Cache
- DB 1: Temporal visibility (if needed)

**Why:** Single user/company doesn't need separation. Simpler operations.

---

### 6. Authentication: Simplified

**Before:**
- OAuth2/OIDC for v1
- API keys mentioned

**After:**
- API keys with scopes (primary)
- OAuth2 deferred to later
- Config-based for CLI

**Why:** Simpler for CLI and CI/CD. OAuth2 adds complexity for single-user case.

---

### 7. Deployment: Clarified as Docker Compose

**Before:**
- Docker container (monolith)
- Kubernetes mentioned
- "Stateless API layer" unclear

**After:**
- Docker Compose with multiple services
- No Kubernetes (overkill for use case)
- Clear service separation:
  - API Gateway
  - Temporal workers (3 replicas)
  - PostgreSQL
  - Redis
  - MinIO
  - Temporal server

**Why:** Single user/company doesn't need K8s. Simpler to operate.

---

### 8. MCP Server: Detailed Integration

**Before:**
- Mentioned briefly
- No implementation details

**After:**
- Complete MCP server design
- Tool definitions (`tron_audit_project`, `tron_check_standards`, etc.)
- Authentication for MCP (stdio + HTTP transport)
- Rate limiting per tool
- Example usage for AI agents

---

### 9. Architecture Decision Records: Added

**Before:**
- No ADRs

**After:**
- 9 ADRs documenting key decisions:
  1. Workflow Engine (Temporal)
  2. Sandbox Isolation (Docker-in-Docker)
  3. Database Architecture (PostgreSQL + MinIO)
  4. Connection Pooling Strategy
  5. Multi-Tenancy Model
  6. Authentication Strategy
  7. Redis Topology
  8. Secrets Management
  9. Deployment Model

**Why:** Document rationale for future reference and onboarding.

---

### 10. Docker Compose: Complete Configuration Added

**Before:**
- Simple service list

**After:**
- Production-ready `docker-compose.yml`
- All services configured with:
  - Health checks
  - Resource limits
  - Proper networking
  - Volume management
- Environment variable template
- Quick start commands

---

### 11. Implementation Phases: Restructured

**Before:**
- 5 phases (20 weeks)
- "PLAN mode in Phase 1"
- Multi-tenancy in Phase 5

**After:**
- 6 phases (24 weeks)
- Phase 1: Secure foundation (infrastructure + security)
- Phase 2: Standards & AUDIT mode only
- Phase 3: Integration (MCP, CLI, CI/CD)
- Phase 4: PLAN mode
- Phase 5: BUILD & FIX modes
- Phase 6: Polish & documentation

**Why:** Security and foundations first. Defer complex modes until basics proven.

---

## Removed Content

### What Was Removed:
- ❌ "Fine for v1" language
- ❌ "Consider later" hedging
- ❌ Multi-tenant complexity
- ❌ Kubernetes deployment
- ❌ OAuth2 for v1
- ❌ Complex user management
- ❌ Business model / pricing sections (refocused on technical design)
- ❌ "Open questions" (all decisions made)

---

## New Sections Added

1. **Security Architecture** (complete section)
2. **Architecture Decision Records** (9 ADRs)
3. **Docker Compose Configuration** (production-ready)
4. **Connection Pooling Strategy** (all resources)
5. **API Design** (MCP, REST, CLI with examples)
6. **Three Access Methods** (detailed per interface)

---

## Key Numbers

| Metric | Before | After |
|--------|--------|-------|
| Total words | ~13,000 (across 5 docs) | ~6,000 (focused proposal) |
| Sections | 86 | 109 |
| ADRs | 0 | 9 |
| Security coverage | Minimal | Comprehensive |
| Docker services | 3-4 | 7 (complete stack) |
| Connection pools | 0 | 4 (DB, Redis, Docker, HTTP) |

---

## Document Status

### Before:
- Status: "Proposal & Expert Review Phase"
- Multiple documents (proposal, reviews, action plans)
- Many "open questions"
- "V1 vs V2" hedging

### After:
- Status: "Finalized & Ready for Implementation"
- Single focused proposal
- All decisions made and documented (ADRs)
- Build-it-right-the-first-time approach

---

## What This Means

**You can now start building with confidence:**

1. ✅ All architecture decisions made
2. ✅ Security designed from day one
3. ✅ Scaling strategy in place (connection pooling)
4. ✅ Clear phases with deliverables
5. ✅ Production-ready infrastructure (docker-compose.yml)
6. ✅ No "temporary solutions" that need rewriting

**No more:**
- ❌ "We'll fix this later"
- ❌ "Fine for v1"
- ❌ "Consider migrating to X"
- ❌ "Open questions"

---

## Next Actions

1. **Review finalized proposal:** `TRON_PROPOSAL.md`
2. **Review architecture decisions:** See ADRs in proposal
3. **Set up development environment:** Use docker-compose.yml
4. **Start Phase 1 implementation:** Secure foundation (Weeks 1-4)

---

**Ready to build Tron the right way.**

**Document Version:** 1.0  
**Date:** April 11, 2026
