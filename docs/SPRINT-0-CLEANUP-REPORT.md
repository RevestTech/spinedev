# Sprint 0 Cleanup Report — 2026-06-01

## QA-Readiness verdict

**YELLOW** — Environment and smoke contract green; fc-sdlc content partially filled; gates still unsigned.

## Gate status

| Gate | Status | Evidence |
|------|--------|----------|
| Tests green | **PASS** (subset) | Smoke 99/0/1/3; `sdlc:run-qa` exit 0; `test_routes_projects` 4/4; rate-limit tests pass |
| Requirements ↔ tech | **WARN** | Dual backlog (`todo/` vs `docs/BACKLOG.md`); PRD panel routes vs SPA |
| Drift handling | **WARN** | Decision `superseded` API gap; duplicate `_fetch_project_row` in `projects.py` |
| Documentation | **WARN** | AI-INTEGRATION/PLAYBOOK/QA paths aligned this session; Flyway V37 vs doc V35 |
| Security | **WARN** | Rate limit wired in `create_app()`; CSRF still open |
| Compliance | **WARN** | fc-sdlc placeholders reduced; G0–G6 unsigned |

## Lane 1 — Environment (completed)

| Check | Result |
|-------|--------|
| `bash tools/hub-up.sh --rebuild` | Success — spine-hub-postgres, spine-hub, tron postgres |
| `bash tools/smoke-test.sh` | **99 PASS / 0 FAIL / 1 WARN / 3 INFO** |
| Hub health | Containers up; API keys loaded from KMac vault |

## Phase 1 audit summary (8 parallel agents)

- **Requirements:** FAIL — traceability/backlog templates; PRD vs SPA route drift
- **Three-way drift:** WARN — decision status/kind API vs V36
- **Documentation:** WARN — fixed STATUS SoT + CI paths in this session
- **Security:** WARN — rate limit was unwired (fixed); CSRF deferred
- **Operational:** FAIL/WARN — fc-sdlc ROOT bug (fixed); SDLC path external to GHA
- **Tests:** FAIL → improved — mock path fixed for `_direct_fetch_project_row`
- **fc-sdlc adoption:** WARN — scaffold committed pending; G0 scope filled

## Resolved this sprint (session)

- `tools/fc-sdlc/ci-lint.sh`, `ci-typecheck.sh`, `ci-build.sh` — ROOT `../..` (repo root)
- `shared/api/app.py` — `install_rate_limit_middleware(app)` in `create_app()`
- `shared/api/tests/test_routes_projects.py` — mock `_direct_fetch_project_row` for delete/summary
- `docs/AI-INTEGRATION.md`, `docs/PLAYBOOK.md`, `docs/QA-READINESS-STANDARD.md` — SoT + CI paths
- `todo/gates/G0-charter.md` — Spine-specific scope in/out (no `{{SCOPE_*}}`)
- `todo/BACKLOG.md` — real test paths + SPINE-003
- `todo/testing/traceability-matrix.md` — REQ-INIT-1/10 starter rows

## Deferred (accepted risk)

| Finding | Owner | Target | Note |
|---------|-------|--------|------|
| CSRF for cookie-auth SPA | Engineering | Pre-G5 | Document SameSite + token strategy |
| Decision API `superseded` + open `kind` | Engineering | Sprint 1 | Align with V36 |
| Dual backlog (`docs/BACKLOG` vs `todo/BACKLOG`) | PO | Sprint 1 | Pick canonical mirror |
| SDLC scripts in sibling repo (GHA) | DevOps | Sprint 1 | Vendor or copy `validate-gates.mjs` |
| §9 founder walkthrough | Founder | Before ship | Needs live LLM + approvals |
| V1_SHIP_CHECKLIST ops gates | Founder | Launch | Outside repo |
| Commit fc-sdlc adoption tree | Engineering | This week | Still `??` on main |
| Full `pytest shared/` in PM QA | QA | Sprint 1 | PM QA remains narrow subset |

## Outstanding (blocking sprint close)

1. Sign **G0** (and program gate table in `todo/BACKLOG.md`)
2. Commit adoption artifacts (`todo/`, `package.json`, `tools/fc-sdlc/`, workflow)
3. Enable `--check-placeholders` in `.github/workflows/sdlc-validate-gates.yml` after commit
4. Run §9 golden-path walkthrough with valid API key

## Verification commands (re-run)

```bash
bash tools/hub-up.sh          # if stack down
bash tools/smoke-test.sh      # expect 99 PASS / 0 FAIL
npm run sdlc:run-qa
npm run sdlc:validate-gates
.venv/bin/python -m pytest shared/api/tests/test_routes_projects.py -q
```
