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
| G0 Charter | **Signed — Go** | PO + Eng lead sign-off 2026-06-19 — [`G0-charter.md`](./gates/G0-charter.md) |
| G1 Requirements | **Signed — Go** | PO + Eng lead sign-off 2026-06-19 — [`G1-requirements.md`](./gates/G1-requirements.md) |
| G2 Architecture | **Signed — Go** | Tech + Eng lead sign-off 2026-06-19 — [`G2-architecture.md`](./gates/G2-architecture.md) |
| G3 Build | **Signed — Go** | Foundation epic SPINE-001–003 — [`G3-build-signoff.md`](./gates/G3-build-signoff.md) |
| G4 Test | **Signed — Go** | QA + Tech lead 2026-06-19 — [`G4-test-signoff.md`](./gates/G4-test-signoff.md) |
| G5 Release | Open | — |
| G6 Operate | Open | — |

---

## Phase 1 — Foundation

*Replace wave title and rows for your domain.*

| ID | Title | Phase | P | Gate | Depends | Tests |
|----|-------|-------|---|------|---------|-------|
| SPINE-001 | Local dev stack + smoke contract | Build | P0 | G2 | — | `tools/smoke-test.sh (contract 99 PASS)` |
| SPINE-002 | CI pipeline (main workflow) | Build | P0 | G2 | SPINE-001 | `.github/workflows/ci.yml` |
| SPINE-003 | Hub project route unit tests | Build | P1 | G4 | SPINE-001 | `shared/api/tests/test_routes_projects.py` |

---

## Phase 2 — Core delivery

| ID | Title | Phase | P | Gate | Depends | Tests |
|----|-------|-------|---|------|---------|-------|
| | | | | | | |

---

## Done

- [x] **SPINE-001** Local dev stack + smoke contract (Sprint 0, 2026-06-19)
- [x] **SPINE-002** CI pipeline main workflow (Sprint 0, 2026-06-19)
- [x] **SPINE-003** Hub project route unit tests (Sprint 0, 2026-06-19)

---

## Suggested / icebox

| ID | Title | Notes |
|----|-------|-------|
| | | |
