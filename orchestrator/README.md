# `orchestrator/` — Central lifecycle state machine

> **Status:** Scaffolded 2026-05-16 (Phase 0). Empty awaiting Sprint 1 work.

## Purpose

The unifying coordinator. Owns project lifecycle, phase gates, routing to Plan/Build/Verify subsystems, cost/audit aggregation, portfolio management, and the user-facing API surface. Without this layer, Plan/Build/Verify are three disconnected things; with it, they're one product.

## Boundary

**In scope:**
- Project lifecycle state machine + Postgres schema (`spine_lifecycle`)
- Phase transitions and gate enforcement
- Routing layer: dispatch directives to Plan / Build / Verify via MCP
- Failure handling (Verify fail → reroute to Build with remediation directive)
- Portfolio management (multiple projects in flight)
- Unified cost ledger + audit log aggregation
- Orchestrator API: MCP server + REST + CLI for user/UI

**Out of scope:**
- Subsystem internals (those live in `plan/`, `build/`, `verify/`)
- Knowledge graph (`build/kg/` + `shared/db/`)
- Standards/policy enforcement (`shared/standards/`)

## Stack

- **Bash + Postgres** for state machine (preserves debuggability moat)
- Minimal Python helpers where needed
- Talks to subsystems via `shared/mcp/`

## Sub-structure (target)

```
orchestrator/
├── lib/                # state machine logic (bash + minimal Python)
├── state/              # Postgres schema (lifecycle, phase, transition, approval)
├── api/                # MCP + REST surface
└── tests/
```

## Backlog

- **INIT-9** Central Orchestrator — primary owner. See `docs/BACKLOG.md`.
- Cross-cutting consumers: every other INIT depends on the orchestrator to dispatch work.

## See also

- `docs/ARCHITECTURE.md` §2 (architecture diagram) + §4 (target structure)
- `docs/PRD.md#req-init-9` (stub — full PRD post-Sprint-1)
