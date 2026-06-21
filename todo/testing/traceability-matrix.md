# Traceability matrix

Map requirements to implementation and tests. Update as items enter Build.

| REQ-ID | Feature | Module / path | Test file | Gate | Status |
|--------|---------|---------------|-----------|------|--------|
| REQ-INIT-1 | Hub Day-0 surfaces | `hub/`, `shared/ui/spa/` | `tools/smoke-test.sh` | G4 | Partial |
| REQ-INIT-10 | KG retrieve/index | `build/kg/`, `shared/runtime/kg_role_context.py` | `shared/api/tests/test_post_ack_golden_path.py` | G4 | Partial |
| SPINE-OP-01 | Security review blocked → remediate | `shared/api/routes/_post_ack.py`, `_role_dispatch_bridge.py` | `shared/api/tests/test_project_recovery.py` | G4 | Done |
| SPINE-OP-02 | Auto-remediate retry on dispatch_in_flight | `shared/api/routes/_project_recovery.py` | `shared/api/tests/test_project_recovery.py` | G4 | Done |
| SPINE-OP-03 | Dedupe auto-remediate schedules | `shared/api/routes/_project_recovery.py` | `shared/api/tests/test_project_recovery.py` | G4 | Done |
| SPINE-OP-04 | Recovery API perf (async workspace scan) | `shared/api/routes/_project_recovery.py` | `shared/api/tests/test_project_recovery.py` | G4 | Done |
| SPINE-OP-06 | devops ack → complete + promote feature | `shared/api/routes/_post_ack.py`, `_project_recovery.py` | `shared/api/tests/test_operate_loop.py` | G4 | Done |
| SPINE-OP-07 | Promoted feature → PRODUCE_FEATURE | `shared/api/routes/_project_recovery.py`, `_role_dispatch_bridge.py` | `shared/api/tests/test_operate_loop.py` | G4 | Done |
| SPINE-OP-08 | Persist operate_serve_url | `shared/api/routes/_post_ack.py` | `shared/api/tests/test_operate_loop.py` | G4 | Done |
| SPINE-OP-09 | Phase watcher operate + full_auto | `shared/runtime/pipeline_runner.py`, `gate_policy.py` | `shared/runtime/tests/test_phase_watcher_rules.py` | G4 | Done |
| SPINE-OP-10 | Operate loop unit coverage | `shared/api/tests/test_operate_loop.py` | same | G4 | Done |
| SPINE-H-02 | Harness sprint-close operate scope | `tools/harness/sprint-close-operate-loop.sh` | `tools/harness/lib/scope_pytest.py` | G4 | Done |
| SPINE-ACC-01 | Black-box operate acceptance | Hub API (read-only) | `tools/acceptance/operate_blackbox.py` | G5 | Planned |
| SPINE-OP-05 | Hub rebuild + smoke (no hot-patch) | `tools/hub-up.sh`, `hub/` | `tools/smoke-test.sh` | G4/G5 | Pending |

**Status values:** Planned · Partial · Done · Deferred (link ticket)

*Add a row per backlog item in [BACKLOG.md](../BACKLOG.md) as items enter Build.*

**Evidence rollup:** `bash tools/harness/wave4-ship-gates.sh` → `todo/gates/evidence/wave4-operate-loop-latest.md`

**Last updated:** 2026-06-21
