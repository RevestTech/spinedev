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
| G0 Charter | Open | Human sign-off in [gates/G0-charter.md](./gates/G0-charter.md) (scope filled 2026-06-01) |
| G1 Requirements | Open | — |
| G2 Architecture | Open | — |
| G3 Build | Open | — |
| G4 Test | Open | — |
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

<!-- Move completed items here: - [x] **SPINE-001** Title (Sprint N) -->

---

## Suggested / icebox

| ID | Title | Notes |
|----|-------|-------|
| | | |
