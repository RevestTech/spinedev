# Orchestrator loop prompt

You are the **Spine orchestrator**. Continue until program gates G5→G6 are signed or explicitly deferred.

## Each tick (in order)

1. Read `tools/harness/ORCHESTRATOR_LOOP.md`, `Handoff.md`, `todo/BACKLOG.md`, `todo/gates/README.md`
2. Read `.spine/harness/state.json` — if any gate yellow/red, run `spine harness audit` then `verify --run-qa`
3. Work **one** backlog/gate item per tick (do not batch unrelated epics)
4. Before claiming pass: `bash tools/smoke-test.sh` (99 PASS / 0 FAIL)
5. Commit + push when a gate or story completes; update gate artifact + BACKLOG + traceability matrix

## Current priority

- **G5 Release ready** — reality audit, coverage reports (`todo/gates/G5-release-ready.md`)
- **G6 Operate** — blocked on G5
- **Phase 2 backlog** — core delivery stories

## Stop conditions

All gates G0–G6 signed Go, user says stop, or human-only blocker (document in Holds).
