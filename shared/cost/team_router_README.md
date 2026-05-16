# Team-of-Models Router

Implements `STORY-3.3.1` (task-complexity scoring) and `STORY-3.3.2`
(model selection table) — both rolled up under PRD `EPIC-3.3` "team of
models router". Spine should pick the right model *for the user*; the
user should not have to know the tier vocabulary to get a good answer
back.

Files: `complexity_scorer.py`, `model_selection_table.py`,
`team_router.py`, plus the default table at `default_model_selection.yaml`.
Cross-refs: `STORY-3.3.1`, `STORY-3.3.2`, `STORY-3.3.3`,
`shared/cost/router.py`, `shared/cost/classifier.py`,
`shared/standards/bundle-schema.yaml` (`cost.model_selection_table`).

## Three-and-a-half-layer model

```
   TeamRouteRequest
        │
        ▼
   ┌───────────────────────────────────────────────────────────────┐
   │ 1. complexity_scorer.score_complexity()  — what kind of work? │  STORY-3.3.1
   │ 2. model_selection_table.lookup()        — which tier suits?  │  STORY-3.3.2
   │ 3. router.route()                        — which model in tier│  STORY-1.5.3
   │ 3.5. classifier.apply_to_route_request() — per-turn nudge     │  STORY-1.5.2
   └───────────────────────────────────────────────────────────────┘
        │
        ▼
   TeamRouteDecision { selected_model, selected_tier, complexity_score,
                       selection_entry, fallback_used, blocked, ... }
```

Layer 3.5 (classifier) is **complementary**, not part of team_route()
itself. The classifier handles in-turn nudges (a "draft the TRD" turn
inside `plan_in_progress`); the team router handles the broader role-
plus-complexity decision *before* a turn even starts.

## Why team-of-models routing

The old shape — caller passes `intended_tier="medium"` — forced every
producer of a directive to develop tier intuition. The team router
re-centres on the two things a caller actually knows: **role** and
**what they're being asked to do** (the directive text + a few
structural hints — file count, LOC, artifact type, retry #). A typo-fix
engineer gets Haiku and an architect doing TRD synthesis gets Opus
without the daemon having to know any of that.

## Complexity scoring (STORY-3.3.1)

`complexity_scorer.score_complexity(TaskContext) → ComplexityScore`

Pure heuristic — zero LLM calls, <5 ms target. Aggregates eight signal
sources, anchored to a 0.20 baseline:

| Signal              | Contribution                                  |
|---------------------|-----------------------------------------------|
| length              | text length buckets (`-0.05` short → `+0.28`) |
| keywords_up         | refactor/redesign/migrate/security/etc.       |
| keywords_down       | typo/rename/format/lint/whitespace            |
| files               | 0 / 1 / ≤3 / ≤10 / >10                         |
| loc                 | 0 / <100 / <500 / <2000 / ≥2000                |
| role_phase_prior    | e.g. architect×synthesis = +0.30              |
| artifact            | TRD=+0.35, PRD=+0.20, Memo=−0.05              |
| retry               | +0.05 per prior attempt (cap +0.20)           |
| history             | summary length (cap +0.10)                    |

Score is bucketed: `[0, 0.2)` trivial · `[0.2, 0.4)` simple · `[0.4,
0.6)` moderate · `[0.6, 0.8)` complex · `[0.8, 1.0]` very_complex.

## Selection table (STORY-3.3.2)

`default_model_selection.yaml` ships entries covering product /
architect / engineer / planner / auditor / qa / operator / datawright /
ux × the five buckets. Each carries `preferred_tier`, optional
`fallback_tier`, a soft `cost_ceiling_usd`, and a rationale.
`SelectionTable.lookup(role, bucket)` falls back when an exact match is
missing: nearest neighbouring bucket → wildcard role `*` → safe
default (`medium` / fallback `low`).

## Customising per org bundle

Bundles override entries under `cost.model_selection_table`:

```yaml
cost:
  model_menu:
    allowed: [claude-sonnet-4, claude-opus-4]   # menu still rules
  model_selection_table:
    version: 1
    entries:
      - { role: engineer, complexity: trivial, preferred_tier: medium,
          fallback_tier: medium, cost_ceiling_usd: 0.10,
          rationale: "no Haiku in regulated builds" }
```

`merge_tables(default, override)` does per-`(role, complexity)`
replacement; untouched entries are preserved. The bundle menu remains
final authority on dispatch — if the selected tier maps to no
menu-allowed model, the cost router downshifts per its own policy.

## User override (STORY-3.3.3)

`TeamRouteRequest.user_override_tier` skips scoring entirely. Use when:

- a specific directive carries an explicit budget ("spend on this one"),
- A/B comparing two tiers on the same directive,
- a regulated workflow mandates a fixed tier independent of complexity.

The cost router still validates the override against the menu and counts
projected cost against caps — overriding to `premium` can still block on
a budget breach.

## Cost-router pass-through

team_route() always finishes by calling `router.route()`, so the org
menu, hard caps, and override-validation rules all still apply. The
verbatim `RouteDecision` is preserved inside
`TeamRouteDecision.cost_router_decision` for audit. If the preferred
tier blocks AND the entry defines a `fallback_tier`, team_route()
retries once at the fallback (`fallback_used=True`).
