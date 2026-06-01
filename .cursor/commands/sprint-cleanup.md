---
description: End-of-sprint 3-phase parallel cleanup (audit → fix → verify). QA-ready zero-defect bar.
---

# /sprint-cleanup

Run at sprint end or before G2/G4/G5 sign-offs. Copy [docs/SPRINT-N-CLEANUP-REPORT-TEMPLATE.md](../docs/SPRINT-N-CLEANUP-REPORT-TEMPLATE.md) to `docs/SPRINT-<N>-CLEANUP-REPORT.md`.

See [docs/QA-READINESS-STANDARD.md](../docs/QA-READINESS-STANDARD.md) and [docs/adr/ADR-008-sprint-cleanup-methodology.md](../docs/adr/ADR-008-sprint-cleanup-methodology.md).

## Inputs

- Sprint number (e.g. `5`)
- `--audit-only` — Phase 1 + 3 only
- `--scope=<area>` — requirements | drift | docs | security | compliance | code-quality | operational | all

## Phase 1 — Audit (READ-ONLY, parallel)

Spawn read-only audits. Output drift table:

```
| Severity | File:line | Claim | Actual | Recommendation |
```

Cap: 400 words per report.

## Phase 2 — Fix (WRITE, file-partitioned)

One agent = one exclusive file scope. HIGH/CRITICAL must fix or defer this wave.

## Phase 3 — Verification (READ-ONLY, last)

Run project QA commands from `pm.config.json`. Write `docs/SPRINT-<N>-CLEANUP-REPORT.md`.

## Report template

```markdown
# Sprint <N> Cleanup Report — <date>
## QA-Readiness verdict: GREEN / YELLOW / RED
## Gate status (6 gates from QA Readiness Standard)
## Resolved | Deferred | Outstanding (blocking)
```

## Rules

- Audit before fix — never same wave
- Validate script names before invoking
- Use `${PIPESTATUS[0]}` after pipes for exit codes
- Sweep `*conflicted*` sync artifacts
