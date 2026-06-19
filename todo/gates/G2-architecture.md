# G2 — Architecture & Design

**Project:** Spine  
**Depends on:** G1 Go (2026-06-19)  
**Date:** 2026-06-19  
**Decision:** ☑ Go  ☐ No-go  ☐ Waiver (link: ___)

## Exit criteria

- [x] TRD / architecture doc approved — [`docs/ARCHITECTURE.md`](../../docs/ARCHITECTURE.md) (v3 authoritative layout); TRD template [`plan/artifacts/trd_v1.py`](../../plan/artifacts/trd_v1.py)
- [x] ADRs for major decisions — [`docs/adr/`](../../docs/adr/) (ADR-005 parallel subagents, ADR-008 sprint-cleanup); locked decisions [`docs/V3_DESIGN_DECISIONS.md`](../../docs/V3_DESIGN_DECISIONS.md) (34 items)
- [x] Data model / schema policy — Flyway migrations `db/flyway/sql/V1–V37`; policy in [`db/README.md`](../../db/README.md)
- [x] API contract outline — Hub REST `/api/v2/*`; OpenAPI emitter [`shared/api/openapi_spec.py`](../../shared/api/openapi_spec.py); MCP 54 tools [`shared/mcp/`](../../shared/mcp/)
- [x] Security model documented — [`docs/SECURITY_GUIDE.md`](../../docs/SECURITY_GUIDE.md) (vault-only #9, OIDC #25, NOT SaaS #15); auth middleware in `shared/api/`
- [x] Test harness baseline in place — `tools/smoke-test.sh` (99 PASS contract), `tools/harness/` (Harness Lite P10), `tools/fc-sdlc/ci-test-full.sh`

## Architecture summary (Sprint 0 baseline)

| Layer | Canonical doc / path |
|-------|----------------------|
| Product vision + golden path | `docs/SPINE_MASTER.md` |
| Subsystem layout (LOCKED) | `docs/ARCHITECTURE.md` §2 |
| Locked decisions | `docs/V3_DESIGN_DECISIONS.md` |
| Hub container | `hub/` + `hub/docker-compose.yml` |
| Orchestration | `orchestrator/` (phases, gates, CLI) |
| Portable harness (Lite) | `tools/harness/` (no Hub required) |
| Postgres schema | `db/flyway/sql/` — spine lifecycle, KG, audit, federation, license |

**Gap acknowledged (not G2 blockers):** Operating company loop still partially unwired per SPINE_MASTER §4; v1 ship ops in `V1_SHIP_CHECKLIST.md`.

## Holds (if any)

| Hold ID | Description | Owner | Target resolution |
|---------|-------------|-------|-------------------|
| — | — | — | — |

## Sign-off

> **Evidence (2026-06-19):** ARCHITECTURE.md v3 refresh; 37 Flyway migrations; OpenAPI spec
> module; SECURITY_GUIDE; smoke 99/0; harness 13 tests pass; Playwright SPA 3/3.

| Role | Name | Date | Decision |
|------|------|------|----------|
| Tech lead | Khash Sarrafi | 2026-06-19 | ☑ Go ☐ No-go |
| Engineering lead | Khash Sarrafi | 2026-06-19 | ☑ Go ☐ No-go |
