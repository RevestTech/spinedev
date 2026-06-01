# G5 — Release Ready

**Project:** Spine  
**Depends on:** G4 Go  
**Date:** ___________  
**Decision:** ☐ Go  ☐ No-go  ☐ Waiver (link: ___)

## Quantified thresholds

All criteria must pass or have a documented defer with visible UI badge + ticket reference.

| Criterion | Threshold | Result | Status |
|-----------|-----------|--------|--------|
| Reality audit | FAKE + BROKEN = 0 OR each remaining has defer ticket + visible badge | | ☐ |
| PRD coverage (P0) | ≥ 90% LIVE | | ☐ |
| API coverage | ≥ 90% SHIPPED-AND-USED | | ☐ |
| Data coverage | ≥ 90% LIVE-USED | | ☐ |
| No silent failures | Every user action persists OR shows defer/loading badge | | ☐ |
| Independent re-audit | Completed after self-audit (earned close) | | ☐ |
| Release tag | Version tagged in git | | ☐ |

## Evidence links

- Reality audit: [REALITY-AUDIT-YYYY-MM-DD.md](../../docs/product/REALITY-AUDIT-YYYY-MM-DD.md)
- PRD coverage: [COVERAGE-PRD-YYYY-MM-DD.md](../../docs/product/COVERAGE-PRD-YYYY-MM-DD.md)
- API coverage: [COVERAGE-TRD-API-YYYY-MM-DD.md](../../docs/product/COVERAGE-TRD-API-YYYY-MM-DD.md)
- Data coverage: [COVERAGE-TRD-DATA-YYYY-MM-DD.md](../../docs/product/COVERAGE-TRD-DATA-YYYY-MM-DD.md)
- Sprint cleanup: [SPRINT-N-CLEANUP-REPORT.md](../../docs/SPRINT-N-CLEANUP-REPORT.md)

## Holds (if any)

| Hold ID | Description | Owner | Target resolution |
|---------|-------------|-------|-------------------|
| — | — | — | — |

## Sign-off

| Role | Name | Date | Decision |
|------|------|------|----------|
| Product owner | | | ☐ Go ☐ No-go |
| Engineering lead | | | ☐ Go ☐ No-go |
| Release manager | | | ☐ Go ☐ No-go |

## Post-G5 backlog (explicitly out of scope for this release)

- [ ] Production deploy pipeline tested
- [ ] Observability + on-call runbooks
- [ ] Load / security audit for production scale
