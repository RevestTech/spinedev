# `shared/` — Cross-cutting modules

> **Status:** Scaffolded 2026-05-16 (Phase 0). Sub-directories appear as work happens.

## Purpose

Modules used by two or more of Plan / Build / Verify / Orchestrator. Lives here once to prevent duplication; subsystems import as needed but never own these directly.

## Sub-structure (target — created as features land)

```
shared/
├── db/                 # Postgres (recording + KG + lifecycle + audit + verify schemas) — moved from /db
│   ├── flyway/         # SQL migrations
│   ├── docker-compose.yml
│   └── watcher/        # file → DB watcher (extended for KG indexing)
├── mcp/                # unified MCP server (consolidates Spine MCP + tron/mcp)
├── cost/               # cost router + ledger
├── audit/              # append-only audit log
├── memory/             # role memory + cross-project playbook
├── standards/          # org policy bundles (lifted from tron/standards)
├── validation/         # cross-LLM consensus (lifted from TRON AuditManager)
├── ui/                 # dashboard / front-door (lifted from tron/frontend)
├── infra/              # Vault, secrets helpers (lifted from tron/infra)
├── realtime/           # WebSocket / SSE plumbing (lifted from tron/realtime)
└── eval/               # LangSmith-style regression harness (lifted from TRON golden_suite)
```

## Boundary

**In scope:** anything used by ≥ 2 subsystems.

**Out of scope:** subsystem-internal code (lives in `plan/`, `build/`, `verify/`, `orchestrator/`).

## Stack

Polyglot — language per concern:
- `db/` — SQL + Flyway + Python (watcher)
- `mcp/` — Python (FastMCP or stdlib MCP)
- `cost/` — Bash + Python (router policy in bash; LangChain helpers in Python)
- `audit/` — SQL views + Bash CLI tools
- `memory/` — Markdown + Postgres index (pgvector for embeddings)
- `standards/` — YAML schemas + Python validation
- `validation/` — Python (TRON-lifted)
- `ui/` — TypeScript / React (TRON-lifted)
- `infra/` — Python (TRON-lifted)
- `eval/` — Python (LangSmith-style)

## Postgres schema layout (single instance)

| Schema | Purpose | Owner |
|---|---|---|
| `spine_recording` | Agent activity history (directives, reports, costs) | existing |
| `spine_kg` | Knowledge graph (kg_node, kg_edge, embeddings) | INIT-6 |
| `spine_lifecycle` | Orchestrator state (project, phase, transitions, approvals) | INIT-9 |
| `spine_audit` | Append-only audit log (every LLM call, every gate decision) | INIT-3 |
| `spine_verify_*` | TRON's existing verify schemas | INIT-8 |
| `spine_calibration` | Platt-scaled outcome corpus | INIT-3 (EPIC-3.6) |

## Backlog

This directory absorbs work from multiple INITs:
- **INIT-2** EPIC-2.4 — TRON Standards Hierarchy lift
- **INIT-3** EPIC-3.5/6/7 — Sandbox / Calibration / Cross-LLM
- **INIT-6** — KG storage in `shared/db/`
- **INIT-8** EPIC-8.2 + EPIC-8.3 — TRON code mapping + Postgres consolidation
- **INIT-9** EPIC-9.6/9.7/9.9 — Cost ledger + audit + MCP server

## See also

- `docs/ARCHITECTURE.md` §4 + §9 (cross-cutting tech decisions table)
- `db/README.md` (legacy location — content moves under `shared/db/` in Phase 2 per `STORY-8.3.3`)
