# Spine Roadmap Decomposer

Planner-led pipeline that turns a signed **PRD** + **TRD** into a validated
`roadmap-v1` artifact (INIT → EPIC → STORY hierarchy + sprint plan).

Implements:
- `STORY-1.3.1` — decomposer playbook (`decomposer.py`)
- `STORY-1.3.2` — story sizing heuristic (`sizing.py`)
- `STORY-1.3.3` — inter-story dependency detection via KG (`dependency_detection.py`)

Cross-refs: `docs/PRD.md` §FR-4 (REQ-INIT-1) · `plan/artifacts/roadmap_v1.py` ·
`shared/mcp/tools/kg.py` (`impact_radius`, `code_neighborhood`) ·
`docs/BACKLOG.md` EPIC-1.3 / STORY-6.6.5 (KG upgrade).

## Algorithm

1. Initiative shape from PRD (MUST→P0, SHOULD→P1, COULD→P2).
2. Epic candidates from TRD (components + integrations + NFRs).
3. Story candidates per epic (single-PR scale, ≤2 weeks).
4. `id_allocator`: stable INIT/EPIC/STORY ids (sha256 over canonical content).
5. `sizing`: XS/S/M/L/XL + USD cost + duration label.
6. `dependency_detection`: KG `impact_radius` primary, text-overlap fallback.
7. Sequence into ≤3 sprints (topological sort, ≤8 stories per sprint).
8. Pydantic validate via `RoadmapV1.refuse_to_advance`.

## Inputs

| Input | Required | Notes |
|---|---|---|
| `prd: PRDv1` | yes | Must be signed (`status=approved`) before invocation. |
| `trd: TRDv1` | yes | Same. `prd.project_id` and `trd.project_id` must match. |
| `existing_roadmap: RoadmapV1` | no | If present → incremental mode (see below). |
| `project_repo: str` | no | Repo slug for `impact_radius` calls. |

## Outputs

A `RoadmapV1` instance with:
- `initiatives` — full hierarchy
- `epics` / `stories` — flattened views for tooling
- `sprint_plan` — ≤3 default sprints + optional overflow bucket
- `metadata.status = draft` (planner sign-off flips it via `STORY-1.3.5`)

Render to BACKLOG-style markdown via `roadmap.to_markdown()` or export to
Jira CSV via `roadmap.to_jira_csv()`.

## Sizing — how it works

`estimate_size(story_text, trd_section, kg_impact) → SizingResult`

Additive score from:
- prose volume (rough LOC proxy)
- KG impact count (strongest signal when available)
- keyword categories: security, novel data model, external integration,
  distributed/async/migration

Score → bucket:

| Points | Size | Cost (USD) | Duration |
|---|---|---|---|
| ≤0 | XS | $1 | <1 day |
| 1-2 | S | $5 | 1-3 days |
| 3-5 | M | $25 | 1-2 weeks |
| 6-9 | L | $100 | 3-6 weeks |
| ≥10 | XL | $500 | release-scale |

Cost / duration are placeholder rates — refine once `EPIC-1.5` cost
router accumulates real history.

## Dependency detection — how it works

`detect_dependencies(stories, kg_available=True, project_id, repo) → list[StoryDependency]`

Two modes:

**KG path (high confidence)** — requires `SPINE_DB_URL` and the
`shared.mcp.tools.kg` module. For each story we:
1. Extract identifier-like refs from the title (CamelCase, snake_case,
   dotted paths, file paths).
2. Call `impact_radius` per ref → union of affected nodes.
3. Any other story whose refs sit in A's impact set ⇒ depends on A.

**Text-overlap fallback (low confidence)** — when KG unreachable:
shared identifier tokens between two stories ⇒ candidate edge. We log
a warning so the planner knows the dependency set is best-effort.

Special-case heuristics (apply in both modes, raise to high/medium
confidence when refs overlap):
- A modifies a fn/schema, B mentions "test/spec/coverage" ⇒ B depends on A.
- A mentions "schema/migration/entity", B uses the same identifier ⇒ B depends on A.

Cycles are detected via DFS and surfaced as `reason="cycle: …"` edges.
The decomposer logs them and excludes them from sprint sequencing — the
planner resolves manually before sign-off.

## Incremental mode

Pass an existing `RoadmapV1` to `decompose(prd, trd, existing_roadmap=…)`:
- Canonical-content hashing preserves ids of unchanged INIT/EPIC/STORY.
- New content gets fresh ids that don't collide with existing slots.
- Orphaned ids (in the old roadmap, no canonical match in the new one)
  are returned via `metadata.created_by` annotation: `"planner (retired=STORY-…)"`.
  Caller can drive a `WontDo` status transition for those.

Idempotency: `decompose(prd, trd)` over the same inputs returns the
same id set on every invocation.

## Integration with the `planner` role daemon

After `STORY-1.4.x` gate engine signs the TRD:

1. Conductor dispatches to the `planner` role with the signed PRD + TRD refs.
2. Planner daemon loads both via `plan/artifacts/{prd_v1,trd_v1}.py`.
3. Daemon calls `plan.decomposer.decompose(prd, trd, existing_roadmap=current)`.
4. Daemon serialises result (`roadmap.to_markdown()` for the UI,
   `roadmap.model_dump_json()` for storage).
5. Roadmap enters the approval queue (STORY-1.4.x); on approval, conductor
   fans out story-level directives to engineers.

See `lib/role-prompts/planner.md` for the role-side contract.
