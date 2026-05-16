# `build/bridge/` — Spine v1 → v2 daemon bridge

> **Status:** Phase A (Sprint 2). Active. Implements parts of `STORY-7.5.1` per `REQ-INIT-7 FR-5` (PRD §7.5) and `docs/ARCHITECTURE.md §6 Phase 4` (incremental drain).

## Why this exists

Spine v1's bash daemons in `lib/team-agent-daemon.sh` are working, debuggable, and in use. The v2 orchestrator (`orchestrator/lib/router.sh` + `shared/mcp/`) needs to dispatch work to those daemons **without** a big-bang rewrite. The bridge is the seam: it speaks the v2 MCP contract on one side and the v1 file-bus on the other.

The bridge is **additive**. Nothing in `lib/` is modified. Removing the bridge directory leaves v1 untouched and v2 stub-only.

## Architecture

```
┌──────────────────────────┐
│ v2 orchestrator          │  router.sh dispatch build <role> <directive> ...
│ orchestrator/lib/router.sh
└──────────────┬───────────┘
               │ MCP build_dispatch(role, directive, project_id, pipeline_version)
               ▼
┌──────────────────────────┐
│ shared/mcp/tools/build.py│  registers `build_dispatch` + `build_completed`
└──────────────┬───────────┘
               │ subprocess (bash)
               ▼
┌──────────────────────────┐
│ build/bridge/            │  v1_dispatcher.sh dispatch
│   v1_dispatcher.sh       │  - composes `# Directive` markdown
│                          │  - atomic-writes teams/<role>/directive.md
│                          │  - records route_history row
└──────────────┬───────────┘
               │ file-bus (PROTOCOL §3a)
               ▼
┌──────────────────────────┐
│ v1 daemon (READ-ONLY)    │  lib/team-agent-daemon.sh detects new hash
│   teams/<role>/directive │  invokes cursor-agent
└──────────────┬───────────┘
               │ rewrites the file header to `# Report` (PROTOCOL §3b)
               ▼
┌──────────────────────────┐
│ build/bridge/            │  v1_report_collector.sh watch (8s poll)
│   v1_report_collector.sh │  - detects `# Report` headers
│   report_parser.py       │  - parses markdown → BuildArtifact JSON
│                          │  - POSTs to MCP build_completed
│                          │  - archives report to teams/<role>/archive/
└──────────────┬───────────┘
               │ MCP build_completed(artifact)
               ▼
┌──────────────────────────┐
│ shared/mcp/tools/build.py│  writes BuildArtifact to spine_audit
│ + spine_audit.audit_event│  + updates spine_lifecycle.route_history
└──────────────────────────┘
```

## Files

| File | Lines | Role |
| --- | --- | --- |
| `__init__.py` | ~13 | Package marker |
| `v1_dispatcher.sh` | ~234 | v2 dispatch → v1 directive file |
| `v1_report_collector.sh` | ~195 | v1 report file → v2 BuildArtifact |
| `report_parser.py` | ~226 | Markdown → typed artifact dict |
| `bridge_README.md` | this file | Architecture + migration plan |

## Migration plan (Phase A → C)

### Phase A — bridge in place (now)
- All v1 roles still run their existing `lib/team-agent-daemon.sh` daemons.
- v2 orchestrator dispatches via MCP `build_dispatch` → bridge → v1 daemon.
- v2 reads completions back via the collector + parser.
- Every artifact has empty `kg_impact` → auditor flags it (see operational notes).

### Phase B — per-role migration (continuous)
- Replace one v1 role daemon at a time with a v2-native daemon that emits `BuildArtifact` directly (no markdown parsing step).
- Order suggestion: `engineer` first (most kg_impact-flagged), then `operator`, then `datawright`. Other roles stay on v1 — only build-track roles need migration per FR-3.
- The bridge **auto-detects** v2-native artifacts (presence of `version: build-artifact-v1` in a JSON sidecar) and skips the parse step.
- Phase A and Phase B daemons can coexist per role family.

### Phase C — retire bridge (one release after Phase B completes)
- All build-track roles run v2-native daemons.
- Remove `build/bridge/` and the call site in `shared/mcp/tools/build.py`.
- Per `REQ-INIT-7` OQ-4: legacy `lib/` symlinks kept for one release cycle, then removed.

## Operational notes

### `kg_impact` is always empty (intentional)
The v1 engineer daemon never calls MCP `impact_radius`. Per `REQ-INIT-7 FR-3` "refuse-to-emit" rule, a sealed `BuildArtifact` with `code_changes` but empty `kg_impact` is supposed to be rejected. The bridge **does** emit such artifacts; the auditor hook (`STORY-7.4.3`) will flag them with `auditor_verdict: kg_impact_mismatch`. This is on purpose — the flag rate is the v2 team's migration prioritisation signal.

### Cost attribution is lossy
v1 daemons emit cost rows to `teams/<role>/state/costs.csv` and (via Pass B / `db-outbox.sh`) to the spine_recording cost ledger — but the bridge does **not** correlate those rows with a specific bridge dispatch. The synthesized `BuildArtifact.cost` defaults to `tokens_input=0, cost_usd=0, model=v1-bridge-unknown`. Use the v1 cost ledger for billing until Phase B per-role migration.

### Role mapping
v2 `BuildArtifact.role` is a `Literal["engineer","operator","datawright"]`. v1 has 13 roles. The parser maps non-build roles (architect, qa, conductor, ...) to `"engineer"` and preserves the original in `metadata.v1_role`. This is honest about the v1 → v2 schema gap and lets auditors filter on it.

### Polling intervals
The collector polls every 8s (`COLLECTOR_POLL_S` env, matches v1 `POLL_INTERVAL`). Worst-case completion → v2 audit row latency is `~v1_poll + collector_poll ≈ 16s`.

### Failure modes
- **MCP server down**: `_emit_artifact` falls back to a direct `spine_audit.audit_event` insert (action=`build_completed_v1bridge`). The artifact is never lost. The orchestrator's reply-intake step (`route_record_reply`) won't fire — the v2 orchestrator will see a route_history row with `outcome=NULL` and may time it out.
- **DB down**: dispatch still succeeds (file write is authoritative for the v1 daemon). Only the route_history row insert is best-effort; a `WARN` is logged and the directive proceeds. Reconciliation: re-run `collect-once` once DB is back.
- **v1 daemon crashed**: dispatch writes the file successfully; the file sits there until the v1 watchdog restarts the manager (PROTOCOL §18). No bridge action needed.

## Cross-references

- `docs/PRD.md` — REQ-INIT-7 §7.5 FR-2 / FR-3 / FR-5
- `docs/BACKLOG.md` — STORY-7.5.1, STORY-7.5.2, STORY-7.5.3, STORY-7.4.3
- `docs/ARCHITECTURE.md` — §6 Phase 4 (incremental drain)
- `PROTOCOL.md` — §2 (file layout), §3 (lifecycle), §11 (cost tiering), §13 (timeouts)
- `shared/schemas/build/build_artifact.py` — the typed contract this bridge synthesises
- `orchestrator/lib/router.sh` — the v2 dispatch surface that calls into MCP `build_dispatch`
- `shared/mcp/tools/build.py` — the MCP tool that delegates to `v1_dispatcher.sh`
