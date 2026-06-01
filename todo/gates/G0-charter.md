# G0 — Charter & Scope

**Project:** Spine  
**Depends on:** — (entry gate)  
**Date:** ___________  
**Decision:** ☐ Go  ☐ No-go  ☐ Waiver (link: ___)

## Scope (in)

- [ ] Hub golden path — containerized Hub product (Day-0 wizard → orchestrator + role loop per `docs/SPINE_MASTER.md`)
- [ ] fc-sdlc adoption — Sprint 0: `tools/fc-sdlc/` gates wired to `todo/` backlog as source of truth
- [ ] Smoke contract — `bash tools/smoke-test.sh` must hold 99 PASS / 0 FAIL; CI (`--ci`) blocks merge on regression
- [ ] Vault-only secrets (#9) — no `env://`, no real values in `.env`; all secrets via `shared/secrets/` vault adapters

## Scope (out)

- [ ] V1 vendor ops — Shamir key ceremony, `spine.dev` / `try.spine.dev` demo sandbox, customer launch gates in `docs/V1_SHIP_CHECKLIST.md`
- [ ] Full federation/license polish — Hub-to-Hub registry UX (#10/#16), Ed25519 quota ledger hardening, feature-flag gating polish beyond Day-0 (#23)

## Risks accepted

| Risk | Mitigation | Owner |
|------|------------|-------|
| | | |

## Holds (if any)

| Hold ID | Description | Owner | Target resolution |
|---------|-------------|-------|-------------------|
| — | — | — | — |

## Sign-off

> **Human action:** Fill Name + Date and check **Go** when approving Sprint 0 scope.
> Agents must not mark Go without your explicit approval.

| Role | Name | Date | Decision |
|------|------|------|----------|
| Product owner | _pending_ | _pending_ | ☐ Go ☐ No-go |
| Engineering lead | _pending_ | _pending_ | ☐ Go ☐ No-go |
