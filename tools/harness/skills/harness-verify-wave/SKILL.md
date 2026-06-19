---
name: harness-verify-wave
description: >-
  Harness Lite Phase 3 — read-only verification gate. Runs QA commands last,
  updates gate rollup in state.json, writes cleanup report. ADR-008 verify after fix.
---

# Harness Verify Wave (Phase 3)

**READ-ONLY verification.** Runs **last** — after fix-wave. Produces gate
rollup and human-readable report.

## When to invoke

- `state.json` wave is `verify`
- Fix wave complete (or no fixable HIGH/CRITICAL remain)
- `release-gate` polling tick when fixes landed

## QA command source

1. Target project's `pm.config.json` → `qa.command` if present
2. Spine defaults: `tools/fc-sdlc/ci-test-full.sh` or `bash tools/smoke-test.sh`

Run commands; capture exit codes. Use `${PIPESTATUS[0]}` after pipes.

## Six-gate bar (QA-READINESS-STANDARD)

Update `state.json` gates:

| Gate | Green when |
|------|------------|
| `tests` | type-check 0, tests 100%, build ok |
| `requirements` | PRD/TRD trace clean or deferrals logged |
| `drift` | three-way checks pass |
| `docs` | no dead links / phantom refs |
| `security` | open items triaged |
| `compliance` | WCAG + commits + audit writes ok |

Status: `green` | `yellow` | `red` | `unknown`

## Report output

Write markdown to:

- `.spine/harness/reports/latest.md` (always)
- Optional: `docs/SPRINT-N-CLEANUP-REPORT.md` for sprint-close

Set `state.json` `last_report` to report path.

Report sections:

1. Executive summary (gate rollup table)
2. QA command results (command, exit code, evidence)
3. Open findings / deferrals (owner, target sprint)
4. Sign-off checklist

## TRON / charter evals (P7)

Lite verify runs **offline charter evals** via committed fixtures (default) or stub (red-path drill):

```bash
spine harness verify --project .
spine harness verify --callable stub --markdown   # exercise red-path gate
spine harness verify --roles qa,auditor,engineer --markdown
```

Optional QA command (needs Postgres/Docker when configured):

```bash
spine harness verify --run-qa
```

Fixtures: `tools/harness/fixtures/charter_evals/<role>/<eval-name>.txt`

## Handoff

- All gates green → set mode `watch` or stop loops
- Red/yellow gates → orchestrator schedules next audit-wave for failed gates only
- Set `state.json` wave → `null` when cycle complete

## Prompt template (≤400 words)

```
Verify wave — READ-ONLY.
Run QA: <command from pm.config.json or default>.
Evaluate 6 gates per QA-READINESS-STANDARD.
Write .spine/harness/reports/latest.md with evidence.
Update state.json gate rollup.
Do not edit source — report and gate status only.
```

## References

- `docs/QA-READINESS-STANDARD.md`
- `docs/adr/ADR-008-sprint-cleanup-methodology.md` Phase 3
- `verify/charter_evals/harness.py`
