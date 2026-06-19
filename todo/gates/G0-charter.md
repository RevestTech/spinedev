# G0 — Charter & Scope

**Project:** Spine  
**Depends on:** — (entry gate)  
**Date:** 2026-06-19 (evidence refreshed); sign-off **Go**  
**Decision:** ☑ Go  ☐ No-go  ☐ Waiver (link: ___)

## Scope (in)

- [x] Hub golden path — containerized Hub product (Day-0 wizard → orchestrator + role loop per `docs/SPINE_MASTER.md`); §9 auto-walk reached `released` on project `65eed349-…` (2026-06-01)
- [x] fc-sdlc adoption — Sprint 0: `tools/fc-sdlc/` gates wired to `todo/` backlog as source of truth; `npm run sdlc:run-qa` exit 0
- [x] Smoke contract — `bash tools/smoke-test.sh` **99 PASS / 0 FAIL** (2026-06-19 re-verified); CI (`--ci`) blocks merge on regression
- [x] Hub SPA workspace — SPA-HANG fix committed; Playwright **3/3 pass** (2026-06-19)
- [x] Harness Lite — P2–P10 dogfood green; `spine harness verify --run-qa` exit 0 (2026-06-19)
- [x] Vault-only secrets (#9) — no `env://`, no real values in `.env`; Hub loads keys from KMac vault via `hub-up.sh`

## Scope (out)

- [x] V1 vendor ops — Shamir key ceremony, `spine.dev` / `try.spine.dev` demo sandbox, customer launch gates in `docs/V1_SHIP_CHECKLIST.md`
- [x] Full federation/license polish — Hub-to-Hub registry UX (#10/#16), Ed25519 quota ledger hardening, feature-flag gating polish beyond Day-0 (#23)

## Risks accepted

| Risk | Mitigation | Owner |
|------|------------|-------|
| CSRF for cookie-auth SPA not wired | SameSite + token strategy before G5; rate limit already in `create_app()` | Engineering |
| Dual backlog (`docs/BACKLOG.md` vs `todo/BACKLOG.md`) | Pick canonical mirror in Sprint 1 | PO |
| GHA gate scripts live in sibling SDLC repo | Vendor or copy `validate-gates.mjs` in Sprint 1 | DevOps |
| PM QA runs narrow subset (not full `pytest shared/`) | Expand in Sprint 1 | QA |

## Holds (if any)

| Hold ID | Description | Owner | Target resolution |
|---------|-------------|-------|-------------------|
| — | — | — | — |

## Sign-off

> **Human action:** Fill Name + Date and check **Go** when approving Sprint 0 scope.
> Agents must not mark Go without your explicit approval.
>
> **Evidence (2026-06-19):** smoke 99/0, Playwright SPA-HANG 3/3, harness verify `--run-qa` pass,
> Hub `:8090/spa/` healthy. Prior: `sdlc:run-qa` pass, §9 automated to `released` (2026-06-01).
> See [`docs/fc-sdlc-STATUS.md`](../../docs/fc-sdlc-STATUS.md), [`docs/SESSION_HANDOFF.md`](../../docs/SESSION_HANDOFF.md).

| Role | Name | Date | Decision |
|------|------|------|----------|
| Product owner | Khash Sarrafi | 2026-06-19 | ☑ Go ☐ No-go |
| Engineering lead | Khash Sarrafi | 2026-06-19 | ☑ Go ☐ No-go |
