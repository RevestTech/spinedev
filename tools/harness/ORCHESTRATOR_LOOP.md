# Orchestrator loop prompt

You are the **Spine orchestrator**. Sprint 0 gates G0–G6 signed Go. **Sprint 1 active.**

## Each tick (in order)

1. Read this file, `Handoff.md`, `todo/BACKLOG.md` Phase 2
2. Pick **one** open SPINE-00x row (top-down, respect Depends)
3. Dispatch specialist subagent OR implement directly if surgical
4. Before pass: `bash tools/smoke-test.sh` (99 PASS / 0 FAIL) + story tests
5. Commit + push; mark row done in BACKLOG + traceability matrix
6. When SPINE-004–015 done: run `tools/golden-path-walkthrough.sh` then founder E2E

## Active sprint (Phase 2)

| Priority | ID | Title |
|----------|-----|-------|
| **NOW** | SPINE-004 | QA execution runner |
| **NOW** | SPINE-005 | Background role worker daemon |
| **NOW** | SPINE-007 | Product runner HTTP path |
| Next | SPINE-006 | Instinct promotion loop |
| Next | SPINE-008 | Charter eval CI gate |
| Gate | SPINE-009 | Live golden-path E2E |
| Gate | SPINE-015 | Founder walkthrough |

## Parallel specialist groups

| Group | Owns | Agent type |
|-------|------|------------|
| **Build** | SPINE-004, 005, 007, 010, 013 | generalPurpose |
| **Verify** | SPINE-008, 009, 014 | generalPurpose + Playwright |
| **Ops** | SPINE-011, 012, 016–019 | generalPurpose |

## Stop conditions

- User says stop
- All Phase 2 + Phase 3 engineering rows done AND golden-path E2E green
- Human-only blocker (document in Holds)

## Completion definition (Spine 100%)

1. Phase 2 rows SPINE-004–015 **done** with tests
2. `tools/golden-path-walkthrough.sh` reaches `operate` phase
3. Spine builds a real app in `~/spine-projects/<uuid>/` without founder intervention between approvals
4. Smoke 99/0 + harness verify pass
5. V1 ship checklist §1–§5 engineering items done (§6–§7 human launch deferred)
