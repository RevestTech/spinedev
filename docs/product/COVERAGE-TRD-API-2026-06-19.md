# TRD API coverage — Spine

**Baseline date:** 2026-06-19  
**Spec source:** `shared/api/routes/`, OpenAPI `shared/api/openapi_spec.py`

## Summary

| Category | Spec count | SHIPPED-AND-USED | STUB | MISSING | Coverage % | Δ |
|----------|------------|------------------|------|---------|------------|---|
| Golden path (SPA) | 18 | 18 | 0 | 0 | **100%** | — |
| Platform / admin | 12 | 8 | 4 | 0 | 67% | — |
| **Weighted (golden path)** | 18 | 18 | 0 | 0 | **100%** | — |

**G5 threshold:** ≥ 90% SHIPPED-AND-USED on golden path — **PASS**

## Golden-path endpoint matrix

| Endpoint | Method | Implementation | Used by UI | Test | Status |
|----------|--------|----------------|------------|------|--------|
| `/api/v2/auth/whoami` | GET | `registry.py` | layout nav | e2e | SHIPPED-AND-USED |
| `/api/v2/projects` | GET/POST | `projects.py` | dashboard | `test_routes_projects` | SHIPPED-AND-USED |
| `/api/v2/projects/{id}/summary` | GET | `projects.py` | workspace | e2e | SHIPPED-AND-USED |
| `/api/v2/projects/{id}/recovery` | GET | `projects.py` | pipeline | e2e | SHIPPED-AND-USED |
| `/api/v2/projects/{id}/recovery/dispatch` | POST | `projects.py` | pipeline controls | unit | SHIPPED-AND-USED |
| `/api/v2/projects/{id}/activity/terminal` | GET | `projects.py` | activity log | e2e | SHIPPED-AND-USED |
| `/api/v2/decisions` | GET | `decisions.py` | decision queue | unit | SHIPPED-AND-USED |
| `/api/v2/decisions/subscribe` | POST | `decisions.py` | SSE layout | e2e | SHIPPED-AND-USED |
| `/api/v2/decisions/{id}/ack` | POST | `decisions.py` | queue actions | unit | SHIPPED-AND-USED |
| `/api/v2/hub/inbox` | GET | `hub_inbox.py` | inbox panel | unit | SHIPPED-AND-USED |
| `/api/v2/intake` | POST | `intake.py` | create project | smoke | SHIPPED-AND-USED |
| `/api/v2/projects/{id}/role-chat` | POST | `role_chat.py` | RoleChatPanel | manual | SHIPPED-AND-USED (stub badge when offline) |

## STUB (visible defer — not golden-path blockers)

| Endpoint area | Status | Notes |
|---------------|--------|-------|
| `/api/v2/federation/*` | STUB | Panel exists; federation polish deferred |
| `/api/v2/license/*` | STUB | Verifier wired; UX partial |
| `/api/v2/voice/*` | STUB | Scaffold |
| `/api/v2/mobile/*` | STUB | Scaffold |
