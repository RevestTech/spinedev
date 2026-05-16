# verify_dispatcher.sh — Verify-as-a-Phase Orchestrator Bridge

Bash wrapper that fires when a project transitions into
`verify_in_progress`. Loads the locked `verify_config` from the SDLC
pipeline manifest, applies org-bundle overrides to the TRON ISO-agent set,
calls the `verify_audit` MCP tool, and routes the response to the right
next phase based on the configured severity transitions. Implements
`STORY-8.7.1`, `STORY-8.7.2`, `STORY-8.7.3` per `docs/PRD.md` REQ-INIT-8
§8.5 FR-6.

## The flow

```
   BuildArtifact lands → phase promoted to verify_in_progress
        │
        ▼  verify_dispatcher.sh dispatch <pid> <baid>
   ┌──────────────────────────────────────────────────────────────┐
   │ 1. route_locked_pipeline_version (project pins manifest)     │
   │ 2. _load_verify_config           (sdlc-pipeline-default.yaml)│
   │ 3. _apply_bundle_overrides       (<bundle>.verify_overrides) │
   │ 4. _fetch_build_artifact         (spine_audit.build_artifact)│
   │ 5. _build_blueprint              (project_type + overrides)  │
   │ 6. _mcp_call verify_audit        (router.sh chokepoint)      │
   │ 7. _apply_transition_rules       (severity → next phase)     │
   └────────────────┬─────────────────────────────────────────────┘
                    ▼
        pass / low → verify_approved              (transition.sh)
        medium     → verify_approved_with_warnings (transition.sh)
        high       → build_in_progress            (remediation.sh dispatch)
        critical   → project.status=paused        (remediation.sh surface)
```

## How bundle overrides work (STORY-8.7.2)

The manifest `verify_config.iso_agents_default` is the floor. Each
project's active org bundle (path stored in
`project.metadata.org_bundle_path`) sets `verify_overrides:` per
`shared/standards/bundle-schema.yaml`. The dispatcher deep-merges
bundle keys over the manifest config (bundle wins).

| Bundle profile     | `iso_agents_enabled`                              | Layers + cap                            |
| ------------------ | ------------------------------------------------- | --------------------------------------- |
| `lean_iso_agents`  | `[SecurityISO]`                                   | sandbox off, cross-LLM off, cap `$0.50` |
| Spine default      | `[SecurityISO, BuilderISO, QAISO, PerformanceISO]`| sandbox on, cross-LLM off, cap `$5.00`  |
| `regulated_iso_agents` | + `ComplianceISO, DocumentationISO`           | cross-LLM on, cap `$25.00`              |

`security.iso_agents_required` (e.g. `ComplianceISO` for HIPAA) wins
over any `iso_agents_disabled` — that floor is absolute.

## The four severity transitions

`verify_config.transitions` maps the worst finding severity to a next
action. The dispatcher reads the merged config (manifest + bundle) and
honors whatever the bundle dictates:

- `on_pass: verify_approved` — no findings; advance via `transition.sh`.
- `on_low: verify_approved` — informational; advance.
- `on_medium: verify_approved_with_warnings` — advance + flag; user must
  acknowledge at the gate before `acceptance`.
- `on_high: build_in_progress` — auto-loop via `remediation.sh
  remediation_dispatch` (composes a remediation directive citing
  `parent_directive_id`; check_retry_budget gates the loop).
- `on_critical: blocked` — `remediation.sh remediation_surface_to_user`
  flips `project.status='paused'` + `metadata.blocked=true`; the
  dashboard surfaces the blocker.

## Integration with `remediation.sh` + cost cap

`on_high` delegates to `remediation_dispatch` (composes a remediation
directive citing `parent_directive_id`, calls
`route_dispatch_remediation`, and runs
`verify_in_progress → build_in_progress` through `transition.sh`).
`remediation_check_retry_budget` enforces
`transitions_metadata.retry_policy.verify_build_loop_max` (default 5)
by counting prior verify→build transitions — the transition table is
the crash-safe source of truth. Budget blown → falls through to
`surface_to_user`.

`verify_config.cost_cap_usd` ($5 default; $0.50 lean; $25 regulated)
caps the single verify run and overrides `tier_routing.budget_caps`
for this phase only.

## CLI

```bash
verify_dispatcher.sh dispatch <project_id> <build_artifact_id> [--dry-run]
```

`--dry-run` composes the payload + skips the MCP call (use to inspect
the resolved verify_config + blueprint).

## Cross-refs

- `plan/artifacts/sdlc-pipeline-default.yaml` — `verify_config:` (manifest)
- `orchestrator/state/phases.yaml` — runtime mirror + `verify_approved_with_warnings`
- `shared/standards/bundle-schema.yaml` — `verify_overrides:`
- `shared/standards/example_org_overrides/{regulated,lean}_iso_agents.yaml`
- `shared/mcp/tools/verify.py` — `verify_audit` (wave 6, do not modify)
- `orchestrator/lib/{remediation,router,transition}.sh` — sourced helpers
- `docs/PRD.md#req-init-8` FR-6, `docs/BACKLOG.md` EPIC-8.6 (STORY-8.7.{1,2,3})
