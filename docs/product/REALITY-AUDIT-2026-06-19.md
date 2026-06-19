# Reality audit — Spine Hub (Sprint 0)

**Date:** 2026-06-19  
**Auditor:** Orchestrator session (automated scout + QA sweep)  
**Re-audit:** Harness `verify --run-qa` exit 0 (2026-06-19)  
**Scope:** Foundation epic + Hub golden path surfaces

## Summary

| Class | Count |
|-------|-------|
| LIVE | 9 |
| PARTIAL | 3 |
| STUB (visible badge) | 1 |
| FAKE | 0 |
| BROKEN | 0 |

**G5 posture:** P0 golden path **ready** — STUB/PARTIAL items documented with defer notes.

## Findings

| Feature | Status | Evidence |
|---------|--------|----------|
| Smoke contract | LIVE | `tools/smoke-test.sh` 99 PASS / 0 FAIL (2026-06-19) |
| Hub SPA dashboard | LIVE | `curl :8090/spa/` → 200 |
| Project workspace | LIVE | Playwright 3/3 (`project-workspace-hang.spec.ts`) |
| Decision queue | LIVE | `panels/decision-queue/+page.svelte` + API |
| Orchestrator bridge | LIVE | `KIND_ROLE_DISPATCH` 13 kinds (tail wired 2026-06-19) |
| Phase watcher tail | PARTIAL | Bridged; live project E2E through `operate` pending |
| Role chat offline | STUB | `RoleChatPanel` shows visible **stub** badge (`:228-231`) |
| PM dashboard | PARTIAL | Wired `pm.config.json`; PM service optional (H-PM) — [PM_DASHBOARD.md](../PM_DASHBOARD.md) |
| Operating loop daemons | PARTIAL | `role_runtime.py` directive bus; background workers Sprint 1 |
| Coverage reports | LIVE | PRD/API/Data 2026-06-19 in `docs/product/` |

## Deferrals (visible / ticket)

| Item | Hold | Owner | Target |
|------|------|-------|--------|
| PM :5190 | H-PM | DevOps | Sprint 1 — see [PM_DASHBOARD.md](../PM_DASHBOARD.md) |
| Background role workers | H-WORKERS | Engineering | Sprint 1 per OPERATING_LOOP_GAP |
| Independent human re-audit | H-REAUDIT | QA | Before customer ship |
