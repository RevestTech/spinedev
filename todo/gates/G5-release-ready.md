# G5 — Release Ready

**Project:** Spine  
**Depends on:** G4 Go  
**Date:** ___________  
**Decision:** ☐ Go  ☐ No-go  ☐ Waiver (link: ___)

## Quantified thresholds (operate-loop release slice)

For this program slice, G5 focuses on **platform operate autonomy** — not full
v1 vendor launch (`docs/V1_SHIP_CHECKLIST.md` remains separate).

| Criterion | Threshold | Result | Status |
|-----------|-----------|--------|--------|
| Scoped pytest | `scope_pytest.py` exit 0 on operate-loop scope | | ☐ |
| Smoke contract | 99 PASS / 0 FAIL (`smoke-test.sh --ci`) | | ☐ |
| Recovery SLA | `GET /recovery` ≤ 2s | | ☐ |
| Black-box iteration | ≥1 `completed` + queued feature (`operate_blackbox.py`) | | ☐ |
| No manual customer-app edits | Acceptance via disposable project only | | ☐ |
| Human gate sign-off | G0 + G4 + G5 artifacts signed | | ☐ |

## Quantified thresholds (full product — deferred)

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

- Wave 4 rollup: [evidence/wave4-operate-loop-latest.md](./evidence/wave4-operate-loop-latest.md)
- Black-box tool: [`tools/acceptance/operate_blackbox.py`](../../tools/acceptance/operate_blackbox.py)
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
