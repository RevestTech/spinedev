# Tron: Enterprise AI Quality Assurance & Development Platform

**Version:** 2.3 Final  
**Date:** April 11, 2026  
**Status:** Production-Ready Design with Graph Capabilities

---

## Executive Summary

Tron is an enterprise-grade AI orchestration platform that solves the critical problem of inconsistent AI-generated code quality. Unlike traditional AI coding assistants that operate in isolation, Tron provides a centralized, standards-enforcing service that ensures code quality, security compliance, and enterprise readiness across all projects and AI tools.

**Core Problem Solved:**
- AI agents produce inconsistent code quality
- Infinite review loops (AI keeps finding different issues)
- Standards enforcement is hope-based, not validated
- Each AI tool requires separate configuration
- No objective "done" criteria

**Tron Solution:**
- Centralized standards enforcement (company-wide)
- Plan-first approach (objective completion criteria)
- Multi-mode operation (PLAN → BUILD → AUDIT → FIX)
- AI-agent agnostic (works with any tool via API/MCP)
- Built-in compliance frameworks (SOC 2, ISO 27001, HIPAA, etc.)

---

## Inspiration: Stripe Minions

Tron is inspired by Stripe's Minions (1,000+ PRs/week) but extends the concept:

| Aspect | Stripe Minions | Tron |
|--------|---------------|------|
| **Purpose** | Build features for Stripe | Universal QA & build service |
| **Scope** | Single organization | Multi-project, multi-client |
| **Quality** | Human review required | Self-validating before return |
| **Standards** | Stripe-specific | Company + project hierarchy |
| **Planning** | Task-based | Architecture-first approach |
| **Compliance** | N/A | Built-in (SOC 2, ISO, HIPAA) |

---

## Architecture Overview

```
┌─────────────────────────────────────────────────┐
│                TRON MANAGER                      │
│         "AI Solution Architect"                  │
│  - Project metadata & context management         │
│  - ISO orchestration (agent pool)                │
│  - Quality gate enforcement                      │
│  - Standards hierarchy management                │
└───────────────────┬─────────────────────────────┘
                    │
        ┌───────────┴────────────┬─────────────────┐
        ▼                        ▼                 ▼
┌──────────────┐         ┌──────────────┐  ┌──────────────┐
│   PLAN MODE  │         │  BUILD MODE  │  │  AUDIT MODE  │
└──────────────┘         └──────────────┘  └──────────────┘
        │                        │                 │
        ▼                        ▼                 ▼
┌──────────────────────────────────────────────────────────┐
│                    ISO POOL                               │
│  (Independent Sales Organizations - Agent Workers)        │
│  - Builder ISOs (feature development)                     │
│  - Security ISOs (vulnerability scanning)                 │
│  - QA ISOs (testing, coverage)                           │
│  - Compliance ISOs (SOC 2, ISO 27001, etc.)              │
│  - Performance ISOs (benchmarking)                        │
│  - Documentation ISOs (API docs, architecture)            │
└──────────────────────────────────────────────────────────┘
                    │
                    ▼
        ┌─────────────────────┐
        │  QUALITY GATES      │
        │  - Security checks  │
        │  - Test coverage    │
        │  - Performance      │
        │  - Compliance       │
        │  - Documentation    │
        └─────────────────────┘
                    │
                    ▼
        ┌─────────────────────┐
        │  PERSISTENT STATE   │
        │  - Project metadata │
        │  - Findings DB      │
        │  - Fix tracking     │
        │  - Audit trails     │
        └─────────────────────┘
```

---

## Core Concepts

### 1. The ISO Agent Model

**ISOs (Independent Sales Organizations)** are specialized AI agents that handle specific aspects of software development and quality assurance.

**Why "ISO"?**
- Borrowed from payment processing terminology (appropriate for Tron name)
- Implies specialized, independent workers
- Scalable and parallel execution model

**ISO Types:**
- **Builder ISOs**: Implement features, write code
- **Security ISOs**: Scan for vulnerabilities, enforce security policies
- **QA ISOs**: Write and run tests, measure coverage
- **Compliance ISOs**: Validate SOC 2, ISO 27001, HIPAA requirements
- **Performance ISOs**: Benchmark, profile, optimize
- **Documentation ISOs**: Generate API docs, architecture diagrams

### 2. Standards Hierarchy

Tron implements a three-tier standards system:

```yaml
DEFAULT STANDARDS (Built into Tron)
  ├─ Security best practices (OWASP Top 10)
  ├─ Code quality rules (complexity, formatting)
  ├─ Testing standards (coverage thresholds)
  ├─ Compliance templates (SOC 2, ISO 27001, HIPAA, PCI-DSS)
  └─ UI/UX frameworks (WCAG accessibility, responsive design)
  
COMPANY STANDARDS (Organization-wide)
  ├─ Inherits from defaults
  ├─ Company-specific patterns (auth, API format, logging)
  ├─ Design systems (colors, typography, components)
  ├─ Tech stack requirements (frameworks, languages)
  └─ Custom validators (Python scripts for specific checks)
  
PROJECT STANDARDS (Project-specific)
  ├─ Inherits from company
  ├─ Project-specific patterns
  └─ Contextual overrides (e.g., lower coverage for MVP)
```

### 3. Plan-First Approach

**The Root Cause:** AI finds infinite issues because there's no objective baseline.

**Tron Solution:** Create a comprehensive plan BEFORE building.

**PLAN Mode Generates:**
1. **Requirements Document** - Functional & non-functional requirements
2. **Architecture Design** - System design, data flow, tech stack
3. **Quality Gates** - Objective pass/fail criteria (JSON contract)
4. **Test Specifications** - Exact tests that MUST exist and pass
5. **Security Policy** - Security requirements and compliance needs
6. **Project Scaffolding** - Directory structure, boilerplate
7. **Skills & Rules** - Auto-generated Cursor skills and project rules
8. **Documentation Plan** - What docs must exist

**Result:** Tron can objectively say "100% complete" or "92% complete - 3 security issues remain"

---

## Operating Modes

### 1. PLAN Mode

**Purpose:** Create comprehensive project blueprint before any code is written.

**Process:**
1. Interactive questionnaire (asks user about project goals, requirements, constraints)
2. Generates complete project plan and architecture
3. Creates quality gates (objective success criteria)
4. Generates test specifications
5. Sets up project scaffolding

**Outputs:**
- `.tron/project.json` - Project metadata
- `.tron/architecture.md` - System design document
- `.tron/requirements.md` - Functional & non-functional requirements
- `.tron/quality-gates.json` - Objective validation criteria
- `.tron/test-specifications.md` - Required tests
- `.cursor/skills/` - Auto-generated project skills
- `tests/test_plan.md` - Test plan
- Documentation structure

**Example Quality Gate:**
```json
{
  "security": {
    "required": true,
    "criteria": [
      {"check": "no_hardcoded_secrets", "severity": "critical"},
      {"check": "dependency_vulnerabilities", "max_high": 0}
    ]
  },
  "testing": {
    "criteria": [
      {"check": "unit_test_coverage", "min_percentage": 80},
      {"check": "all_endpoints_tested", "min_percentage": 100}
    ]
  }
}
```

### 2. BUILD Mode

**Purpose:** Implement features according to the plan.

**Process:**
1. Receives task/feature request
2. Loads project metadata and standards
3. Spawns Builder ISOs to write code
4. Spawns QA ISOs in parallel to prepare tests
5. Runs internal validation loop (against quality gates)
6. Only returns when code meets quality standards

**Difference from Stripe Minions:**
- Tron validates code BEFORE returning (self-checking)
- Minions require human review
- Tron enforces company standards automatically

**Example:**
```python
tron.build(
    project_id="my-app",
    task="Add JWT authentication",
    quality_requirements={
        "security_scan": True,
        "test_coverage": 80,
        "documentation": True
    }
)

# Returns:
{
    "status": "complete",
    "quality_score": 95,
    "files_changed": ["auth.py", "middleware.py", "test_auth.py"],
    "tests_passed": "45/45",
    "security_issues": 0,
    "standards_compliance": "PASS"
}
```

### 3. AUDIT Mode

**Purpose:** Comprehensive code quality review against objective standards.

**Process:**
1. Receives project for audit
2. Loads quality gates and standards
3. Spawns specialized ISOs:
   - Security ISO scans for vulnerabilities
   - QA ISO checks test coverage
   - Compliance ISO validates regulatory requirements
   - Performance ISO runs benchmarks
4. Generates detailed report with objective scores
5. No subjective opinions - only measurable violations

**Solves Infinite Loop Problem:**
```
Traditional AI: "You should add rate limiting" (subjective)
                "You should add JWT rotation" (another opinion)
                "You should add 2FA" (infinite suggestions)

Tron: Checks against quality-gates.json
      ✓ SEC-001: JWT auth - PASS
      ✓ SEC-003: Rate limiting - PASS
      ✗ SEC-002: RBAC incomplete - FAIL (3 endpoints missing)
      
      Quality Score: 92/100
      Status: 1 critical issue
      
      After fix:
      ✓ All gates PASSED
      Quality Score: 100/100
      Status: COMPLETE ✅
```

### 4. FIX Mode

**Purpose:** Interactive issue remediation.

**Process:**
1. Receives audit report
2. User/AI agent can iterate on specific issues
3. Tron tracks which issues are fixed (persistent state)
4. Prevents re-reporting same issues
5. Can auto-fix or provide instructions to calling agent

**Example:**
```python
# Get audit
report = tron.audit(project_id="my-app")

# Work through issues
for issue in report.critical_issues:
    fix = tron.suggest_fix(issue_id=issue.id)
    tron.apply_fix(issue_id=issue.id, approved=True)

# Check status
final = tron.status(project_id="my-app")
# "100% of critical issues resolved"
```

### 5. EVOLVE Mode (Future)

**Purpose:** Update project plan as requirements change.

---

## Standards Enforcement

### Problem with Current AI Tools

```
User sets up standards:
├─ .cursor/rules/RULES.md         (Cursor-specific)
├─ .cursor/skills/                (Cursor-specific)
├─ .github/copilot-instructions   (Copilot-specific)
├─ .cline/                        (Cline-specific)
└─ .continue/config.json          (Continue-specific)

Issues:
❌ Each AI interprets differently
❌ No enforcement (hope-based)
❌ Inconsistent across team
❌ New AI tool = redo everything
❌ No compliance audit trail
```

### Tron Solution: Centralized Enforcement

**Single Source of Truth:**
```
~/.tron/company-standards.yaml    (Your organization)
    ↓
/Projects/MyApp/.tron/project-standards.yaml
    ↓
Tron Validation Engine (AST analysis, pattern matching, tool scanning)
    ↓
PASS or FAIL (objective, auditable)
```

**All AI tools become "dumb clients":**
- Cursor calls Tron API
- Claude calls Tron API
- Copilot calls Tron API
- Future tools call Tron API

**Tron enforces standards, not AI tools.**

### Example Company Standards

```yaml
# ~/.tron/company-standards.yaml

company:
  name: "Future Capital"
  standards_version: "2.0"

inherit:
  - security/owasp-top-10
  - compliance/soc2
  - ui-ux/wcag-accessibility

overrides:
  security:
    authentication:
      method: "JWT + MFA required"
      session_timeout: 900
      password_policy:
        min_length: 16
    
  ui_ux:
    design_system: "Future Capital Design System v3"
    rules:
      - "All buttons must use FC color palette"
      - "Typography: Inter for body, Outfit for headings"
      - "Mobile-first responsive design required"
      - "Dark mode support mandatory"
    
  code_patterns:
    backend:
      - "Use Repository pattern for database access"
      - "All API responses must follow FC API standard"
    frontend:
      - "React: functional components only"
      - "State management: Zustand preferred"
  
  testing:
    coverage_minimum: 85
    
  compliance:
    soc2_controls:
      - "CC6.1: Audit logging on all data mutations"
      - "CC6.2: Encryption at rest using AWS KMS"

custom_validators:
  - validator: "validators/fc_api_response_validator.py"
  - validator: "validators/fc_color_palette_checker.py"
```

### Built-in Standards Library

```
/opt/tron/standards/
├─ security/
│  ├─ owasp-top-10.json
│  ├─ secrets-detection.json
│  ├─ authentication.json
│  └─ encryption.json
├─ compliance/
│  ├─ soc2/
│  ├─ iso27001/
│  ├─ hipaa/
│  └─ pci-dss/
├─ code-quality/
│  ├─ python-pep8.json
│  ├─ javascript-airbnb.json
│  └─ complexity-rules.json
└─ ui-ux/
   ├─ wcag-accessibility.json
   ├─ responsive-design.json
   └─ design-systems/
```

---

## Technical Architecture

### Deployment Model

**Tron Services Architecture:**
```
┌──────────────────────────────────────────────────┐
│          AI Agents / Users / CI/CD               │
└────────────────┬─────────────────────────────────┘
                 │
      ┌──────────┼──────────┐
      ▼          ▼          ▼
  ┌──────┐  ┌───────┐  ┌────────┐
  │ MCP  │  │  CLI  │  │ REST   │
  │Server│  │       │  │  API   │
  └───┬──┘  └───┬───┘  └───┬────┘
      │         │          │
      └─────────┼──────────┘
                ▼
       ┌────────────────────┐
       │  FastAPI Gateway   │
       │  - Authentication  │
       │  - Rate Limiting   │
       │  - Audit Logging   │
       └──────────┬─────────┘
                  │
                  ▼
       ┌─────────────────────┐
       │  Temporal Workflows │
       │  - Multi-step flows │
       │  - State management │
       │  - Error recovery   │
       └──────────┬──────────┘
                  │
       ┌──────────┼──────────┐
       ▼          ▼          ▼
   ┌────────┐ ┌──────┐ ┌────────┐
   │Postgres│ │MinIO │ │ Redis  │
   │(Pool:20│ │ S3   │ │(Pool:50│
   └────────┘ └──────┘ └────────┘
                  │
                  ▼
         ┌────────────────┐
         │ Docker Sandbox │
         │ Pool (10 warm) │
         └────────────────┘
```

**Scalability:**
- Connection pooling (DB, Redis, Docker, HTTP)
- Multiple Temporal workers (horizontal scaling)
- Pre-warmed Docker containers for fast execution
- Stateless API layer (can add more instances)
- Persistent state in PostgreSQL
- Object storage for large artifacts

**Target Deployment:**
- Single user/company with multiple projects
- Docker Compose for local or single-server deployment
- No Kubernetes required (designed for simplicity)

### Technology Stack

```yaml
Backend:
  Language: Python 3.11+
  API Framework: FastAPI
  Workflow Engine: Temporal (multi-step orchestration)
  Database: PostgreSQL 15+ with Graph Capabilities
    - Connection pooling (PgBouncer)
    - Graph extensions: ltree, pg_trgm, btree_gist
    - Recursive CTEs for graph traversal
    - Hierarchical data modeling
    - Time-based partitioning
  Object Storage: MinIO (S3-compatible)
  Cache: Redis 7+ (single instance, multi-DB)
  Container: Docker + Docker Compose

Frontend (Admin UI):
  Framework: React 18 + TypeScript
  Build Tool: Vite
  State Management: Zustand
  UI Components: shadcn/ui + Tailwind CSS
  Charts: Recharts + D3.js
  Real-time: WebSocket (Socket.IO)
  Data Fetching: React Query

AI Integration:
  - OpenAI SDK (GPT-4, GPT-4o, GPT-4o-mini)
  - Anthropic SDK (Claude Sonnet, Claude Haiku)
  - MCP Protocol (Model Context Protocol)
  - Local fallback: Ollama integration

Code Analysis:
  - AST parsing (Python: ast module)
  - Linting: ruff, mypy, eslint, prettier
  - Security: bandit, safety, semgrep
  - Testing: pytest, coverage.py
  - Dependency scanning: pip-audit, npm audit

Security:
  - API Key authentication with scopes
  - Rate limiting (per key, per project)
  - Docker sandbox isolation (no network, resource limits)
  - Secrets encryption (AES-256)
  - Audit logging for all operations
  - HTTPS/TLS for all external communication
  - Admin access control (role-based)

Connection Pooling:
  - PostgreSQL: 20 connections + 10 overflow
  - Redis: 50 connections
  - Docker: 10 pre-warmed containers
  - HTTP Client: 100 connections (for LLM APIs)

Monitoring & Observability:
  - Structured logging (JSON format)
  - Metrics: Prometheus + Grafana
  - Distributed tracing: OpenTelemetry
  - Real-time dashboards: WebSocket streaming
  - Alerting: Custom notification system

Interfaces:
  - MCP Server (for AI agents like Cursor, Claude)
  - REST API (for CI/CD, webhooks)
  - CLI (for local development)
  - Admin Web UI (real-time monitoring & management)
```

---

## Security Architecture

### Authentication & Authorization

**Three Access Methods:**

1. **MCP Server (AI Agents)**
   - Stdio transport: Inherits user's local permissions
   - HTTP transport: Requires API key in headers
   - Scoped per project
   - Rate limited per tool

2. **REST API (CI/CD, Webhooks)**
   - Bearer token authentication
   - API keys with scopes (`audit:read`, `audit:write`, `standards:read`)
   - Per-project access control
   - Rate limiting (100 req/hour default)
   - Request audit logging

3. **CLI (Local Development)**
   - Config-based (`~/.tron/config.yaml`)
   - Reads project API keys from local config
   - Secure local storage

### API Key Model

```python
# Database schema
class APIKey:
    id: UUID
    key_hash: str  # bcrypt hash
    name: str  # "GitHub Actions", "Claude Desktop"
    project_id: UUID
    scopes: list[str]  # ["audit:read", "audit:write"]
    rate_limit: int  # requests/hour
    created_at: datetime
    expires_at: datetime
    last_used_at: datetime
```

### Security Features

- ✅ **Docker Sandbox Isolation**
  - No network access (network_mode: none)
  - Read-only root filesystem
  - CPU/memory limits (0.5 CPU, 512MB RAM)
  - Timeout enforcement (5 min max)
  - No privileged mode
  - All capabilities dropped

- ✅ **Secrets Management**
  - Encrypted at rest (AES-256)
  - Master key from environment/keychain
  - Never logged or exposed in errors
  - Automatic rotation support

- ✅ **Audit Logging**
  - All API calls logged
  - Project access logged
  - Workflow execution tracked
  - Immutable append-only logs

- ✅ **Rate Limiting**
  - Per API key
  - Configurable per project
  - Redis-backed counters
  - 429 response when exceeded

---

## Graph-Based Database Design

### Overview

Tron uses **PostgreSQL with graph modeling** to provide scalable, searchable, and relationship-rich data storage. This approach combines the reliability of a traditional RDBMS with the power of graph databases.

**Key Design Principle:**
> **Model data as a graph, query with SQL + Recursive CTEs**

### Why Graph-Based?

**Tron's domain is inherently a graph:**
```
Projects → Audit Runs → Findings → Code Files → Dependencies
                ↓             ↓            ↓
            Workflows    Related      File Tree
                         Findings    (Hierarchy)
                             ↓
                        Standards
                       (Inheritance)
```

**Benefits:**
- ✅ **Relationship Queries:** "What files depend on this file?" (transitive)
- ✅ **Impact Analysis:** "If I change this file, what breaks?"
- ✅ **Duplicate Detection:** "Which findings are related?"
- ✅ **Standards Inheritance:** "What's the effective standard for this project?"
- ✅ **Circular Dependency Detection:** Find cycles in imports
- ✅ **Hierarchical Queries:** "All files in /src/ and subdirectories"

### Graph Extensions

```sql
-- Enable PostgreSQL graph capabilities
CREATE EXTENSION IF NOT EXISTS ltree;        -- Hierarchical data (standards, file paths)
CREATE EXTENSION IF NOT EXISTS pg_trgm;      -- Similarity search (fuzzy matching)
CREATE EXTENSION IF NOT EXISTS btree_gist;   -- Advanced indexing for ltree
```

### Graph Tables

#### 1. Code Files (Nodes)
```sql
CREATE TABLE code_files (
    id UUID PRIMARY KEY,
    project_id UUID REFERENCES projects(id),
    file_path TEXT NOT NULL,
    file_hash VARCHAR(64) NOT NULL,
    
    -- Graph: Directory hierarchy
    directory_path ltree,  -- e.g., 'src.api.users'
    
    -- Metrics
    lines_of_code INT,
    complexity_score INT,
    
    UNIQUE(project_id, file_path)
);

-- Indexes for graph queries
CREATE INDEX idx_code_files_directory_gist ON code_files USING GIST (directory_path);
CREATE INDEX idx_code_files_path_trgm ON code_files USING GIN (file_path gin_trgm_ops);
```

#### 2. File Dependencies (Edges)
```sql
CREATE TABLE file_dependencies (
    id UUID PRIMARY KEY,
    source_file_id UUID REFERENCES code_files(id),
    target_file_id UUID REFERENCES code_files(id),
    dependency_type VARCHAR(50),  -- import, require, include
    
    UNIQUE(source_file_id, target_file_id, dependency_type)
);

-- Indexes for bidirectional traversal
CREATE INDEX idx_file_deps_source ON file_dependencies(source_file_id);
CREATE INDEX idx_file_deps_target ON file_dependencies(target_file_id);
```

#### 3. Finding Relationships (Edges)
```sql
CREATE TABLE finding_relationships (
    id UUID PRIMARY KEY,
    finding_id UUID REFERENCES findings(id),
    related_finding_id UUID REFERENCES findings(id),
    relationship_type VARCHAR(50),  -- duplicate, similar, caused_by, fixes
    confidence DECIMAL(3,2),  -- 0.00 to 1.00
    
    UNIQUE(finding_id, related_finding_id, relationship_type)
);
```

#### 4. Standards Hierarchy (ltree)
```sql
CREATE TABLE standards (
    id UUID PRIMARY KEY,
    hierarchy_path ltree NOT NULL UNIQUE,  -- 'default.company.project'
    level INT GENERATED ALWAYS AS (nlevel(hierarchy_path)) STORED,
    parent_id UUID REFERENCES standards(id),
    rules JSONB NOT NULL,
    
    project_id UUID REFERENCES projects(id)
);

-- Hierarchical queries with ltree
CREATE INDEX idx_standards_path_gist ON standards USING GIST (hierarchy_path);
```

### Sample Graph Queries

#### Find All Files Depending on a File (Transitive)
```sql
WITH RECURSIVE dependency_tree AS (
    SELECT source_file_id, target_file_id, 1 AS depth
    FROM file_dependencies
    WHERE source_file_id = 'file-uuid'
    
    UNION ALL
    
    SELECT fd.source_file_id, fd.target_file_id, dt.depth + 1
    FROM file_dependencies fd
    JOIN dependency_tree dt ON fd.source_file_id = dt.target_file_id
    WHERE dt.depth < 10  -- Prevent infinite loops
)
SELECT cf.file_path, dt.depth
FROM dependency_tree dt
JOIN code_files cf ON dt.target_file_id = cf.id
ORDER BY dt.depth;
```

#### Find Circular Dependencies
```sql
WITH RECURSIVE cycle_detection AS (
    SELECT 
        source_file_id,
        target_file_id,
        ARRAY[source_file_id, target_file_id] AS path,
        false AS is_cycle
    FROM file_dependencies
    
    UNION ALL
    
    SELECT 
        fd.source_file_id,
        fd.target_file_id,
        cd.path || fd.target_file_id,
        fd.target_file_id = ANY(cd.path[:array_length(cd.path, 1)-1])
    FROM file_dependencies fd
    JOIN cycle_detection cd ON fd.source_file_id = cd.target_file_id
    WHERE NOT cd.is_cycle AND array_length(cd.path, 1) < 50
)
SELECT path FROM cycle_detection WHERE is_cycle = true;
```

#### Standards Inheritance Chain
```sql
-- Get effective standards for a project (merged from default → company → project)
SELECT s.id, s.hierarchy_path, s.level, s.rules
FROM standards s
WHERE 'default.company_acme.project_website' ~ (s.hierarchy_path::text || '.*')::lquery
ORDER BY s.level DESC;  -- Most specific first
```

#### All Files in Directory and Subdirectories
```sql
-- Using ltree for hierarchical queries
SELECT file_path, lines_of_code
FROM code_files
WHERE directory_path <@ 'src.api'::ltree  -- All descendants
ORDER BY file_path;
```

### Performance Optimizations

**1. Materialized Views for Common Queries**
```sql
CREATE MATERIALIZED VIEW mv_file_dependency_stats AS
SELECT 
    cf.id AS file_id,
    cf.file_path,
    COUNT(DISTINCT fd_out.target_file_id) AS dependencies_count,
    COUNT(DISTINCT fd_in.source_file_id) AS dependents_count
FROM code_files cf
LEFT JOIN file_dependencies fd_out ON cf.id = fd_out.source_file_id
LEFT JOIN file_dependencies fd_in ON cf.id = fd_in.target_file_id
GROUP BY cf.id, cf.file_path;

-- Refresh after each audit
REFRESH MATERIALIZED VIEW CONCURRENTLY mv_file_dependency_stats;
```

**2. Covering Indexes**
```sql
CREATE INDEX idx_file_deps_covering ON file_dependencies(source_file_id, target_file_id) 
    INCLUDE (dependency_type);
```

### Graph API Endpoints

```python
# New REST endpoints for graph queries

GET /api/files/{file_id}/dependencies
# Returns all files this file depends on (transitive)

GET /api/files/{file_id}/dependents
# Returns all files that depend on this file

GET /api/files/{file_id}/impact-analysis
# Returns all files + findings that would be affected by changing this file

GET /api/projects/{project_id}/circular-dependencies
# Detects and returns circular dependency chains

GET /api/projects/{project_id}/dependency-graph
# Returns full dependency graph (nodes + edges) for visualization

GET /api/findings/{finding_id}/related
# Returns related findings (duplicates, similar, caused-by)

GET /api/standards/{project_id}/inheritance
# Returns standards inheritance chain (default → company → project)

GET /api/files/search?path=/src/api/&recursive=true
# Hierarchical file search using ltree
```

### Graph Visualizations (Admin UI Phase 2)

**Planned visualizations:**
- **Dependency Graph:** Interactive D3.js visualization of file dependencies
- **Circular Dependencies:** Highlight cycles in red
- **Finding Relationships:** Show clusters of related findings
- **Impact Analysis:** Show "blast radius" of changing a file
- **Standards Hierarchy Tree:** Visual representation of inheritance

### Migration Strategy

**Incremental adoption:**
1. ✅ **Phase 1:** Add extensions and graph tables
2. ✅ **Phase 1:** Populate code_files from existing findings
3. ⏳ **Phase 2:** Parse dependencies during audits
4. ⏳ **Phase 2:** Build finding relationships (ML-based)
5. ⏳ **Phase 3:** Add graph visualizations to Admin UI

**See:** [DATABASE_GRAPH_DESIGN.md](./DATABASE_GRAPH_DESIGN.md) for complete implementation details.

---

## API Design

### MCP Server Tools

```python
# AI agents call these tools via MCP

@mcp_tool
async def tron_audit_project(
    project_id: str,
    scope: str = "full"  # "full", "security", "quality"
) -> dict:
    """
    Audit a project for quality and compliance.
    Returns: {score, findings, status}
    """
    pass

@mcp_tool
async def tron_check_standards(
    project_id: str,
    file_path: str
) -> dict:
    """
    Quick check if file meets standards.
    Returns: {compliant, violations}
    """
    pass

@mcp_tool
async def tron_get_project_status(
    project_id: str
) -> dict:
    """
    Get current project quality status.
    Returns: {score, last_audit, critical_issues}
    """
    pass
```

### REST API Endpoints

**Authentication: `Authorization: Bearer <api_key>`**

```python
# Project Management
POST   /api/v1/projects/register
GET    /api/v1/projects/{project_id}
PATCH  /api/v1/projects/{project_id}

# AUDIT Mode
POST   /api/v1/projects/{project_id}/audit
GET    /api/v1/projects/{project_id}/audits
GET    /api/v1/projects/{project_id}/audits/{audit_id}

# Standards Management
GET    /api/v1/projects/{project_id}/standards
PUT    /api/v1/projects/{project_id}/standards

# Quality Gates
GET    /api/v1/projects/{project_id}/quality-gates
PUT    /api/v1/projects/{project_id}/quality-gates

# Findings
GET    /api/v1/projects/{project_id}/findings
PATCH  /api/v1/findings/{finding_id}/resolve

# Status & Reports
GET    /api/v1/projects/{project_id}/status
GET    /api/v1/projects/{project_id}/reports/{audit_id}
```

### CLI Commands

```bash
# Project management
tron project register --path /path/to/project
tron project list
tron project show my-app

# AUDIT operations
tron audit my-app
tron audit my-app --scope security
tron audit my-app --watch  # Continuous

# Standards
tron standards show my-app
tron standards validate my-app

# Status & reports
tron status my-app
tron report my-app --audit-id abc-123
```

### MCP Server Integration

```python
# AI Agents call Tron via MCP

# MCP Tools exposed by Tron:
- tron_plan_project()
- tron_build_feature()
- tron_audit_code()
- tron_fix_issues()
- tron_check_standards()
- tron_get_quality_score()

# Example: Cursor calls Tron
@mcp_tool
def tron_audit_code(project_path: str) -> dict:
    """
    Audit code quality against company standards.
    Returns objective quality score and violations.
    """
    pass
```

---

## Admin & Monitoring Platform

### Overview

Tron includes a comprehensive real-time admin dashboard for monitoring and managing all aspects of the platform. The admin UI provides visibility into projects, workflows, costs, and system health.

### Architecture

```
┌─────────────────────────────────────────────────┐
│      Admin Web App (React + TypeScript)         │
└──────────────────┬──────────────────────────────┘
                   │
        ┌──────────┼──────────┐
        ▼          ▼          ▼
   ┌────────┐ ┌────────┐ ┌────────┐
   │  REST  │ │WebSocket│ │GraphQL│
   │  API   │ │(realtime│ │(future)│
   └────┬───┘ └────┬────┘ └────────┘
        │          │
        └──────────┼─────────────────┐
                   ▼                 ▼
          ┌─────────────────┐  ┌──────────┐
          │  FastAPI Admin  │  │Prometheus│
          │     Backend     │  │ Metrics  │
          └────────┬────────┘  └──────────┘
                   │
        ┌──────────┼──────────┬──────────┐
        ▼          ▼          ▼          ▼
    ┌──────┐  ┌──────┐  ┌────────┐  ┌──────┐
    │Postgres│ │Redis │  │Temporal│  │MinIO │
    └──────┘  └──────┘  └────────┘  └──────┘
```

---

### Dashboard Pages

#### 1. Main Dashboard (Overview)

**Real-time metrics:**
- Active workflows count
- Total projects
- AI cost (daily/monthly)
- Success rate
- Resource utilization (CPU, memory, disk)

**Visualizations:**
- Live activity stream (WebSocket updates)
- Workflow status distribution (pie chart)
- Operations timeline (last 24 hours)
- Resource usage gauges

**Key features:**
- Auto-refreshing every 1-5 seconds
- Customizable widgets
- Drill-down to details

---

#### 2. Projects Management

**Features:**
- Grid/list view of all projects
- Project cards showing:
  - Quality score (0-100)
  - Last audit date
  - Critical issues count
  - Quick action buttons (Audit, Configure)
- Search and filter projects
- Bulk operations

**Project Detail View:**
- Real-time status (if workflow running)
- Tabbed interface:
  - **Overview:** Quality metrics, recent activity
  - **Audit History:** Past audit runs with results
  - **Findings:** Current issues by severity
  - **Standards:** View/edit project standards
  - **Costs:** AI spending for this project
  - **Activity Log:** Audit trail of all operations

**Drill-down capability:**
- Click project → see full details
- Live progress bar if audit running
- File-level findings browser
- Standards editor (YAML)

---

#### 3. Workflow Monitoring

**Real-time workflow tracking:**
- All active workflows displayed as cards
- Live progress updates via WebSocket
- Status indicators (running, completed, failed)
- Duration tracking
- Resource usage per workflow

**Workflow details (expandable):**
- Timeline visualization
- Activity list (each step with timing)
- Live logs streaming
- Error details if failed
- Retry/cancel actions

**Filters:**
- By project
- By status (running, completed, failed)
- By type (AUDIT, PLAN, BUILD, FIX)
- Date range

---

#### 4. System Monitoring

**Service health:**
- API Gateway status
- Temporal worker pool status
- PostgreSQL connection pool
- Redis cache status
- MinIO storage status

**Resource charts:**
- CPU usage (real-time line chart)
- Memory usage (real-time line chart)
- Disk I/O
- Network traffic

**Docker sandbox pool:**
- List of pre-warmed containers
- Status of each (idle, busy, warming)
- Resource usage per container

**Error tracking:**
- Recent errors/exceptions
- Error rate trends
- Stack traces and context

---

#### 5. AI Cost Analytics

**Cost dashboard:**
- Total spent (daily/monthly)
- Budget remaining with progress bar
- Cache savings (how much saved by caching)
- Average cost per operation

**Breakdown charts:**
- Cost by operation type (PLAN, BUILD, AUDIT, FIX)
- Cost by project
- Cost by model (GPT-4, GPT-4o, GPT-4o-mini)
- Cost trend (30-day line chart)

**Model usage table:**
- Calls per model
- Tokens used per model
- Cost per model
- Average cost per call

**Budget alerts:**
- Visual warnings at 80% budget
- Critical alerts at 90% budget
- Automatic notifications

---

#### 6. Settings & Configuration

**General settings:**
- System name
- Default project paths
- Max concurrent workflows
- Auto-run audits on push

**Security settings:**
- API key management
- Rate limit configuration
- Session timeout
- Audit log retention

**Cost limits:**
- Default daily/monthly budgets
- Per-project budget overrides
- Budget alert thresholds
- Auto-downgrade settings

**Notifications:**
- Email configuration
- Slack webhooks
- Discord webhooks
- Alert rules and conditions

**Integrations:**
- GitHub/GitLab tokens
- LLM API keys (OpenAI, Anthropic)
- Webhook endpoints
- MCP server configuration

---

### Real-Time Updates

**WebSocket implementation:**

```python
# Backend: Real-time event broadcasting
from fastapi import WebSocket
import socketio

sio = socketio.AsyncServer(async_mode='asgi')

@app.websocket("/ws/admin")
async def admin_websocket(websocket: WebSocket):
    await websocket.accept()
    
    # Subscribe to events
    async for event in event_stream():
        await websocket.send_json({
            "type": event.type,
            "data": event.data,
            "timestamp": event.timestamp
        })

# Broadcast from workflows
async def broadcast_event(event_type: str, data: dict):
    await sio.emit(event_type, data, room="admin")
```

**Frontend: React hooks**

```typescript
// useRealTimeMetrics.ts
export function useRealTimeMetrics() {
  const [metrics, setMetrics] = useState({})
  
  useEffect(() => {
    const socket = io('ws://localhost:8000/ws/admin')
    
    socket.on('workflow_started', (data) => {
      // Update metrics
    })
    
    socket.on('workflow_completed', (data) => {
      // Update metrics
    })
    
    return () => socket.disconnect()
  }, [])
  
  return metrics
}
```

**Event types broadcasted:**
- `workflow_started` - New workflow initiated
- `workflow_progress` - Progress update (percentage)
- `workflow_completed` - Workflow finished
- `workflow_failed` - Workflow error
- `metrics_update` - Periodic metrics refresh
- `cost_alert` - Budget threshold reached
- `system_alert` - System health issue

---

### Admin Features

#### User Management (Future)
- Admin/viewer roles
- API key scoping per user
- Activity audit per user
- Permission management

#### Bulk Operations
- Batch audit multiple projects
- Bulk standards update
- Export/import project configs
- Batch delete old audit results

#### Reporting
- Export audit reports (PDF, JSON, SARIF)
- Cost reports (CSV, Excel)
- Compliance reports
- Executive summaries

#### Alerting
- Email notifications
- Slack/Discord integration
- Webhook triggers
- Custom alert rules

#### Backup & Recovery
- Export project metadata
- Export standards configurations
- Backup audit history
- Restore configurations

---

### UI Component Library

**Built with shadcn/ui + Tailwind:**
- Modern, accessible components
- Dark mode support
- Responsive design (mobile, tablet, desktop)
- Consistent design system

**Key components:**
- `MetricCard` - Dashboard stat cards
- `ActivityStream` - Live event feed
- `WorkflowCard` - Collapsible workflow details
- `ResourceGauges` - CPU/memory/disk gauges
- `CostChart` - Various cost visualizations
- `FindingsList` - Security/quality findings
- `LogViewer` - Real-time log streaming

**Charts:**
- Line charts (time series data)
- Bar charts (comparisons)
- Pie charts (distributions)
- Area charts (stacked metrics)
- Heatmaps (activity patterns)

---

### Performance Optimizations

**Frontend:**
- Code splitting (lazy loading pages)
- Virtual scrolling (large lists)
- Debounced search/filters
- Memoized components
- Optimistic UI updates

**Backend:**
- WebSocket connection pooling
- Redis caching for metrics
- Database query optimization
- Pagination for large datasets
- Server-sent events (SSE) for logs

**Caching strategy:**
- Metrics: 5 second cache
- Project list: 30 second cache
- Standards: 5 minute cache
- Audit history: 1 minute cache

---

### Security

**Admin access control:**
- Separate admin API keys
- Role-based access (admin, viewer)
- Session management
- Activity audit logging

**Data protection:**
- Encrypted WebSocket (WSS)
- HTTPS only
- CSRF protection
- XSS prevention
- Rate limiting on admin endpoints

**Audit trail:**
- All admin actions logged
- Who did what when
- IP address tracking
- Export audit logs

---

### Deployment

**Docker container:**

```yaml
# docker-compose.yml (addition)
tron-admin:
  build:
    context: ./admin
    dockerfile: Dockerfile
  ports:
    - "3000:3000"
  environment:
    - VITE_API_URL=http://tron-api:8000
    - VITE_WS_URL=ws://tron-api:8000
  depends_on:
    - tron-api
```

**Build process:**
```bash
# Development
cd admin && npm run dev

# Production build
cd admin && npm run build

# Docker
docker build -t tron-admin:latest ./admin
```

**Nginx configuration (production):**
```nginx
server {
    listen 80;
    server_name admin.tron.local;
    
    # Serve React app
    location / {
        root /usr/share/nginx/html;
        try_files $uri $uri/ /index.html;
    }
    
    # Proxy API requests
    location /api/ {
        proxy_pass http://tron-api:8000;
    }
    
    # WebSocket upgrade
    location /ws/ {
        proxy_pass http://tron-api:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

---

## AI Cost Management System

### Overview

Tron includes comprehensive AI cost management to prevent budget overruns and optimize LLM usage. The system tracks every AI call, enforces budgets, intelligently selects models, and uses aggressive caching.

### Cost by Operation Mode

```
┌──────────────────────────────────────────────────┐
│ Mode      │ AI Usage │ Cost/Op  │ Volume │ Total │
├──────────────────────────────────────────────────┤
│ AUDIT     │ None     │ $0.00    │ High   │ $0    │
│           │ (tools)  │          │        │       │
├──────────────────────────────────────────────────┤
│ PLAN      │ High     │ $2-5     │ Low    │ ~$15  │
│           │ (design) │          │        │/month │
├──────────────────────────────────────────────────┤
│ BUILD     │ Very High│ $10-20   │ Medium │ ~$160 │
│           │ (coding) │          │        │/month │
├──────────────────────────────────────────────────┤
│ FIX       │ Medium   │ $3-8     │ Medium │ ~$100 │
│           │ (repair) │          │        │/month │
└──────────────────────────────────────────────────┘

With caching (67% hit rate): ~$90/month
With budget models for simple operations: ~$50/month
```

---

### Smart Model Selection

**Three-tier strategy:**

```python
class ModelTier(Enum):
    PREMIUM = "premium"    # GPT-4, Claude Sonnet 4
    STANDARD = "standard"  # GPT-4o, Claude Sonnet 3.5
    BUDGET = "budget"      # GPT-4o-mini, Claude Haiku
    LOCAL = "local"        # Ollama (free)

# Model pricing (per 1M tokens)
PRICING = {
    "gpt-4": {"input": 30.0, "output": 60.0},
    "gpt-4o": {"input": 5.0, "output": 15.0},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "claude-sonnet-4": {"input": 15.0, "output": 75.0},
    "claude-sonnet-3.5": {"input": 3.0, "output": 15.0},
    "claude-haiku": {"input": 0.25, "output": 1.25},
}
```

**Automatic model selection:**
- Complex operations (architecture, system design) → Premium models
- Standard operations (code generation) → Standard models
- Simple operations (fix suggestions, explanations) → Budget models
- Budget exhausted → Local models (Ollama)

**Auto-downgrade:**
- At 80% of budget → downgrade to cheaper models
- At 100% → use local models only
- Configurable per project

---

### Cost Tracking Database

```python
class LLMUsage(Base):
    """Track every LLM API call"""
    id: UUID
    project_id: UUID
    workflow_id: str
    mode: str  # PLAN, BUILD, AUDIT, FIX
    
    # LLM details
    provider: str  # "openai", "anthropic", "local"
    model: str  # "gpt-4", "claude-sonnet-4"
    
    # Usage
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_usd: float
    
    # Context
    operation: str  # "plan_architecture", "generate_code"
    duration_ms: int
    cached: bool  # Was this a cache hit?
    
    created_at: datetime

class ProjectCostLimit(Base):
    """Budget limits per project"""
    id: UUID
    project_id: UUID
    
    # Limits
    daily_limit_usd: float  # Default: $10
    monthly_limit_usd: float  # Default: $100
    
    # Current usage
    daily_spent_usd: float
    monthly_spent_usd: float
    
    # Reset dates
    daily_reset_at: datetime
    monthly_reset_at: datetime
    
    # Action when limit reached
    action_on_limit: str  # "block", "warn", "throttle"
```

---

### Caching Strategy

**Two-level cache:**

```python
class LLMCacheManager:
    """Multi-level caching to reduce costs"""
    
    async def get(self, prompt: str, model: str) -> Optional[str]:
        """Get cached response"""
        cache_key = sha256(f"{prompt}|{model}").hexdigest()
        
        # Level 1: Redis (hot cache, fast)
        cached = await redis.get(f"llm:cache:{cache_key}")
        if cached:
            return cached  # Cost: $0
        
        # Level 2: MinIO (warm cache, persistent)
        try:
            response = await minio.get_object("llm-cache", cache_key)
            content = await response.read()
            
            # Promote to Redis
            await redis.setex(f"llm:cache:{cache_key}", 3600, content)
            
            return content.decode()  # Cost: $0
        except:
            return None  # Cache miss - will call LLM
    
    async def set(self, prompt: str, model: str, response: str):
        """Cache response"""
        cache_key = sha256(f"{prompt}|{model}").hexdigest()
        
        # Store in both caches
        await redis.setex(f"llm:cache:{cache_key}", 3600, response)
        await minio.put_object("llm-cache", cache_key, response.encode())
```

**What gets cached:**
- PLAN mode: Architecture designs (rarely change)
- FIX mode: Fix suggestions for same errors
- Explanations: Error explanations

**What doesn't get cached:**
- BUILD mode: Unique code generation
- Interactive chat: Context-dependent

**Expected savings:** 60-80% reduction in LLM calls

---

### Budget Configuration

```yaml
# ~/.tron/cost-policy.yaml

cost_management:
  enabled: true
  
  # Default limits
  default_limits:
    daily: 10.00    # $10/day
    monthly: 100.00  # $100/month
    per_operation: 5.00  # Max $5 per operation
  
  # Auto-downgrade at threshold
  auto_downgrade: true
  downgrade_threshold: 0.8  # 80% of budget
  
  # What to do when limit reached
  on_limit_reached:
    action: "block"  # "block", "warn", "throttle"
    notify: true
    notify_email: "admin@example.com"
  
  # Model preferences
  operation_models:
    plan_architecture: "gpt-4"
    generate_code: "gpt-4o"
    suggest_fix: "gpt-4o-mini"
    explain_error: "gpt-4o-mini"
  
  # Fallback chain
  fallback_chain:
    - "gpt-4o"
    - "gpt-4o-mini"
    - "local"  # Ollama

# Per-project overrides
projects:
  critical-app:
    daily: 50.00
    monthly: 500.00
  
  experimental:
    daily: 2.00
    monthly: 20.00
```

---

### Cost Dashboard (Admin UI)

**Real-time cost tracking:**
- Total spent (daily/monthly)
- Budget remaining with progress bar
- Cache savings (how much saved)
- Average cost per operation

**Visualizations:**
- Cost by operation type (pie chart)
- Cost by project (bar chart)
- Cost by model (table)
- 30-day trend (line chart)

**Alerts:**
- 80% budget → Yellow warning
- 90% budget → Orange alert
- 100% budget → Red alert + block/throttle

---

### CLI Cost Commands

```bash
# View costs
$ tron cost status
┌────────────────────────────────────┐
│ AI Cost Summary                    │
├────────────────────────────────────┤
│ Today:  $2.45 / $10.00 (24%)      │
│ Month:  $12.30 / $100.00 (12%)    │
│                                    │
│ Cache Hit Rate: 67%                │
│ Savings: $8.20                     │
└────────────────────────────────────┘

# Set budget
$ tron cost set-limit my-app --daily 20 --monthly 200

# View breakdown
$ tron cost breakdown my-app --period month
```

---

### Local Model Fallback

**Ollama integration for zero-cost operation:**

```python
class LocalLLMClient:
    """Fallback to local models when budget exhausted"""
    
    async def complete(
        self,
        prompt: str,
        model: str = "codellama:13b"
    ) -> str:
        """Use Ollama (free)"""
        response = await httpx.post(
            "http://localhost:11434/api/generate",
            json={"model": model, "prompt": prompt}
        )
        return response.json()["response"]
```

**Automatic fallback:**
- Budget exhausted → Switch to local models
- LLM API down → Use local models
- Network issues → Use local models

---

## Project Structure

### Tron Codebase Structure

```
tron/
├── api/                           # FastAPI Gateway
│   ├── main.py                    # App entry point
│   ├── auth.py                    # Authentication middleware
│   ├── rate_limit.py              # Rate limiting
│   ├── routes/
│   │   ├── projects.py            # Project management
│   │   ├── audits.py              # Audit endpoints
│   │   ├── standards.py           # Standards endpoints
│   │   └── reports.py             # Report endpoints
│   └── models.py                  # Pydantic models
│
├── workflows/                     # Temporal Workflows
│   ├── audit_workflow.py          # AUDIT mode workflow
│   ├── plan_workflow.py           # PLAN mode workflow
│   ├── build_workflow.py          # BUILD mode workflow
│   └── fix_workflow.py            # FIX mode workflow
│
├── activities/                    # Temporal Activities
│   ├── standards/
│   │   ├── loader.py              # Load standards
│   │   ├── merger.py              # Merge hierarchy
│   │   └── validator.py           # Validate standards
│   ├── tools/
│   │   ├── ruff_runner.py         # Run ruff
│   │   ├── bandit_runner.py       # Run bandit
│   │   ├── pytest_runner.py       # Run pytest
│   │   └── coverage_runner.py     # Run coverage
│   ├── sandbox/
│   │   ├── docker_pool.py         # Docker container pool
│   │   ├── executor.py            # Execute in sandbox
│   │   └── security.py            # Security hardening
│   ├── evaluator.py               # Quality gate evaluator
│   └── reporter.py                # Report generator
│
├── database/
│   ├── models.py                  # SQLAlchemy models
│   ├── repositories.py            # Data access layer
│   ├── migrations/                # Alembic migrations
│   └── pools.py                   # Connection pooling
│
├── storage/
│   ├── minio_client.py            # MinIO/S3 client
│   └── artifact_store.py          # Artifact storage
│
├── cache/
│   ├── redis_client.py            # Redis client
│   └── cache_manager.py           # Cache operations
│
├── security/
│   ├── secrets.py                 # Secrets management
│   ├── encryption.py              # AES-256 encryption
│   ├── api_keys.py                # API key management
│   └── audit_log.py               # Audit logging
│
├── integrations/
│   ├── mcp_server/
│   │   ├── server.py              # MCP server
│   │   └── tools.py               # MCP tool definitions
│   ├── cli/
│   │   ├── main.py                # CLI entry point
│   │   ├── commands/              # CLI commands
│   │   └── config.py              # Config management
│   ├── ci_cd/
│   │   ├── github_action/
│   │   └── gitlab_ci/
│   └── admin_api/
│       ├── websocket.py           # WebSocket server
│       ├── events.py              # Event broadcasting
│       └── routes.py              # Admin-specific endpoints
│
├── standards/                     # Built-in standards
│   ├── defaults/
│   │   ├── security.yaml
│   │   ├── quality.yaml
│   │   └── testing.yaml
│   └── compliance/
│       ├── soc2/
│       ├── iso27001/
│       └── hipaa/
│
├── observability/
│   ├── logging.py                 # Structured logging
│   ├── metrics.py                 # Prometheus metrics
│   └── tracing.py                 # OpenTelemetry
│
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── e2e/
│   └── fixtures/
│
├── docker/
│   ├── Dockerfile.api             # API service
│   ├── Dockerfile.worker          # Temporal worker
│   ├── Dockerfile.sandbox         # Sandbox image
│   └── docker-compose.yml         # Local development
│
├── config/
│   ├── settings.py                # Application settings
│   └── logging.yaml               # Logging config
│
├── pyproject.toml                 # Dependencies
├── poetry.lock
├── alembic.ini                    # DB migrations
└── README.md

# Admin Frontend
admin/
├── src/
│   ├── app/
│   │   ├── App.tsx                # Main app component
│   │   ├── routes.tsx             # Route definitions
│   │   └── layout/
│   │       ├── Sidebar.tsx        # Navigation sidebar
│   │       ├── Header.tsx         # Top header bar
│   │       └── Layout.tsx         # Main layout wrapper
│   │
│   ├── pages/
│   │   ├── Dashboard.tsx          # Main overview dashboard
│   │   ├── Projects.tsx           # Projects list/grid
│   │   ├── ProjectDetail.tsx      # Single project drill-down
│   │   ├── Workflows.tsx          # Active workflows monitor
│   │   ├── SystemMonitoring.tsx   # System health dashboard
│   │   ├── CostAnalytics.tsx      # AI cost analytics
│   │   └── Settings.tsx           # System settings
│   │
│   ├── components/
│   │   ├── ui/                    # shadcn/ui components
│   │   │   ├── card.tsx
│   │   │   ├── button.tsx
│   │   │   ├── badge.tsx
│   │   │   └── [...]
│   │   ├── charts/
│   │   │   ├── LineChart.tsx
│   │   │   ├── BarChart.tsx
│   │   │   ├── PieChart.tsx
│   │   │   └── AreaChart.tsx
│   │   ├── MetricCard.tsx         # Dashboard metric card
│   │   ├── ActivityStream.tsx     # Live event feed
│   │   ├── WorkflowCard.tsx       # Workflow status card
│   │   ├── ResourceGauges.tsx     # CPU/memory gauges
│   │   ├── FindingsList.tsx       # Security findings
│   │   └── LogViewer.tsx          # Real-time log viewer
│   │
│   ├── hooks/
│   │   ├── useRealTimeMetrics.ts  # WebSocket metrics
│   │   ├── useProject.ts          # Project data hook
│   │   ├── useWorkflows.ts        # Workflows data hook
│   │   ├── useWebSocket.ts        # WebSocket connection
│   │   └── useCostData.ts         # Cost analytics hook
│   │
│   ├── services/
│   │   ├── api.ts                 # API client (axios)
│   │   ├── websocket.ts           # WebSocket client
│   │   └── auth.ts                # Authentication
│   │
│   ├── stores/
│   │   ├── useAppStore.ts         # Global state (Zustand)
│   │   ├── useAuthStore.ts        # Auth state
│   │   └── useMetricsStore.ts     # Metrics cache
│   │
│   ├── lib/
│   │   ├── utils.ts               # Utility functions
│   │   ├── constants.ts           # Constants
│   │   └── formatters.ts          # Data formatters
│   │
│   └── types/
│       ├── project.ts             # TypeScript types
│       ├── workflow.ts
│       ├── metrics.ts
│       └── index.ts
│
├── public/
│   ├── favicon.ico
│   └── assets/
│
├── package.json
├── vite.config.ts                 # Vite configuration
├── tailwind.config.js             # Tailwind CSS config
├── tsconfig.json                  # TypeScript config
├── Dockerfile                     # Admin UI Docker image
└── README.md

# User/Company Configuration
~/.tron/
├── config.yaml                    # Global config
├── secrets.yaml                   # Encrypted secrets
├── company-standards.yaml         # Company standards
└── validators/                    # Custom validators
    └── my_validator.py

# Project Configuration
/Users/khash/Projects/my-app/.tron/
├── project.yaml                   # Project metadata
├── standards.yaml                 # Project standards
├── quality-gates.yaml             # Quality gate definitions
└── .api-key                       # Project API key (gitignored)
```

---

## Architecture Decision Records

### ADR-001: Workflow Engine - Temporal

**Decision:** Use Temporal for workflow orchestration (not Celery)

**Rationale:**
- Multi-step workflows with durable state (PLAN, BUILD modes)
- Long-running operations (hours/days)
- Retry logic with exponential backoff
- Human-in-the-loop approval gates
- Workflow history and replay
- Error recovery and compensation

**Trade-offs:**
- More complex setup than Celery
- Steeper learning curve
- But: Won't need to rewrite when adding complex workflows

---

### ADR-002: Sandbox Isolation - Docker-in-Docker

**Decision:** Use Docker-in-Docker with security hardening

**Configuration:**
- Network disabled (network_mode: none)
- Read-only root filesystem
- CPU limit: 0.5 cores
- Memory limit: 512MB
- Timeout: 5 minutes
- No privileged mode
- All capabilities dropped

**Rationale:**
- Sufficient security for linters and custom validators
- Works on Mac, Linux, Windows
- Simple to debug and iterate
- Mature Docker Python SDK
- Can upgrade to Firecracker later if needed

**Rejected:** Firecracker (Linux-only), Kubernetes Jobs (overkill)

---

### ADR-003: Database Architecture - PostgreSQL + MinIO

**Decision:** Split structured data (PostgreSQL) and artifacts (MinIO)

**PostgreSQL stores:**
- Project metadata
- Audit run records
- Findings (file, line, severity)
- Standards versions
- API keys

**MinIO stores:**
- Full audit reports (JSON)
- SARIF output
- Tool outputs (ruff.json, bandit.json)
- Large logs
- Generated plans

**Rationale:**
- Query performance (relational in Postgres)
- Storage costs (artifacts cheaper in object storage)
- Scalability (Postgres won't bloat)

---

### ADR-004: Connection Pooling Strategy

**Decision:** Connection pools for all resources

**Pool Sizes:**
- PostgreSQL: 20 connections + 10 overflow
- Redis: 50 connections
- Docker containers: 10 pre-warmed
- HTTP client: 100 connections (LLM APIs)

**Rationale:**
- Prevent resource exhaustion under load
- Faster execution (pre-warmed containers)
- Better cost control (reuse connections)
- Horizontal scaling support

---

### ADR-005: Multi-Tenancy Model

**Decision:** Project isolation (not full multi-tenancy)

**Use case:** Single user/company with multiple projects

**Model:**
- All projects in one database
- `project_id` foreign key on all tables
- Application-level filtering
- API keys scoped to projects

**Future:** Can upgrade to schema-per-tenant or DB-per-tenant if needed

**Rationale:**
- Simpler for single-user case
- No tenant isolation overhead
- Easier to query across projects
- Sufficient security for use case

---

### ADR-006: Authentication Strategy

**Decision:** API keys with scopes (not OAuth2 for v1)

**API Key Model:**
- Stored hashed (bcrypt)
- Scoped permissions (`audit:read`, `audit:write`)
- Per-project access
- Rate limited
- Expiration dates

**Three access methods:**
1. MCP Server: API key in transport headers
2. REST API: Bearer token authentication
3. CLI: Config file with API keys

**Future:** Add OAuth2/OIDC for web users later

**Rationale:**
- Simple for CLI and CI/CD use
- Easy to rotate and revoke
- Sufficient for single-user/company

---

### ADR-007: Redis Topology

**Decision:** Single Redis instance with multiple DBs

**Layout:**
- DB 0: Cache (standards, tool results)
- DB 1: Temporal visibility (if needed)

**Rationale:**
- Single user/company = no cache starvation risk
- Simpler operations
- Can split to separate instances later if needed

**Rejected:** Two separate Redis instances (overkill for use case)

---

### ADR-008: Secrets Management

**Decision:** Encrypted config files (AES-256)

**Storage:**
```
~/.tron/secrets.yaml (encrypted at rest)
```

**Encryption:**
- Master key from environment or system keychain
- AES-256 cipher
- Automatic decryption on load
- Never logged or exposed

**Rationale:**
- Simple for single user
- Version controllable (encrypted)
- No external secret service needed

---

### ADR-009: Deployment Model

**Decision:** Docker Compose (not Kubernetes)

**Target:**
- Local development on Mac/Linux
- Single-server deployment for remote access

**Rationale:**
- No need for K8s complexity
- Single user/company doesn't need auto-scaling
- Easier to operate and debug
- Can migrate to K8s later if needed

---

### ADR-010: Admin UI Framework

**Decision:** React 18 + TypeScript with shadcn/ui

**Stack:**
- **Framework:** React 18 + TypeScript (type safety)
- **Build:** Vite (fast dev server, optimized builds)
- **State:** Zustand (lightweight, simple API)
- **UI:** shadcn/ui + Tailwind CSS (modern, accessible)
- **Charts:** Recharts + D3.js (declarative, flexible)
- **Real-time:** Socket.IO (WebSocket with fallbacks)

**Rationale:**
- React is standard for admin dashboards
- TypeScript prevents runtime errors
- shadcn/ui is modern, accessible, customizable
- Vite is faster than Webpack/CRA
- Zustand simpler than Redux
- WebSocket for real-time without polling overhead

**Rejected alternatives:**
- ❌ Vue.js: React ecosystem larger for admin UIs
- ❌ Angular: Too heavy, slower development
- ❌ Svelte: Smaller ecosystem, less familiar
- ❌ Next.js: SSR not needed for admin tool
- ❌ Material UI: shadcn/ui more modern and customizable

---

### ADR-011: Real-Time Updates Strategy

**Decision:** WebSocket (Socket.IO) for admin dashboard

**Implementation:**
- Server: FastAPI with Socket.IO server
- Client: Socket.IO client in React
- Event-driven architecture
- Broadcast from workflows/activities

**Event types:**
- Workflow lifecycle (started, progress, completed, failed)
- Metrics updates (every 1-5 seconds)
- Cost alerts (budget thresholds)
- System alerts (health issues)

**Rationale:**
- True real-time (no polling delay)
- Efficient (push vs pull)
- Bi-directional communication
- Automatic reconnection
- Room-based broadcasting (future multi-user)

**Rejected alternatives:**
- ❌ Polling: Wasteful, higher latency, more load
- ❌ Server-Sent Events: Unidirectional only
- ❌ GraphQL subscriptions: More complex setup

---

### ADR-012: Cost Management Strategy

**Decision:** Multi-tier model selection with caching

**Approach:**
1. **Smart model selection:**
   - Premium (GPT-4, Claude Sonnet 4) for complex tasks
   - Standard (GPT-4o, Claude Sonnet 3.5) for most tasks
   - Budget (GPT-4o-mini, Claude Haiku) for simple tasks
   - Local (Ollama) as zero-cost fallback

2. **Aggressive caching:**
   - Redis hot cache (1 hour)
   - MinIO warm cache (24 hours)
   - Content-hash based (deterministic)
   - Expected 60-80% hit rate

3. **Budget enforcement:**
   - Per-project daily/monthly limits
   - Automatic model downgrade at 80% budget
   - Block/warn/throttle options
   - Real-time tracking

**Cost tracking:**
- Every LLM call logged to database
- Per-operation breakdown
- Cost dashboard with alerts
- Model usage analytics

**Rationale:**
- Prevents cost explosion
- Gives visibility into spending
- Allows budget control
- Optimizes without sacrificing quality

---

### ADR-013: Graph-Based Database Design

**Decision:** Use PostgreSQL with graph extensions (ltree, pg_trgm) instead of a separate graph database

**Context:**
Tron's domain is inherently relationship-rich:
- Code files have dependencies (imports, requires)
- Findings can be related (duplicates, similar issues)
- Standards follow an inheritance hierarchy (default → company → project)
- File systems are hierarchical trees

**Alternatives Considered:**
1. **Pure relational** (foreign keys only) → Poor for transitive queries
2. **Neo4j/ArangoDB** (dedicated graph DB) → Operational complexity, two databases
3. **PostgreSQL + Apache AGE** → Immature, limited ecosystem
4. **PostgreSQL + ltree + recursive CTEs** → **CHOSEN**

**Approach:**
1. **Extensions:**
   - `ltree` for hierarchical paths (standards, file trees)
   - `pg_trgm` for similarity/fuzzy search
   - `btree_gist` for efficient ltree indexing

2. **Graph Tables:**
   - `code_files` (nodes with ltree directory_path)
   - `file_dependencies` (edges for imports/requires)
   - `finding_relationships` (edges for related findings)
   - `standards` (hierarchy with ltree path)

3. **Query Pattern:**
   - Recursive CTEs for transitive closure
   - ltree operators for hierarchical queries
   - Materialized views for common aggregations

4. **Performance:**
   - GiST indexes on ltree columns
   - Covering indexes on edge tables
   - Materialized views for expensive graph traversals
   - Partial indexes for common filters

**Benefits:**
- ✅ Single database (simpler operations)
- ✅ ACID transactions (critical for Tron)
- ✅ Excellent for mixed workload (OLTP + graph + analytics)
- ✅ Mature ecosystem (PgBouncer, replication, backups)
- ✅ Handles 1-5 hop queries efficiently (covers 99% of our needs)
- ✅ Can add AGE extension later if needed

**Trade-offs:**
- ⚠️ Deep traversals (>10 hops) slower than Neo4j
- ⚠️ No native graph algorithms (PageRank, community detection)
- ⚠️ Recursive CTEs can be verbose (vs Cypher)

**When to Reconsider:**
- If >50% of queries require deep traversals (>5 hops)
- If graph algorithms become core feature
- If graph data exceeds 100M edges

**Rationale:**
Tron's queries are mostly 1-3 hops (files → dependencies, findings → related), with transactional integrity critical for cost tracking and audit runs. PostgreSQL handles this perfectly while keeping operations simple.

**See:** [GRAPH_DATABASE_STANDARD.md](./GRAPH_DATABASE_STANDARD.md) for complete implementation guide (use for all applications).

---

## Key Differentiators

### vs. Traditional AI Coding Assistants (Cursor, Copilot, etc.)

| Feature | Traditional AI | Tron |
|---------|---------------|------|
| **Standards** | Hope AI follows | Enforced & validated |
| **Quality** | Inconsistent | Objective quality score |
| **Completion** | Subjective "done" | 100% or specific % complete |
| **Multi-project** | No shared learning | Centralized service |
| **Compliance** | Manual checks | Built-in (SOC 2, ISO, etc.) |
| **Monitoring** | None | Real-time admin dashboard |
| **Cost Control** | No visibility | Built-in cost tracking & limits |
| **Future-proof** | Tool-specific config | AI-agnostic API |

### vs. Stripe Minions

| Feature | Stripe Minions | Tron |
|---------|---------------|------|
| **Audience** | Stripe only | Any organization |
| **Planning** | Task-based | Architecture-first |
| **Quality** | Human review | Self-validating |
| **Standards** | Stripe-specific | Configurable hierarchy |
| **Modes** | Build only | PLAN + BUILD + AUDIT + FIX |
| **Monitoring** | Temporal UI | Real-time admin dashboard with full visibility |
| **Cost Management** | Not addressed | Built-in tracking, budgets, model selection |

### vs. Traditional QA Tools (SonarQube, etc.)

| Feature | Traditional QA | Tron |
|---------|---------------|------|
| **Integration** | Post-build scanning | Embedded in dev process |
| **Intelligence** | Rule-based | AI-powered |
| **Fix Mode** | Reports only | Can fix issues |
| **Context** | Code only | Full project context |
| **Planning** | None | Built-in |
| **Real-time Visibility** | Static reports | Live dashboard with drill-down |
| **Multi-project View** | Separate dashboards | Unified admin interface |

---

## Use Cases

### 1. New Project Initialization

```
Developer: "I need to build a SaaS platform for X"

Tron PLAN Mode:
  ├─ Asks clarifying questions
  ├─ Generates architecture
  ├─ Creates quality gates
  ├─ Sets up scaffolding
  └─ Configures standards

Developer: "Build user authentication"

Tron BUILD Mode:
  ├─ Implements JWT + MFA (per company standards)
  ├─ Writes tests (coverage: 85%)
  ├─ Generates API docs
  ├─ Validates security (PASS)
  └─ Returns: "Feature complete - 98% quality score"

Result: Production-ready code, first time.
```

### 2. Code Review & Remediation

```
Developer: *builds feature with multiple AI tools*

Developer: "Tron, audit this"

Tron AUDIT Mode:
  ├─ Scans against company standards
  ├─ Finds 12 violations (objective)
  │  ├─ 3 critical (security)
  │  ├─ 5 high (standards)
  │  └─ 4 medium (best practices)
  └─ Quality Score: 72%

Developer: "Fix critical issues"

Tron FIX Mode:
  ├─ Fixes 3 critical issues
  └─ Re-validates: 92%

Developer: "Audit again"

Tron: "Status unchanged - 92% (9 issues remain)"
  (No infinite loop - same issues reported)

Developer: "Fix remaining"

Tron: "100% - All standards met ✅"
```

### 3. Multi-Project Company Standard Enforcement

```
Company: Enforces FC Design System across 20 projects

~/.tron/company-standards.yaml:
  ui_ux:
    - "Only use FC color palette"
    - "Inter font for body"

Project A uses Tron → Standards enforced
Project B uses Tron → Standards enforced
Project C uses different AI tool → Calls Tron API → Standards enforced

Result: Consistent UI/UX across all projects
```

### 4. Compliance Audit Preparation

```
Company: Needs SOC 2 Type II certification

Tron AUDIT Mode (Compliance):
  ├─ Loads SOC 2 requirements
  ├─ Scans all codebases
  ├─ Generates compliance report
  │  ├─ CC6.1: Audit logging - 85% compliant
  │  ├─ CC6.2: Encryption - 100% compliant
  │  └─ CC6.6: RBAC - 92% compliant
  └─ Provides remediation steps

Tron FIX Mode:
  └─ Adds missing audit logs

Result: SOC 2 ready with audit trail
```

---

## Benefits

### For Developers
- ✅ No more infinite review loops
- ✅ Objective "done" criteria
- ✅ Can use any AI tool (Cursor, Claude, Copilot)
- ✅ Standards enforced automatically
- ✅ Production-ready code from day one

### For Engineering Managers
- ✅ Consistent code quality across team
- ✅ Enforced standards (not hope-based)
- ✅ Audit trails for compliance
- ✅ Reduced technical debt
- ✅ Faster code reviews

### For Companies
- ✅ Centralized governance
- ✅ Compliance-ready (SOC 2, ISO, HIPAA)
- ✅ Future-proof (AI-agnostic)
- ✅ Scalable across projects
- ✅ Reduced security risks

---

## Implementation Phases

### Phase 1: Secure Foundation (Weeks 1-4)

**Core Infrastructure:**
- [ ] Project structure & Docker Compose setup
- [ ] PostgreSQL with connection pooling (20+10)
- [ ] Redis with connection pooling (50)
- [ ] MinIO object storage
- [ ] Temporal workflow engine setup

**Security Layer:**
- [ ] API key authentication system
- [ ] Rate limiting (Redis-backed)
- [ ] Secrets management (AES-256 encryption)
- [ ] Docker sandbox with security hardening
- [ ] Audit logging framework

**Basic API:**
- [ ] FastAPI gateway with auth middleware
- [ ] Project registration endpoints
- [ ] Health checks and metrics

**Deliverables:**
- Secure, scalable infrastructure
- Authentication working end-to-end
- Docker sandbox executing safely

---

### Phase 2: Standards & AUDIT Mode (Weeks 5-8)

**Standards Engine:**
- [ ] Built-in standards library (security, quality, compliance)
- [ ] Standards hierarchy (default → company → project)
- [ ] Standards loader with caching
- [ ] YAML validation and schema

**AUDIT Workflow:**
- [ ] Temporal workflow for AUDIT mode
- [ ] Tool runners (ruff, bandit, pytest, coverage)
- [ ] Quality gate evaluator (deterministic)
- [ ] Report generator (JSON, SARIF)
- [ ] Findings storage (PostgreSQL + MinIO)

**Connection Pooling:**
- [ ] Database connection pool
- [ ] Redis connection pool
- [ ] Docker container pool (10 pre-warmed)
- [ ] HTTP client pool (for future LLM calls)

**Deliverables:**
- Full AUDIT mode working
- Standards enforcement operational
- All connections pooled for scale

---

### Phase 3: Integration & Admin UI (Weeks 9-12)

**MCP Server:**
- [ ] MCP server implementation
- [ ] Tool registration (`tron_audit_project`, etc.)
- [ ] Authentication for MCP (stdio + HTTP)
- [ ] Rate limiting per tool
- [ ] MCP client examples (Cursor, Claude)

**CLI:**
- [ ] Command-line interface (typer)
- [ ] Config file management
- [ ] Local project registration
- [ ] Interactive audit runs
- [ ] Report viewing

**CI/CD Integration:**
- [ ] GitHub Action
- [ ] GitLab CI template
- [ ] Generic CI/CD pattern
- [ ] SARIF output support
- [ ] PR comment integration

**Admin UI (Foundation):**
- [ ] React + TypeScript project setup
- [ ] shadcn/ui + Tailwind CSS integration
- [ ] WebSocket client implementation
- [ ] Authentication and routing
- [ ] Main dashboard (overview page)
- [ ] Basic metric cards and charts

**Deliverables:**
- AI agents can call Tron via MCP
- Developers can use Tron via CLI
- CI/CD can enforce Tron checks
- Basic admin dashboard operational

---

### Phase 4: PLAN Mode & Admin UI (Part 2) (Weeks 13-16)

**Planning Workflow:**
- [ ] Interactive questionnaire system
- [ ] Project blueprint generator
- [ ] Quality gates generator
- [ ] Test specifications generator
- [ ] Architecture document generator
- [ ] Scaffolding creator

**LLM Integration:**
- [ ] OpenAI SDK integration
- [ ] Anthropic SDK integration
- [ ] Prompt templates
- [ ] Response caching
- [ ] Cost tracking and optimization

**Admin UI (Advanced Features):**
- [ ] Projects management page
- [ ] Project detail drill-down view
- [ ] Workflow monitoring page
- [ ] Real-time workflow cards
- [ ] Live progress tracking
- [ ] Activity stream component

**Deliverables:**
- PLAN mode fully functional
- Generates comprehensive project blueprints
- Creates objective quality gates
- Advanced admin pages operational
- Real-time project monitoring

---

### Phase 5: BUILD & FIX Modes & Admin UI (Part 3) (Weeks 17-20)

**BUILD Mode:**
- [ ] Feature development workflow
- [ ] Builder activities (LLM-driven)
- [ ] Integrated validation (uses AUDIT)
- [ ] Iterative improvement loop
- [ ] Success criteria enforcement

**FIX Mode:**
- [ ] Issue remediation workflow
- [ ] Suggestion generator
- [ ] Auto-apply with approval gates
- [ ] Issue tracking (resolved/unresolved)
- [ ] Progress monitoring

**Admin UI (Complete Feature Set):**
- [ ] System monitoring dashboard
- [ ] Resource usage charts (CPU, memory, disk)
- [ ] Docker sandbox pool monitor
- [ ] AI cost analytics dashboard
- [ ] Cost breakdowns and trends
- [ ] Settings & configuration pages
- [ ] User management (if multi-user)
- [ ] Notification configuration
- [ ] Integration management

**Advanced Features:**
- [ ] Webhook support
- [ ] Custom validator SDK
- [ ] Extended compliance modules
- [ ] Export/import configurations
- [ ] Bulk operations UI

**Deliverables:**
- Full Tron feature set operational
- End-to-end PLAN → BUILD → AUDIT → FIX workflow
- Complete admin UI with all features
- Production-ready platform

---

### Phase 6: Polish & Documentation (Weeks 21-24)

**Documentation:**
- [ ] User guide
- [ ] API documentation (OpenAPI)
- [ ] MCP integration guide
- [ ] CI/CD setup guides
- [ ] Standards authoring guide
- [ ] Troubleshooting guide

**Testing:**
- [ ] Integration test suite
- [ ] End-to-end test scenarios
- [ ] Load testing
- [ ] Security testing
- [ ] Chaos testing

**Optimization:**
- [ ] Performance profiling
- [ ] Query optimization
- [ ] Cache tuning
- [ ] Resource limit tuning

**Deliverables:**
- Comprehensive documentation
- Production-hardened system
- Performance benchmarks

---

## Docker Compose Configuration

### Complete Production-Ready Setup

```yaml
version: '3.8'

services:
  # PostgreSQL Database
  postgres:
    image: postgres:15-alpine
    container_name: tron-postgres
    environment:
      POSTGRES_DB: tron
      POSTGRES_USER: tron
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - postgres-data:/var/lib/postgresql/data
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U tron"]
      interval: 10s
      timeout: 5s
      retries: 5
    command:
      - "postgres"
      - "-c"
      - "max_connections=50"          # Connection limit
      - "-c"
      - "shared_buffers=256MB"        # Memory tuning
      - "-c"
      - "effective_cache_size=1GB"
  
  # Redis Cache & Queue
  redis:
    image: redis:7-alpine
    container_name: tron-redis
    command: redis-server --appendonly yes --maxmemory 512mb
    volumes:
      - redis-data:/data
    ports:
      - "6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5
  
  # MinIO Object Storage
  minio:
    image: minio/minio:latest
    container_name: tron-minio
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: ${MINIO_USER}
      MINIO_ROOT_PASSWORD: ${MINIO_PASSWORD}
    volumes:
      - minio-data:/data
    ports:
      - "9000:9000"
      - "9001:9001"
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9000/minio/health/live"]
      interval: 30s
      timeout: 20s
      retries: 3
  
  # Temporal Server
  temporal:
    image: temporalio/auto-setup:latest
    container_name: tron-temporal
    depends_on:
      postgres:
        condition: service_healthy
    environment:
      - DB=postgresql
      - DB_PORT=5432
      - POSTGRES_USER=tron
      - POSTGRES_PWD=${POSTGRES_PASSWORD}
      - POSTGRES_SEEDS=postgres
      - DYNAMIC_CONFIG_FILE_PATH=config/dynamicconfig/development.yaml
    ports:
      - "7233:7233"   # gRPC
      - "8080:8080"   # Web UI
    volumes:
      - ./config/temporal:/etc/temporal/config/dynamicconfig
  
  # Temporal Web UI
  temporal-ui:
    image: temporalio/ui:latest
    container_name: tron-temporal-ui
    depends_on:
      - temporal
    environment:
      - TEMPORAL_ADDRESS=temporal:7233
    ports:
      - "8081:8080"
  
  # Tron API Gateway
  tron-api:
    build:
      context: .
      dockerfile: docker/Dockerfile.api
    container_name: tron-api
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
      temporal:
        condition: service_started
      minio:
        condition: service_healthy
    environment:
      # Database
      DATABASE_URL: postgresql+asyncpg://tron:${POSTGRES_PASSWORD}@postgres:5432/tron
      DB_POOL_SIZE: 20
      DB_MAX_OVERFLOW: 10
      
      # Redis
      REDIS_URL: redis://redis:6379/0
      REDIS_POOL_SIZE: 50
      
      # MinIO
      MINIO_ENDPOINT: minio:9000
      MINIO_ACCESS_KEY: ${MINIO_USER}
      MINIO_SECRET_KEY: ${MINIO_PASSWORD}
      MINIO_SECURE: "false"
      
      # Temporal
      TEMPORAL_HOST: temporal:7233
      
      # Security
      SECRET_KEY: ${SECRET_KEY}
      TRON_MASTER_KEY: ${TRON_MASTER_KEY}
      
      # App
      LOG_LEVEL: INFO
      WORKERS: 4
    ports:
      - "8000:8000"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock  # For Docker sandbox
      - ~/.tron:/root/.tron:ro                      # Config files
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
  
  # Tron Temporal Workers (scaled to 3)
  tron-worker:
    build:
      context: .
      dockerfile: docker/Dockerfile.worker
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
      temporal:
        condition: service_started
      minio:
        condition: service_healthy
    environment:
      DATABASE_URL: postgresql+asyncpg://tron:${POSTGRES_PASSWORD}@postgres:5432/tron
      REDIS_URL: redis://redis:6379/0
      MINIO_ENDPOINT: minio:9000
      MINIO_ACCESS_KEY: ${MINIO_USER}
      MINIO_SECRET_KEY: ${MINIO_PASSWORD}
      TEMPORAL_HOST: temporal:7233
      TRON_MASTER_KEY: ${TRON_MASTER_KEY}
      LOG_LEVEL: INFO
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - ~/.tron:/root/.tron:ro
    deploy:
      replicas: 3  # 3 worker instances for parallel execution
    command: python -m tron.worker
  
  # Tron Admin UI
  tron-admin:
    build:
      context: ./admin
      dockerfile: Dockerfile
    container_name: tron-admin
    depends_on:
      tron-api:
        condition: service_healthy
    environment:
      - VITE_API_URL=http://tron-api:8000
      - VITE_WS_URL=ws://tron-api:8000
      - VITE_APP_NAME=Tron Admin
    ports:
      - "3000:80"  # Nginx serves on port 80
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:80"]
      interval: 30s
      timeout: 10s
      retries: 3

volumes:
  postgres-data:
    driver: local
  redis-data:
    driver: local
  minio-data:
    driver: local

networks:
  default:
    name: tron-network
```

### Environment Variables (.env)

```bash
# Database
POSTGRES_PASSWORD=your_secure_password_here

# MinIO
MINIO_USER=tron
MINIO_PASSWORD=your_minio_password_here

# Application Security
SECRET_KEY=your_secret_key_for_jwt_signing
TRON_MASTER_KEY=your_master_encryption_key_base64

# Optional: LLM API Keys (for PLAN/BUILD modes)
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
```

### Quick Start Commands

```bash
# Generate secure keys
export SECRET_KEY=$(openssl rand -base64 32)
export TRON_MASTER_KEY=$(openssl rand -base64 32)

# Start all services
docker-compose up -d

# Check status
docker-compose ps

# View logs
docker-compose logs -f tron-api

# Scale workers
docker-compose up -d --scale tron-worker=5

# Stop all services
docker-compose down

# Clean volumes (WARNING: deletes all data)
docker-compose down -v
```

### Service URLs

- **Tron Admin UI:** http://localhost:3000 ⭐ Main interface
- **Tron API:** http://localhost:8000
- **API Docs:** http://localhost:8000/docs
- **Temporal UI:** http://localhost:8081
- **MinIO Console:** http://localhost:9001
- **PostgreSQL:** localhost:5432
- **Redis:** localhost:6379

---

## Success Metrics

### Development Quality
- **Code Quality Score:** 90%+ on first submission
- **Security Vulnerabilities:** 0 critical/high on release
- **Test Coverage:** 85%+ (company standard)
- **Standards Compliance:** 100%

### Developer Experience
- **Infinite Loop Elimination:** 0 instances
- **Review Cycles:** 1-2 max (vs. 5+ before)
- **Time to Production:** 50% reduction
- **Developer Satisfaction:** >8/10

### Business Impact
- **Compliance Audit Time:** 70% reduction
- **Security Incidents:** 80% reduction
- **Technical Debt:** 60% reduction
- **Cross-team Consistency:** 95%+

---

## Open Questions

1. **ISO Agent Intelligence:**
   - What AI models for different ISO types?
   - How specialized should ISOs be?
   - Dynamic ISO spawning strategy?

2. **Standards Customization:**
   - How flexible should custom validators be?
   - Versioning strategy for standards?
   - Override conflict resolution?

3. **Performance & Scaling:**
   - How many concurrent projects?
   - ISO worker pool sizing?
   - Database sharding strategy?

4. **Integration Points:**
   - CI/CD integration (GitHub Actions, GitLab CI)?
   - IDE plugins (VS Code, JetBrains)?
   - Slack/Teams notifications?

5. **Business Model:**
   - Open-source core + enterprise features?
   - SaaS vs. self-hosted?
   - Pricing model?

---

## Risks & Mitigation

| Risk | Impact | Mitigation |
|------|--------|------------|
| **AI Hallucination** | ISO generates bad code | Multi-layer validation, code review gates |
| **Performance** | Slow audit times | Parallel ISO execution, caching, incremental scans |
| **Cost** | High AI API costs | Optimize prompts, cache results, use smaller models for simple tasks |
| **Adoption** | Developers resist | Frictionless integration, clear ROI demonstration |
| **Standards Drift** | Company standards become outdated | Versioning system, regular reviews |
| **Compliance Gaps** | Missing regulatory requirements | Partner with compliance experts, regular audits |

---

## Conclusion

Tron represents a paradigm shift from **hope-based AI assistance** to **enforced AI governance**. By combining:

1. **Plan-first architecture** (objective completion criteria)
2. **Centralized standards enforcement** (company-wide consistency)
3. **Multi-mode operation** (PLAN → BUILD → AUDIT → FIX)
4. **AI-agent agnostic design** (works with any tool via MCP, REST, CLI)
5. **Security-first approach** (sandboxing, auth, secrets, audit logging)
6. **Built-in scalability** (connection pooling, pre-warmed containers, Temporal workflows)
7. **Real-time monitoring** (comprehensive admin dashboard with full visibility)
8. **Cost management** (AI spending tracking, budgets, model optimization)

Tron solves the critical problems facing AI-assisted development:
- ✅ Eliminates infinite review loops (objective quality gates)
- ✅ Ensures consistent code quality (deterministic validation)
- ✅ Enforces company standards (hierarchical inheritance)
- ✅ Provides secure execution (Docker sandboxing)
- ✅ Scales with your needs (connection pooling, horizontal workers)
- ✅ Integrates everywhere (MCP for AI agents, REST for CI/CD, CLI for developers)
- ✅ Full visibility (real-time dashboard showing all projects, workflows, and resources)
- ✅ Cost control (track AI spending, set budgets, optimize model selection)

**Key Design Principles:**

1. **Build Once, Build Right**
   - No temporary "v1" solutions
   - Temporal for workflows (supports complex multi-step flows)
   - Connection pooling from day one
   - Security baked in, not bolted on

2. **Single User/Company Focus**
   - Optimized for multiple projects, not multi-tenancy
   - Simple config-based setup
   - Docker Compose (no Kubernetes complexity)
   - Local or single-server deployment

3. **Objective, Deterministic Validation**
   - Quality gates defined upfront
   - Tools produce reproducible results
   - Clear pass/fail criteria
   - No subjective LLM judgment in gates

4. **Four Access Methods**
   - Admin Web UI (real-time monitoring and management)
   - MCP Server (for AI agents)
   - REST API (for CI/CD, webhooks)
   - CLI (for local development)
   - All secured with API keys and rate limiting

**Technology Decisions:**

| Component | Choice | Why |
|-----------|--------|-----|
| Workflow Engine | Temporal | Multi-step flows, durable state, error recovery |
| Database | PostgreSQL | Proven, scalable, JSONB support |
| Object Storage | MinIO | S3-compatible, local & cloud |
| Cache/Queue | Redis | Fast, simple, single instance |
| Sandbox | Docker-in-Docker | Secure, debuggable, works everywhere |
| Authentication | API Keys with scopes | Simple for CI/CD and CLI |
| Admin UI | React + TypeScript | Modern, real-time, responsive |
| Real-time Updates | WebSocket | Live monitoring without polling |
| Deployment | Docker Compose | Right-sized for use case |

**Next Steps:**

**Phase 1 (Weeks 1-4): Secure Foundation**
- Infrastructure setup (PostgreSQL, Redis, MinIO, Temporal)
- Security layer (auth, rate limiting, secrets, sandboxing)
- Basic API with authentication working

**Phase 2 (Weeks 5-8): Standards & AUDIT**
- Standards engine (hierarchy, loading, caching)
- AUDIT workflow (tools, evaluation, reporting)
- Connection pooling operational

**Phase 3 (Weeks 9-12): Integration**
- MCP server (AI agent access)
- CLI (developer access)
- CI/CD integration (GitHub Actions, GitLab CI)

**Ready to start building.**

---

**Document Version:** 2.3 Final (Production-Ready with Graph Design)  
**Last Updated:** April 11, 2026  
**Status:** Undergoing improvements based on 10-agent expert review  
**Expert Reviews:** Initial 6-agent review incorporated; 10-agent deep review completed; fixes in progress
