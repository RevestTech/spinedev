# SDLC Plan — Spine

Program-level SDLC overview. Gates G0→G6 live in [todo/gates/](../../todo/gates/).

## Gate sequence

| Gate | Purpose | Primary artifact |
|------|---------|------------------|
| G0 | Charter — scope in/out | [G0-charter.md](../../todo/gates/G0-charter.md) |
| G1 | Requirements signed | PRD + traceability |
| G2 | Architecture / ADRs | TRD + schema policy |
| G3 | Build complete | Per-epic signoff |
| G4 | Test sign-off | Coverage + traceability |
| G5 | Release ready | Quantified DoD thresholds |
| G6 | Operate | Runbooks, kill-switches |

**Rule:** No phase advance without signed artifact or documented waiver.

## Roles

| Role | Responsibilities |
|------|------------------|
| Product owner | G0/G1/G5 sign-off, backlog priority |
| Tech lead | G2/G3/G4 sign-off, architecture |
| QA lead | G4 evidence, reality audit |
| Release manager | G5/G6, deploy readiness |

## Ceremony cadence

| Ceremony | Frequency | Output |
|----------|-----------|--------|
| Sprint planning | Every 2 weeks | Sprint plan doc |
| Daily standup | Daily | Blockers in STATUS |
| Sprint review | End of sprint | Demo + metrics update |
| Sprint cleanup | End of sprint | SPRINT-N-CLEANUP-REPORT.md |
| Retrospective | End of sprint | VELOCITY-LEDGER update |

## Related docs

- [DELIVERY-MECHANISM.md](./DELIVERY-MECHANISM.md)
- [STATUS.md](../STATUS.md)
- [QA-READINESS-STANDARD.md](../QA-READINESS-STANDARD.md)
