# `verify/` — Spine Verify Subsystem (TRON Integration)

> **Spine subsystem boundary doc.** Lives alongside TRON's own `verify/README.md` (TRON's project docs). This file describes the *Spine* role of this subsystem — what it owns, its contract to the Orchestrator, its stack, its boundary. Renamed from `README.md` to `SUBSYSTEM_BOUNDARY.md` to avoid clash with TRON's pre-existing README.md when integrated via `git subtree`.
>
> **Status:** TRON subtree-merged 2026-05-16 (Phase 1) from `/Users/khashsarrafi/Projects/Utilities/tron@main` (`adcebe33`).

## Purpose

The verification subsystem. Runs TRON's 7-layer verification pipeline on Build outputs: deterministic scanners (Bandit / Semgrep / ESLint / OSV) → schema-validated LLM ISO agents → execution sandbox → cross-LLM consensus → Platt-calibrated confidence → prompt regression CI. Returns `VerifyFindings` to the Orchestrator, which routes back to Build for remediation or surfaces to user for approval.

This is TRON, integrated as a first-class Spine subsystem.

## Boundary

**In scope:**
- ISO agents (SecurityISO, BuilderISO, QAISO, PerformanceISO, ComplianceISO, DocumentationISO) — live at `verify/tron/agents/`
- 7-layer verification pipeline — `verify/tron/verification/`
- Docker ephemeral sandbox + seccomp — `verify/tron/sandbox/`
- Temporal workflows — `verify/tron/workflows/`
- Platt-scaled confidence calibration
- FastAPI routes (verify-internal) — `verify/tron/api/`
- Verify-specific output templates (`verify/tron/agent_handoff_templates/`)

**Out of scope (cross-cutting; will move to `shared/` in Phase 2):**
- TRON's standards hierarchy → `shared/standards/` (`STORY-2.4.1`)
- TRON's MCP server → `shared/mcp/` (`STORY-8.2.2`)
- TRON's memory → `shared/memory/` (`STORY-8.2.3`)
- TRON's tree-sitter parsers → `build/kg/parsers/` (`STORY-8.2.4`)
- TRON's frontend → `shared/ui/` (`STORY-8.2.6`)
- TRON's infra (Vault, etc.) → `shared/infra/` (`STORY-8.2.5`)

These haven't moved yet — they're staged for Phase 2 per `docs/ARCHITECTURE.md §6`.

## Stack

- **Python 3.11+ + FastAPI + Temporal + Postgres + Docker** (TRON's existing stack, preserved)
- Talks to Orchestrator via MCP (`verify_audit(build_artifact, blueprint)` returns `VerifyFindings`)
- Postgres schemas: `spine_verify_*` (within the unified single Postgres instance)

## Sub-structure (post-Phase-1; per ARCHITECTURE.md §4)

```
verify/                       # ← Subtree merged from TRON 2026-05-16
├── README.md                 # TRON's own project README (preserved)
├── SUBSYSTEM_BOUNDARY.md     # ← this file — Spine boundary doc
├── AGENTS.md                 # TRON's agent context
├── tron/                     # TRON application code
│   ├── agents/               # ISO agents
│   ├── verification/         # 7-layer pipeline
│   ├── sandbox/              # Docker + seccomp
│   ├── workflows/            # Temporal
│   ├── api/                  # FastAPI
│   ├── schemas/              # Pydantic models
│   ├── services/             # ThreatIntel, handoff exports
│   ├── standards/            # → moves to shared/standards/ in Phase 2
│   ├── mcp/                  # → moves to shared/mcp/ in Phase 2
│   ├── memory/               # → moves to shared/memory/ in Phase 2
│   ├── parsers/              # → moves to build/kg/parsers/ in Phase 2
│   ├── infra/                # → moves to shared/infra/ in Phase 2
│   └── realtime/             # → moves to shared/realtime/ in Phase 2
├── frontend/                 # → moves to shared/ui/ in Phase 2
├── admin-ui/                 # → retires per TRON roadmap
├── alembic/                  # → migrates to Flyway in Phase 2 (shared/db/)
├── docker-compose.yml        # TRON dev stack
├── Makefile                  # TRON's per-subsystem targets
├── pyproject.toml
└── tests/                    # TRON's pytest suite
```

## Standalone deployability (hard requirement — G-8 in REQ-INIT-8)

`verify/` is designed to **still run standalone** after integration — preserves TRON's existing audit-only deployment model for orgs that want the verification product without the full Spine pipeline:

- `cd verify/ && docker compose up -d` runs TRON audit-only with no Orchestrator
- TRON's existing `tron` CLI continues to work standalone
- No env var, schema, or service from outside `verify/` is required to run TRON audit-only
- Phase 2 consolidation (shared Postgres, shared MCP) is **additive** — TRON's standalone compose still wires its own services if the umbrella isn't present

**Don't break this property when wiring to Orchestrator.**

## Backlog

- **INIT-8** Verify Subsystem (TRON Integration) — primary owner. 6 epics, ~22 stories. See `docs/BACKLOG.md`.
- **EPIC-3.5/6/7** — Sandbox / Calibration / Cross-LLM Validation lifted from TRON; some live here, some in `shared/`.
- **Sprint 2** includes `STORY-8.5.1` (orchestrator invokes TRON `AuditManager`).

## See also

- `docs/ARCHITECTURE.md` §5 (full TRON → Spine code mapping)
- `docs/PRD.md#req-init-8` (Draft v1)
- `verify/README.md` — TRON's own project README (immediately below this file in the same dir)
- `verify/AGENTS.md` — TRON's agent context
- `verify/docs/BLUEPRINT.md` — TRON's canonical doc index
- Original TRON source (pre-subtree): `/Users/khashsarrafi/Projects/Utilities/tron`
