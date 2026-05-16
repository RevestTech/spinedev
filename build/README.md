# `build/` — Build subsystem (execution layer)

> **Status:** Scaffolded 2026-05-16 (Phase 0). Empty awaiting Sprint 2 work; existing daemons stay in `lib/` until opportunistically migrated.

## Purpose

The execution subsystem. Receives directives from the Orchestrator, dispatches to engineer / operator / datawright role daemons, emits typed `BuildArtifact` outputs (code + tests + manifest + KG impact set), hands off to Verify.

Also houses the **Knowledge Graph parsers** (tree-sitter) — feeds the KG schema in `shared/db/` so every role across Plan/Build/Verify can query code structure deterministically.

## Boundary

**In scope:**
- Engineer / operator / datawright role daemons
- Worker pool primitives (10 workers per manager)
- Bash daemon infrastructure (migrated from `lib/team-agent-daemon.sh`)
- Knowledge graph parsers (tree-sitter for v1 language set: Python, TS/JS, Go, Rust, Bash, SQL, Markdown)
- `BuildArtifact` Pydantic schema (replaces free-form markdown reports)

**Out of scope:**
- Planning / requirements (lives in `plan/`)
- Verification / audit / security scanning (lives in `verify/`)
- Knowledge graph *storage* (lives in `shared/db/spine_kg`)
- MCP server (lives in `shared/mcp/`) — Build *consumes* graph tools from MCP

## Stack

- **Bash** daemons (preserves debuggability moat — NOT replaced by LangGraph at orchestration layer)
- **Tree-sitter** for code parsing (no LSP servers required)
- Optional Python for KG parser extractors

## Sub-structure (target)

```
build/
├── roles/              # engineer, operator, datawright role prompts + memory
├── daemons/            # bash daemon infra (migrated from lib/)
├── workers/            # worker pool primitives
├── kg/                 # knowledge graph
│   ├── parsers/        # tree-sitter parsers (lifted from tron/parsers/)
│   └── extractors/     # per-language AST → node/edge config
└── tests/
```

## Backlog

- **INIT-7** Build Subsystem — primary owner. 5 epics, ~14 stories.
- **INIT-6** Code & Document Knowledge Graph — KG parsers/indexer live here; storage in `shared/db/`.
- Migration: `STORY-7.5.1` moves `lib/team-agent-daemon.sh` here; `STORY-8.2.4` moves `tron/parsers/` here.

## See also

- `docs/ARCHITECTURE.md` §4 (structure) + §5 (TRON → Spine code mapping)
- `docs/PRD.md#req-init-7` (stub — full PRD post-Sprint-1)
- `docs/PRD.md#req-init-6` (KG, approved)
