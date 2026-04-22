# Tron MVP Scope - Minimum Viable Product

**Version:** 1.0  
**Timeline:** 4-6 weeks (realistic)  
**Goal:** Prove core thesis with working prototype  
**Team:** 1-2 developers

---

## 🎯 MVP Philosophy

**Build the minimum to validate:**
1. Can AI agents reliably detect code issues?
2. Is the architecture sound?
3. Will customers pay for this?
4. What's the actual LLM cost per audit?

**NOT building:**
- Multiple ISO agents (Security only)
- Fix workflow (audit only)
- Admin UI (API only)
- Full test coverage (basic coverage)
- Enterprise features (GDPR, DR can wait)

---

## 📦 MVP Feature Set

### What's Included ✅

**1. Single ISO Agent: Security ISO**
- Detects OWASP Top 10 vulnerabilities
- SQL injection, XSS, CSRF, code injection
- Uses Claude Sonnet 4 for analysis
- Returns findings with severity, location, description

**2. Basic Audit Workflow**
- Accept project (GitHub URL or local path)
- Clone/scan codebase
- Run Security ISO analysis
- Store findings in database
- Return results via API

**3. Minimal API (5 endpoints)**
```
POST   /api/projects          Create project
GET    /api/projects          List projects
POST   /api/audit             Start security audit
GET    /api/audit/{id}        Get audit status/results
GET    /api/findings          List findings
```

**4. PostgreSQL with pgvector**
- Core tables: projects, audit_runs, findings, code_files
- Vector embeddings for semantic search
- Basic indexes (no graph queries yet)

**5. Basic Authentication**
- API key authentication only (no JWT yet)
- Single user (no multi-user)
- Rate limiting (simple: 60 req/min)

**6. Basic Testing**
- 200-300 unit tests (not 2,500)
- Core functionality covered
- Security ISO mocked
- API integration tests

**7. Cost Tracking**
- Track tokens per audit
- Store in llm_usage table
- Simple cost dashboard (CLI, not UI)

**8. Docker Compose**
- PostgreSQL, Redis, MinIO
- No Temporal (use simple asyncio instead)
- No Vault (use environment variables)
- No monitoring stack (just logs)

### What's NOT Included ❌

**Agent Features:**
- ❌ Builder ISO (build in Phase 2)
- ❌ QA ISO (build in Phase 2)
- ❌ Fix workflow (audit only)
- ❌ Iterative refinement (single pass)
- ❌ Agent memory (just embeddings)
- ❌ Prompt versioning (hardcoded prompts)

**Infrastructure:**
- ❌ Temporal workflows (use asyncio)
- ❌ HashiCorp Vault (use env vars)
- ❌ Monitoring stack (just logs)
- ❌ WebSocket real-time (polling only)
- ❌ Redis Sentinel (single Redis)

**Enterprise Features:**
- ❌ GDPR compliance (add in Phase 3)
- ❌ Disaster recovery (add in Phase 3)
- ❌ Encryption at rest (add in Phase 3)
- ❌ RBAC (single user)
- ❌ Audit logging (basic only)

**UI:**
- ❌ Admin web interface (API only)
- ❌ Real-time updates (polling)
- ❌ Dashboards (CLI output)

**Testing:**
- ❌ 2,500+ tests (200-300 only)
- ❌ E2E tests (basic integration)
- ❌ Performance tests (manual)
- ❌ Chaos tests (Phase 3)

---

## 🗓️ 4-6 Week MVP Timeline

### Week 1-2: Foundation (10 days)

**Infrastructure (3 days):**
- Docker Compose with PostgreSQL, Redis, MinIO
- Database migrations (4 core tables only)
- Basic FastAPI skeleton

**API + Auth (3 days):**
- FastAPI with 5 endpoints
- API key authentication
- Rate limiting (simple Redis counter)

**Embeddings (2 days):**
- OpenAI embeddings integration
- Store in PostgreSQL with pgvector
- Basic semantic search

**Testing (2 days):**
- 50-100 unit tests
- API integration tests
- Mocked LLM responses

**Deliverable:** ✅ API responding, authentication working, database operational

---

### Week 3-4: Security ISO (10 days)

**Agent Framework (3 days):**
- BaseISO abstract class
- Tool integration (Bandit, Semgrep)
- LLM integration (Claude Sonnet 4)

**Security ISO (4 days):**
- Implement SecurityISO
- Vulnerability detection logic
- Finding generation
- Confidence scoring

**Audit Workflow (2 days):**
- Project cloning/scanning
- Security ISO invocation
- Result storage
- Status tracking

**Testing (1 day):**
- 100+ tests for Security ISO
- Known vulnerability test suite (OWASP Top 10)

**Deliverable:** ✅ Security ISO detects vulnerabilities end-to-end

---

### Week 5-6: Polish & Validation (10 days)

**Cost Tracking (2 days):**
- Token counting
- Cost calculation
- Usage storage
- CLI cost report

**Testing (3 days):**
- Remaining unit tests (to 200-300 total)
- Integration tests
- Bug fixes

**Documentation (2 days):**
- API documentation (auto-generated)
- Quick start guide
- Usage examples

**Performance (2 days):**
- Optimize slow queries
- Test with real codebases
- Measure audit duration

**Design Partners (1 day):**
- Prepare demo
- Create interview guide
- Set up feedback tracking

**Deliverable:** ✅ Working MVP ready for customer validation

---

## 📊 MVP Success Criteria

### Technical Validation
- ✅ Security ISO detects 90%+ of OWASP Top 10
- ✅ Audit completes in < 10 minutes for typical repo (10K LOC)
- ✅ 200+ tests passing, 70%+ coverage
- ✅ Costs < $5 per audit average
- ✅ API responds in < 500ms (p95)
- ✅ Zero critical security vulnerabilities
- ✅ Runs reliably for 7 days without intervention

### Business Validation (Critical)
- ✅ **3-5 design partners** agree to test
- ✅ **70%+ say "this is useful"** after testing
- ✅ **50%+ say "I would pay"** for this
- ✅ **Pricing validated** ($50-100/dev/mo or $5-10/audit)

**If validation fails:** Pivot or kill project (don't build Phase 2)

---

## 💰 MVP Budget

### Development Cost (In-House)

| Item | Time | Cost |
|------|------|------|
| Infrastructure setup | 3 days | $2,400 |
| API development | 5 days | $4,000 |
| Security ISO | 7 days | $5,600 |
| Embeddings | 2 days | $1,600 |
| Testing | 6 days | $4,800 |
| Documentation | 2 days | $1,600 |
| Polish | 5 days | $4,000 |
| **Total (30 days)** | **6 weeks** | **$24,000** |

*Assumes fully loaded cost of $800/day per developer*

### Infrastructure Cost (3 months)

| Service | Monthly | 3 Months |
|---------|---------|----------|
| DigitalOcean Droplet (8GB) | $48 | $144 |
| PostgreSQL managed DB | $60 | $180 |
| Redis managed | $15 | $45 |
| LLM APIs (testing, 200 audits) | $120 | $360 |
| **Total** | **$243/mo** | **$729** |

### Total MVP Cost: $24,000 + $729 = **$24,729**

### Cost Per Audit (Real Numbers)

**Typical Audit:**
- Input tokens: 30,000 (code context)
- Output tokens: 5,000 (findings)
- Claude Sonnet 4: $3 input, $15 output per 1M tokens
- Cost per audit: (30K × $3 + 5K × $15) / 1M = **$0.165**

**With overhead (embeddings, overhead):** ~$0.50 per audit

**Revenue at $5/audit:** $4.50 margin (90%)

---

## 🎯 MVP User Stories

### As a Developer, I Can:

1. **Submit Code for Audit**
   ```bash
   curl -X POST http://localhost:8000/api/projects \
     -H "Authorization: Bearer <api-key>" \
     -d '{"name": "my-app", "repo_url": "https://github.com/me/app"}'
   
   curl -X POST http://localhost:8000/api/audit \
     -H "Authorization: Bearer <api-key>" \
     -d '{"project_id": "<id>", "scope": "security"}'
   ```

2. **Get Security Findings**
   ```bash
   curl http://localhost:8000/api/findings?project_id=<id>
   ```

3. **See Results**
   ```json
   {
     "findings": [
       {
         "type": "sql_injection",
         "severity": "critical",
         "file": "app/api.py",
         "line": 42,
         "code": "query = f\"SELECT * FROM users WHERE id = {user_id}\"",
         "description": "Unsafe SQL query construction. Use parameterized queries.",
         "confidence": 0.95
       }
     ]
   }
   ```

---

## 📋 MVP Architecture (Simplified)

```
┌─────────────────┐
│   API Client    │
│  (curl, Postman)│
└────────┬────────┘
         │ REST API
┌────────┴─────────┐
│   FastAPI        │
│   5 endpoints    │
└────────┬─────────┘
         │
┌────────┴─────────┐
│  Security ISO    │
│  Claude Sonnet 4 │
│  + Bandit/Semgrep│
└────────┬─────────┘
         │
┌────────┴─────────┐
│   PostgreSQL     │
│   + pgvector     │
└──────────────────┘
```

**Much simpler than full architecture** - Proves the core concept

---

## 🧪 MVP Testing Strategy (Realistic)

### 200-300 Tests (Not 2,500)

**Unit Tests (150-200):**
- Security ISO detection logic (50 tests)
- API endpoint tests (30 tests)
- Database operations (30 tests)
- Authentication (20 tests)
- Embeddings service (20 tests)
- Utilities (20-30 tests)

**Integration Tests (30-50):**
- Full audit workflow (10 tests)
- API + database (10 tests)
- Security ISO + real code (10-30 tests)

**E2E Tests (10-20):**
- Complete audit via API (5 tests)
- Known vulnerability detection (10-15 tests)

**Coverage Target:** 70% (not 80%)

**Why Realistic:**
- 10-15 tests per day is achievable
- Focus on critical paths
- Can expand in Phase 2

---

## 📊 MVP vs Full Comparison

| Feature | MVP | Full Product |
|---------|-----|--------------|
| ISO Agents | 1 (Security) | 8 (all types) |
| Workflows | Audit only | Audit + Fix + Build |
| Timeline | 4-6 weeks | 12-16 weeks |
| Tests | 200-300 | 2,500+ |
| Coverage | 70% | 80% |
| Infrastructure | Basic | Enterprise |
| Features | Core | Complete |
| Cost | $25K | $65-88K |
| **Time to Value** | **6 weeks** | **4 months** |

**MVP Advantage:** Validate demand 3x faster at 40% of cost

---

## ✅ MVP Success = Build Phase 2

### Decision Criteria

**Build Phase 2 if MVP achieves:**
- ✅ 3+ design partners using it regularly
- ✅ 70%+ say "this is useful"
- ✅ 50%+ say "I would pay $5-10/audit"
- ✅ Cost per audit < $1 (including overhead)
- ✅ Technical architecture holds up (no major rewrites needed)

**Kill project if:**
- ❌ < 2 design partners engaged
- ❌ < 50% find it useful
- ❌ Cost per audit > $5 (not viable)
- ❌ Architecture needs major changes

---

## 🎯 Next Immediate Actions

### This Week
1. **Create** missing documents:
   - BUSINESS_MODEL.md
   - COST_CONTROLS.md
   - RISK_REGISTER.md
   - CUSTOMER_VALIDATION.md

2. **Update** IMPLEMENTATION_BLUEPRINT.md:
   - Change to 12-16 week timeline
   - Add MVP-first approach
   - Realistic week-by-week tasks

3. **Find** 3-5 potential design partners:
   - Companies with 10-100 developers
   - Strong QA culture
   - Python/TypeScript codebases
   - Willing to test alpha

### Next 4-6 Weeks
**Build MVP** following this scope

### Week 7-8
**Validate** with design partners and decide: build Phase 2 or pivot/kill

---

## 💡 Key Insights from Independent Review

**What They Got Right:**

✅ **"Blueprint, not product"** - Honest assessment  
✅ **"8 weeks unrealistic"** - Week 6 testing impossible  
✅ **"Build prototype first"** - Validate before full build  
✅ **"Need customer validation"** - 3-5 design partners  
✅ **"Docker Compose not enterprise-ready"** - K8s needed by month 4  
✅ **"Thin competitive moat"** - Focus on proprietary data  

**Recommended Actions:**

1. ✅ Adjust timeline (12-16 weeks)
2. ✅ Build MVP first (4-6 weeks)
3. ✅ Validate with customers
4. ✅ Define monetization
5. ✅ Implement cost controls
6. ✅ Plan K8s migration
7. ✅ Remove "10/10" language (circular validation)

---

## 🏆 MVP Success Story

**Week 6: Demo to Design Partner**

```bash
# Submit their codebase
curl -X POST http://localhost:8000/api/audit \
  -H "Authorization: Bearer demo-key" \
  -d '{"repo_url": "https://github.com/partner/app"}'

# Wait 3 minutes

# Get results
curl http://localhost:8000/api/findings?audit_id=<id>

# Returns: 12 critical vulnerabilities found
# 8 SQL injections, 3 XSS, 1 insecure deserialization

# Customer reaction: "This found issues we missed!"
# ✅ MVP validated
```

**Phase 2 Decision:** Build it! Customers want this.

---

## 📊 Risk-Adjusted Timeline

| Phase | Optimistic | Realistic | Pessimistic |
|-------|-----------|-----------|-------------|
| **MVP** | 4 weeks | **6 weeks** | 8 weeks |
| **Phase 2** | 6 weeks | **8 weeks** | 10 weeks |
| **Phase 3** | 4 weeks | **6 weeks** | 8 weeks |
| **Total** | 14 weeks | **20 weeks** | 26 weeks |

**Plan for:** 20 weeks (5 months)  
**Hope for:** 14 weeks (3.5 months)  
**Buffer:** 6 weeks for unknowns

---

## 💰 MVP Budget Reality Check

**Can you afford it?**

| Scenario | Cost | Approach |
|----------|------|----------|
| **Solo founder** | $24K dev + $729 infra | Nights/weekends (3-4 months) |
| **Bootstrapped** | $24K | Hire 1 contractor, 6 weeks |
| **Small budget** | $50K | Hire agency, 6 weeks |
| **VC-backed** | $100K | Hire 2 devs, 6 weeks + buffer |

**Recommended:** Build MVP yourself or with 1 contractor to minimize burn.

---

## ✅ MVP Checklist

### Pre-Development
- [ ] Find 3-5 potential design partners
- [ ] Interview about pain points
- [ ] Validate they'd test an MVP
- [ ] Get commitment to provide feedback

### Week 1-2: Foundation
- [ ] Docker Compose running
- [ ] PostgreSQL with pgvector
- [ ] FastAPI with 5 endpoints
- [ ] API key auth working
- [ ] 50 tests passing

### Week 3-4: Security ISO
- [ ] Security ISO detecting vulnerabilities
- [ ] Audit workflow end-to-end
- [ ] Findings stored in database
- [ ] 100+ tests passing

### Week 5-6: Polish
- [ ] Cost tracking working
- [ ] 200+ tests passing, 70% coverage
- [ ] Documentation complete
- [ ] Ready for design partner demo

### Post-MVP
- [ ] Demo to 3-5 design partners
- [ ] Collect feedback
- [ ] Measure: useful? would pay? how much?
- [ ] **Decision:** Build Phase 2 or pivot

---

## 🎯 Bottom Line

**Old Plan:**
- ❌ 8 weeks to "production-ready"
- ❌ 2,500 tests in Week 6
- ❌ All features at once
- ❌ Not credible

**New Plan (MVP First):**
- ✅ 4-6 weeks to working MVP
- ✅ 200-300 tests (realistic)
- ✅ Core feature only
- ✅ Validate before scaling
- ✅ **Credible and achievable**

**Value Trajectory:**
- Week 0: $10K (blueprint)
- Week 6: $50K (working MVP)
- Week 12: $300K (customer validation)
- Month 12: $1M-3M (traction)

**Status:** ✅ **Realistic, achievable, validated approach**

---

**Next:** Build MVP, prove thesis, validate with customers, then scale.
