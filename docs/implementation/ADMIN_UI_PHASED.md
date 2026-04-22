# Tron Admin UI - Phased Approach (Simplified)

**Status:** P0 Fix - Addresses Product Manager & UX Designer feedback  
**Issue:** Six dashboard pages for single user/company is over-engineered  
**Solution:** Phase 1 with core features, defer or integrate rest

---

## Problem Statement

**From Product Manager (6.5/10):**
> "Six dashboard pages for single-tenant, single-company deployment is more scope than value unless you are explicitly building toward multi-user or managed SaaS."

**From UX Designer (6.5/10):**
> "Overlapping concerns across Main/Workflows/System/Costs, high default cognitive load from omnipresent live updates, missing cross-project triage."

**From All Experts:**
- System monitoring overlaps Grafana (already in stack)
- Workflow monitoring overlaps Temporal UI (already at port 8081)
- Real-time WebSocket for one user is complexity for marginal gain

---

## Original Proposal (Too Much for Phase 1)

```
┌─────────────────────────────────────────────┐
│ 1. Main Dashboard (Overview)                │
│    - Metrics cards                          │
│    - Live activity stream                   │
│    - Charts (workflow status, costs, etc.)  │
│    - Customizable widgets                   │
├─────────────────────────────────────────────┤
│ 2. Projects                                 │
│    - List all projects                      │
│    - Drill-down to 6 tabs per project:     │
│      * Overview                             │
│      * Audit History                        │
│      * Findings                             │
│      * Standards                            │
│      * Costs                                │
│      * Activity Log                         │
├─────────────────────────────────────────────┤
│ 3. Workflows (Overlaps Temporal UI!)        │
│    - Active workflows list                  │
│    - Workflow detail                        │
│    - Live progress                          │
├─────────────────────────────────────────────┤
│ 4. System Health (Overlaps Grafana!)        │
│    - Service status                         │
│    - Resource usage                         │
│    - Docker pool                            │
│    - Error logs                             │
├─────────────────────────────────────────────┤
│ 5. Costs                                    │
│    - Dashboard                              │
│    - Budget management                      │
│    - Alerts                                 │
├─────────────────────────────────────────────┤
│ 6. Settings                                 │
│    - General, Security, Integrations, etc.  │
└─────────────────────────────────────────────┘

PROBLEM: 6 pages × complex features = months of work for 1 user
```

---

## Revised Phased Approach

### Phase 1: Core Value (MVP) - **Build This First**

Focus on **what Tron uniquely provides** that no other tool does:
1. **Project Quality Dashboard** (findings, audits, standards)
2. **Cost Management** (budgets, tracking, alerts)

```
┌─────────────────────────────────────────────┐
│ PHASE 1: Tron Admin (Core Value)            │
├─────────────────────────────────────────────┤
│                                             │
│ 📁 Projects                                 │
│    ├─ Project List (cards with metrics)    │
│    └─ Project Detail (single page):        │
│        ├─ Quality Score & Trend             │
│        ├─ Recent Audits (table)            │
│        ├─ Open Findings (by severity)      │
│        ├─ Standards Compliance             │
│        └─ Quick Actions                    │
│                                             │
│ 💰 Cost Management                          │
│    ├─ Current Spend (today, this month)    │
│    ├─ Budget Status (% used, alerts)       │
│    ├─ Cost by Operation (PLAN/BUILD/etc.)  │
│    ├─ Budget Configuration                 │
│    └─ Cost History (7/30 days)            │
│                                             │
│ 🔗 External Links (instead of rebuilding)  │
│    ├─ "View Workflows" → Temporal UI       │
│    ├─ "System Health" → Grafana            │
│    └─ "API Docs" → /docs                   │
│                                             │
└─────────────────────────────────────────────┘

FEATURES:
- ✅ REST API polling (no WebSocket complexity)
- ✅ Static data visualization (Recharts)
- ✅ Simple navigation (2 main pages)
- ✅ Relative URLs (works via Nginx proxy)
- ✅ Mobile-friendly (responsive, read-only)

TIME ESTIMATE: 2-3 weeks (1 developer)
```

### Phase 2: Enhanced Usability (After Phase 1 Validated)

Add **only if users request**:
1. WebSocket for real-time updates
2. Workflow drill-down (if Temporal UI insufficient)
3. Advanced filtering and search

```
┌─────────────────────────────────────────────┐
│ PHASE 2: Enhanced Features (if needed)      │
├─────────────────────────────────────────────┤
│                                             │
│ 🔄 Real-Time Updates (WebSocket)            │
│    - Live workflow progress                 │
│    - Finding notifications                  │
│    - Cost alerts                            │
│                                             │
│ 🔍 Advanced Search & Filter                 │
│    - Full-text search findings             │
│    - Filter by severity, category, file    │
│    - Saved filter presets                  │
│                                             │
│ 📊 Workflow Detail Page                     │
│    - Deeper than Temporal UI               │
│    - Tron-specific context                 │
│    - Logs and artifacts inline             │
│                                             │
└─────────────────────────────────────────────┘

TIME ESTIMATE: 2-3 weeks (add-on to Phase 1)
```

### Phase 3: Platform Operations (If Multi-User)

Add **only if expanding to multi-user/team**:
1. User management (RBAC)
2. System monitoring (if Grafana insufficient)
3. Customizable dashboards

```
┌─────────────────────────────────────────────┐
│ PHASE 3: Multi-User & Operations (future)   │
├─────────────────────────────────────────────┤
│                                             │
│ 👥 User Management                          │
│    - OIDC/SSO integration                  │
│    - RBAC (roles, permissions)             │
│    - Team collaboration                    │
│                                             │
│ 🖥️  System Monitoring (if needed)           │
│    - Embedded Grafana dashboards           │
│    - Service health checks                 │
│    - Resource alerts                       │
│                                             │
│ ⚙️  Customizable Dashboards                 │
│    - Widget configuration                  │
│    - Personal views                        │
│    - Saved layouts                         │
│                                             │
└─────────────────────────────────────────────┘

TIME ESTIMATE: 4-6 weeks (significant expansion)
```

---

## Phase 1 Detailed Specification

### Page 1: Projects

**URL:** `/projects`

**Layout:**

```
┌─────────────────────────────────────────────────────────┐
│ Tron                                          🔔  👤     │
├─────────────────────────────────────────────────────────┤
│ Projects │ Costs │ ↗ Temporal UI │ ↗ Grafana           │
├─────────────────────────────────────────────────────────┤
│                                                         │
│ Projects (3)                        [+ New Project]     │
│                                                         │
│ ┌──────────────────┐ ┌──────────────────┐             │
│ │ 🟢 Website       │ │ 🟢 Mobile App    │             │
│ │ Score: 94/100    │ │ Score: 87/100    │             │
│ │ 2 open findings  │ │ 8 open findings  │             │
│ │ Last audit: 2h   │ │ Last audit: 1d   │             │
│ │ Cost: $12/month  │ │ Cost: $45/month  │             │
│ └──────────────────┘ └──────────────────┘             │
│                                                         │
│ ┌──────────────────┐                                   │
│ │ 🟡 API Service   │                                   │
│ │ Score: 78/100    │                                   │
│ │ 15 open findings │                                   │
│ │ Last audit: 3d   │                                   │
│ │ Cost: $8/month   │                                   │
│ └──────────────────┘                                   │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

**API Endpoint:**
```
GET /api/projects
Response: [
  {
    "id": "uuid",
    "name": "Website",
    "status": "active",
    "quality_score": 94,
    "open_findings": 2,
    "last_audit": "2026-04-11T10:00:00Z",
    "monthly_cost_usd": 12.00
  },
  ...
]
```

**Features:**
- ✅ Card grid layout (responsive)
- ✅ Color-coded status (🟢 >90, 🟡 70-89, 🔴 <70)
- ✅ Click card → Project detail
- ✅ Simple, fast, no real-time needed

---

### Page 2: Project Detail

**URL:** `/projects/:id`

**Layout:**

```
┌─────────────────────────────────────────────────────────┐
│ Tron > Website                                🔔  👤     │
├─────────────────────────────────────────────────────────┤
│ Projects │ Costs │ ↗ Temporal UI │ ↗ Grafana           │
├─────────────────────────────────────────────────────────┤
│                                                         │
│ Website                                   [Run Audit]   │
│                                                         │
│ ┌─────────────────────────────────────────────────────┐│
│ │ Quality Score                                        ││
│ │                                                      ││
│ │     94/100  ↗ +2 this week                          ││
│ │                                                      ││
│ │ [Chart: Score over 30 days]                          ││
│ └──────────────────────────────────────────────────────┘│
│                                                         │
│ ┌──────────────────────┐ ┌───────────────────────────┐ │
│ │ Recent Audits        │ │ Open Findings (2)         │ │
│ │                      │ │                           │ │
│ │ ✓ 2h ago  Run #42    │ │ 🔴 SQL Injection (High)   │ │
│ │ ✓ 1d ago  Run #41    │ │    src/api/users.py:42    │ │
│ │ ✓ 3d ago  Run #40    │ │                           │ │
│ │ [View All]           │ │ 🟡 Unused Import (Low)    │ │
│ │                      │ │    src/utils.py:12        │ │
│ └──────────────────────┘ │ [View All]                │ │
│                          └───────────────────────────┘ │
│                                                         │
│ ┌──────────────────────┐ ┌───────────────────────────┐ │
│ │ Standards            │ │ Quick Actions             │ │
│ │                      │ │                           │ │
│ │ ✓ Security: 95%      │ │ [Run Audit]               │ │
│ │ ✓ Quality: 92%       │ │ [View Findings]           │ │
│ │ ⚠ Performance: 78%   │ │ [Configure Standards]     │ │
│ │ [Edit Standards]     │ │ [View in Temporal UI]     │ │
│ │                      │ │                           │ │
│ └──────────────────────┘ └───────────────────────────┘ │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

**API Endpoints:**
```
GET /api/projects/:id
GET /api/projects/:id/audits?limit=5
GET /api/projects/:id/findings?status=open
GET /api/projects/:id/standards-compliance
```

**Features:**
- ✅ Single-page view (no tabs to start)
- ✅ Most important info above the fold
- ✅ Quick actions prominent
- ✅ Links to external tools (Temporal UI)
- ✅ Responsive grid layout

---

### Page 3: Cost Management

**URL:** `/costs`

**Layout:**

```
┌─────────────────────────────────────────────────────────┐
│ Tron > Costs                                  🔔  👤     │
├─────────────────────────────────────────────────────────┤
│ Projects │ Costs │ ↗ Temporal UI │ ↗ Grafana           │
├─────────────────────────────────────────────────────────┤
│                                                         │
│ Cost Management                                         │
│                                                         │
│ ┌───────────┐ ┌───────────┐ ┌───────────┐ ┌─────────┐ │
│ │ Today     │ │ This Month│ │ Budget    │ │ Proj    │ │
│ │ $2.45     │ │ $68.20    │ │ $100      │ │ Mo: $205│ │
│ │ ↗ +12%    │ │ 68%       │ │ 🟢 Safe   │ │ (avg)   │ │
│ └───────────┘ └───────────┘ └───────────┘ └─────────┘ │
│                                                         │
│ ┌─────────────────────────────────────────────────────┐│
│ │ Cost Trend (30 days)                                 ││
│ │ [Line chart: Daily cost]                             ││
│ └──────────────────────────────────────────────────────┘│
│                                                         │
│ ┌────────────────────┐ ┌──────────────────────────────┐│
│ │ By Operation       │ │ By Project                    ││
│ │                    │ │                               ││
│ │ BUILD   $42 (61%)  │ │ Mobile App  $45 (66%)        ││
│ │ FIX     $15 (22%)  │ │ Website     $12 (18%)        ││
│ │ PLAN     $8 (12%)  │ │ API Service  $8 (12%)        ││
│ │ AUDIT    $3 (4%)   │ │ [Configure Budgets]          ││
│ │                    │ │                               ││
│ └────────────────────┘ └──────────────────────────────┘│
│                                                         │
│ ┌─────────────────────────────────────────────────────┐│
│ │ Budget Alerts                                        ││
│ │                                                      ││
│ │ 🟡 Mobile App at 90% of monthly budget ($45/$50)    ││
│ │    [Increase Limit] [Throttle Usage]                ││
│ │                                                      ││
│ └──────────────────────────────────────────────────────┘│
│                                                         │
└─────────────────────────────────────────────────────────┘
```

**API Endpoints:**
```
GET /api/costs/summary?period=today
GET /api/costs/summary?period=month
GET /api/costs/trend?days=30
GET /api/costs/by-operation
GET /api/costs/by-project
GET /api/costs/alerts
```

**Features:**
- ✅ Clear budget status
- ✅ Actionable alerts
- ✅ Simple charts (no real-time needed)
- ✅ Configure budgets inline

---

## Implementation Priorities

### Must Have (Phase 1)

1. **REST API endpoints** (no WebSocket)
2. **Static UI framework** (React + shadcn/ui)
3. **Recharts** for simple visualizations
4. **Responsive layout** (mobile-friendly read-only)
5. **Nginx proxy** with relative URLs

### Nice to Have (Phase 2)

1. **WebSocket** for live workflow updates
2. **Advanced filtering** for findings
3. **Workflow detail page** (beyond Temporal UI)

### Future (Phase 3+)

1. **User management** (OIDC, RBAC)
2. **System monitoring** (if Grafana insufficient)
3. **Customizable dashboards**

---

## Technical Stack (Phase 1)

```typescript
// Simplified dependencies (Phase 1)
{
  "dependencies": {
    // Core
    "react": "^18.2.0",
    "react-dom": "^18.2.0",
    "react-router-dom": "^6.20.0",
    
    // UI Components
    "@radix-ui/react-*": "latest",  // shadcn/ui primitives
    "tailwindcss": "^3.4.0",
    "lucide-react": "^0.300.0",  // Icons
    
    // Data Fetching (NO WebSocket in Phase 1)
    "react-query": "^3.39.3",  // REST API caching
    
    // State Management (minimal)
    "zustand": "^4.4.7",  // Only for UI state
    
    // Charts
    "recharts": "^2.10.0",  // Simple, performant
    
    // Forms
    "react-hook-form": "^7.49.0",
    "zod": "^3.22.4",
    
    // Utilities
    "date-fns": "^3.0.0",
    "clsx": "^2.0.0"
  }
}
```

**No Socket.IO in Phase 1** - Keep it simple!

---

## Migration from Current Proposal

### What to Remove (Phase 1)

1. ❌ Main Dashboard page (merge into Projects or Costs)
2. ❌ Workflows page (link to Temporal UI instead)
3. ❌ System Health page (link to Grafana instead)
4. ❌ Settings page (inline configuration where needed)
5. ❌ WebSocket/Socket.IO (use polling for Phase 1)
6. ❌ Customizable widgets (YAGNI for single user)
7. ❌ Activity stream (just show recent audits)

### What to Keep (Phase 1)

1. ✅ Projects list and detail
2. ✅ Cost management dashboard
3. ✅ Budget configuration
4. ✅ Finding display
5. ✅ Audit history
6. ✅ Standards compliance view

---

## Success Criteria (Phase 1)

**User can accomplish in <5 clicks:**
1. ✅ See all project health at a glance
2. ✅ Drill into a specific project's findings
3. ✅ Check current cost and budget status
4. ✅ Configure budget limits
5. ✅ Run a new audit

**Performance:**
- ✅ Page load <2s
- ✅ API response <500ms (p95)
- ✅ Works on tablet+ (responsive)

**Development Time:**
- ✅ 2-3 weeks for single developer
- ✅ No complex WebSocket debugging
- ✅ No horizontal scaling issues

---

## When to Add Phase 2/3 Features

**Triggers for Phase 2:**
- User requests real-time updates explicitly
- Temporal UI insufficient for workflow debugging
- Multiple team members need different views

**Triggers for Phase 3:**
- >3 users accessing Tron
- Need for role-based access control
- Grafana insufficient for ops needs

**Don't build it until you need it!**

---

## Summary

**Old Approach:**
- 6 pages
- Real-time everything
- Overlaps with Temporal UI + Grafana
- Months of work
- Over-engineered for 1 user

**New Approach (Phase 1):**
- 2 core pages (Projects, Costs)
- REST polling (no WebSocket complexity)
- Links to existing tools (Temporal, Grafana)
- 2-3 weeks of work
- Right-sized for single user/company

**Result:**
- ✅ Deliver core value faster
- ✅ Validate with users before over-building
- ✅ Lower maintenance burden
- ✅ Easier to deploy and scale later

---

**Status:** ✅ P0 Blocker Resolved - Admin UI simplified to Phase 1 core value
