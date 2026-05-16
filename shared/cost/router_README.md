# Cost-Aware Tier Router

Implements PRD `REQ-INIT-1 FR-6`. Decides which LLM model to call for every
Spine directive, honours the org bundle's model menu, and **hard-blocks**
dispatches that would exceed any budget cap.

Files: `shared/cost/router.py` + `shared/cost/router_cli.sh`. Sibling helper:
`shared/cost/budget_rollup.sh` (rollup printer + project budget enforcer).
Cross-refs: `STORY-1.5.1`–`STORY-1.5.7`, `STORY-2.3.1`–`STORY-2.3.4`.

## The five mechanisms (layered)

```
  RouteRequest (caller fills tier, tokens, actor, optional override)
        │
        ▼
  ┌─────────────────────────────────────────────────────────────────┐
  │ 1. Per-phase default tier  (sdlc-pipeline.yaml: tier_default)   │  STORY-1.5.1
  │ 2. Per-turn classifier     (synthesis→high; chitchat→low) TODO  │  STORY-1.5.2
  │ 3. Org-bundle model menu + budget caps (THIS FILE)              │  STORY-1.5.3
  │ 4. Prompt caching                                          TODO │  STORY-1.5.4
  │ 5. User override (pin tier; logged; counted against budget)     │  STORY-1.5.5
  └─────────────────────────────────────────────────────────────────┘
        │
        ▼
  RouteDecision { selected_model, tier, projected_cost_usd, blocked, rationale }
```

Mechanisms 1, 3, 5 are implemented. (2) and (4) slot in as caller
responsibility — the classifier sets `RouteRequest.intended_tier`, and the
prompt-cache discount reduces `estimated_input_tokens` before route().

## Model menu — sourcing

Most-specific wins: **org bundle** → team override → project override.
Active org bundle = `~/.spine/active/org` → `~/.spine/bundles/<id>/v*/bundle.yaml`
(highest version). Menu = `cost.model_menu.allowed − disallowed`.
Missing pointer or empty menu → router fails **closed**.

## Hard cap vs warn — NFR-1

Per PRD §1.6 NFR-1: caps are **hard**, not warn. `route()` checks
project (`per_project_cap_usd`), user-today (`daily_cap_usd`, proxy
until STORY-2.3.1), and per-phase (`per_phase_caps.<phase>`); blocks on
the first breach; lists every breached cap in the rationale. Spend
numbers come from `spine_recording.costs` (V16). If the V16 views
aren't reachable, queries fall back to direct `SUM(cost_usd)` against
the same table.

## Per-phase caps — worked example

`bundle-regulated-enterprise.yaml` sets `daily_cap_usd: 500`,
`per_project_cap_usd: 500`, plus `per_phase_caps: {plan_in_progress: 20,
verify_in_progress: 30, intake: 3}`. An *intake* turn (chitchat) and a
*plan_in_progress* synthesis turn share the org envelope but live under
very different ceilings — a runaway intake loop dies at $3, while TRD
synthesis has room to breathe.

## User override — STORY-1.5.5

`RouteRequest.override = ModelOverride(model_id, justification, granted_by)`.
The router validates:

1. The override `model_id` MUST be in the bundle's allowed menu —
   otherwise `blocked=True, rationale="override blocked: model '<id>'
   not in allowed menu"`. The bundle is final authority; an override
   never smuggles in a disallowed model.
2. Cost is still projected and counted against caps — overriding to
   `claude-opus-4` can still trip a cap.
3. `justification` (≥4 chars, required) ends up in the rationale and the
   audit log.

`would_violate()` is the quick yes/no pre-flight (e.g. `STORY-1.5.7`
phase-start projection).

## Cost estimation

Token estimates are the **caller's** responsibility for now:
`estimated_input_tokens` + `estimated_output_tokens`. A future story
ships per-role heuristics. The router computes
`(in/1000)*price_in + (out/1000)*price_out` against
`R__2_model_pricing.sql` (DB authoritative; an in-file fallback registry
covers DB-unreachable runs).

## Example: SecurityISO on regulated-enterprise

```bash
shared/cost/router_cli.sh route \
  --project 42 --phase verify_in_progress --role SecurityISO \
  --tier high --est-in 6000 --est-out 3000 --actor verify-daemon
```

Output (active bundle = `regulated-enterprise-reference`, no spend yet):

```json
{ "selected_model": "claude-sonnet-4", "selected_tier": "high",
  "rationale": "tier matched (intended=high, selected=high); under budget (projected $0.0630)",
  "projected_cost_usd": "0.0630", "blocked": false }
```

Exit `0` → daemon proceeds. If today's `verify_in_progress` spend were
already $29.95, the same call returns `blocked=true,
would_exceed_budget=true`, exit `2`, daemon halts the directive and
surfaces the cap miss in the dashboard.
