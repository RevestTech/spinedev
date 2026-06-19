# Traceability matrix

Map requirements to implementation and tests. Update as items enter Build.

| REQ-ID | Feature | Module / path | Test file | Gate | Status |
|--------|---------|---------------|-----------|------|--------|
| REQ-INIT-1 | Plan pipeline — intake → PRD → TRD | `plan/`, `orchestrator/` | `orchestrator/cli/tests/` | G4 | Partial |
| REQ-INIT-2 | Hub — containerized product | `hub/`, `shared/ui/spa/` | `tools/smoke-test.sh` | G4 | Partial |
| REQ-INIT-5 | Vault-only secrets | `shared/secrets/`, `vault/` | `tools/smoke-test.sh` (vault phase) | G4 | Partial |
| REQ-INIT-6 | Identity — Keycloak | `keycloak/`, `shared/identity/` | `tools/smoke-test.sh` | G4 | Partial |
| REQ-INIT-7 | LLM-agnostic | `shared/llm/` | `shared/llm/tests/` | G4 | Partial |
| REQ-INIT-13 | Verify — TRON + Cite-or-Refuse | `verify/`, `shared/mcp/tools/` | `verify/charter_evals/tests/` | G4 | Partial |
| SPINE-001 | Local dev + smoke contract | `tools/smoke-test.sh`, `tools/hub-up.sh` | `tools/smoke-test.sh` | G2 | Done |
| SPINE-002 | CI pipeline | `.github/workflows/ci.yml` | CI workflow | G2 | Partial |
| SPINE-003 | Hub project route tests | `shared/api/routes/` | `shared/api/tests/test_routes_projects.py` | G4 | Partial |
| HARNESS-P10 | Harness Lite loop-bridge | `tools/harness/` | `tools/harness/tests/test_loop_bridge.py` | G4 | Done |

**Status values:** Planned · Partial · Done · Deferred (link ticket)

*Add a row per backlog item in [BACKLOG.md](../BACKLOG.md) as items enter Build.*

**Last updated:** 2026-06-19
