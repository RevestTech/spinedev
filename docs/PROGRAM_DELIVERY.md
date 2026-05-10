# Program delivery with SpineDevelopment (SDLC orchestration)

This document is the operational bridge between **business intent** and the **daemon-backed AI team**.

## 1. Artifact stack (canonical locations)

Install places templates under `.planning/orchestration/program/`. Maintain at least:

| Path | Purpose |
|------|---------|
| `POLICY.stub.md` | Linked corporate controls (privacy, branching, ML usage, spend caps) |
| `REQ-xxxx.md` or similar | Approved/draft requirement records |
| `PROGRAM_PHASES.md` | Lifecycle gate ledger (who signed what, when) |
| `DECISIONS.md` | Append-only ADRs |
| `ux/`, `qa/` subfolders | Specialized narrative outputs |

Agents load these via directives and `memory` hygiene passes.

## 2. Who runs which phase

1. **`product`** — drafts REQ, captures stakeholder intents.
2. **Humans** (CPO/COO/legal/CTO delegates) flip `revision: approved`.
3. **`architect`** + **`planner`** — technical planning, decomposition, spikes.
4. **`conductor`** — issues parallel squad directives with `## Linked REQ` guards.
5. **`engineering-*` / `qa` / `ux` / `operator` / `datawright`** execute with workers.
6. **`auditor` + `memory`** mitigate drift once milestones close.

Always propagate **`## Tier hint`** so telemetry in `teams/*/state/costs.csv` reflects spend policy.

## 3. Recursive collaboration pattern

Squads rerun the **exact same orchestration primitives**:

- `# Directive → # Plan → # Worker Directive/report → aggregated # Report`.

No extra daemon tiers—breadth emerges from parallel roles enumerated in `scripts/roles.sh`.

## 4. Executive alignment

Executive titles (**CTO**, **COO**, **CPO**) do **not** map 1:1 to always-on AI daemons—they anchor approvals in Markdown and ADR merges. Exceptions require explicit waiver text inside the REQ or ADR with human attribution.

---

