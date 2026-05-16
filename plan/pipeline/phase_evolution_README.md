# `plan/pipeline/phase_evolution.py` — Phase-Set Evolution Runtime

> Implements `STORY-9.1.4`: when `sdlc-pipeline.yaml` changes the phase set, the runtime detects what changed + decides which projects can auto-migrate vs need manual review.

## Why this exists

Pipeline manifests evolve. An org bundle might add a `compliance_review` phase between `verify_approved` and `acceptance`. Or rename `build_complete` to `engineering_done`. Or remove a phase entirely. **In-flight projects are locked** to the pipeline version that was current when they started (per `STORY-1.7.5`), so they keep running on the old shape — but the runtime needs to know which evolution events warrant which response.

Three concerns:

1. **Detect** what changed between two manifest versions (added / removed / renamed / reordered / gate-changed / rollback-changed).
2. **Classify** each event as auto-migratable (safe) vs needs-review (risky).
3. **Migrate** projects across events with full audit + capability + rationale enforcement.

## The flow

```
Old manifest (v3)               New manifest (v4)
       │                                │
       └────────► detect_evolution_events ────────►  list of PhaseEvolutionEvent
                                                              │
                                                              ▼
                                             ┌──────────────────────────────┐
                                             │ For each event:              │
                                             │   - find affected_projects() │
                                             │   - can_auto_migrate()?      │
                                             │   - migration_plan() → exec  │
                                             └──────────────────────────────┘
                                                              │
                                                              ▼
                                                         Audit trail
                                                         + project locks updated
```

## Auto-migratable vs needs-review

| Event type | Auto-migrate? | Why |
|---|---|---|
| `phase_added` (default gate, end of pipeline) | ✅ | Safe — adds new phase at the end; in-flight projects can opt to adopt or skip |
| `phase_added` (mid-pipeline w/ user_approval gate) | ⚠️ Review | Inserts a new approval requirement; user must explicitly accept |
| `phase_removed` | ❌ Review | Could leave projects in a phase that no longer exists |
| `phase_renamed` (same semantics) | ⚠️ Review | Mechanical update; safe IF semantics unchanged; user confirms |
| `phase_reordered` (no skips, just relabeling order) | ✅ | Order in manifest is presentation; behavior unchanged |
| `phase_reordered` (with skips) | ❌ Review | Could mean a project skips a required phase |
| `gate_changed` (auto → user_approval) | ❌ Review | Tightening a gate could block in-flight |
| `gate_changed` (user_approval → auto) | ⚠️ Review | Relaxing — user should consciously approve weakening |
| `rollback_changed` (added targets) | ✅ | Strictly additive |
| `rollback_changed` (removed targets) | ⚠️ Review | Removes recovery paths |

## CLI usage

```bash
# Detect what changed
python3 plan/pipeline/phase_evolution.py detect \
    --old-version v3 --new-version v4

# Find affected projects
python3 plan/pipeline/phase_evolution.py affected \
    --event-id <event_uuid>

# Generate migration plan (dry-run by default)
python3 plan/pipeline/phase_evolution.py plan \
    --project-id <pid> --event-id <event_uuid>

# Execute migration
python3 plan/pipeline/phase_evolution.py execute \
    --plan-path <plan.yaml> --actor <name> --rationale <text>

# Human-readable summary
python3 plan/pipeline/phase_evolution.py report \
    --old-version v3 --new-version v4
```

Exit codes: 0=ok, 2=manual review needed, 3=db error, 64=unknown subcommand.

## Integration points

- **`manifest_loader.py`** — `load_pipeline()` produces the `PipelineManifest`s this module diffs
- **`project_lock.py`** — `migrate_locked_project()` is the underlying mechanism; `phase_evolution.py` wraps it with detection + classification
- **`capability_checker.py`** — migrations require `can_modify_sdlc_pipeline` capability + non-empty rationale
- **`shared/audit/`** — every migration writes an `audit_event` with `action="phase_evolution_migrated"`, full diff in metadata

## Edge cases handled

- **Empty old manifest** (first install) — all phases treated as `phase_added`; no migration needed since no projects are locked yet
- **Phases-only-in-new** but project never reached that phase — auto-migrate (no impact)
- **Phase removed mid-flight** — refuses; user must rollback the project first
- **Concurrent migrations** — uses Postgres advisory lock per project_id to serialize

## Edge cases NOT handled (future work)

- **Bulk migration UI** — current CLI is per-project; needs dashboard story
- **Migration impact preview** — shows diff but not "what would have happened if this version had been active"
- **Rollback of migration** — once applied, only manual rollback via `rollback.sh` to a phase that exists in both versions

## Cross-refs

- `docs/PRD.md` REQ-INIT-9 §9.5 FR-2 (canonical phase set + evolution)
- `docs/BACKLOG.md` STORY-9.1.4
- `plan/pipeline/manifest_loader.py` — produces inputs
- `plan/pipeline/project_lock.py` — underlying migration mechanism
- `plan/pipeline/versioning.py` — pipeline version history
- `orchestrator/lib/rollback.sh` — manual rollback path when migration not safe
