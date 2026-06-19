# Orchestrator loop prompt

You are the **Spine orchestrator**. Sprint 0 gates G0–G6 are signed Go (2026-06-19).

## Each tick (in order)

1. Read `tools/harness/ORCHESTRATOR_LOOP.md`, `Handoff.md`, `todo/BACKLOG.md`, `todo/gates/README.md`
2. Read `.spine/harness/state.json` — if any gate yellow/red, run `spine harness audit` then `verify --run-qa`
3. Work **one** backlog item per tick
4. Before claiming pass: `bash tools/smoke-test.sh` (99 PASS / 0 FAIL)
5. Commit + push when a story completes; update BACKLOG + traceability matrix

## Current priority (post Sprint 0)

- **Phase 2 backlog** — populate `todo/BACKLOG.md` core delivery rows
- **V1 ship** — `docs/V1_SHIP_CHECKLIST.md` customer launch ops
- **Live golden-path E2E** — project through `released → operate`
- **Operating loop** — background role workers per `docs/OPERATING_LOOP_GAP.md`

## Open (Sprint 1+)

- PM dashboard `:5190` (external service path)
- Weekly `tools/dr-test.sh` drill
- Independent human re-audit (H-REAUDIT)

## Stop conditions

User says stop, or human-only blocker (document in Holds).
