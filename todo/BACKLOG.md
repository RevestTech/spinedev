# Spine — Backlog

**Cadence:** SDLC gates **G0→G6** ([gates/](./gates/)) · Tests required before **G4** ([testing/](./testing/))  
**Source of truth:** This file lives in git. External ALM (Jira, Linear) mirrors IDs — never replaces this file.

---

## How to use

1. Work **top to bottom within each wave** unless blocked by **Depends**.
2. Do not pass a **Gate** until the linked artifact in `todo/gates/` is signed.
3. Every **Build** row must name a **test file**; add a traceability row in [traceability-matrix.md](./testing/traceability-matrix.md).
4. IDs are stable: `SPINE-###` (configure prefix in [DELIVERY-MECHANISM.md](../docs/product/DELIVERY-MECHANISM.md)).
5. PR title convention: `[SPINE-###] short description`

---

## Gate status (program)

| Gate | Status | Blocker |
|------|--------|---------|
| G0 Charter | **Signed — Go** | 2026-06-19 |
| G1 Requirements | **Signed — Go** | 2026-06-19 |
| G2 Architecture | **Signed — Go** | 2026-06-19 |
| G3 Build | **Signed — Go** | Foundation epic SPINE-001–003 |
| G4 Test | **Signed — Go** | 2026-06-19 |
| G5 Release | **Signed — Go** | Sprint 0 golden path |
| G6 Operate | **Signed — Go** | Sprint 0 laptop baseline |

---

## Phase 1 — Foundation (done)

| ID | Title | Phase | P | Gate | Depends | Tests |
|----|-------|-------|---|------|---------|-------|
| SPINE-001 | Local dev stack + smoke contract | Build | P0 | G2 | — | `tools/smoke-test.sh` |
| SPINE-002 | CI pipeline (main workflow) | Build | P0 | G2 | SPINE-001 | `.github/workflows/ci.yml` |
| SPINE-003 | Hub project route unit tests | Build | P1 | G4 | SPINE-001 | `shared/api/tests/test_routes_projects.py` |

---

## Phase 2 — Operating loop closure (Sprint 1)

*Closes `docs/OPERATING_LOOP_GAP.md` + live golden-path E2E.*

| ID | Title | Phase | P | Gate | Depends | Tests |
|----|-------|-------|---|------|---------|-------|
| SPINE-004 | QA execution runner (sprint AC against engineer commit) | Build | P0 | G4 | SPINE-003 | `verify/runtime/tests/test_qa_execution_runner.py` |
| SPINE-005 | Background role worker daemon (directive queue poller) | Build | P0 | G3 | SPINE-003 | `shared/runtime/tests/test_role_worker.py` |
| SPINE-006 | Instinct promotion loop (Hub lifespan) | Build | P1 | G4 | SPINE-005 | `shared/runtime/tests/test_instinct_promotion_loop.py` |
| SPINE-007 | Product runner HTTP path (Hub intake → product charter PRD) | Build | P0 | G4 | SPINE-003 | `plan/runtime/tests/test_product_runner.py` |
| SPINE-008 | Charter eval CI gate on `shared/charters/*.md` changes | Build | P1 | G4 | SPINE-002 | `tools/smoke-test.sh` + charter eval |
| SPINE-009 | Live golden-path E2E through `released → operate` | Test | P0 | G4 | SPINE-004,005 | `tools/golden-path-walkthrough.sh` + E2E report |
| SPINE-010 | RoleChat live surface (replace STUB badge) | Build | P1 | G4 | SPINE-009 | Playwright role-chat spec |
| SPINE-011 | PM dashboard wire or document Sprint 1 defer | Ops | P2 | G6 | — | `docs/PM_DASHBOARD.md` |
| SPINE-012 | Weekly DR drill automation (H-DR-DRILL) | Ops | P2 | G6 | SPINE-002 | `tools/dr-test.sh` CI job |
| SPINE-013 | Operate planes 2–8 real impl (beyond heartbeat stub) | Build | P1 | G6 | SPINE-009 | `devops/runtime/tests/test_operate_runner.py` |
| SPINE-014 | Independent human re-audit (H-REAUDIT) | QA | P1 | G5 | SPINE-009 | `docs/product/REALITY-AUDIT-*.md` |
| SPINE-015 | Founder walkthrough — non-engineer golden path | Test | P0 | G5 | SPINE-009 | `docs/FOUNDER_WALKTHROUGH.md` |

---

## Phase 3 — Customer ship (V1)

*Engineering-prep only; many items in `docs/V1_SHIP_CHECKLIST.md` are human/ops.*

| ID | Title | Phase | P | Gate | Depends | Tests |
|----|-------|-------|---|------|---------|-------|
| SPINE-016 | BYOC provision smoke (AWS + Railway dry-run) | Ops | P0 | G6 | SPINE-012 | `tools/byoc/` integration test |
| SPINE-017 | Multi-arch Docker publish pipeline | Ops | P0 | G6 | SPINE-002 | `.github/workflows/docker-build.yml` |
| SPINE-018 | All vault paths real-values audit (not InMemory) | Security | P0 | G6 | SPINE-016 | `bash tools/audit-secrets.sh` |
| SPINE-019 | Timed DR drill RTO ≤ 30m | Ops | P1 | G6 | SPINE-012 | `tools/dr-test.sh` timed run |
| SPINE-020 | Design partner onboarding E2E (no founder) | Test | P0 | G5 | SPINE-015 | V1 checklist §6 |

---

## Done

- [x] **SPINE-001** Local dev stack + smoke contract (Sprint 0, 2026-06-19)
- [x] **SPINE-002** CI pipeline main workflow (Sprint 0, 2026-06-19)
- [x] **SPINE-003** Hub project route unit tests (Sprint 0, 2026-06-19)
- [x] **SPINE-004** QA execution runner (2026-06-19, `846ef8f`)
- [x] **SPINE-005** Background role worker daemon (2026-06-19, `846ef8f`)
- [x] **SPINE-006** Instinct promotion loop (2026-06-19, `53856ab`)
- [x] **SPINE-007** Product runner HTTP path (2026-06-19, `846ef8f`)
- [x] **SPINE-008** Charter eval smoke gate (2026-06-19, `1294533`)
- [x] **SPINE-010** Live role-chat dev mode (2026-06-19, `57538c1`)
- [x] **SPINE-015** Founder walkthrough doc (2026-06-19, `fe20407`)

---

## Suggested / icebox

| ID | Title | Notes |
|----|-------|-------|
| SPINE-ICE-01 | Federation hub-to-hub operate events | After Smart Spine loop closed |
| SPINE-ICE-02 | Voice / mobile v1.1+ | `V1_SHIP_CHECKLIST.md` §8 |
| SPINE-ICE-03 | Full Grafana observability stack | H-OBS-STACK |
