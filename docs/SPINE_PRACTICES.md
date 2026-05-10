# Spine practices — multi-agent development without drift

This document explains **what the SpineDevelopment pattern is for** and how to use it so software stays coherent when many agents and humans work in parallel.

## Goals

1. **Multi-agentic development** — Specialized roles (planner, researcher, engineer, operator, datawright, seer, auditor, memory) run in parallel where safe, coordinated through a **file bus** instead of one overloaded chat.
2. **Less drift** — Single protocol, structured reports, ADRs, session handoff, and per-role memory so context does not live only in one model turn.
3. **Durable documentation** — Protocol, requirements, recipes in-repo, and optional `DECISIONS.md` / `SESSION_HANDOFF.md` / `MASTER_TODO.md` at `.planning/orchestration/` give every new session the same baseline.

## How drift shows up (and how the spine counters it)

| Risk | Mitigation |
|------|------------|
| Two agents edit the same file | Role boundaries; manager declares file scope per worker; optional `file-lock.sh` |
| “It passed” without running checks | Auditor role; reports list **Files touched**; engineer runs gates |
| Lost decisions | `memory` role + `DECISIONS.md`; append-only ADRs |
| Model spend runaway | Tier hints + `costs.csv` + `make team-budget` |
| Sloppy temp files | Scratch dirs wiped per directive; hygiene rules in protocol |
| Stale instructions | `--pull-knowledge-only` refresh of recipes and role prompts without replacing daemons |

## Context stack (what to read, in order)

1. **`.planning/orchestration/AGENT_TEAM_PROTOCOL.md`** — Contract for all roles.  
2. **`.planning/orchestration/DECISIONS.md`** — What was decided and why.  
3. **`SESSION_HANDOFF.md` / `MASTER_TODO.md`** — If present, current focus and queue.  
4. **`teams/<role>/memory.md`** — Lessons for that role on this repo.  
5. **`~/.spine-development/playbook/<role>/lessons.md`** — Cross-project lessons (optional).

Agents invoked by the daemon get role prompt + memory + directive; keeping these files accurate is **the** lever for quality.

## Architect habits that help

- Write directives with **explicit constraints**, **report format**, and **`## Tier hint`** when non-default.  
- Use **`## Requires approval: yes`** for destructive or production-adjacent work.  
- After major work, queue a **`memory`** directive to fold outcomes into spine docs.  
- Periodically run **`make team-budget`** and **`make team-clean`** (or `team.sh clean all`).  
- Re-run **`install.sh <repo> --pull-knowledge-only`** on long-lived projects to pick up new recipes and prompts without touching customized scripts.

## Trust boundary

Only **trusted** people and processes should write under `.planning/orchestration/`. Directive files can trigger shell-backed agent CLIs. Treat that tree like commit access to your build.

## See also

- `README.md` — Quick start and layout  
- `PROTOCOL.md` — Full contract (copied to targets as `AGENT_TEAM_PROTOCOL.md`)  
- `docs/IMPROVEMENT_CHECKLIST.md` — Maintainer-oriented backlog  
- `CHANGELOG.md` — Package history  
