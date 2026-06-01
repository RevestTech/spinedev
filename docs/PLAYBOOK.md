# Spine — fc-sdlc playbook

One-page onboarding for product owners, tech leads, and AI agents.

## Day 0 — Bootstrap (30 minutes)

1. Confirm fc-sdlc init ran (`todo/`, `pm.config.json`, `docs/fc-sdlc-STATUS.md`)
2. Fill [G0 charter](../todo/gates/G0-charter.md) scope in/out
3. Set epic blocks and `SPINE-###` IDs in [DELIVERY-MECHANISM](./product/DELIVERY-MECHANISM.md)
4. Write first honest [fc-sdlc-STATUS](./fc-sdlc-STATUS.md) baseline (`docs/STATUS.md` = historical v3 wave log only)
5. Run Sprint 0 harness: `npm run test:ci` (or stack equivalent)

## Every sprint

| When | Action | Artifact |
|------|--------|----------|
| Start | Sprint plan from template | `docs/product/SPRINT-N-PLAN.md` |
| Daily | Update blockers in fc-sdlc-STATUS | `docs/fc-sdlc-STATUS.md` |
| End | Run `/sprint-cleanup` | `docs/SPRINT-N-CLEANUP-REPORT.md` |
| End | Update velocity ledger | `docs/VELOCITY-LEDGER.md` |
| Gate | Sign gate file or document waiver | `todo/gates/G*.md` |

## Earned sprint close (not declared)

1. Self-audit reality + coverage matrices
2. **Independent re-audit** before G5
3. Quantified G5 thresholds in gate file
4. If bar not met → hotfix sprint (e.g. 7.5), not silent overconfidence

## Honesty over theater

- FAKE/BROKEN = 0 at G5, **or** visible defer badge + ticket in UI
- STUB must be user-visible with ticket reference
- fc-sdlc-STATUS separates "true now" from "planned next"

## Three layers reminder

| Layer | You edit | PM reads |
|-------|----------|----------|
| 1 | `todo/BACKLOG.md`, gates | derive.js |
| 2 | ADRs, QA standard, cleanup reports | gate % |
| 3 | Check-ins, QA runs | dashboard SSE |

## ALM (optional)

Jira/Linear mirror IDs only — see [JIRA-LINEAR-MAPPING.md](./JIRA-LINEAR-MAPPING.md).

## Parallel agents

Before multi-agent waves: read [PARALLEL-BATCH-CHECKLIST.md](./PARALLEL-BATCH-CHECKLIST.md) and [ADR-005](./adr/ADR-005-parallel-subagent-orchestration.md).

## AI agents

Read [AI-INTEGRATION.md](./AI-INTEGRATION.md) first.
