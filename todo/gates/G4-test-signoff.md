# G4 — Test Sign-off

**Project:** Spine  
**Depends on:** G3 Go  
**Date:** ___________  
**Decision:** ☐ Go  ☐ No-go  ☐ Waiver (link: ___)

## Exit criteria

- [ ] Type-check / static analysis exits 0
- [ ] Unit tests 100% pass (zero unjustified skips)
- [ ] Integration tests pass for critical paths
- [ ] Traceability matrix updated — every P0/P1 REQ has test link or defer note
- [ ] Coverage meets project threshold (see QA Readiness Standard)
- [ ] Latest sprint cleanup report green or deferrals documented

## Test evidence

| Check | Command | Last run | Result |
|-------|---------|----------|--------|
| Unit tests | `scripts/ci-test.sh` | | ☐ Pass |
| Build | `scripts/ci-build.sh` | | ☐ Pass |
| Lint | `scripts/ci-lint.sh` | | ☐ Pass |

## Holds (if any)

| Hold ID | Description | Owner | Target resolution |
|---------|-------------|-------|-------------------|
| — | — | — | — |

## Sign-off

| Role | Name | Date | Decision |
|------|------|------|----------|
| QA lead | | | ☐ Go ☐ No-go |
| Tech lead | | | ☐ Go ☐ No-go |
