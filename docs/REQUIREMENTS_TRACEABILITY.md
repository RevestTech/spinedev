# Requirements traceability and compliance policy

This document defines **how Tron matches documented requirements** so we do not rely on informal “good enough” judgments.

## Sources of truth (in order)

1. **`docs/archive/PROPOSAL.md`** — product intent and full feature set (large; not all items are in scope for every milestone).
2. **`docs/project/MASTER_PROPOSAL_TODO.md`** — living checklist vs the proposal (must stay current).
3. **This file** — rules for marking items **done**, **partial**, or **out of scope**.

## Status vocabulary (strict)

| Mark | Meaning |
|------|---------|
| **Done** | Implemented, covered by automated tests where practical, and observable in running services (API route, workflow, UI, or config). |
| **Partial** | Implemented with documented limitations; **not** advertised as complete in user-facing copy. |
| **Not started** | No production path; stubs do not count. |
| **Deferred** | Explicitly excluded by ADR or milestone (e.g. third-party **certified attestation** packs only — see ADR-002). |

**Rule:** If something is **Partial**, the limitation must appear in `MASTER_PROPOSAL_TODO.md` (or an ADR), not only in chat.

## Verified deliveries (evidence index)

| Requirement (proposal / backlog) | Evidence |
|-----------------------------------|----------|
| **FIX verification uses execution sandbox when available** | `tron/workflows/activities.py` `verify_fix`; `tron/sandbox/server.py` **`POST /verify`**. |
| **Workflow monitoring (admin)** | **`GET /api/workflow-runs`** (`tron/api/routes/workflow_runs.py`); UI **`frontend/src/pages/WorkflowRuns.tsx`** (`/workflows`). Integration coverage: **`tests/integration/test_workflow_runs_integration.py`**. |
| **LLM budget enforcement** | **`tron/infra/llm/budget.py`**; **`LLMClient.complete`** calls **`assert_llm_budget_allows_estimated_call`**; settings **`TRON_LLM_BUDGET_ENFORCE`**, **`TRON_LLM_SOFT_CAP_PCT`**. |
| **Scoped API keys + per-route scopes** | Alembic **`005_api_keys.py`**; model **`ApiKey`**; auth **`tron/api/middleware/auth.py`** (`lookup_scoped_api_key_scopes`); enforcement **`tron/api/middleware/scopes.py`**; **`/api/api-keys`** (`tron/api/routes/api_keys.py`); Settings UI. |
| **Product admin UI (browser session)** | **`POST /api/admin/login`**, **`POST /api/admin/logout`**, **`GET /api/admin/me`** (`tron/api/routes/admin_auth.py`); httpOnly cookie JWT (`tron/api/admin_session.py`); **`require_api_key`** accepts cookie before `X-API-Key`; audit **WebSocket** accepts cookie (`tron/api/routes/ws.py`); SPA **`/login`**, **`SessionGate`**, **`Layout`** sign-out (`frontend/`). Integration: **`tests/integration/test_admin_auth_integration.py`**. Optional vault **`auth/admin-password`**; if unset, login password falls back to **master API key** (documented in **`.env.example`**). |
| **Audit workflow metadata for visibility** | **`POST /api/audits`** sets `workflow_id` / `workflow_run_id` for Temporal or background paths; **`_dispatch_temporal_audit`** persists Temporal `run_id` (`tron/api/routes/audits.py`). Verified by **`TestAuditWorkflowRowMetadata`** + **`GET /api/workflow-runs`**. |
| **Temporal audit failure → DB ``failed`` (not stuck ``queued``)** | **`mark_audit_run_failed`** activity (`tron/workflows/activities.py`); **`AuditWorkflow.run`** try/except → activity then re-raise (`tron/workflows/audit_workflow.py`); **`POST /api/audits`** marks **`failed`** on dispatch exception after commit (`tron/api/routes/audits.py`); activity registered on **`tron/worker.py`**. Unit test **`tests/unit/test_workflow_handlers.py`** **`test_run_calls_mark_failed_then_reraises_on_phase_error`**. |
| **Stale ``queued`` audit reconciliation (ops)** | **`POST /api/audits/reconcile-stale-queued`** (master only); **`tron/services/audit_reconcile.py`**; CLI **`python -m tron.cli audit reconcile-stale-queued`**; env **`TRON_STALE_QUEUED_AUDIT_MINUTES`**. Optional **API startup** pass: **`TRON_RECONCILE_STALE_QUEUED_ON_STARTUP`** (`tron/api/main.py` lifespan). **`load_project_metadata`** sets DB **`running`** early for Temporal audits (`tron/workflows/activities.py`). Compose defaults: **`docker-compose.yml`** **`tron-api`**. Tests: **`tests/integration/test_audit_reconcile_integration.py`**. |
| **WebSocket audit stream auth parity** | **`tron/api/routes/ws.py`** `_authenticate_ws` + **`WS_AUDIT_PROGRESS_SCOPES`** in **`tron/api/middleware/scopes.py`**. Verified by **`tests/unit/test_ws.py`**. |
| **Graph ltree subtree** | **`GET /api/projects/{id}/graph/subtree`** (`tron/api/routes/graph.py`). |
| **Graph transitive / impact / standards chain** | **`GET .../graph/transitive`**, **`GET .../graph/impact`**, **`GET .../graph/standards-chain`**; **`tron/services/graph_analytics.py`**; tests **`tests/unit/test_graph_analytics.py`**. |
| **BUILD self-check + validation + optional git branch** | **`BuildWorkflow`** (`tron/workflows/build_workflow.py`); activities **`evaluate_build_quality_gates`**, **`run_build_repo_validation`**, **`save_build_result`**, **`maybe_push_build_report_branch`**, **`merge_build_git_metadata`**; **`tron/services/git_build_report.py`**. |
| **Ollama / local fallback path** | **`Provider.OLLAMA`**, **`ollama/`** model prefix, **`OLLAMA_BASE_URL`** (`tron/infra/llm/client.py`, `.env.example`). |
| **Compliance ISO scanning (audit)** | **`ComplianceISO`** (`tron/agents/compliance_iso.py`); **`AuditExecutor`** / workflow activities; optional **`ISOConfig.compliance_reference_context`** from built-in packs. Tests: **`tests/unit/test_audit_executor.py`**, **`tests/unit/test_workflow_handlers.py`**. |
| **Built-in compliance reference packs** | **`tron/standards/control_packs.py`**, **`tron/standards/packs/*.json`**; **`GET /api/standards/control-packs`**, **`GET /api/standards/control-packs/{id}`**; project **`compliance_control_pack_ids`**; env **`TRON_COMPLIANCE_PACKS`**. Tests: **`tests/unit/test_control_packs.py`**, **`tests/integration/test_standards_control_packs.py`**. |
| **EVOLVE operating mode** | **`EvolveWorkflow`** (`tron/workflows/evolve_workflow.py`); **`POST /api/evolve/{project_id}`**; **`save_evolve_result`** → **`evolve_artifact_json`** (Alembic **`006`**); worker registration **`tron/worker.py`**. |
| **Sandbox pre-warm + remote HTTP pool** | **`tron/sandbox/server.py`** lifespan + **`SANDBOX_PREWARM_EXECUTIONS`**; **`tron/services/sandbox_client.py`** shared **`httpx.AsyncClient`** + **`TRON_SANDBOX_HTTP_POOL_SIZE`**. |
| **MCP in main venv** | **`requirements.txt`** (`mcp[cli]`); **`requirements-mcp.txt`** re-exports **`-r requirements.txt`**. Tools include **`tron_start_evolve`**, **`tron_list_control_packs`**, **`tron_get_control_pack`**, **`tron_list_workflow_runs`**, **`tron_evaluate_audit_quality_gates`** (`tron/mcp/__main__.py`). |
| **Project plan/build visibility (UI)** | **`frontend/src/pages/ProjectDetail.tsx`** — plan artifact + last build JSON summary; **`startBuildWorkflow`** in **`frontend/src/api.ts`**. |
| **Scanned-application agent handoff** | **`tron/services/scan_handoff_export.py`** — `TRON_HANDOFF_MANAGED_*` merge, **`write_audit_handoff_bundle`**, **`append_tron_md_activity_log`**; **`tron/services/agent_handoff.py`** after audit if **`agent_handoff_path`**; **`tron/api/config.py`** **`tron_handoff_append_tron_md`**; CLI **`tron/cli.py`** `audit handoff`; **`scripts/init_tron_scan_handoff.sh`**; templates **`tron/agent_handoff_templates/`**; **`.cursor/rules/tron-scanned-app-handoff.mdc`**. Tests: **`tests/unit/test_scan_handoff_export.py`**, **`tests/unit/test_agent_handoff.py`**. |

## Deferred (documented, not “missing”)

- **Third-party certified attestation / vendor compliance subscriptions** — explicitly excluded; see **`docs/project/ADR-002-compliance-certified-packs.md`**. Shipped **reference** JSON packs and APIs are **Done** (see index above).

## Known partials (must stay visible until closed)

_None for the current milestone. Certified packs are **Deferred** (above), not a shipped **Partial** feature path._

**Resume work:** open **`docs/project/MASTER_PROPOSAL_TODO.md`** → section **“Current snapshot (where we left off)”** for the latest agreed scope and evidence pointers.

**Process (not a Partial product gap):** For repositories **scanned by** Tron, triage artifacts belong in **that repository’s root** (`TRON_POST_SCAN.md`, `CLAUDE.md`, `AGENTS.md`, `.cursor/rules/tron-scan-followups.mdc`). Tron **updates a managed HTML-comment region** inside each file on handoff (text outside the markers is preserved). It **appends** deduplicated entries to **`tron.md`** for **Tron activity** unless **`TRON_HANDOFF_APPEND_TRON_MD`** is disabled. Automatic write when **`projects.agent_handoff_path`** points at an absolute path the **audit worker** can access; otherwise **`tron/cli.py` `audit handoff`** or **`scripts/init_tron_scan_handoff.sh`** — see **`tron/agent_handoff_templates/README.md`** and **`MASTER_PROPOSAL_TODO.md`** “Scanned applications”.

## Process

1. Any change that closes a requirement updates **`MASTER_PROPOSAL_TODO.md`** in the same PR/commit.
2. New scope decisions use **`docs/architecture/`** or a short ADR under **`docs/project/`** when they override the proposal.
