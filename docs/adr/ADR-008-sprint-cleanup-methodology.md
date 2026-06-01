# ADR-008 — Sprint Cleanup Methodology

**Status:** Accepted (YYYY-MM-DD)

## Context

End-of-sprint cleanup must produce QA-ready code with zero defects — verified alignment across requirements, implementation, schema, documentation, security, and compliance. Serial review does not scale; parallel agents require strict file ownership.

## Decision

Adopt a **3-phase parallel cleanup pattern** at every sprint close and before G2/G4/G5 sign-offs.

### Phase 1 — Audit fan-out (READ-ONLY)
20–30 parallel agents, single scope each. Output: structured drift tables.

### Phase 2 — Fix fan-out (WRITE)
Agents with **exclusive file ownership**. HIGH/CRITICAL first. No shared files in same wave.

### Phase 3 — Verification gate (READ-ONLY)
Full pipeline + `docs/SPRINT-N-CLEANUP-REPORT.md`. Sprint close requires green or formal deferrals.

## Operational rules

1. Audit before fix — never mix phases in one wave
2. One agent = one file scope per wave
3. Three-way drift: code ↔ spec ↔ DB
4. Match agent type to capability (writers must have Write tools)
5. Word-count cap every prompt (200–400 words)
6. Sweep sync conflict artifacts (`*conflicted*`) every cleanup

## References

- `.cursor/commands/sprint-cleanup.md`
- [docs/QA-READINESS-STANDARD.md](../QA-READINESS-STANDARD.md)
