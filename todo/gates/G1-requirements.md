# G1 — Requirements Sign-off

**Project:** Spine  
**Depends on:** G0 Go (2026-06-19)  
**Date:** 2026-06-19  
**Decision:** ☑ Go  ☐ No-go  ☐ Waiver (link: ___)

## Exit criteria

- [x] PRD approved — [`docs/PRD.md`](../../docs/PRD.md) (canonical; Sprint 0 P0 REQs **Approved**: INIT-1, 5, 6, 7; remaining INITs **Draft v1** deferred to later sprints)
- [x] User journeys documented for primary personas — [`docs/SPINE_MASTER.md` §2.1](../../docs/SPINE_MASTER.md#21-user-journey-golden-path); personas below
- [x] Non-functional requirements documented — security: [`docs/SECURITY_GUIDE.md`](../../docs/SECURITY_GUIDE.md); performance/QA bar: [`docs/QA-READINESS-STANDARD.md`](../../docs/QA-READINESS-STANDARD.md); a11y: QA standard §6 (WCAG 2.2 AA)
- [x] Traceability matrix started — [`traceability-matrix.md`](../testing/traceability-matrix.md)
- [x] DoR defined for stories entering sprint backlog — [`docs/product/DELIVERY-MECHANISM.md` §Definition of Ready](../../docs/product/DELIVERY-MECHANISM.md#definition-of-ready-story)

## Primary personas & journeys

| Persona | Segment (#14) | Primary journey | Doc anchor |
|---------|---------------|-----------------|------------|
| **Solo founder** | Laptop / BYOC | Idea → intake → PRD/TRD cards → build → release | SPINE_MASTER §2.1 steps 1–8 |
| **Engineering lead** | Team / mid-market | Approve architecture, gate sign-offs, operate loop | SPINE_MASTER §2.3, G2–G6 gates |
| **Enterprise admin** | Enterprise / airgapped | Hub deploy, vault/IdP, federation, compliance evidence | PRD INIT-3/5/6/9, SECURITY_GUIDE |

**Golden path acceptance question (SPINE_MASTER §9):** *Can a non-engineer founder describe an app, approve a handful of cards, and receive a deployed product with audit trail?* — §9 automated walkthrough reached `released` (2026-06-01); SPA manual pass 2026-06-19 (Playwright 3/3).

## Non-functional requirements (Sprint 0 baseline)

| NFR | Source | Sprint 0 posture |
|-----|--------|------------------|
| **Security** | Vault-only secrets (#9), NOT SaaS (#15), Cite-or-Refuse (#12) | `SECURITY_GUIDE.md`; smoke vault checks pass |
| **Performance** | Hub SPA responsive; API p95 targets in TRD (G2) | SPA-HANG fixed; recovery ~150ms API, ~2–5s paint |
| **Accessibility** | WCAG 2.2 AA for Hub SPA | Tracked in QA-READINESS §6; full audit at G4 |
| **Reliability** | Smoke contract 99 PASS / 0 FAIL | Evidenced 2026-06-19 |
| **Auditability** | Hash-chained ledger (#24) | `shared/audit/`; Conductor hygiene gate (#34) |

## Holds (if any)

| Hold ID | Description | Owner | Target resolution |
|---------|-------------|-------|-------------------|
| — | — | — | — |

## Sign-off

> **Evidence (2026-06-19):** PRD P0 REQs approved; personas/journeys in SPINE_MASTER §2.1;
> NFRs cross-linked above; traceability matrix seeded; DoR in DELIVERY-MECHANISM.
> Harness Lite P2–P10 dogfood green. G0 Go 2026-06-19.

| Role | Name | Date | Decision |
|------|------|------|----------|
| Product owner | Khash Sarrafi | 2026-06-19 | ☑ Go ☐ No-go |
| Engineering lead | Khash Sarrafi | 2026-06-19 | ☑ Go ☐ No-go |
