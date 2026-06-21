# Technical Requirements Document (TRD) — Tron

**Audience:** Engineers implementing or operating Tron.  
**Companion:** **`docs/project/BRD.md`** (business outcomes). Open engineering backlog: **`docs/project/MASTER_PROPOSAL_TODO.md`**. **Documentation map:** **`docs/BLUEPRINT.md`**.

## 1. System overview

Tron runs as **Docker Compose–friendly services**: FastAPI (**`tron-api`**), Temporal worker (**`tron-worker`**), optional **sandbox** HTTP runner, Postgres, Redis, MinIO, Vault patterns per **`docker-compose.yml`**. Primary UI builds to **`frontend/dist`** for nginx.

## 2. Core runtime paths

| Concern | Implementation |
|---------|----------------|
| **Audits** | **`AuditWorkflow`** (Temporal) or background executor; **`AuditExecutor`** loads repo content, **`AuditManager`** runs ISO agents concurrently (**`asyncio.gather`** in **`tron/agents/manager.py`** `_dispatch_agents`), merge → Layer 3 (**`tron/services/layer3_findings.py`**) → persist findings. |
| **Verification** | Pipeline described in **`docs/architecture/ZERO_DRIFT_VERIFICATION_PIPELINE.md`**; execution verifier **`tron/verification/execution_verifier.py`**. |
| **Threat signals** | **`tron/services/threat_intel.py`** (OSV + advisory keywords); **`BuilderISO`** attaches **`threat_intel_alerts`** to audit metrics → **`audit_runs.threat_intel_alerts_json`**. |
| **Standards / gates** | **`tron/standards/engine.py`**; **`POST /api/audits/{id}/evaluate-quality-gates`**. |
| **Handoff** | **`tron/services/scan_handoff_export.py`**, **`tron/services/agent_handoff.py`** after audit completion when **`projects.agent_handoff_path`** set. |

## 3. Major modules (`tron/`)

| Module | Role |
|--------|------|
| **`tron/api/`** | REST routes, auth, scopes, admin session, WebSocket audit progress. |
| **`tron/workflows/`** | Temporal workflows + **`activities.py`** (audit phases, build/evolve/fix). |
| **`tron/agents/`** | ISO agents, **`AuditManager`**, prompts (**`tron/prompts/`**). |
| **`tron/services/`** | Repo scan, graph sync, SARIF import, finding triage, sandbox client, path filters. |
| **`tron/infra/`** | LLM client, budget/reservation, observability, DB. |

## 4. Data and migrations

- Alembic under **`alembic/`**; models **`tron/domain/models.py`**.
- Graph: **`code_files`**, **`file_dependencies`**, ltree **`directory_path`** — **`tron/services/graph_sync.py`**, **`tron/services/graph_analytics.py`**.

## 5. Interfaces

- **REST** — Projects, audits, findings (triage + suppressions), standards, workflow-runs, graph, costs, integrations (e.g. audit webhook schema), api-keys (see **`docs/reference/API_REFERENCE.md`** and OpenAPI where current).
- **CLI** — **`python -m tron.cli`**.
- **MCP** — **`python -m tron.mcp`**.

## 6. Testing and quality bars

- Full suite: **`pytest tests/`** (project convention: green except known skips).
- CI: **`.github/workflows/ci.yml`** — import smoke, unit+integration subset, ruff, bandit.

## 7. Verified deliveries index

Row-level evidence (routes, workflows, migrations, tests) lives in **`docs/project/REQUIREMENTS_TRACEABILITY.md`** — do not duplicate here; update that file when closing requirements.

## 8. Remaining technical backlog

**Proposal-aligned:** none — **`SEC-5`** deep verification second pass is **Done** (**`deep_verify_follow_up_findings`** + **`apply_deep_verify_retry_pass_to_outputs`**; see **`MASTER_PROPOSAL_TODO.md`** evidence pointers).

**Deferred:** certified attestation packs — **ADR-002** (no implementation milestone).

## 9. Roadmap (non-blocking enhancements)

Aligned with strategic direction; not required to clear proposal backlog:

- Optional **audit profile** (e.g. prod-oriented vs full-repo)—called out as not required for SEC-3 Done.
- **Issue-tracker sync** for dismiss/suppress (optional).
- **Golden corpus expansion / thresholds** — optional; the **prompt regression CI gate** is already automated (**`.github/workflows/prompt-regression.yml`**: daily cron plus path-filtered PR/push on `tron/agents/**`, `tron/schemas/**`, `tests/golden_suite/**`).
- Graph **`DATABASE_SCHEMA.md`** / **`AI_AGENT_ARCHITECTURE.md`** aspirational features until explicitly scheduled.

## 10. Ops and hardening

**Not feature scope:** **`docs/project/HARDENING_REVIEW_TODO.md`** (TLS, CORS prod, sandbox isolation hardening beyond defaults — seccomp mount/gVisor, horizontal scaling docs, Grafana validation, docs hygiene).

## 11. References

- **`docs/architecture/`** — verification pipeline, agents, DB, WebSocket.
- **`docs/operations/`** — ports, runbooks.
- **`docs/security/`** — TLS runbook, sandbox threat model.
