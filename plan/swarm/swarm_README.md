# Technical Review Swarm

Implements REQ-INIT-1 FR-3 (`docs/PRD.md`) and `STORY-1.2.1` + `STORY-1.2.4`
(`docs/BACKLOG.md` EPIC-1.2). Companion schema: `plan/artifacts/trd_v1.py`.

## Why a swarm?

The architect cannot be an expert in every lens at once. The PRD declares
*what* to build; the TRD must answer *how* — and "how" spans current-system
shape, feasibility, data, infra, and quality. Forcing the architect to hold
all five lenses solo produces shallow TRDs. The swarm pattern dispatches a
scoped sub-directive to a specialist scout per lens, collects per-lens
contributions, and lets the architect synthesize a single artifact whose
provenance is the union of expert inputs.

## Flow

```
              ┌─────────────┐
              │    start    │  (PRD, project_type, pipeline_version)
              └──────┬──────┘
                     │
              ┌──────▼───────┐
              │compose_swarm │  composition_rules.py → roster
              └──────┬───────┘
                     │
              ┌──────▼─────────┐
              │dispatch_scouts │  fan-out: directive.md per scout
              └──────┬─────────┘
                     │
              ┌──────▼─────────┐
              │wait_for_scouts │  collect ScoutContribution per scout
              └──────┬─────────┘
                     │
              ┌──────▼──────┐
              │ synthesize  │  synthesis.py → trd-v1 (deterministic + LLM prose)
              └──────┬──────┘
                     │
              ┌──────▼──────┐
              │validate_trd │  Pydantic v2 validation
              └──┬───────┬──┘
       ok        │       │  validation_errors + attempts<2
                 │       └─────┐
              ┌──▼──┐          │
              │ end │          └──► back to `synthesize` (one retry)
              └─────┘
```

Every node returns an updated `SwarmState` (TypedDict). LangGraph persists
state at each boundary via `SqliteSaver` (preferred) or `MemorySaver`
(fallback). When LangGraph isn't installed the engine runs the same node
functions in a linear Python loop so unit tests still pass.

## The scouts and their lenses

| Scout | Lens | TRD sections it feeds |
|---|---|---|
| `researcher` | `current_state` | `architecture.system_overview`, `risks` |
| `engineer` | `feasibility` | `architecture.components`, `tech_choices`, `nfrs.security`, `nfrs.cost` |
| `datawright` | `data` | `data_model`, `cost_projection` |
| `operator` | `infra` | `integrations`, `nfrs.performance/scalability/observability` |
| `qa` | `quality` | `nfrs`, `open_questions`, `risks` |

Composition per project type (FR-3 / `sdlc-pipeline-default.yaml`):

- web-app → researcher + engineer + operator + qa
- internal-tool → researcher + engineer + qa
- data-pipeline → researcher + engineer + datawright + operator
- mobile → researcher + engineer + qa + operator
- api-service → researcher + engineer + qa + operator
- cli-tool → researcher + engineer + qa

## Synthesis (synthesis.py)

Two-pass:

1. **Deterministic merge** — group contributions by lens; map each lens to
   its TRD section. Risks + open-questions are unioned across all scouts
   and deduped by lowercase description. This pass alone yields a
   structurally valid TRD.
2. **LLM prose pass** (optional `ProsePass` callable) — narrative fields
   (`system_overview`, `data_flow`, NFR blurbs) are filled by routing
   through `shared/cost/router.py` at the `medium` tier; the escalation
   classifier may bump to `high` for synthesis-heavy calls.

The deterministic pass means the swarm is resilient to LLM outages.

## Failure modes + resumption

- **Scout failure** — captured in `state['unrun']`; synthesis proceeds
  with the remaining lenses; the missing lens is flagged in the TRD's
  `open_questions`. Degraded but useful.
- **Synthesis failure** — engine retries once with the same inputs. On a
  second failure `validation_errors` is populated and the caller (architect
  daemon) escalates to the user.
- **Validation failure** — same retry path as synthesis failure; the
  Pydantic error list is fed back into the synthesis prompt on retry.
- **Mid-run crash** — LangGraph checkpoints at every node boundary; resume
  via `python -m plan.swarm.swarm_engine --resume <run_id>`.

## Adding a new scout

1. Add the role to `ScoutRole` in `scout_contribution.py` and map it to a
   `ScoutLens` in `DEFAULT_LENS_FOR_ROLE`.
2. Add a TRD-section mapping in `synthesis.py` (e.g. security-scout →
   `nfrs.security` + dedicated `Risk` entries).
3. Add the scout to the appropriate `project_types.*.swarm_override` lists
   in `plan/artifacts/sdlc-pipeline-default.yaml`.
4. Wire the scout's role prompt under `lib/role-prompts/<role>.md` (out of
   scope for this story — handled in the architect-integration follow-up).

## Cross-references

- `docs/PRD.md` REQ-INIT-1 §1.5 FR-3 — swarm requirements
- `docs/BACKLOG.md` EPIC-1.2 — stories 1.2.1 / 1.2.4 (this work),
  1.2.2 (composition rules), 1.2.3 (`trd-v1` schema, done)
- `plan/artifacts/trd_v1.py` — synthesis target schema
- `plan/artifacts/sdlc-pipeline-default.yaml` — composition source of truth
- `lib/role-prompts/architect.md` — architect role (swarm-mode section
  added in a separate integration story)
