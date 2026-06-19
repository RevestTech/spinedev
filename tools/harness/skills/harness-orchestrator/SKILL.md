---
name: harness-orchestrator
description: >-
  Harness Lite orchestrator — reads .spine/harness/state.json, schedules
  ADR-008 audit/fix/verify waves, dispatches token-capped subagents, and
  updates gate rollup. Use when spine harness start is active or on loop wake.
---

# Harness Orchestrator (Lite)

Portable playbook for **Harness Lite** — runs on any repo without Hub.
Coordinates the ADR-008 3-phase pattern via background loops and foreground
agent dispatch.

## When to invoke

- After `spine harness start <mode>` or on `AGENT_LOOP_WAKE_harness_*` sentinel
- When user asks for harness status, next wave, or gate rollup
- Before transitioning from audit → fix → verify

## Read state first

1. Read `.spine/harness/state.json` — mode, wave, gates, active_loops
2. If missing, tell user: `spine harness init --project .`
3. Skip re-audit of gates already `green` unless mode is `sprint-close`

## Mode behavior

| Mode | Next action |
|------|-------------|
| `bootstrap` | Run one audit-wave scout, then suggest `start watch` |
| `feature` | On git wake: audit-wave for changed files only |
| `sprint-close` | Full 3-phase: audit-wave → fix-wave → verify-wave |
| `release-gate` | audit-wave until all gates green or deferrals logged |
| `watch` | Long heartbeat; event watchers primary |

## Wave dispatch (ADR-008 — never mix phases)

```
Phase 1 audit-wave  (READ-ONLY, parallel investigators)
        ↓
Phase 2 fix-wave    (WRITE, exclusive file scope per agent)
        ↓
Phase 3 verify-wave (READ-ONLY, QA commands last)
```

Update `state.json` `wave` field when entering each phase.

## Subagent rules (token caps)

| Rule | Value |
|------|-------|
| Prompt word cap | 200–400 words per dispatch |
| Audit output cap | 400 words per agent report |
| Output contract | `path:line: severity: claim vs actual. fix.` |
| Audit agents | `cavecrew-investigator` (locate/drift); Explore only if prose needed |
| Fix agents | `cavecrew-builder` for ≤2 file surgical edits |
| Parallel scouts | 2–3 investigators in one message, different angles |

## Findings I/O

- Write Phase 1 output to `.spine/harness/findings/<gate>-<timestamp>.json`
- Schema: `tools/harness/templates/.spine/harness/findings.schema.json`
- Main thread reads **summary + structured JSON**, not raw prose dumps

## Gate rollup

After verify-wave, update `state.json` gates from QA-READINESS-STANDARD:

`tests` · `requirements` · `drift` · `docs` · `security` · `compliance`

Status values: `green` | `yellow` | `red` | `unknown`

## References

- `Handoff.md` — Harness Lite architecture
- `docs/adr/ADR-008-sprint-cleanup-methodology.md`
- `docs/QA-READINESS-STANDARD.md`
- `tools/harness/skills/harness-audit-wave/SKILL.md`
- `tools/harness/skills/harness-fix-wave/SKILL.md`
- `tools/harness/skills/harness-verify-wave/SKILL.md`
