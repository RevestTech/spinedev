# Tron API Reference

Auto-generated API documentation for Tron API v1.0

## Overview

The Tron API provides programmatic access to:
- Health checks and readiness probes
- Project management (CRUD)
- Audit lifecycle and findings
- Standards and quality gate enforcement
- AI-driven project evolution (EVOLVE mode)
- Real-time progress via WebSocket
- GDPR data subject rights (export/delete)
- Cost analytics and dashboards

Base URL: `https://api.tron.example.com/api`

### Authentication

All API endpoints (except `/health` and `/ready`) require an API key in the `X-API-Key` header:

```bash
curl -H "X-API-Key: your-api-key" https://api.tron.example.com/api/projects
```

### API Documentation

- **Swagger UI**: `/api/docs`
- **ReDoc**: `/api/redoc`
- **OpenAPI JSON**: `/api/openapi.json`

All endpoints return JSON. See individual sections below for request/response schemas.

---

## Health & Readiness

### GET /health

**Liveness probe** — indicates if the API process is alive.

**Response (200 OK):**
```json
{
  "status": "ok",
  "service": "tron-api",
  "uptime_seconds": 12345.5
}
```

**No authentication required.**

---

### GET /ready

**Readiness probe** — indicates if all dependencies (database, Redis) are healthy.

**Response (200 OK):** All dependencies healthy
```json
{
  "status": "ready",
  "checks": {
    "database": "ok",
    "redis": "ok"
  }
}
```

**Response (503 Service Unavailable):** At least one dependency failed
```json
{
  "status": "not_ready",
  "checks": {
    "database": "error: connection timeout",
    "redis": "ok"
  }
}
```

**No authentication required.**

---

## Projects

### POST /api/projects

**Create a new project.**

**Request:**
```json
{
  "name": "string (required, 1-255 chars)",
  "description": "string (optional)",
  "repo_url": "string (optional, must be valid URL)",
  "default_branch": "string (default: 'main')"
}
```

**Response (201 Created):**
```json
{
  "id": "uuid",
  "name": "My Project",
  "description": "A security audit project",
  "repo_url": "https://github.com/example/myproject",
  "default_branch": "main",
  "status": "active",
  "created_at": "2026-04-13T10:30:00Z",
  "updated_at": "2026-04-13T10:30:00Z"
}
```

**Auth:** Required (X-API-Key)

---

### GET /api/projects

**List all projects with pagination.**

**Query Parameters:**
- `page` (integer, default: 1, min: 1)
- `page_size` (integer, default: 20, min: 1, max: 100)
- `status` (string, optional) — filter by status (e.g., "active", "deleted")

**Response (200 OK):**
```json
{
  "items": [
    {
      "id": "uuid",
      "name": "Project 1",
      "description": "...",
      "repo_url": "...",
      "default_branch": "main",
      "status": "active",
      "created_at": "2026-04-13T10:30:00Z",
      "updated_at": "2026-04-13T10:30:00Z"
    }
  ],
  "total": 42,
  "page": 1,
  "page_size": 20
}
```

**Auth:** Required (X-API-Key)

---

### GET /api/projects/{project_id}

**Get a specific project by ID.**

**Path Parameters:**
- `project_id` (uuid, required)

**Response (200 OK):**
```json
{
  "id": "uuid",
  "name": "My Project",
  "description": "...",
  "repo_url": "...",
  "default_branch": "main",
  "status": "active",
  "created_at": "2026-04-13T10:30:00Z",
  "updated_at": "2026-04-13T10:30:00Z"
}
```

**Response (404 Not Found):** Project does not exist or is deleted

**Auth:** Required (X-API-Key)

---

### PUT /api/projects/{project_id}

**Update a project.**

**Path Parameters:**
- `project_id` (uuid, required)

**Request:**
```json
{
  "name": "string (optional)",
  "description": "string (optional)",
  "repo_url": "string (optional)",
  "default_branch": "string (optional)",
  "status": "string (optional)"
}
```

**Response (200 OK):** Updated project object

**Response (404 Not Found):** Project does not exist

**Auth:** Required (X-API-Key)

---

### DELETE /api/projects/{project_id}

**Soft-delete a project.**

Deleted projects are marked with `deleted_at` timestamp and `status="deleted"` but remain in the database for audit/compliance.

**Path Parameters:**
- `project_id` (uuid, required)

**Response (204 No Content):** Deletion successful

**Response (404 Not Found):** Project does not exist

**Auth:** Required (X-API-Key)

---

## Audits

### POST /api/audits

**Start a new audit run for a project.**

**Request:**
```json
{
  "project_id": "uuid (required)",
  "branch": "string (default: 'main')",
  "commit_hash": "string (optional)",
  "trigger_type": "string (default: 'manual')"
}
```

**Response (201 Created):**
```json
{
  "id": "uuid",
  "project_id": "uuid",
  "status": "queued",
  "progress": 0,
  "findings_total": 0,
  "findings_critical": 0,
  "findings_high": 0,
  "findings_medium": 0,
  "findings_low": 0,
  "started_at": "2026-04-13T10:30:00Z",
  "completed_at": null,
  "error_message": null,
  "created_at": "2026-04-13T10:30:00Z"
}
```

**Status values:** `queued`, `running`, `completed`, `failed`

**Auth:** Required (X-API-Key)

---

### GET /api/audits

**List audit runs with optional filters.**

**Query Parameters:**
- `project_id` (uuid, optional) — filter by project
- `status` (string, optional) — filter by status (queued, running, completed, failed)
- `page` (integer, default: 1)
- `page_size` (integer, default: 20, max: 100)

**Response (200 OK):**
```json
{
  "items": [
    {
      "id": "uuid",
      "project_id": "uuid",
      "status": "completed",
      "progress": 100,
      "findings_total": 15,
      "findings_critical": 2,
      "findings_high": 5,
      "findings_medium": 8,
      "findings_low": 0,
      "started_at": "2026-04-13T10:30:00Z",
      "completed_at": "2026-04-13T11:15:00Z",
      "error_message": null,
      "created_at": "2026-04-13T10:30:00Z"
    }
  ],
  "total": 127,
  "page": 1,
  "page_size": 20
}
```

**Auth:** Required (X-API-Key)

---

### GET /api/audits/{audit_id}

**Get a specific audit run status and summary.**

**Path Parameters:**
- `audit_id` (uuid, required)

**Response (200 OK):** Audit summary object (same as POST response)

**Response (404 Not Found):** Audit does not exist

**Auth:** Required (X-API-Key)

---

### GET /api/audits/{audit_id}/findings

**List findings for a specific audit run.**

**Path Parameters:**
- `audit_id` (uuid, required)

**Query Parameters:**
- `severity` (string, optional) — filter by severity (critical, high, medium, low)
- `status` (string, optional) — filter by status (new, triaged, fixed, ignored)
- `page` (integer, default: 1)
- `page_size` (integer, default: 50, max: 200)

**Response (200 OK):**
```json
{
  "items": [
    {
      "id": "uuid",
      "audit_run_id": "uuid",
      "project_id": "uuid",
      "fingerprint": "sha256-hash",
      "rule_id": "SEC-001",
      "file_path": "src/auth/password.py",
      "line_start": 42,
      "line_end": 45,
      "severity": "critical",
      "category": "credential-exposure",
      "title": "Hardcoded API Key Detected",
      "description": "API key found in source code at line 42",
      "suggested_fix": "Move API key to environment variable",
      "status": "new",
      "code_snippet": "API_KEY = 'sk-...'",
      "created_at": "2026-04-13T10:45:00Z"
    }
  ],
  "total": 15,
  "page": 1,
  "page_size": 50
}
```

**Severity levels:** `critical`, `high`, `medium`, `low`

**Finding statuses:** `new`, `triaged`, `fixed`, `ignored`

**Auth:** Required (X-API-Key)

---

### POST /api/audits/{audit_id}/evaluate-quality-gates

**Evaluate merged quality gates against completed audit findings.**

Combines the project's custom quality gates (if any) with the system-wide defaults and evaluates them against the counts and categories of findings in the specified audit run.

**Path Parameters:**
- `audit_id` (uuid, required)

**Response (200 OK):**
```json
{
  "audit_id": "uuid",
  "project_id": "uuid",
  "passed": true,
  "criteria_results": [
    {
      "check": "no_critical_findings",
      "severity": "critical",
      "max_count": 0,
      "actual_count": 0,
      "passed": true
    },
    {
      "check": "max_high_severity",
      "severity": "high",
      "max_count": 5,
      "actual_count": 2,
      "passed": true
    }
  ]
}
```

**Response (404 Not Found):** Audit run or project not found.

**Auth:** Required (X-API-Key)

---

## Standards & Quality Gates

### GET /api/standards/defaults

**Retrieve the built-in system-wide default quality gate contract.**

Returns the JSON definition of the default security, testing, and compliance gates.

**Response (200 OK):**
```json
{
  "version": 1,
  "security": {
    "required": true,
    "criteria": [
      { "check": "no_critical_findings", "severity": "critical", "max_count": 0 },
      { "check": "max_high_severity", "severity": "high", "max_count": 5 }
    ]
  },
  "testing": { "required": false, "criteria": [] },
  "compliance": { "required": false, "criteria": [] }
}
```

**Auth:** Required (X-API-Key)

---

### GET /api/standards/merged

**Get the effective quality gates for a project, merging defaults with optional project-specific overrides.**

**Query Parameters:**
- `project_id` (uuid, optional) — if provided, merges project-level and company-level overrides.

**Response (200 OK):**
```json
{
  "project_id": "uuid",
  "gates": {
    "version": 1,
    "security": { "..." : "..." }
  }
}
```

**Auth:** Required (X-API-Key)

---

### GET /api/standards/control-packs

**List available reference control packs (e.g., SOC2, HIPAA, ISO).**

**Response (200 OK):**
```json
{
  "items": [
    { "id": "soc2" },
    { "id": "hipaa" },
    { "id": "iso-27001" }
  ]
}
```

**Auth:** Required (X-API-Key)

---

### GET /api/standards/control-packs/{pack_id}

**Get the JSON definition for a specific reference control pack.**

**Path Parameters:**
- `pack_id` (string, required)

**Response (200 OK):** JSON object representing the pack definition.

**Response (404 Not Found):** Unknown control pack ID.

**Auth:** Required (X-API-Key)

---

## Agent Modes

### POST /api/evolve/{project_id}

**Start EVOLVE workflow — iterative improvement of a project based on a directive.**

Triggers a Temporal workflow where the agent analyzes the project and applies fixes or improvements according to the provided instruction.

**Path Parameters:**
- `project_id` (uuid, required)

**Request Body:**
```json
{
  "directive": "string (required, min 3 chars)"
}
```

**Response (200 OK):**
```json
{
  "workflow_id": "evolve-uuid-suffix",
  "status": "started"
}
```

**Response (503 Service Unavailable):** Temporal is not enabled on this instance.

**Auth:** Required (X-API-Key)

---

## WebSocket (Real-time Progress)

### WebSocket /ws/audits/{audit_id}

**Stream live audit progress events in real-time.**

**Connection Parameters:**
- `audit_id` (uuid, required, in path)
- `token` (string, required as query param) — API key for authentication (if WS_REQUIRE_AUTH=true)

**Example JavaScript:**
```javascript
const ws = new WebSocket('wss://api.tron.example.com/ws/audits/{audit_id}?token=your-api-key');

ws.onmessage = (event) => {
  const message = JSON.parse(event.data);
  console.log('Event:', message.event);
  console.log('Data:', message.data);
};

ws.onclose = () => console.log('Audit complete or connection closed');
```

**Event Types:**

1. **snapshot** — Initial audit status (sent when client connects)
```json
{
  "event": "snapshot",
  "audit_run_id": "uuid",
  "data": {
    "status": "running",
    "progress": 45,
    "findings_total": 8,
    "findings_critical": 1,
    "findings_high": 3,
    "findings_medium": 4,
    "findings_low": 0,
    "started_at": "2026-04-13T10:30:00Z",
    "completed_at": null,
    "error_message": null
  }
}
```

2. **progress_update** — Audit progress increment
```json
{
  "event": "progress_update",
  "audit_run_id": "uuid",
  "timestamp": "2026-04-13T10:35:00Z",
  "data": {
    "progress": 50,
    "current_phase": "security_analysis",
    "message": "Scanning for SQL injection vulnerabilities"
  }
}
```

3. **finding_discovered** — New finding detected
```json
{
  "event": "finding_discovered",
  "audit_run_id": "uuid",
  "timestamp": "2026-04-13T10:36:00Z",
  "data": {
    "finding_id": "uuid",
    "severity": "high",
    "rule_id": "SEC-042",
    "file_path": "src/db.py",
    "line": 123,
    "title": "SQL Injection Vulnerability"
  }
}
```

4. **agent_status** — Agent state change
```json
{
  "event": "agent_status",
  "audit_run_id": "uuid",
  "timestamp": "2026-04-13T10:37:00Z",
  "data": {
    "agent": "SecurityAnalyzer",
    "status": "running",
    "findings_count": 5
  }
}
```

5. **audit_completed** — Audit finished successfully (terminal event)
```json
{
  "event": "audit_completed",
  "audit_run_id": "uuid",
  "timestamp": "2026-04-13T11:00:00Z",
  "data": {
    "status": "completed",
    "total_findings": 15,
    "duration_seconds": 1800,
    "summary": "Found 2 critical, 5 high, 8 medium severity issues"
  }
}
```

6. **audit_failed** — Audit encountered an error (terminal event)
```json
{
  "event": "audit_failed",
  "audit_run_id": "uuid",
  "timestamp": "2026-04-13T10:50:00Z",
  "data": {
    "status": "failed",
    "error_message": "Database connection timeout after 30 minutes",
    "error_code": "TIMEOUT"
  }
}
```

7. **heartbeat** — Keep-alive ping (every 30 seconds of inactivity)
```json
{
  "event": "heartbeat"
}
```

8. **close** — Connection closing (final message before close frame)
```json
{
  "event": "close",
  "data": {
    "reason": "Audit completed"
  }
}
```

**Close Codes:**
- 1000 — Normal closure, audit completed
- 1013 — Too many connections, try again later
- 4001 — Authentication required

**Auth:** Required (token as query param)

---

## GDPR / Data Subject Rights

### POST /api/gdpr/export

**Export all user data as JSON.**

Includes all projects, audit runs, and findings accessible to the user.

**Query Parameters:**
- `user_id` (uuid, optional) — specific user to export (admin-only if not self)

**Response (200 OK):**
```json
{
  "user_id": "uuid",
  "export_timestamp": "2026-04-13T10:30:00Z",
  "projects": [
    {
      "id": "uuid",
      "name": "Project Name",
      "description": "...",
      "repo_url": "...",
      "created_at": "2026-04-13T10:30:00Z",
      "updated_at": "2026-04-13T10:30:00Z"
    }
  ],
  "audit_runs": [
    {
      "id": "uuid",
      "project_id": "uuid",
      "status": "completed",
      "findings_total": 15,
      "started_at": "2026-04-13T10:30:00Z",
      "completed_at": "2026-04-13T11:15:00Z"
    }
  ],
  "findings": [
    {
      "id": "uuid",
      "audit_run_id": "uuid",
      "rule_id": "SEC-001",
      "file_path": "src/app.py",
      "severity": "high",
      "title": "Hardcoded Secret",
      "status": "new",
      "created_at": "2026-04-13T10:45:00Z"
    }
  ],
  "total_records": 127
}
```

**Auth:** Required (X-API-Key)

---

### POST /api/gdpr/delete

**Right to be forgotten — soft-delete all user data.**

All projects and related audit runs/findings are soft-deleted (marked as deleted but retained for compliance).

**Query Parameters:**
- `user_id` (uuid, required) — user whose data to delete

**Response (200 OK):**
```json
{
  "user_id": "uuid",
  "deletion_timestamp": "2026-04-13T10:30:00Z",
  "projects_deleted": 5,
  "audit_runs_deleted": 42,
  "findings_deleted": 127,
  "total_records_deleted": 174
}
```

**Auth:** Required (X-API-Key)

---

### GET /api/gdpr/retention-policy

**Retrieve the data retention policy configuration.**

**Response (200 OK):**
```json
{
  "project_retention_days": 2555,
  "audit_run_retention_days": 1095,
  "finding_retention_days": 1095,
  "soft_delete_grace_period_days": 30,
  "last_updated": "2026-04-13T10:30:00Z"
}
```

Default values:
- Projects: 7 years (2555 days)
- Audit runs: 3 years (1095 days)
- Findings: 3 years (1095 days)
- Soft-delete grace period: 30 days

**Auth:** Required (X-API-Key)

---

## Costs & Analytics

### GET /api/costs/dashboard

**Get aggregated cost dashboard data for analytics UI.**

**Query Parameters:**
- `start_date` (ISO format, optional) — defaults to 30 days ago
- `end_date` (ISO format, optional) — defaults to now

**Response (200 OK):**
```json
{
  "summary": {
    "total_cost_usd": 1250.50,
    "total_tokens": 5000000,
    "total_audits": 42,
    "avg_cost_per_audit": 29.78,
    "period_start": "2026-03-14T00:00:00Z",
    "period_end": "2026-04-13T23:59:59Z"
  },
  "by_provider": [
    {
      "provider": "openai",
      "model": "gpt-4",
      "cost_usd": 800.00,
      "tokens": 3000000,
      "requests": 1200
    },
    {
      "provider": "anthropic",
      "model": "claude-3-opus",
      "cost_usd": 450.50,
      "tokens": 2000000,
      "requests": 800
    }
  ],
  "by_project": [
    {
      "project_id": "uuid",
      "project_name": "My Web App",
      "cost_usd": 450.00,
      "audit_count": 15
    }
  ],
  "daily_trend": [
    {
      "date": "2026-04-13",
      "cost_usd": 50.25,
      "tokens": 200000,
      "audits": 2
    }
  ],
  "budget_limit_usd": 5000.0,
  "budget_used_pct": 25.01
}
```

**Auth:** Required (X-API-Key)

---

### GET /api/costs/summary

**Get cost summary for the last N days.**

**Query Parameters:**
- `days` (integer, default: 30, min: 1, max: 365)

**Response (200 OK):**
```json
{
  "total_cost_usd": 1250.50,
  "total_tokens": 5000000,
  "total_audits": 42,
  "avg_cost_per_audit": 29.78,
  "period_start": "2026-03-14T00:00:00Z",
  "period_end": "2026-04-13T23:59:59Z"
}
```

**Auth:** Required (X-API-Key)

---

## Error Responses

All error responses follow this format:

```json
{
  "detail": "Error message describing what went wrong"
}
```

**Common HTTP Status Codes:**

| Code | Meaning |
|------|---------|
| 200 | Success |
| 201 | Created |
| 204 | No Content (successful deletion) |
| 400 | Bad Request (invalid input) |
| 401 | Unauthorized (missing/invalid API key) |
| 404 | Not Found |
| 422 | Unprocessable Entity (validation error) |
| 429 | Too Many Requests (rate limit exceeded) |
| 500 | Internal Server Error |
| 503 | Service Unavailable (dependency failure) |

---

## Rate Limiting

The API implements rate limiting per API key:
- **100 requests per minute** for standard endpoints
- **10 requests per minute** for long-running operations (audits)
- **1000 WebSocket connections** per instance maximum

Rate limit status is returned in response headers:
```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 87
X-RateLimit-Reset: 1681234567
```

---

## Pagination

List endpoints support cursor-based pagination:

**Query Parameters:**
- `page` — page number (1-indexed, default: 1)
- `page_size` — results per page (default: 20, max: 100)

**Response:**
```json
{
  "items": [...],
  "total": 542,
  "page": 1,
  "page_size": 20
}
```

Calculate total pages: `ceil(total / page_size)`

---

## API Documentation Tools

### Swagger UI

Interactive API documentation with "Try it out" functionality.

URL: `/api/docs`

Uses: Swagger/OpenAPI 3.0

### ReDoc

Beautiful, responsive API documentation optimized for reading.

URL: `/api/redoc`

Uses: OpenAPI 3.0

### OpenAPI JSON

Raw OpenAPI specification for code generation or external tooling.

URL: `/api/openapi.json`

---

## SDK & Client Libraries

Official SDKs:
- **Python**: `pip install tron-sdk`
- **JavaScript/TypeScript**: `npm install @tron/sdk`
- **Go**: `go get github.com/tron-project/sdk-go`

Open-source generators for other languages available at https://openapi-generator.tech/

---

## Support & Issues

- GitHub Issues: https://github.com/tron-project/tron/issues
- Slack Community: #tron-api
- Email: api-support@tron-project.io

Last updated: 2026-04-13
