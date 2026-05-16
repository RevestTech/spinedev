# `build/runtime/` — daemon-side KG hooks (EPIC-7.3)

Wires the Build subsystem's role daemons to the KG MCP tools so the
`BuildArtifact.kg_impact` field gets populated whether or not the LLM agent
remembers to call `impact_radius` itself.

## Why daemon-level enforcement?

The role prompts in `lib/role-prompts/{engineer,operator,datawright}.md`
already instruct the LLM to call the KG MCP tools (wave 4). But:

- An LLM can forget. The auditor (STORY-7.4.3) will then reject the artifact
  with `kg_impact_missing` and force a re-dispatch, wasting tokens.
- The v1 bash daemons never knew about MCP at all. The bridge
  (`build/bridge/`) feeds their markdown reports into a `BuildArtifact`
  whose `kg_impact` defaults to `[]` — same auditor rejection.

Daemon-level hooks close both gaps: the daemon runs them itself before the
artifact ships to `build_completed`. Failures degrade gracefully — we log,
the auditor still has authoritative say.

## Per-role hooks (`kg_caller.py`)

| Role         | Story        | Hook                                     | KG tool          |
| ------------ | ------------ | ---------------------------------------- | ---------------- |
| `engineer`   | STORY-7.3.1  | `EngineerKGHook.compute_kg_impact`       | `impact_radius`  |
| `operator`   | STORY-7.3.2  | `OperatorKGHook.find_owner` + `.warn_if_no_owner` | `who_owns`       |
| `datawright` | STORY-7.3.3  | `DatawrightKGHook.register_output`       | direct SQL insert (Document node + PRODUCED_BY edges) |

Tool resolution per call: `mcp` CLI subprocess → in-process import of
`shared.mcp.tools.kg` → empty result on failure.

## Enrichment flow (v1 bridge)

```
v1 daemon completes
  └─ writes # Report markdown
     └─ v1_report_collector.sh picks it up
        └─ report_parser.parse_v1_report  (kg_impact = [])
           └─ enrich_artifact.enrich_build_artifact  (mode=fill)
              └─ EngineerKGHook.compute_kg_impact / DatawrightKGHook.register_output
                 └─ artifact has kg_impact populated
                    └─ _emit_artifact → MCP build_completed
                       └─ auditor.verify_build_artifact (STORY-7.4.3)
```

## Pre-seal vs post-seal enforcement

- **Pre-seal** (v2 native daemons): role daemon calls `kg_caller.EngineerKGHook`
  *before* constructing the `BuildArtifact`. The pydantic validator
  (`_refuse_seal_without_kg_impact`) is then satisfied at construction time.
- **Post-seal** (v1 bridge): the daemon never called MCP, so
  `report_parser.py` runs `enrich_artifact.enrich_build_artifact(mode="fill")`
  to populate `kg_impact` *before* the artifact reaches the auditor.

## CLI (`cli.py`)

```
python -m build.runtime.cli enrich artifact.json --in-place
python -m build.runtime.cli find-owner src/auth/session.py --repo .
python -m build.runtime.cli register-output data/out.parquet --source-nodes data:src:foo,data:src:bar
python -m build.runtime.cli pre-build-check directive.json
```

## Disable temporarily

```
SPINE_AUTO_ENRICH_KG=false   # report_parser.py skips enrichment
```

When disabled, the v1 bridge falls back to its previous behaviour (empty
`kg_impact`, auditor flags the artifact). Use only when debugging the KG
schema; production should leave it on.

## Cross-refs

- `docs/BACKLOG.md` EPIC-7.3 stories (7.3.1 / 7.3.2 / 7.3.3)
- `docs/PRD.md` REQ-INIT-7 §7.5 FR-4 (KG integration call sites)
- `shared/mcp/tools/kg.py` (impact_radius, who_owns, kg_node/kg_edge schema)
- `shared/schemas/build/build_artifact.py` (KGImpactNode + refuse-to-seal rule)
- `shared/mcp/tools/auditor.py` STORY-7.4.3 (verify_build_artifact)
- `build/bridge/report_parser.py` (auto-enrichment integration point)
- `lib/role-prompts/{engineer,operator,datawright}.md` (LLM-side instructions)
