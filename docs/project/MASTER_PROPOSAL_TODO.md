# Master checklist: Original proposal (`docs/archive/PROPOSAL.md`) vs implementation

**Status:** Formerly deferred proposal items (**EVOLVE**, **sandbox pre-warm/pool**, **reference control packs**) are now **Done** in code with tests; **third-party certified attestation packs** remain **[D]** per **ADR-002**. Post-scan triage for **other** repos: templates in **`tron/agent_handoff_templates/`**; worker **auto-updates managed handoff regions** and **append-only `tron.md` activity** (**`tron/services/scan_handoff_export.py`**) when **`projects.agent_handoff_path`** is set (Alembic **`007`**); CLI **`audit handoff`** / **`scripts/init_tron_scan_handoff.sh`** for manual export. Full **`pytest tests/`** green (1 skipped); run **`frontend`** **`npm run build`** after UI changes.

**Source:** PROPOSAL v2.3 + `PROPOSAL_VS_REALITY.md`  
**Rule:** Items below track delivery; `[x]` = implemented in codebase, `[~]` = partial, `[ ]` = not started, **`[D]`** = explicitly deferred (see `docs/REQUIREMENTS_TRACEABILITY.md`).

## Current snapshot (where we left off)

- **Sprint S1–S9:** **Done** (see table below + evidence column).
- **Operating modes AUDIT / PLAN / BUILD / FIX / EVOLVE:** **Done** in code + UI/CLI/MCP where listed.
- **Explicit gap vs proposal:** only **[D]** **third-party certified attestation packs** (**`docs/project/ADR-002-compliance-certified-packs.md`**); reference control packs + APIs are **Done**.
- **Scanned other repos (FCNow, etc.):** handoff is **Done** — **`tron/services/scan_handoff_export.py`** refreshes **managed** regions in `TRON_POST_SCAN.md`, `CLAUDE.md`, `AGENTS.md`, `.cursor/rules/tron-scan-followups.mdc`; **append-only** **`tron.md`** run log when **`TRON_HANDOFF_APPEND_TRON_MD`** is true (default); **`projects.agent_handoff_path`** + **`TRON_AGENT_HANDOFF`** for worker; CLI **`audit handoff`**; **`scripts/init_tron_scan_handoff.sh`**. Tests: **`tests/unit/test_scan_handoff_export.py`**, **`tests/unit/test_agent_handoff.py`**.
- **Quality bar:** full **`pytest tests/`** expected green (known **1 skipped**); **`frontend`** **`npm run build`** after UI edits.

## Sprint checklist (fixed scope — do not expand without updating this table)

| ID | Outcome | Validation | Status |
|----|---------|------------|--------|
| **S1** | For every new audit row, `audit_runs.workflow_id` matches the dispatcher: Temporal uses `audit-{audit_run_id}`; non-Temporal uses `background-audit-{audit_run_id}`. After Temporal `start_workflow`, `workflow_run_id` is the client handle run id (not a project placeholder). | `tests/integration/test_audits_integration.py` **`TestAuditWorkflowRowMetadata`** (asserts via **`GET /api/workflow-runs`**). | [x] |
| **S2** | WebSocket `GET /ws/audits/{audit_id}?token=…` accepts the **master** key **or** a scoped API key whose scopes satisfy **`audits`** (or `*`), same privilege model as REST. | `tests/unit/test_ws.py` **`TestAuthenticateWs`** (`scoped` + `projects` cases). | [x] |
| **S3** | **`GET /api/workflow-runs`** is covered by integration tests: 200 with seeded rows, 401 without key, **`workflows`** scope required (403 when only **`projects`**). | `tests/integration/test_workflow_runs_integration.py` (four cases). | [x] |
| **S4** | MCP exposes workflow-runs listing and audit quality-gate evaluation aligned with REST. | **`tron/mcp/__main__.py`**: **`tron_list_workflow_runs`**, **`tron_evaluate_audit_quality_gates`**. | [x] |
| **S5** | Primary UI surfaces plan/build artifacts on the project page and can start a BUILD workflow. | **`frontend/src/pages/ProjectDetail.tsx`** (plan/last-build cards, **Run build**); **`frontend/src/api.ts`** **`startBuildWorkflow`**. | [x] |
| **S6** | **EVOLVE** operating mode: Temporal **`EvolveWorkflow`**, **`POST /api/evolve/{project_id}`**, persist **`evolve_artifact_json`** (Alembic **`006`**). | **`tron/workflows/evolve_workflow.py`**, **`save_evolve_result`** in **`tron/workflows/activities.py`**, **`tron/api/routes/modes.py`**, **`tests/unit/test_evolve_workflow.py`**; CLI **`tron.cli evolve`**; MCP **`tron_start_evolve`**; **`frontend`** **Run evolve**. | [x] |
| **S7** | **Sandbox warm-up + client pool:** optional **`SANDBOX_PREWARM_EXECUTIONS`** (capped 10) on **`tron-sandbox`** startup; shared HTTP pool **`TRON_SANDBOX_HTTP_POOL_SIZE`** toward **`TRON_SANDBOX_URL`** in **`tron/services/sandbox_client.py`**. | **`tron/sandbox/server.py`** lifespan; **`docker-compose.yml`** env on **`tron-sandbox`** / **`tron-worker`**; `.env.example`. | [x] |
| **S8** | **Built-in compliance reference packs** (not attestation): JSON packs + list/get API + merge into **`ComplianceISO`** (project **`compliance_control_pack_ids`** + **`TRON_COMPLIANCE_PACKS`**). | **`tron/standards/control_packs.py`**, **`GET /api/standards/control-packs`**, **`tests/unit/test_control_packs.py`**, **`tests/integration/test_standards_control_packs.py`**. | [x] |
| **S9** | **Audit runs do not stick ``queued`` on hard failure:** Temporal **`AuditWorkflow`** calls **`mark_audit_run_failed`** on uncaught workflow errors; **`POST /api/audits`** marks **`failed`** if Temporal dispatch throws after the row is committed; worker registers the activity. | **`tron/workflows/audit_workflow.py`**, **`mark_audit_run_failed`** in **`tron/workflows/activities.py`**, **`tron/worker.py`**, **`tron/api/routes/audits.py`**; **`tests/unit/test_workflow_handlers.py`** **`test_run_calls_mark_failed_then_reraises_on_phase_error`**. | [x] |

## Operating modes

- [x] **AUDIT** — Temporal `AuditWorkflow`, multi-ISO, synthesis, Layer 3 sandbox path
- [x] **PLAN** — `PlanWorkflow` + questionnaire persisted on project + interactive **`frontend` Plan wizard** (`/projects/:id/plan`); optional git push via `TRON_PLAN_GIT_TOKEN`
- [x] **BUILD** — `BuildWorkflow` + builder ISO + `last_build_result_json` + **in-workflow quality-gate evaluation** (`evaluate_build_quality_gates` / `tron/standards/engine.py`) + **`python -m compileall` validation** (`run_build_repo_validation`) + optional **git branch push** (`.tron/build-result.json` on `tron/build-*`, `TRON_BUILD_GIT_TOKEN` or `TRON_PLAN_GIT_TOKEN`; `tron/services/git_build_report.py`)
- [x] **FIX** — `FixWorkflow`; **`POST /verify`** on sandbox + `verify_fix` (see `docs/REQUIREMENTS_TRACEABILITY.md`)
- [x] **EVOLVE** — **`EvolveWorkflow`** (Builder ISO + directive) + **`evolve_artifact_json`**; **`POST /api/evolve/{project_id}`**; CLI / MCP / **`frontend`**

## ISO agents (proposal: 6 types)

- [x] Security ISO
- [x] Builder ISO
- [x] Performance ISO
- [x] QA ISO — wired into `AuditWorkflow` (full scope)
- [x] Compliance ISO — `ComplianceISO` + audit activity
- [x] Documentation ISO — `DocumentationISO` + audit activity

## Standards & quality gates

- [x] Default quality gates JSON — `tron/standards/defaults.py`
- [x] Merge engine — `tron/standards/engine.py` (order: **default → company → project**; company layer is `projects.company_quality_gates_json` per row, not a shared org entity)
- [x] **GET `/api/standards/defaults`**, **GET `/api/standards/merged?project_id=`**
- [x] **Quality gates persistence** — `quality_gates_json` / `company_quality_gates_json` via **PUT `/api/projects/{project_id}`** (`ProjectUpdate`), not a separate `/quality-gates` route
- [x] **POST `/api/audits/{id}/evaluate-quality-gates`** — objective pass/fail vs findings
- [x] **GET `/api/standards/control-packs`**, **GET `/api/standards/control-packs/{id}`** — built-in reference packs (`tron/standards/packs/`)

## Interfaces

- [x] REST — extended with plan/build/**evolve**/fix/standards, **workflow-runs**, **graph** (full, subtree, **transitive**, **impact**, **standards-chain**), **api-keys**, **standards/control-packs**
- [x] **CLI** — `python -m tron.cli` (Typer): `projects`, `audit` (incl. **`audit reconcile-stale-queued`**, **`audit handoff`** → merges managed regions in `TRON_POST_SCAN.md` + agent breadcrumbs into **`--dest`** app repo), `plan`, `build`, `evolve`, `fix`
- [x] **Stale ``queued`` audit cleanup** — **`POST /api/audits/reconcile-stale-queued`** (master only); startup hook **`TRON_RECONCILE_STALE_QUEUED_ON_STARTUP`** + **`TRON_STALE_QUEUED_AUDIT_MINUTES`** (`tron/api/main.py`, **`docker-compose.yml`** **`tron-api`**); **`tron/services/audit_reconcile.py`**; **`tests/integration/test_audit_reconcile_integration.py`**
- [x] **MCP** — `python -m tron.mcp` (stdio); tools call API via `TRON_API_URL` + `TRON_API_KEY`; **same venv as the API** via root `requirements.txt` (`mcp[cli]`)
- [x] **Admin UI** — `frontend/`: **Session gate** + **`/login`** (vault `auth/admin-password` or master-key fallback → httpOnly JWT cookie), Overview, projects, audits, **Live** (`/live`), **Workflows**, costs, system health, **Settings** (optional `X-API-Key` for automation), **Sign out**; API: **`POST /api/admin/login`**, **`POST /api/admin/logout`**, **`GET /api/admin/me`**; `require_api_key` + WebSocket accept admin cookie (`tron/api/routes/admin_auth.py`, `tron/api/admin_session.py`, `tron/api/middleware/auth.py`, `tron/api/routes/ws.py`)

## Infrastructure (proposal highlights)

- [x] Temporal + workers
- [x] Postgres, Redis, MinIO (compose)
- [x] `tron-sandbox` HTTP + Layer 3 remote execution (`TRON_SANDBOX_URL`)
- [x] LLM **Redis cache** — optional TTL cache in `LLMClient` (`LLM_CACHE_ENABLED=1`, `LLM_CACHE_TTL_SECONDS`)
- [x] **Pre-warmed sandbox path + HTTP pool** — **`SANDBOX_PREWARM_EXECUTIONS`** (optional, max 10 trivial runs after **`tron-sandbox`** startup); **`TRON_SANDBOX_HTTP_POOL_SIZE`** keep-alive pool for remote **`/execute`** in **`tron/services/sandbox_client.py`**
- [x] **Full observability stack** — all services defined in `docker-compose.yml`; operators run the compose set for metrics/tracing (delivery = defined stack + app OTEL hooks, not a single-process “always-on” bundle)
- [x] MCP / CLI **production** packaging — unified **`requirements.txt`**; `requirements-mcp.txt` is a **`-r requirements.txt`** alias for backward compatibility

## Security / cost / compliance modules

- [x] API key auth — **master key** + **`api_keys` table** (hashed, scopes JSONB, Alembic `005`); **POST/GET/DELETE `/api/api-keys`** (master only); **per-route scope enforcement** — `tron/api/middleware/scopes.py` + router dependencies
- [x] Rate limits (existing)
- [x] Cost routes + **enforcement** — **`TRON_LLM_BUDGET_USD`**, **`TRON_LLM_BUDGET_ENFORCE`**, soft warning at **`TRON_LLM_SOFT_CAP_PCT`**; **`assert_llm_budget_allows_estimated_call`** in `LLMClient.complete` before billable provider calls (cache hits skip new spend)
- [x] Compliance **scanning** — **`ComplianceISO`** in audit pipeline (`tron/agents/compliance_iso.py`, **`AuditExecutor`** / **`AuditWorkflow`** activities). Evidence: **`tests/unit/test_audit_executor.py`** (six ISO agents), **`tests/unit/test_workflow_handlers.py`** (compliance agent wiring).
- [x] **Built-in SOC2 / HIPAA / ISO27001 reference control packs** — shipped JSON + API + **`ComplianceISO`** context (**ADR-002** distinguishes attestation).
- [D] **Third-party certified attestation / vendor pack subscriptions** — not a product deliverable (**ADR:** `docs/project/ADR-002-compliance-certified-packs.md`).

## Graph / analytics

- [x] **GET `/api/projects/{id}/graph`** — nodes/edges from `code_files` / `file_dependencies`
- [x] **GET `/api/projects/{id}/graph/subtree?path_prefix=`** — **ltree** `directory_path <@ prefix` (requires `directory_path` populated on rows)
- [x] **GET `/api/projects/{id}/graph/transitive?root_path=`** — transitive internal dependency closure (`tron/services/graph_analytics.py`)
- [x] **GET `/api/projects/{id}/graph/impact?target_path=`** — reverse-impact (upstream dependents)
- [x] **GET `/api/projects/{id}/graph/standards-chain`** — active `standards` rows for the project ordered by `hierarchy_path`

## Local LLM

- [x] **Ollama** — models `ollama/<model_id>` in `LLMClient` + **`OLLAMA_BASE_URL`** (see `.env.example`)

## Migrations

- **Docker / API container:** with **`TRON_AUTO_MIGRATE=true`** (compose default), the API runs **`alembic upgrade head`** before opening the async pool — see **`tron/infra/db/migrate.py`**, **`tron/api/main.py`**, **`.env.example`**.
- **Manual / CI:** after pull, still valid:

```bash
alembic upgrade head
```

Adds among others: `api_keys` table (`005`); **`evolve_artifact_json`**, **`compliance_control_pack_ids`** on **`projects`** (`006`); **`agent_handoff_path`** on **`projects`** (`007`).

## Remaining gaps (explicit)

_None tracked against the current proposal milestone. **[D]** rows are explicit exclusions (third-party attestation packs — **ADR-002**)._

**Scanned applications (FCNow, etc.):** Tron does **not** own per-app triage under `docs/audit-reports/`. Prefer **`agent_handoff_path`** on the project so the **worker** refreshes managed regions in the four agent files when each audit completes; otherwise **`python -m tron.cli audit handoff`** or **`scripts/init_tron_scan_handoff.sh`**. See **`tron/agent_handoff_templates/README.md`** (app-repo **`tron.md`** append-only **Tron activity** log; **`TRON_HANDOFF_APPEND_TRON_MD`**).

## Milestone closure (checklist vocabulary)

Sprint and interface checklists above are **[x] Done** except the single **[D]** attestation exclusion (**ADR-002**, **`docs/REQUIREMENTS_TRACEABILITY.md`**).

## Prioritized backlog (proposal alignment)

| Priority | Item | Status |
|----------|------|--------|
| Done | **FIX** `verify_fix` → sandbox | Shipped (`docs/REQUIREMENTS_TRACEABILITY.md`) |
| Done | **Workflow runs** admin view | **`GET /api/workflow-runs`**, **`/workflows`** in `frontend` |
| Done | **Budget enforcement** | **`tron/infra/llm/budget.py`** + `LLMClient.complete` |
| Done | **Graph** ltree + analytics | **`/graph/subtree`**, **`/graph/transitive`**, **`/graph/impact`**, **`/graph/standards-chain`**; `code_files.directory_path` via **`tron/services/graph_sync.py`** `_directory_path_as_ltree` (GiST `CAST(... AS ltree)`) |
| Done | **API keys** table + routes + scopes | Alembic **`005`**, **`/api/api-keys`**, **`tron/api/middleware/scopes.py`**, Settings UI |
| Done | **Ollama** | **`ollama/`** model prefix in `LLMClient` |
| Done | **MCP + main venv** | **`requirements.txt`** includes **`mcp[cli]`**; **`requirements-mcp.txt`** → `-r requirements.txt` |
| Done | **Scanned-app Tron handoff** | **`tron/services/scan_handoff_export.py`** (managed markers + merge), **`tron/agent_handoff_templates/`**, **`scripts/init_tron_scan_handoff.sh`**, **`tron/cli.py` `audit handoff`**, **`tron/services/agent_handoff.py`** (auto after audit if **`agent_handoff_path`** set), **`.cursor/rules/tron-scanned-app-handoff.mdc`**. |

---

*Last updated: **Scanned-app handoff** — managed markers + merge + **`tron.md`** append-only activity (**`TRON_HANDOFF_APPEND_TRON_MD`**, **`docker-compose.yml`**); templates + **`AGENTS.md`** / traceability aligned. Prior: **`007`** `agent_handoff_path`, **S9**, **S6–S8**, nginx **`/api`**, **`TRON_AUTO_MIGRATE`**; attestation **[D]** (ADR-002).*
