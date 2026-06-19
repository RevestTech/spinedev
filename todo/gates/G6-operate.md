# G6 — Operate

**Project:** Spine  
**Depends on:** G5 Go (2026-06-19)  
**Date:** 2026-06-19  
**Decision:** ☑ Go  ☐ No-go  ☐ Waiver (link: ___)

**Scope:** Sprint 0 **laptop / local-dev** operate baseline. Customer production ops gates remain in `docs/V1_SHIP_CHECKLIST.md`.

## Exit criteria

- [x] Production deploy pipeline defined and tested — `.github/workflows/docker-build.yml` + `tools/hub-up.sh` (local); CI `docker-build` on PR/main
- [x] Infrastructure provisioned — `hub/docker-compose.yml` (Hub + Postgres + Vault + Keycloak + TRON PG); smoke 99/0 (2026-06-19)
- [x] Secrets migrated to approved provider — vault-only (#9); `docs/SECURITY_GUIDE.md`; no real values in repo
- [x] Backup + restore procedure rehearsed — `docs/DR_RUNBOOK.md` + `tools/dr-test.sh` (architectural); automated weekly drill deferred H-DR-DRILL
- [x] Observability — Hub `/healthz`, `shared/runtime/watchdog.sh`, `devops/runtime/operate_runner.py` (8 planes); full Grafana stack deferred
- [x] On-call runbook + escalation — `docs/HUB_OPERATIONS_GUIDE.md`, `docs/DR_RUNBOOK.md` §escalation
- [x] Kill-switches / feature flags — `license/` feature flags (#23); env toggles `SPINE_PHASE_WATCHER`, `SPINE_HOOK_PROFILE`
- [x] CHANGELOG and release notes — `CHANGELOG.md`; release tag `v1.4.4`

## Operational readiness

| Area | Runbook link | Last drill | Status |
|------|--------------|------------|--------|
| Deploy | [`docs/HUB_OPERATIONS_GUIDE.md`](../../docs/HUB_OPERATIONS_GUIDE.md), `tools/hub-up.sh` | 2026-06-19 smoke | ☑ |
| Rollback | `hub/docker-compose` image pin; git tag `v1.4.4` | N/A local | ☑ (documented) |
| Incident response | [`docs/HUB_OPERATIONS_GUIDE.md`](../../docs/HUB_OPERATIONS_GUIDE.md) §troubleshooting | — | ☑ |
| DR / failover | [`docs/DR_RUNBOOK.md`](../../docs/DR_RUNBOOK.md), `tools/dr-test.sh` | Sprint 1 scheduled | ☑ (partial) |

## Holds (if any)

| Hold ID | Description | Owner | Target resolution |
|---------|-------------|-------|-------------------|
| H-DR-DRILL | Weekly `tools/dr-test.sh` automated drill | Ops | Sprint 1 |
| H-PROD-DEPLOY | Customer-cloud / K8s production shape rehearsal | DevOps | `V1_SHIP_CHECKLIST.md` |
| H-OBS-STACK | Full metrics/traces/alerting (Grafana/Prometheus) | Ops | Sprint 1+ |

## Sign-off

> **Evidence (2026-06-19):** Hub healthy locally; operate_runner wired; DR + ops guides
> landed; smoke 99/0; harness verify pass. Full vendor launch ops out of scope (V1 checklist).

| Role | Name | Date | Decision |
|------|------|------|----------|
| Ops / on-call lead | Khash Sarrafi | 2026-06-19 | ☑ Go ☐ No-go |
| Engineering lead | Khash Sarrafi | 2026-06-19 | ☑ Go ☐ No-go |
| Product owner | Khash Sarrafi | 2026-06-19 | ☑ Go ☐ No-go |
