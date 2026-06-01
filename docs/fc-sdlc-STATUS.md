# Spine — fc-sdlc execution state

> **Read me first for fc-sdlc / PM dashboard.** Spine's historical wave log stays in [`docs/STATUS.md`](./STATUS.md).

**Last updated:** 2026-06-01 — Sprint 0 cleanup (lane 1 + audit fan-out)  
**Active phase:** Adoption — Sprint 0 (process bootstrap)  
**Sprint verdict:** Smoke **99/0** green with hub-up; fc-sdlc placeholders partially filled; gates unsigned  
**Branch:** `main`  
**Repo root:** `/Users/khashsarrafi/Projects/Apps/SpineDevelopment`

---

## TL;DR — what's true right now

| Area | Status | Evidence |
|------|--------|----------|
| Local dev stack | **Green** | `bash tools/hub-up.sh --rebuild` + `bash tools/smoke-test.sh` → 99 PASS / 0 FAIL |
| fc-sdlc scaffold | Done (uncommitted) | `todo/`, `pm.config.json`, `tools/fc-sdlc/` |
| G0 charter content | Filled | `todo/gates/G0-charter.md` — scope in/out, no `{{SCOPE_*}}` |
| Backlog | Partial | `todo/BACKLOG.md` — SPINE-001..003 with real test paths |
| Gate sign-offs | Open | All G0–G6 unsigned |
| PM dashboard | Not running | `npm run pm:dev` → http://localhost:5190 |
| Cleanup report | Written | [`docs/SPRINT-0-CLEANUP-REPORT.md`](./SPRINT-0-CLEANUP-REPORT.md) |

---

## Commands

```bash
bash tools/hub-up.sh --rebuild    # before smoke / DB tests
bash tools/smoke-test.sh          # 99 PASS / 0 FAIL contract
npm run sdlc:validate-gates
npm run sdlc:run-qa
npm run pm:dev                      # optional dashboard
```

---

## Session fixes (2026-06-01)

- fc-sdlc `ci-lint` / `ci-typecheck` / `ci-build` ROOT → repo root
- Hub rate-limit middleware registered in `create_app()`
- Project route tests mock `_direct_fetch_project_row`
- Doc SoT: process state → this file; QA scripts → `tools/fc-sdlc/ci-*.sh`

---

## Links

- [SPINE_MASTER](./SPINE_MASTER.md) · [PLAYBOOK](./PLAYBOOK.md) · [AI-INTEGRATION](./AI-INTEGRATION.md)
- [SPRINT-0-CLEANUP-REPORT](./SPRINT-0-CLEANUP-REPORT.md)
