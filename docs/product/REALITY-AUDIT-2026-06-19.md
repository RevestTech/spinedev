# Reality audit — Spine Hub (Sprint 0)

**Date:** 2026-06-19  
**Auditor:** Orchestrator session (automated scout + QA sweep)  
**Scope:** Foundation epic + Hub golden path surfaces

## Summary

| Class | Count |
|-------|-------|
| LIVE | 8 |
| PARTIAL | 4 |
| FAKE | 1 |
| BROKEN | 0 |

**G5 posture:** Not ready — PARTIAL/FAKE items need defer badges or fixes before sign-off.

## Findings

| Feature | Status | Evidence |
|---------|--------|----------|
| Smoke contract | LIVE | `tools/smoke-test.sh` 99 PASS / 0 FAIL (2026-06-19) |
| Hub SPA dashboard | LIVE | `curl :8090/spa/` → 200 |
| Project workspace | LIVE | Playwright 3/3 (`project-workspace-hang.spec.ts`) |
| Decision queue | LIVE | `panels/decision-queue/+page.svelte` + API |
| Orchestrator bridge | LIVE | `KIND_ROLE_DISPATCH` 13 kinds incl. watcher tail (2026-06-19 fix) |
| Phase watcher tail | PARTIAL | Rules exist; tail kinds now bridged — needs live project E2E |
| Role chat stubs | FAKE | `RoleChatPanel` shows `metadata.stub` when MCP tool absent |
| PM dashboard | PARTIAL | `pm.config.json` present; service not running locally |
| Operating loop daemons | PARTIAL | `role_runtime.py` directive bus only; no background workers |
| G5 coverage reports | MISSING | PRD/API/Data coverage docs not yet filled |

## Next orchestrator actions

1. Live project E2E through `verify_approved → operate` with phase watcher
2. Fill `COVERAGE-PRD-2026-06-19.md` from `docs/PRD.md` index
3. Defer or wire RoleChatPanel stub with visible badge
