# Spine — Backlog

**Cadence:** SDLC gates **G0→G6** ([gates/](./gates/)) · Tests required before **G4** ([testing/](./testing/))  
**Source of truth:** This file lives in git. External ALM mirrors IDs — never replaces this file.

**Program:** Finish autonomous operate loop. See [`docs/MASTER_TODO.md`](../docs/MASTER_TODO.md) for live queue.

---

## Gate status (program)

| Gate | Status | Blocker |
|------|--------|---------|
| G0 Charter | **Ready for sign-off** | PO + Eng lead — [`G0-charter.md`](./gates/G0-charter.md) |
| G1 Requirements | Open | — |
| G2 Architecture | Open | — |
| G3 Build | **Evidence ready** | Wave 1–2 operate loop code landed |
| G4 Test | **Evidence tooling ready** | `wave4-ship-gates.sh` + human sign-off |
| G5 Release | **Black-box tooling ready** | `operate_blackbox.py` + disposable project |
| G6 Operate | Open | Deferred post-v1 unless BYOC in scope |

---

## Wave 1 — Operate loop reliability (P0)

| ID | Title | Phase | P | Gate | Depends | Tests |
|----|-------|-------|---|------|---------|-------|
| SPINE-OP-01 | Security review blocked ack → engineer remediate | Build | P0 | G3 | — | `shared/api/tests/test_project_recovery.py` |
| SPINE-OP-02 | Auto-remediate retry on dispatch_in_flight | Build | P0 | G3 | SPINE-OP-01 | `shared/api/tests/test_project_recovery.py` |
| SPINE-OP-03 | Dedupe concurrent auto-remediate schedules | Build | P0 | G3 | SPINE-OP-02 | `shared/api/tests/test_project_recovery.py` |
| SPINE-OP-04 | Recovery API perf (async workspace scan, hub task schedule) | Build | P0 | G3 | — | `shared/api/tests/test_project_recovery.py` |
| SPINE-OP-05 | Hub rebuild — no container-only patches | DevOps | P0 | G3 | SPINE-OP-01..04 | `tools/smoke-test.sh` |

---

## Wave 2 — Autonomous operate chain (P0) — **DONE (code)**

| ID | Title | Phase | P | Gate | Depends | Tests |
|----|-------|-------|---|------|---------|-------|
| SPINE-OP-06 | devops_approval → feature complete + promote + redeploy | Build | P0 | G3 | SPINE-OP-05 | `shared/api/tests/test_operate_loop.py` |
| SPINE-OP-07 | Promoted feature → PRODUCE_FEATURE dispatch | Build | P0 | G3 | SPINE-OP-06 | `shared/api/tests/test_operate_loop.py` |
| SPINE-OP-08 | Persist operate_serve_url from local deploy | Build | P0 | G3 | SPINE-OP-06 | `_post_ack.py` deploy path |
| SPINE-OP-09 | Phase watcher: operate + full_auto rules | Build | P0 | G3 | SPINE-OP-07 | `shared/runtime/tests/test_phase_watcher_rules.py` |
| SPINE-OP-10 | Operate loop unit tests | Verify | P0 | G4 | SPINE-OP-06..09 | `shared/api/tests/test_operate_loop.py` |

---

## Wave 3 — Harness Lite dogfood (P1)

| ID | Title | Phase | P | Gate | Depends | Tests |
|----|-------|-------|---|------|---------|-------|
| SPINE-H-01 | spine harness init on platform repo | Build | P1 | G3 | SPINE-OP-05 | `sprint-close-operate-loop.sh` init |
| SPINE-H-02 | Sprint-close on operate-loop scope | Verify | P1 | G4 | SPINE-H-01 | `bash tools/harness/sprint-close-operate-loop.sh` |

---

## Wave 4 — Ship gates (P0)

| ID | Title | Phase | P | Gate | Depends | Tests |
|----|-------|-------|---|------|---------|-------|
| SPINE-G4-01 | G4 evidence rollup script | Verify | P0 | G4 | SPINE-H-02 | `bash tools/harness/wave4-ship-gates.sh --smoke` |
| SPINE-G5-01 | Black-box operate acceptance tool | Verify | P0 | G5 | SPINE-OP-05 | `tools/acceptance/operate_blackbox.py` |
| SPINE-ACC-01 | Run black-box on disposable project | Verify | P0 | G5 | SPINE-G5-01 | wave4 with `--project-uuid` |

---

## Foundation (existing)

| ID | Title | Phase | P | Gate | Depends | Tests |
|----|-------|-------|---|------|---------|-------|
| SPINE-001 | Local dev stack + smoke contract | Build | P0 | G2 | — | `tools/smoke-test.sh` |
| SPINE-002 | CI pipeline (main workflow) | Build | P0 | G2 | SPINE-001 | `.github/workflows/ci.yml` |
| SPINE-003 | Hub project route unit tests | Build | P1 | G4 | SPINE-001 | `shared/api/tests/test_routes_projects.py` |

---

## Done

- [x] **SPINE-OP-01** Security review blocked ack handler (2026-06-21)
- [x] **SPINE-OP-02** Auto-remediate retry (2026-06-21)
- [x] **SPINE-OP-03** Auto-remediate dedupe (2026-06-21)
- [x] **SPINE-OP-04** Recovery perf + hub task scheduling (2026-06-21)
- [x] **SPINE-OP-06** devops operate ack → complete + promote (2026-06-21)
- [x] **SPINE-OP-07** Promoted feature → PRODUCE_FEATURE dispatch (2026-06-21)
- [x] **SPINE-OP-08** Persist operate_serve_url (2026-06-21)
- [x] **SPINE-OP-09** Phase watcher operate rules (2026-06-21)
- [x] **SPINE-OP-10** Operate loop unit tests (2026-06-21)
- [x] **SPINE-H-01** Harness init + sprint-close entry (2026-06-21)
- [x] **SPINE-H-02** Operate-loop scoped audit/verify script (2026-06-21)
- [x] **SPINE-G4-01** Wave 4 ship-gates rollup (2026-06-21)
- [x] **SPINE-G5-01** operate_blackbox.py (2026-06-21)

---

## Icebox

| ID | Title | Notes |
|----|-------|-------|
| SPINE-ACC-JB | Jelly Beans acceptance | Explicitly **not** platform work |

---

## PR convention

`[SPINE-OP-##] short description`
