# PRD coverage — Spine

**Baseline date:** 2026-06-19  
**Prior baseline:** N/A (Sprint 0 first baseline)  
**Scope:** G0 charter in-scope capabilities (Sprint 0)

## Summary

| Priority | Total reqs | LIVE | STUB | MISSING | Coverage % | Δ |
|----------|------------|------|------|---------|------------|---|
| P0 (Sprint 0) | 6 | 6 | 0 | 0 | **100%** | — |
| P1 (deferred) | 7 | 0 | 7 | 0 | 0% (deferred) | — |

**G5 threshold (P0):** ≥ 90% LIVE — **PASS**

## Requirement matrix (Sprint 0 P0)

| PRD-ID | Requirement | Priority | Status | Implementation | Test | Notes |
|--------|-------------|----------|--------|----------------|------|-------|
| REQ-INIT-1 | Plan pipeline intake→PRD→TRD→Roadmap | P0 | LIVE | `plan/`, `orchestrator/` | smoke phase 6 | Hub runners wired |
| REQ-INIT-2 | Hub containerized product | P0 | LIVE | `hub/`, `shared/ui/spa/` | Playwright 3/3, smoke | Core surfaces; full §9 walkthrough automated |
| REQ-INIT-5 | Vault-only secrets | P0 | LIVE | `shared/secrets/`, `vault/` | smoke vault phase | No env:// |
| REQ-INIT-6 | Identity Keycloak | P0 | LIVE | `keycloak/`, `shared/identity/` | smoke | Day-0 compose |
| REQ-INIT-7 | LLM-agnostic | P0 | LIVE | `shared/llm/` | `shared/llm/tests/` | 7 providers |
| REQ-INIT-13 | Verify TRON + Cite-or-Refuse | P0 | LIVE | `verify/`, `auditor_runner.py` | charter evals 12 pass | Hub verify chain |

## Deferred (out of Sprint 0 scope per G0/G1)

| PRD-ID | Requirement | Status | Notes |
|--------|-------------|--------|-------|
| REQ-INIT-3 | Federation | STUB | Scaffold; G2 acknowledged |
| REQ-INIT-4 | Operate 8 planes | STUB | `operate_runner` partial |
| REQ-INIT-8 | Licensing | STUB | Day-1 primitive; polish deferred |
| REQ-INIT-9 | Evidence pipeline | STUB | Collectors exist |
| REQ-INIT-10 | Smart Spine | STUB | Bridge partial |
| REQ-INIT-11 | DR 12 layers | STUB | `recovery/` scaffold |
| REQ-INIT-12 | Migration | STUB | `migration/` scaffold |
