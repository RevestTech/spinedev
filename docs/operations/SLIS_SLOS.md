# Tron Service Level Indicators & Objectives

**Status:** P0 Fix - Addresses SRE feedback  
**Issue:** No SLIs/SLOs defined (only product KPIs)  
**Solution:** Concrete service-level objectives with error budgets

---

## Overview

**SRE Review (5/10):**
> "Success Metrics are product KPIs, not service SLIs. No targets for API availability, latency percentiles, workflow success rate, or error budgets."

**This Document Defines:**
1. **SLIs:** What we measure (metrics)
2. **SLOs:** What we promise (targets)
3. **Error Budgets:** How much failure is acceptable
4. **Alerting:** When to page on-call
5. **Monitoring:** How to track and report

---

## Service Level Indicators (SLIs)

### 1. API Gateway SLIs

#### Availability
```
SLI: successful_requests / total_requests
Where: successful = HTTP 2xx or 3xx

Measurement Window: 28 days (rolling)
Measured From: Nginx access logs + API metrics
```

#### Latency
```
SLI: requests_below_threshold / total_requests
Where: threshold = 500ms (p95)

Percentiles: p50, p95, p99
Measurement Window: 5 minutes (for alerting), 28 days (for SLO)
Measured From: API response time histogram
```

#### Error Rate
```
SLI: error_requests / total_requests
Where: error = HTTP 5xx

Measurement Window: 5 minutes (for alerting), 28 days (for SLO)
Measured From: API metrics
```

---

### 2. Workflow SLIs

#### Success Rate
```
SLI: successful_workflows / total_workflows
Where: successful = status = 'completed' without errors

By Mode: PLAN, BUILD, AUDIT, FIX
Measurement Window: 7 days (rolling)
Measured From: audit_runs table
```

#### Time to Complete
```
SLI: workflows_completed_within_threshold / total_workflows

Thresholds:
- AUDIT: 10 minutes (p95)
- PLAN: 30 minutes (p95)
- FIX: 20 minutes (p95)
- BUILD: 60 minutes (p95)

Measurement Window: 7 days
Measured From: audit_runs.duration_seconds
```

#### Schedule-to-Start Latency (Temporal)
```
SLI: workflows_started_within_threshold / total_workflows
Where: threshold = 30 seconds (p95)

Measurement: Time from workflow enqueue to first activity
Measured From: Temporal metrics
```

---

### 3. Database SLIs

#### Query Latency
```
SLI: queries_below_threshold / total_queries
Where: threshold = 100ms (p95)

Measurement Window: 5 minutes (for alerting)
Measured From: pg_stat_statements
```

#### Connection Pool Saturation
```
SLI: 1 - (active_connections / max_connections)

Threshold: >20% available connections
Measured From: pg_stat_activity
```

---

### 4. Sandbox SLIs

#### Availability
```
SLI: available_containers / total_pool_size
Where: available = ready and not in use

Threshold: >30% available (3/10 for pool of 10)
Measured From: Docker API
```

#### Startup Time
```
SLI: containers_started_within_threshold / total_starts
Where: threshold = 5 seconds (p95)

Measurement Window: 1 hour
Measured From: Container startup duration metric
```

---

### 5. LLM Provider SLIs

#### Success Rate
```
SLI: successful_llm_calls / total_llm_calls
Where: successful = HTTP 200 with valid response

By Provider: OpenAI, Anthropic, Local
Measurement Window: 1 hour (fast-changing)
Measured From: llm_usage table
```

#### Latency
```
SLI: llm_calls_below_threshold / total_llm_calls
Where: threshold = 30 seconds (p95)

Measurement Window: 1 hour
Measured From: llm_usage.duration_ms
```

---

## Service Level Objectives (SLOs)

### Tier 1: Critical (Impact = Loss of Service)

| SLI | Target | Error Budget | Alert On | Page On-Call? |
|-----|--------|--------------|----------|---------------|
| **API Availability** | **99.5%** | 0.5% (3.6h/month) | <99.7% in 1h | Yes (P1) |
| **API Latency (p95)** | **<500ms** | 5% above threshold | >600ms for 10m | Yes (P2) |
| **Database Available** | **99.9%** | 0.1% (43m/month) | Connection fails | Yes (P0) |
| **Temporal Available** | **99.9%** | 0.1% | Worker disconnected | Yes (P0) |

### Tier 2: Important (Impact = Degraded Service)

| SLI | Target | Error Budget | Alert On | Page On-Call? |
|-----|--------|--------------|----------|---------------|
| **Workflow Success (AUDIT)** | **95%** | 5% can fail | <90% in 1h | No (Slack) |
| **Workflow Success (BUILD)** | **90%** | 10% can fail | <85% in 2h | No (Slack) |
| **LLM Provider Success** | **98%** | 2% can fail | <95% in 1h | No (Slack) |
| **Sandbox Availability** | **>30% free** | N/A | <20% for 10m | No (Slack) |

### Tier 3: Nice to Have (Impact = User Inconvenience)

| SLI | Target | Error Budget | Alert On | Page On-Call? |
|-----|--------|--------------|----------|---------------|
| **Workflow Time (AUDIT p95)** | **<10m** | 20% over | >15m for 30m | No |
| **Database Query (p95)** | **<100ms** | 10% over | >150ms for 10m | No |
| **Cache Hit Rate** | **>10%** | N/A | <5% in 1d | No |
| **WebSocket Uptime** | **99%** | 1% | <98% in 1h | No |

---

## Error Budgets

### What is an Error Budget?

```
Error Budget = (1 - SLO) × Measurement Window

Example:
- API Availability SLO: 99.5%
- Measurement Window: 28 days = 40,320 minutes
- Error Budget: (1 - 0.995) × 40,320 = 201.6 minutes = 3.36 hours

Meaning: We can be "down" for up to 3.36 hours per month
without violating our SLO.
```

### Error Budget Policies

**When Error Budget > 50% remaining:**
- ✅ Deploy new features freely
- ✅ Aggressive experimentation
- ✅ Normal development pace

**When Error Budget < 50% remaining:**
- ⚠️  Increase testing rigor
- ⚠️  Reduce deploy frequency
- ⚠️  Focus on reliability

**When Error Budget < 10% remaining:**
- 🔴 **FREEZE** non-critical deploys
- 🔴 Focus **only** on reliability fixes
- 🔴 Post-mortem required for all incidents
- 🔴 Review SLO targets (too aggressive?)

**When Error Budget Exhausted (< 0%):**
- 🚨 **FULL FREEZE** on all deploys
- 🚨 Emergency incident response mode
- 🚨 Executive visibility
- 🚨 Mandatory post-mortem with action items

---

## Prometheus Alert Rules

### Critical Alerts (P0 - Page Immediately)

```yaml
# API Availability
- alert: APIAvailabilityLow
  expr: |
    (sum(rate(http_requests_total{status=~"2.."}[1h]))
     /
     sum(rate(http_requests_total[1h]))) < 0.997
  for: 5m
  labels:
    severity: critical
    tier: tier1
    page: "yes"
  annotations:
    summary: "API availability below SLO (current: {{ $value }})"
    description: "API success rate is {{ $value | humanizePercentage }}, below 99.7% threshold"

# Database Connections
- alert: DatabaseConnectionsExhausted
  expr: |
    (pg_stat_database_numbackends / pg_settings_max_connections) > 0.9
  for: 2m
  labels:
    severity: critical
    tier: tier1
    page: "yes"
  annotations:
    summary: "PostgreSQL connection pool nearly exhausted"
    description: "{{ $value | humanizePercentage }} of connections in use"

# Temporal Worker Disconnected
- alert: TemporalWorkerDown
  expr: |
    temporal_worker_task_slots_available == 0
  for: 5m
  labels:
    severity: critical
    tier: tier1
    page: "yes"
  annotations:
    summary: "Temporal worker has no available task slots"
    description: "Worker may be stuck or disconnected"
```

### Important Alerts (P2 - Slack Notification)

```yaml
# Workflow Success Rate
- alert: WorkflowSuccessRateLow
  expr: |
    (sum(rate(audit_runs_total{status="completed"}[1h]))
     /
     sum(rate(audit_runs_total[1h]))) < 0.90
  for: 10m
  labels:
    severity: warning
    tier: tier2
    page: "no"
  annotations:
    summary: "Workflow success rate below 90%"
    description: "Only {{ $value | humanizePercentage }} workflows completing successfully"

# LLM Provider Errors
- alert: LLMProviderErrorRateHigh
  expr: |
    sum(rate(llm_calls_total{status="error"}[1h])) by (provider)
     /
    sum(rate(llm_calls_total[1h])) by (provider) > 0.05
  for: 15m
  labels:
    severity: warning
    tier: tier2
    page: "no"
  annotations:
    summary: "LLM provider {{ $labels.provider }} error rate high"
    description: "{{ $value | humanizePercentage }} of calls failing"

# Sandbox Pool Low
- alert: SandboxPoolLow
  expr: |
    (docker_container_pool_available / docker_container_pool_total) < 0.20
  for: 10m
  labels:
    severity: warning
    tier: tier2
    page: "no"
  annotations:
    summary: "Sandbox container pool low"
    description: "Only {{ $value }} containers available"
```

### Performance Alerts (P3 - Slack, No Urgency)

```yaml
# API Latency
- alert: APILatencyHigh
  expr: |
    histogram_quantile(0.95, 
      sum(rate(http_request_duration_seconds_bucket[5m])) by (le)
    ) > 0.6
  for: 15m
  labels:
    severity: info
    tier: tier3
    page: "no"
  annotations:
    summary: "API p95 latency above target"
    description: "p95: {{ $value }}s (target: 0.5s)"

# Workflow Duration
- alert: AuditWorkflowSlow
  expr: |
    histogram_quantile(0.95,
      sum(rate(workflow_duration_seconds_bucket{mode="AUDIT"}[30m])) by (le)
    ) > 900
  for: 30m
  labels:
    severity: info
    tier: tier3
    page: "no"
  annotations:
    summary: "AUDIT workflows running slow"
    description: "p95: {{ $value }}s (target: 600s/10m)"
```

---

## Grafana Dashboards

### Dashboard 1: SLO Overview

```
┌─────────────────────────────────────────────────────────┐
│ Tron SLO Dashboard                        [Last 28 days]│
├─────────────────────────────────────────────────────────┤
│                                                         │
│ Tier 1: Critical                                        │
│                                                         │
│ API Availability      99.8% ✓  [===== 0.2% budget]     │
│ API Latency (p95)     450ms ✓  [====== 10% over]       │
│ Database Available    99.95% ✓ [== 0.05% budget]       │
│ Temporal Available    100% ✓   [== 0% budget]          │
│                                                         │
│ Tier 2: Important                                       │
│                                                         │
│ Workflow Success (A)  96% ✓    [==== 1% budget]        │
│ Workflow Success (B)  88% ⚠    [====== 2% budget]      │
│ LLM Provider Success  99% ✓    [= 1% budget]           │
│ Sandbox Availability  40% ✓    [===== 10% over]        │
│                                                         │
│ Error Budget Status: HEALTHY (All >50%)                │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

**Queries:**
```promql
# API Availability (28 days)
sum(rate(http_requests_total{status=~"2.."}[28d]))
/
sum(rate(http_requests_total[28d]))

# Error Budget Remaining
(1 - (SLI / SLO)) / (1 - SLO)
```

### Dashboard 2: RED Metrics (Rate, Errors, Duration)

```
┌─────────────────────────────────────────────────────────┐
│ Tron RED Metrics                           [Last 1 hour]│
├─────────────────────────────────────────────────────────┤
│                                                         │
│ Rate (Requests/sec)                                     │
│ [Line chart: http_requests_total rate]                 │
│ Current: 42 req/s  Peak: 120 req/s                     │
│                                                         │
│ Errors (% of requests)                                  │
│ [Line chart: Error rate by status code]                │
│ 5xx: 0.2%  4xx: 1.5%  Target: <0.5% (5xx)             │
│                                                         │
│ Duration (Latency)                                      │
│ [Heatmap: Request latency distribution]                │
│ p50: 120ms  p95: 480ms  p99: 850ms                     │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

### Dashboard 3: Temporal Metrics

```
┌─────────────────────────────────────────────────────────┐
│ Temporal Workflow Metrics                  [Last 1 hour]│
├─────────────────────────────────────────────────────────┤
│                                                         │
│ Active Workflows: 8                                     │
│ Queue Depth: 12  (⚠ Above 10)                          │
│ Worker Slots: 45/50 available                          │
│                                                         │
│ Schedule-to-Start Latency (p95)                         │
│ [Line chart]                                            │
│ Current: 15s  Target: <30s ✓                           │
│                                                         │
│ Workflow Duration by Mode                               │
│ AUDIT:  p95 = 8m  ✓                                    │
│ PLAN:   p95 = 25m ✓                                    │
│ BUILD:  p95 = 55m ✓                                    │
│ FIX:    p95 = 18m ✓                                    │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

---

## SLO Review Process

### Weekly Review (Engineering Team)

**Check:**
1. Are we meeting all SLOs? (✓ or ⚠)
2. How much error budget remains?
3. Any alerts fired this week?
4. Trends: improving or degrading?

**Action:**
- Celebrate wins (SLOs met with budget remaining)
- Investigate near-misses (SLO met but <20% budget)
- Plan fixes for SLO violations

### Monthly Review (Leadership)

**Questions:**
1. Did we meet SLOs this month?
2. How much error budget did we consume?
3. Were SLO violations due to:
   - Known incidents?
   - Degradation over time?
   - Too aggressive targets?
4. Do we need to adjust SLOs?

**Outcome:**
- Quarterly SLO adjustment (if needed)
- Investment decisions (reliability vs features)
- Incident post-mortem action items

### Quarterly SLO Adjustment

**Tighten SLOs (make more aggressive) if:**
- ✅ Consistently meeting SLOs with >80% error budget remaining
- ✅ Users expect better reliability
- ✅ Competitive pressure

**Relax SLOs (make less aggressive) if:**
- ❌ Frequently violating SLOs despite best efforts
- ❌ Blocking all feature development for reliability
- ❌ Targets were set unrealistically high

**Rule:** Don't change SLOs mid-month (unfair to measure against moving target)

---

## Incident Response Runbook

### When SLO Violated

1. **Acknowledge Alert** (within 5m for P0, 30m for P2)
2. **Triage** (is this an emergency?)
   - User-facing impact? → Emergency
   - Internal only? → Standard
3. **Mitigate** (restore service fast)
   - Rollback recent deploy?
   - Scale up resources?
   - Switch to degraded mode?
4. **Resolve Root Cause** (after mitigation)
5. **Post-Mortem** (for all SLO violations)
   - What happened?
   - Why did it happen?
   - Action items (assign owners, due dates)

### Post-Mortem Template

```markdown
# Incident: [Title]

**Date:** 2026-04-11  
**Duration:** 45 minutes  
**Severity:** P1 (API Availability SLO violated)  
**Impact:** 200+ failed requests, 5 users affected

## Timeline
- 10:00 - Deploy v2.3.5
- 10:15 - Alert: API Availability <99.7%
- 10:20 - Acknowledged, began investigation
- 10:30 - Identified database connection leak
- 10:35 - Rolled back to v2.3.4
- 10:45 - Service restored, SLO met again

## Root Cause
Database connection pool leak in new code path.
Connections not properly closed in error handling.

## Impact
- API Availability: 98.5% (SLO: 99.5%, violated by 1%)
- Error Budget Consumed: 20% in 45 minutes
- Users Affected: 5
- Data Loss: None

## Action Items
- [ ] Fix: Add try/finally for DB connections (@dev1, 2026-04-12)
- [ ] Test: Add integration test for connection leaks (@qa1, 2026-04-12)
- [ ] Monitor: Alert on DB conn pool >70% (@sre1, 2026-04-12)
- [ ] Process: Require staging soak test >1h (@em1, 2026-04-15)

## Lessons Learned
- Staging environment needs production-like connection pool size
- Need automated connection leak detection
```

---

## SLI/SLO Implementation Checklist

### Phase 1: Instrumentation (Week 1)

- [ ] Add Prometheus exporters to all services
- [ ] Instrument API with RED metrics (rate, errors, duration)
- [ ] Instrument Temporal workers with workflow metrics
- [ ] Instrument database with pg_exporter
- [ ] Instrument LLM calls with custom metrics
- [ ] Set up Prometheus scraping (see docker-compose)

### Phase 2: Dashboards (Week 2)

- [ ] Create SLO Overview dashboard
- [ ] Create RED Metrics dashboard
- [ ] Create Temporal dashboard
- [ ] Create Database dashboard
- [ ] Create LLM Provider dashboard
- [ ] Create Error Budget tracking dashboard

### Phase 3: Alerting (Week 3)

- [ ] Configure Alertmanager
- [ ] Define alert rules (critical, important, info)
- [ ] Set up PagerDuty integration (P0/P1)
- [ ] Set up Slack integration (P2/P3)
- [ ] Test alert routing and on-call schedule
- [ ] Document runbooks for each alert

### Phase 4: Review Process (Week 4)

- [ ] Weekly SLO review meeting (recurring)
- [ ] Monthly leadership review (recurring)
- [ ] Post-mortem template and process
- [ ] Error budget policy documented
- [ ] SLO adjustment process defined

---

## Summary

**What Changed:**
- ❌ Old: "Success Metrics" (product KPIs only)
- ✅ New: Concrete SLIs/SLOs with error budgets

**Coverage:**
- ✅ API Gateway (availability, latency, errors)
- ✅ Workflows (success rate, duration)
- ✅ Database (query latency, connections)
- ✅ Sandbox (availability, startup time)
- ✅ LLM Providers (success rate, latency)

**Operationalization:**
- ✅ Prometheus metrics and queries
- ✅ Grafana dashboards
- ✅ Alertmanager rules (P0/P1/P2/P3)
- ✅ Error budget policies
- ✅ Incident response runbooks
- ✅ Review processes (weekly, monthly, quarterly)

---

**Status:** ✅ P0 Blocker Resolved - SLIs/SLOs defined with operational processes
