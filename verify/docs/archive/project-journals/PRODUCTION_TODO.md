# Production Readiness Master Checklist

**Goal:** Elevate Tron from a feature-complete prototype to a fully production-ready Enterprise AI QA platform. This checklist addresses critical gaps in execution verification, policy enforcement, security, and user experience.

## 1. Verification Pipeline (Layer 3 & 6/7)
- [x] **L3: SQL Injection Verifier:** Implement execution test for `sql_injection` in `ExecutionVerifier._verify_injection`.
  - *Validation:* Unit test passing with a mock SQLite/sandbox DB injection.
- [x] **L3: Command Injection Verifier:** Implement execution test for `command_injection` in `ExecutionVerifier._verify_injection`.
  - *Validation:* Unit test passing by executing a safe command (`echo`) in the sandbox.
- [x] **L3: Path Traversal Verifier:** Implement execution test for `path_traversal` in `ExecutionVerifier._verify_path_traversal`.
  - *Validation:* Unit test passing by reading a safe file (`/etc/os-release` or similar) in the sandbox.
- [x] **L3: SSRF Verifier:** Implement execution test for `ssrf` in `ExecutionVerifier._verify_ssrf`.
  - *Validation:* Unit test passing by fetching a mock internal endpoint in the sandbox.
- [x] **L6/L7: Calibration & Drift Engine:** Implement a service to calculate `CalibrationMetric` and `DriftScore`. Add CLI commands to trigger regression tests.
  - *Validation:* Tests confirming confidence scores adjust based on historical accuracy data.

## 2. Policy & Scope Enforcement
- [x] **`NOT_IN_SCOPE` Prompt Integration:** Update `BaseISO._build_prompt` and `SecurityISO` to explicitly instruct the LLM to ignore paths/patterns listed in the Blueprint's `not_in_scope`.
  - *Validation:* Unit test ensuring the prompt contains the exclusion instructions and the agent respects them.
- [x] **Dynamic Blueprint Scoping:** Update `AuditWorkflow` (specifically `_execute_iso_agent` in `activities.py`) to respect the project's configured scope rather than hardcoding `*.*` and all vulnerability types.
  - *Validation:* Integration test verifying that files outside the configured scope are ignored during the audit.

## 3. Infrastructure & Security
- [x] **Sandbox Deterministic Tools:** Move `bandit` and `semgrep` execution from local subprocesses in `SecurityISO` to isolated containers via `SandboxClient` (or dedicated remote endpoints).
  - *Validation:* Agent tests pass without `bandit` or `semgrep` installed on the host running the worker.
- [x] **Workflow Error Compensation:** Enhance Temporal workflow activities to properly clean up or mark partial findings when an agent fails mid-execution.
  - *Validation:* Workflow test showing graceful degradation when one of the parallel ISO agents fails.

## 4. Frontend & UX
- [x] **Graph Analytics UI:** Implement a visualization component (e.g., using `react-force-graph` or similar) in `frontend/src/pages/ProjectDetail.tsx` to explore dependency graphs.
  - *Validation:* UI renders the graph correctly when hitting the `/api/projects/{id}/graph` endpoint.
- [x] **Rich Artifact Visualization:** Update `ProjectDetail.tsx` to render PLAN, BUILD, and EVOLVE JSON artifacts as structured components (lists, tables, code blocks) instead of raw JSON strings.
  - *Validation:* Visual inspection of the UI showing formatted artifacts.
- [x] **Granular Quality Gates:** Update the UI to display individual failed quality gates rather than a generic "failed" boolean.
  - *Validation:* UI shows a checklist of passed/failed criteria.

## 5. Documentation
- [x] **Update API Reference:** Document EVOLVE mode endpoints (`POST /api/evolve/{project_id}`) and Standards API endpoints in `docs/reference/API_REFERENCE.md`.
  - *Validation:* Documentation matches the FastAPI route definitions.

---
*Note: This checklist is executed systematically to ensure Tron meets its "Zero-Drift" and "Trust Nothing" enterprise promises.*
