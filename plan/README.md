# `plan/` — Plan subsystem (intake → PRD → TRD → Roadmap)

> **Status:** Scaffolded 2026-05-16 (Phase 0). Empty awaiting Sprint 2/3 work.

## Purpose

The upfront SDLC pipeline that takes a vibecoder from "I have an idea" to "fully baked, signed-off PRD + TRD + Roadmap, ready to execute." Three phases: **Product Discovery → Technical Review (swarm) → Decomposition.** Each phase produces a signed artifact gated on user approval.

This is Spine's *defining* feature.

## Boundary

**In scope:**
- `product` role — intake interrogator (5-move dialogue protocol)
- `architect` role + Technical Review swarm (architect-lead + scout roles)
- `planner` + `conductor` — Roadmap decomposer
- Project-type intake templates (web-app, internal-tool, data-pipeline, mobile, api-service, cli-tool)
- PRD / TRD / Roadmap artifact schemas (Pydantic)

**Out of scope:**
- Code execution (lives in `build/`)
- Code verification (lives in `verify/`)
- Approval gate UI (lives in `shared/ui/`; orchestrator owns gate enforcement)
- Pipeline customization manifest (lives in `shared/standards/` — org bundle)

## Stack

- **Bash daemons** for the role agents (preserves debuggability moat)
- **LangGraph subgraph** inside the architect daemon for swarm orchestration (typed state + checkpointing; see `EPIC-1.2`)
- Pydantic artifact schemas (pattern lifted from TRON `FindingOutput`)

## Sub-structure (target)

```
plan/
├── roles/              # product, architect, planner, swarm-scout roles
├── templates/          # intake templates per project type (templates/intake/<type>.yaml)
├── artifacts/          # PRD/TRD/Roadmap Pydantic schemas
└── tests/
```

## Backlog

- **INIT-1** Plan Subsystem — primary owner. 7 epics, ~37 stories. See `docs/BACKLOG.md`.
- **EPIC-1.2** uses LangGraph for swarm — sole LangGraph use site in the orchestration layer.
- **EPIC-1.3** (Roadmap Decomposer) depends on `INIT-6` KG for deterministic story-dependency detection.

## See also

- `docs/ARCHITECTURE.md` §2 + §4
- `docs/PRD.md#req-init-1` (approved)
- `~/.claude/.../memory/spine_intake_pattern.md` — the 5-move dialogue protocol
