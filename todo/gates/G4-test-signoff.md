# G4 — Test Sign-off

**Project:** Spine  
**Depends on:** G3 Go  
**Date:** 2026-06-21 (evidence); sign-off pending  
**Decision:** ☐ Go  ☐ No-go  ☐ Waiver (link: ___)

## Exit criteria (operate-loop program)

- [x] Operate-loop scoped unit tests pass (Wave 3 harness)
- [ ] Smoke contract **99 PASS / 0 FAIL** with `--ci` (run via wave4 rollup)
- [x] Traceability matrix updated — SPINE-OP-* rows in [`traceability-matrix.md`](../testing/traceability-matrix.md)
- [ ] Hub rebuild evidence (SPINE-OP-05) — `bash tools/hub-up.sh --rebuild`
- [ ] Recovery API SLA ≤2s on live Hub (black-box or manual curl)
- [ ] Human QA + tech lead sign-off below

## Test evidence

| Check | Command | Last run | Result |
|-------|---------|----------|--------|
| Scoped operate pytest | `python3 tools/harness/lib/scope_pytest.py --scope-file tools/harness/scopes/operate-loop.txt` | 2026-06-21 | ☐ Pass (run locally) |
| Wave 3 sprint-close | `bash tools/harness/sprint-close-operate-loop.sh` | 2026-06-21 | ☐ Pass (run locally) |
| Wave 4 rollup | `bash tools/harness/wave4-ship-gates.sh --smoke` | | ☐ Pass |
| Smoke contract | `bash tools/smoke-test.sh --ci` | | ☐ Pass |
| Operate unit tests | `.venv/bin/python -m pytest shared/api/tests/test_operate_loop.py shared/api/tests/test_project_recovery.py shared/runtime/tests/test_phase_watcher_rules.py -q` | | ☐ Pass |

Automated evidence file: [`evidence/wave4-operate-loop-latest.md`](./evidence/wave4-operate-loop-latest.md)

## Holds (if any)

| Hold ID | Description | Owner | Target resolution |
|---------|-------------|-------|-------------------|
| H-G4-01 | Hub rebuild not evidenced in CI/agent shell | DevOps | SPINE-OP-05 |

## Sign-off

> **Human action:** Mark Go only after wave4 rollup + smoke pass on your machine.

| Role | Name | Date | Decision |
|------|------|------|----------|
| QA lead | _pending_ | _pending_ | ☐ Go ☐ No-go |
| Tech lead | _pending_ | _pending_ | ☐ Go ☐ No-go |
