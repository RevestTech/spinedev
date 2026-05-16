# `plan/pipeline` — SDLC pipeline customization runtime

Runtime for `EPIC-1.7` in `docs/BACKLOG.md`. Brings the **flexibility
principle** (PRD `REQ-INIT-1` `NFR-4` in `docs/PRD.md`) to live code:
zero phases, roles, artifacts, or gates are hardcoded — everything lives
in a manifest, every edit is git-tracked with required rationale, and
every project locks to the manifest version that was current at start.

## The flexibility principle

> An org can run an entirely different SDLC shape without forking Spine.

Concretely:
- The default manifest is `plan/artifacts/sdlc-pipeline-default.yaml`.
- Org bundles overlay surgical edits via `pipeline_overrides`
  (`shared/standards/bundle-schema.yaml`).
- Teams and projects may further narrow within what they're authorized to.
- Adding a phase / changing approvers / inserting a "compliance review"
  step requires only YAML — no Spine source change.

## Override hierarchy + merge semantics (`STORY-1.7.3`)

Most-specific wins, but a sub-bundle may only do what its parent permits.

| Level | Source                                                      |
|-------|-------------------------------------------------------------|
| 1     | `plan/artifacts/sdlc-pipeline-default.yaml`                 |
| 2     | Active org bundle's `pipeline_overrides`                    |
| 3     | `~/.spine/active/team/<team_id>/pipeline_overrides.yaml`    |
| 4     | Caller-supplied project overrides (`load_pipeline(...)`)    |

Per-section merge:

| Section          | Rule                                                      |
|------------------|-----------------------------------------------------------|
| `phases`         | append / modify / remove by `id` (order preserved)        |
| `project_types`  | append by `id`, modify by `id`                            |
| `tier_routing`   | shallow deep-merge (caps + per-phase defaults)            |
| `gates`          | per-phase deep-merge into `phase.gate`                    |
| `capabilities`   | org bundle authoritative; sub-bundles may **narrow only** |

## Capability model (`STORY-1.7.2`)

Capabilities, not titles, gate edits. `capability_checker.KNOWN_CAPABILITIES`:

- `can_modify_sdlc_pipeline` — edit any `pipeline_overrides` section.
- `can_modify_cost_policy`   — edit `tier_routing` + cost caps.
- `can_grant_capabilities`   — add / remove principals on the grants map.
- `can_override_security`    — relax security packs / required ISO agents.

Principals are `role:<name>`, `user:<id>`, or `group:<id>` (wildcards `*` ok).
`require_capability(actor, cap, pipeline)` raises `CapabilityDenied` if the
actor isn't in the grant list — the single chokepoint for every mutator.

## Versioning + required rationale (`STORY-1.7.4`)

Every pipeline edit is a git commit:

```
pipeline: <one-line summary>

Actor: <actor>
Rationale: <≥8 chars; never optional per PRD FR-8>
```

`commit_pipeline_edit()` (in `versioning.py`) enforces both:
1. `assert_rationale()` — empty / `<8` chars → `CapabilityDenied`.
2. `require_capability()` against the currently active manifest.
3. Write file → `git add` → `git commit` → return new sha256 version.

`pipeline_history(manifest_path)` walks `git log <path>` and parses the
trailer back into structured `PipelineEdit` rows for the UI.

## Project lock + migration (`STORY-1.7.5`)

A project locks to the resolved pipeline at start:

```python
manifest = load_pipeline(project_id=p)
version  = lock_project_to_pipeline(p, manifest)
```

This writes `spine_lifecycle.project.pipeline_version` + a JSON snapshot
into `metadata.pipeline_manifest_snapshot` (schema:
`db/flyway/sql/V14__spine_lifecycle_schema.sql`).

`get_locked_pipeline(p)` reconstitutes that snapshot — in-flight projects
keep running on it even after the org bundle ships new edits.

`migrate_locked_project(p, new_manifest, actor, rationale)` is the only way
to move a project off its lock; it requires capability + rationale + writes
an audit event with a section-level diff.

`is_pipeline_drifted(p)` returns `True` when the active resolved manifest
diverges from the project's locked version — the UI surfaces this so users
can choose to migrate.

## Worked example

Org adds a `compliance_review` phase between `verify_approved` and `acceptance`:

1. Compliance officer (`role:compliance-officer`) is granted
   `can_modify_sdlc_pipeline` in the org bundle.
2. They edit `pipeline_overrides.phases.append:` + run `spine pipeline edit …
   --rationale "SOC2 mandates a compliance gate before acceptance"`.
3. New projects: `load_pipeline()` returns the 12-phase manifest; the project
   locks to its sha at creation.
4. In-flight projects keep running on their 11-phase locked snapshot.
5. To pull an in-flight project forward: `spine pipeline migrate <pid> --to
   latest --actor user:alice --rationale "operator-approved upgrade" --confirm`
   — capability checked, section diff written to audit.

## Cross-references

- PRD `REQ-INIT-1` `FR-7` / `FR-8` — `docs/PRD.md`.
- Backlog `EPIC-1.7` (stories 1.7.2 – 1.7.5) — `docs/BACKLOG.md`.
- Manifest schema + default — `plan/artifacts/sdlc-pipeline-{schema,default}.yaml`.
- Bundle schema (`pipeline_overrides`, `capabilities.grants`) — `shared/standards/bundle-schema.yaml`.
- Locked-pipeline column — `db/flyway/sql/V14__spine_lifecycle_schema.sql`.
