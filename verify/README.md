# `verify/` — Verify subsystem (TRON integration)

> **Status:** Scaffolded 2026-05-16 (Phase 0). Empty awaiting **Phase 1** — `git subtree add` of TRON.

## Purpose

The verification subsystem. Runs TRON's 7-layer verification pipeline on Build outputs: deterministic scanners (Bandit / Semgrep / ESLint / OSV) → schema-validated LLM ISO agents → execution sandbox → cross-LLM consensus → Platt-calibrated confidence → prompt regression CI. Returns `VerifyFindings` to the Orchestrator, which routes back to Build for remediation or surfaces to user for approval.

This is TRON, integrated as a first-class Spine subsystem via `git subtree`.

## Boundary

**In scope:**
- ISO agents (SecurityISO, BuilderISO, QAISO, PerformanceISO, ComplianceISO, DocumentationISO)
- 7-layer verification pipeline
- Docker ephemeral sandbox + seccomp
- Temporal workflows
- Platt-scaled confidence calibration
- FastAPI routes (verify-internal)
- Verify-specific output templates (`agent_handoff_templates/`)

**Out of scope (moved to `shared/` during integration):**
- TRON's standards hierarchy → `shared/standards/` (`STORY-2.4.1`)
- TRON's MCP server → `shared/mcp/` (`STORY-8.2.2`)
- TRON's memory → `shared/memory/` (`STORY-8.2.3`)
- TRON's tree-sitter parsers → `build/kg/parsers/` (`STORY-8.2.4`)
- TRON's frontend → `shared/ui/` (`STORY-8.2.6`)
- TRON's infra (Vault, etc.) → `shared/infra/` (`STORY-8.2.5`)

## Stack

- **Python 3.11+ + FastAPI + Temporal + Postgres + Docker** (TRON's existing stack, preserved)
- Talks to Orchestrator via MCP (`verify_audit(build_artifact, blueprint)` returns `VerifyFindings`)
- Postgres schemas: `spine_verify_*` (within the unified single Postgres instance)

## Sub-structure (target — populated by Phase 1 `git subtree`)

```
verify/
├── agents/             # ISO agents
├── pipeline/           # 7-layer verification
├── sandbox/            # Docker ephemeral + seccomp
├── workflows/          # Temporal workflows
├── calibration/        # Platt scaling
├── api/                # FastAPI routes
├── agent_handoff_templates/
└── tests/
```

## Standalone deployability

`verify/` is designed to **still run standalone** after integration — preserves TRON's existing audit-only deployment model for orgs that want the verification product without the full Spine pipeline. Don't break this property when wiring to Orchestrator.

## Backlog

- **INIT-8** Verify Subsystem (TRON Integration) — primary owner. 6 epics, ~22 stories.
- **EPIC-3.5/6/7** — Sandbox / Calibration / Cross-LLM Validation lifted from TRON; some live here, some in `shared/`.
- **Sprint 1** includes `STORY-8.1.1` (the actual `git subtree add` operation).

## See also

- `docs/ARCHITECTURE.md` §5 (full TRON → Spine code mapping)
- `docs/PRD.md#req-init-8` (stub — full PRD post-Phase-1)
- TRON source repo (current path): `/Users/khashsarrafi/Projects/Utilities/tron`
