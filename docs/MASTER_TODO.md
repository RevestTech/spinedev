# Master TODO — operational queue

> **Resume here.** Living task list for *what to do next* on Spine development.
> Last updated: **2026-06-21**
>
> **Related docs (do not duplicate their role):**
> - [`SESSION_HANDOFF.md`](SESSION_HANDOFF.md) — current-session state (authoritative on resume)
> - [`SPINE_MASTER.md`](SPINE_MASTER.md) — vision, gap matrix, execution tracker (§8)
> - [`todo/BACKLOG.md`](../todo/BACKLOG.md) — gate-linked backlog (SPINE-### IDs)
> - [`V1_SHIP_CHECKLIST.md`](V1_SHIP_CHECKLIST.md) — customer launch ops gates
> - [`Handoff.md`](../Handoff.md) — Harness Lite dogfood architecture

---

## Active focus

**Finish Spine — autonomous operate loop (Wave 1→4).**

Spine is the product. Customer apps (Jelly Beans, Booger, etc.) are **black-box
acceptance tests only** — never edit them manually to unblock platform work.

**Execution model:** Orchestrator + virtual team (PM / Project Manager / Dev /
QA) dogfoods Spine via **Harness Lite** + **spine-on-spine** on this repo.

---

## Virtual team (Spine finishes Spine)

| Role | Mission |
|------|---------|
| **Orchestrator / Architect** | Gate sequence, architecture decisions, no customer-app edits |
| **Product Manager** | Done = one `full_auto` feature iteration without manual recovery |
| **Project Manager** | G0→G5 gates, `todo/BACKLOG.md`, daily blockers |
| **Dev Squad A** | Operate loop: `_post_ack`, `_project_recovery`, `pipeline_runner` |
| **Dev Squad B** | Hub reliability: asyncpg pool, `/recovery` SLA |
| **Dev Squad C** | Harness Lite: `tools/harness/`, `.cursor/skills/harness-*` |
| **QA** | `test_project_recovery.py`, smoke 99/0, operate-loop integration test |
| **DevOps** | `hub-up.sh --rebuild` only — **no container-only patches** |

---

## Wave program

### Wave 1 — Stop the bleeding (P0) — **DONE**

| ID | Task | Status | Files |
|----|------|--------|-------|
| SPINE-OP-01 | `security_review_blocked` → engineer on ack | **DONE** | `_post_ack.py`, `_role_dispatch_bridge.py` |
| SPINE-OP-02 | Auto-remediate retry when `dispatch_in_flight` | **DONE** | `_project_recovery.py` |
| SPINE-OP-03 | Dedupe concurrent auto-remediate dispatches | **DONE** | `_project_recovery.py` |
| SPINE-OP-04 | `/recovery` perf: off-thread workspace scan + hub task scheduling | **DONE** | `_project_recovery.py` |
| SPINE-OP-05 | Tests for Wave 1 | **DONE** | `test_project_recovery.py` |
| SPINE-OP-06 | Hub rebuild + verify `/recovery` <2s | **Pending** | `tools/hub-up.sh --rebuild` |

### Wave 2 — Autonomous operate chain (P0) — **DONE**

| ID | Task | Status |
|----|------|--------|
| SPINE-OP-07 | `devops_approval` → complete + promote + redeploy | **DONE** |
| SPINE-OP-08 | Promoted feature → `PRODUCE_FEATURE` dispatch | **DONE** |
| SPINE-OP-09 | Persist `operate_serve_url` from local deploy | **DONE** |
| SPINE-OP-10 | Phase watcher rules for operate + `full_auto` | **DONE** |
| SPINE-OP-11 | Integration tests for operate loop | **DONE** (unit) |
| SPINE-OP-06 | Hub rebuild + smoke evidence | **Pending** |

### Wave 3 — Harness dogfood (P1) — **Scaffolded** (run locally)

| ID | Task | Status |
|----|------|--------|
| SPINE-H-01 | `spine harness init` on platform repo (spine-on-spine) | **DONE** (`sprint-close-operate-loop.sh` init step) |
| SPINE-H-02 | Sprint-close audit → verify on operate-loop files | **DONE** (`bash tools/harness/sprint-close-operate-loop.sh`) |

### Wave 4 — Ship gates — **Scaffolded** (run locally)

| ID | Task | Status |
|----|------|--------|
| SPINE-G4-01 | G4 evidence rollup (pytest + harness + smoke) | **DONE** (`wave4-ship-gates.sh`) |
| SPINE-G5-01 | Black-box operate acceptance (read-only Hub) | **DONE** (`tools/acceptance/operate_blackbox.py`) |
| SPINE-G0-01 | Human G0 sign-off | **Pending** — [`todo/gates/G0-charter.md`](../todo/gates/G0-charter.md) |
| SPINE-G4-02 | Human G4 sign-off | **Pending** — [`todo/gates/G4-test-signoff.md`](../todo/gates/G4-test-signoff.md) |
| SPINE-G5-02 | Human G5 sign-off + black-box run | **Pending** — disposable project UUID |
| SPINE-OP-05 | Hub rebuild + smoke evidence | **Pending** |

| Gate | Criterion |
|------|-----------|
| G0 | Charter signed — `todo/gates/G0-charter.md` |
| G4 | Traceability + pytest evidence — `bash tools/harness/wave4-ship-gates.sh --smoke` |
| G5 | Smoke + black-box operate acceptance — `--project-uuid` on wave4 script |

---

## Rules (non-negotiable)

1. **No edits** to `~/spine-projects/*` except engineer role output
2. **No manual** `retry_engineer_remediate` except Wave 1 debug windows
3. **No port babysitting** (19001/19002 monitors)
4. **No container hot-patches** — git → rebuild → verify
5. Jelly Beans / customer apps = acceptance test **after** Wave 2

---

## Verification (run after Hub rebuild)

```bash
# Wave 4 — Ship gates (G4 + G5 evidence)
bash tools/harness/wave4-ship-gates.sh --smoke
bash tools/harness/wave4-ship-gates.sh --smoke --project-uuid '<disposable-operate-uuid>'

# Wave 3 — Harness Lite (no Hub)
bash tools/harness/sprint-close-operate-loop.sh
# optional full smoke:
bash tools/harness/sprint-close-operate-loop.sh --smoke

# Wave 2 platform tests + Hub
bash tools/hub-up.sh --rebuild
.venv/bin/python -m pytest shared/api/tests/test_operate_loop.py \
  shared/api/tests/test_project_recovery.py \
  shared/runtime/tests/test_phase_watcher_rules.py -q
bash tools/smoke-test.sh   # expect 99 PASS / 0 FAIL
curl -s --max-time 2 "http://localhost:8090/healthz" | jq .ok
curl -s --max-time 10 "http://localhost:8090/api/v2/projects/<uuid>/recovery" | jq .ok
```

---

## Prior work (ECC borrows) — complete

B1–B9 ECC borrows landed 2026-05-29. See git history. Not blocking Wave 1.

---

*Update this file when a wave task closes or focus shifts.*
