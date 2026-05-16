# `iso.py` — TRON ISO agents exposed as MCP tools (early-detect)

**Stories:** `STORY-8.6.1`, `STORY-8.6.2`
**Spec:** `docs/PRD.md` REQ-INIT-8 FR-5

## Why early-detect

The canonical Verify pass runs after Build seals a `BuildArtifact`. That's fine for catching regressions, but it's slow for the engineer who *just wrote* a security-sensitive change and would like a second opinion **before** declaring the directive done. Exposing each TRON ISO agent as an individually-addressable MCP tool lets the engineer (or any other Spine actor) run, e.g., `SecurityISO` mid-Build, self-remediate, and ship a cleaner artifact. Cycle time drops and the canonical Verify pass has less to flag.

## Wrapper architecture

```
Spine actor (engineer, daemon, orchestrator)
        │
        ▼  MCP call
shared/mcp/tools/iso.py::iso_invoke           ← validates + audits
        │
        ▼  lazy import
verify/tron/agents/<agent>.py::<AgentClass>   ← TRON's existing public API
        │
        ▼  FindingBatch[FindingOutput]
        ▼  mapped → list[Finding] (Spine envelope)
ToolResponse(status, data=IsoInvokeOutput, audit_id)
```

The wrapper does **not** modify TRON. It imports TRON's existing classes lazily so this module loads even when `verify/` isn't on `PYTHONPATH` yet (returns `ToolError(code="tron_not_importable")` instead of crashing — important during Phase 1 wiring).

## The tools

- `iso_invoke` — core tool. Takes `agent_name: Literal[...6 ISOs]`, `code_region`, optional `blueprint`, `project_id`, `actor`, `cost_attribution`.
- `security_iso_scan`, `builder_iso_scan`, `qa_iso_scan`, `performance_iso_scan`, `compliance_iso_scan`, `documentation_iso_scan` — thin convenience wrappers; each delegates to `iso_invoke` with the right `agent_name`.

## Cost attribution rule (FR-5)

`cost_attribution` is a `Literal["pre_verify", "verify_phase"]`:

- `pre_verify` (default) — early-detect call from Build. Audit row tagged `subsystem='build'`, counted against the **Build phase budget**. No double-charge when the canonical Verify pass runs later — same project budget line item.
- `verify_phase` — explicit Verify-time call (rare path; mostly for tests + the orchestrator's own re-runs). Audit row tagged `subsystem='verify'`.

Choose based on **who is invoking**: the engineer daemon mid-Build sends `pre_verify`; the Verify subsystem itself sends `verify_phase`.

## Standalone TRON preserved (G-8 in REQ-INIT-8)

This wrapper is a one-way dependency: Spine imports TRON, TRON never imports Spine. Running `cd verify/ && docker compose up -d` still gives you TRON audit-only with no Orchestrator. The MCP wrapper layer is purely additive.

## Adding a new ISO agent

1. Add the TRON agent class under `verify/tron/agents/` (TRON-side change — not this PR's scope).
2. Extend `AgentName` literal + `_AGENT_MODULES` map in `iso.py`.
3. Add a `<name>_iso_scan` convenience tool that calls `_delegate("<NewAgentName>", payload)`.

That's it — no orchestrator or audit changes needed; the existing audit row will carry the new agent name in its `subject_id`.

## TODOs

- `TODO(STORY-8.6.2)` in `iso_invoke` — wire to TRON's actual `BaseISO.execute(blueprint, file_contents)` signature. Today returns a structurally-correct empty envelope so the MCP contract is correct.
- `TODO(STORY-8.6.1)` — promote `_audit_from_iso_invoke` to `AuditRecord.from_iso_invoke` in `shared/audit/audit_record.py` once that module's classmethod API stabilizes.
- Consider promoting `CodeRegion` / `Blueprint` / `Finding` to `shared/schemas/verify/` once a second tool reuses them.

## Cross-refs

- `verify/tron/agents/` — TRON ISO agent implementations
- `verify/tron/schemas/verification.py` — TRON's `Blueprint`, `FindingOutput`, `FindingBatch`
- `shared/mcp/tools/verify.py` — sibling `verify_audit` tool (FR-4)
- `shared/audit/audit_record.py` — `AuditRecord` (audit row model)
- `docs/PRD.md` REQ-INIT-8 FR-5 — early-detect spec
- `docs/BACKLOG.md` EPIC-8.5 — STORY-8.6.1, 8.6.2, 8.6.3
