# QA Readiness Standard — Spine

**Bar:** Code shipped after sprint close is QA-ready with **zero defects**. QA is not the discovery surface for bugs we could catch ourselves.

## Definition of Done (sprint-level)

A sprint cannot close until all six gates pass for every committed story:

### 1. Tests green
- Type-check exits 0 (`tools/fc-sdlc/ci-typecheck.sh`)
- All tests 100% pass, zero unjustified skips (`tools/fc-sdlc/ci-test.sh`)
- Production build succeeds (`tools/fc-sdlc/ci-build.sh`)
- Size/bundle budgets pass (if applicable — budget: 150 KB)
- E2E smoke passes for all critical user journeys

### 2. Requirements ↔ tech match
- Every PRD requirement traces to a delivered story, deferred ticket, or explicit defer note
- Every TRD architectural claim matches actual file structure
- Sprint plan story IDs map 1:1 to merged work or open follow-ups
- Permission/auth catalog ↔ spec doc ↔ DB schema fully in sync

### 3. Drift handling (three-way checks)
Every cross-cutting concern verified across **code ↔ spec ↔ DB**:
- Auth model
- Audit/event taxonomy
- Status enum vocabulary across all consumers
- Public-facing API contracts
- Data model and migrations

### 4. Documentation best practices
- Zero dead internal markdown links
- Zero phantom file references (every cited path exists)
- All "Last updated" timestamps current
- STATUS doc internally consistent (no header vs body contradictions)
- ADRs still apply (audited, not assumed)

### 5. Security review
- Security review doc open items triaged: CLOSED, PARTIAL, or OPEN (with owner)
- OWASP-applicable checks current
- Rate-limit posture documented for every public endpoint
- Secrets via approved provider: **project-approved vault** — no hardcoded keys/tokens/passwords
- Server-side enforcement parity for every client-side permission check

### 6. Compliance review
- Org/style rules sweep clean (adapt per project)
- WCAG 2.2 AA + Level A: zero new failures
- Conventional Commits enforced (hook present + tested)
- Audit log writes verified for every privileged mutation

## Enforcement

Run `/sprint-cleanup` at sprint end. Phase 3 verification report is the gate.

Deferrals are first-class — list in `docs/SPRINT-N-CLEANUP-REPORT.md` with owner, target sprint, and approver.

## Cadence

- End of every sprint (mandatory)
- Before G2, G4, G5 gate sign-offs (mandatory)
- Ad-hoc when STATUS and code visibly drift

## References

- [docs/adr/ADR-008-sprint-cleanup-methodology.md](./adr/ADR-008-sprint-cleanup-methodology.md)
- `.cursor/commands/sprint-cleanup.md`
