# Delivery mechanism — Spine

## Source of truth

**Git markdown is canonical.** Jira, Linear, and other ALM tools are optional mirrors. Ticket IDs originate here in [BACKLOG.md](../../todo/BACKLOG.md).

## Work hierarchy

```
INIT → EPIC → STORY → TASK → PR → Gate
```

| Level | ID pattern | Lives in |
|-------|------------|----------|
| Initiative | INIT-### | Backlog / roadmap doc |
| Epic | SPINE-E### or epic block | BACKLOG wave header |
| Story | SPINE-### | BACKLOG table |
| Task | Sub-row or SPINE-### | BACKLOG / sprint plan |
| PR | `[SPINE-###] description` | GitHub PR title |
| Gate | G0–G6 | todo/gates/ |

## Epic number blocks (configure for your domain)

| Block | Range | Domain area |
|-------|-------|-------------|
| Foundation | SPINE-010–019 | Scaffold, CI, harness |
| Core | SPINE-020–039 | Primary product surface |
| Integrations | SPINE-040–059 | External systems |
| Ops | SPINE-060–079 | Deploy, observability |

## Definition of Ready (story)

- [ ] Clear acceptance criteria
- [ ] Story points estimated
- [ ] Dependencies identified
- [ ] Technical approach sketched
- [ ] Test approach named

## Definition of Done (story)

- [ ] Code merged with tests
- [ ] Traceability matrix row updated
- [ ] Docs updated if user-visible
- [ ] No CRITICAL/HIGH issues without defer ticket

## Gate coupling

| Gate | Blocks | Unblocks |
|------|--------|----------|
| G0 | G1+ | Formal scope |
| G1 | G2+ | Architecture work |
| G2 | G3 build at scale | Epic build signoffs |
| G3 | G4 | Test sign-off |
| G4 | G5 | Release candidate |
| G5 | Production deploy | G6 operate |

## Escalation

| Situation | Escalate to | Timebox |
|-----------|-------------|---------|
| Gate waiver needed | Product owner + tech lead | 24h |
| Sprint scope slip > 20% | PO re-plan | Same sprint |
| Security CRITICAL open | Block G5 | Until mitigated or deferred |

## ALM mirror (optional)

See [JIRA-LINEAR-MAPPING.md](../../docs/JIRA-LINEAR-MAPPING.md) for one-way sync policy.
