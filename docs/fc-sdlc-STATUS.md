# Spine — fc-sdlc execution state

> **Read me first for fc-sdlc / PM dashboard.** Spine's historical wave log stays in [`docs/STATUS.md`](./STATUS.md).

**Last updated:** 2026-06-01 — priorities 1–8 (partial; G0 sign + §9 E2E human)  
**Active phase:** Adoption — Sprint 0 (process bootstrap)  
**Sprint verdict:** Smoke **99/0**; `sdlc:run-qa` pass; PM dashboard live; §9 walkthrough **partial** (intake → `build_in_progress`, no role workers)  
**Branch:** `main`  
**Repo root:** `/Users/khashsarrafi/Projects/Apps/SpineDevelopment`

---

## TL;DR — what's true right now

| Area | Status | Evidence |
|------|--------|----------|
| Local dev stack | **Green** | `bash tools/hub-up.sh --rebuild` + `bash tools/smoke-test.sh` → 99 PASS / 0 FAIL |
| fc-sdlc scaffold | **Committed** | `todo/`, `pm.config.json`, `tools/fc-sdlc/` |
| CSRF + rate limit | Code done | Rebuild Hub: `bash tools/hub-up.sh --rebuild` |
| QA breadth | `pm.config.json` → `ci-test-full.sh` | `npm run sdlc:run-qa` / `:full` both pass locally |
| G0 charter content | Filled | `todo/gates/G0-charter.md` — scope in/out; **Go sign-off still human** |
| Backlog | Partial | `todo/BACKLOG.md` — SPINE-001..003 with real test paths |
| Gate sign-offs | Open | All G0–G6 unsigned |
| PM dashboard | **Running** | `npm run pm:dev` → http://127.0.0.1:5190 (`/api/dashboard`) |
| §9 golden path | **Near complete** | `65eed349-…` → `released`; intake→verify→release acked; deploy loop fix landed; stale `role_failure` card cleared manually |
| Cleanup report | Written | [`docs/SPRINT-0-CLEANUP-REPORT.md`](./SPRINT-0-CLEANUP-REPORT.md) |

---

## Commands

```bash
bash tools/hub-up.sh --rebuild    # before smoke / DB tests
bash tools/smoke-test.sh          # 99 PASS / 0 FAIL contract
npm run sdlc:validate-gates
npm run sdlc:run-qa
npm run sdlc:run-qa:full            # API + MCP smoke suites
npm run pm:dev                      # optional dashboard
```

---

## Session fixes (2026-06-01)

- fc-sdlc `ci-lint` / `ci-typecheck` / `ci-build` ROOT → repo root
- Hub rate-limit middleware registered in `create_app()`
- Project route tests mock `_direct_fetch_project_row`
- Doc SoT: process state → this file; QA scripts → `tools/fc-sdlc/ci-*.sh`
- PM dashboard started; `pm.config.json` QA → `ci-test-full.sh` (uncommitted)
- Golden-path: run with `PYTHONUNBUFFERED=1`; resume via `PROJECT_UUID=…` + `MAX_EMPTY_POLLS=5` for quick drain
- **Deploy fix:** `devops/runtime/hub_deploy_runner.py` schedules on Hub lifespan loop (fixes asyncpg cross-loop error from MCP `to_thread`)

---

## Links

- [SPINE_MASTER](./SPINE_MASTER.md) · [PLAYBOOK](./PLAYBOOK.md) · [AI-INTEGRATION](./AI-INTEGRATION.md)
- [SPRINT-0-CLEANUP-REPORT](./SPRINT-0-CLEANUP-REPORT.md)
