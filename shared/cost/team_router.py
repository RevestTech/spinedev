"""Team-of-models router (STORY-3.3.1 + STORY-3.3.2; EPIC-3.3).

Composes three pieces — each owned by a separate module — into the
single auto-routing entry point Spine daemons call before dispatching a
directive:

    1. complexity_scorer.score_complexity()         — what kind of work?
    2. model_selection_table.lookup()               — which tier suits?
    3. router.route()                               — which model in tier?

The cost router (`router.py`) is treated as an opaque dependency: this
file selects the *intended tier*, then delegates to `route()` which
performs menu-validation, budget checks, and per-tier model selection.
On a hard-cap block at the preferred tier, team_route() optionally
retries at the entry's `fallback_tier`.

User overrides bypass the scorer entirely (the user has pinned a tier
intentionally — e.g. "spend on this one").

Cross-refs: `STORY-3.3.1`, `STORY-3.3.2`, `STORY-3.3.3`,
`shared/cost/router.py`, `shared/cost/classifier.py`.
"""
from __future__ import annotations
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from shared.cost.complexity_scorer import (ComplexityScore, TaskContext,
                                           score_complexity)
from shared.cost.model_selection_table import (SelectionEntry, SelectionTable,
                                               build_active_table)
from shared.cost.router import (RouteDecision, RouteRequest, Tier,
                                _load_active_bundle, route)

_PYD_CONFIG = ConfigDict(protected_namespaces=())


# ── Request / decision models ────────────────────────────────────────────────
class TeamRouteRequest(BaseModel):
    """Caller fills role + phase + directive text; everything else is
    optional. If `task_context` is supplied we use it as-is (saves a
    rebuild); otherwise we synthesise one from the request fields."""
    model_config = _PYD_CONFIG
    role: str
    phase: str
    directive_text: str
    project_id: int = Field(default=0, ge=0)
    actor: str = "unknown"
    estimated_input_tokens: int = Field(default=0, ge=0)
    estimated_output_tokens: int = Field(default=0, ge=0)
    task_context: TaskContext | None = None
    user_override_tier: Tier | None = None
    file_count_touched: int = Field(default=0, ge=0)
    estimated_loc: int = Field(default=0, ge=0)
    artifact_type: str | None = None
    prior_attempts: int = Field(default=0, ge=0)
    history_summary: str = ""


class TeamRouteDecision(BaseModel):
    model_config = _PYD_CONFIG
    selected_tier: Tier
    selected_model: str
    complexity_score: ComplexityScore
    selection_entry: SelectionEntry
    rationale: str
    fallback_used: bool = False
    blocked: bool = False
    cost_router_decision: RouteDecision


# ── Internal helpers ─────────────────────────────────────────────────────────
def _context_for(req: TeamRouteRequest) -> TaskContext:
    """Reuse the caller's TaskContext if it exists; else build one."""
    if req.task_context is not None:
        return req.task_context
    return TaskContext(role=req.role, phase=req.phase,
                       directive_text=req.directive_text,
                       file_count_touched=req.file_count_touched,
                       estimated_loc=req.estimated_loc,
                       artifact_type=req.artifact_type,
                       prior_attempts=req.prior_attempts,
                       history_summary=req.history_summary)


def _override_score() -> ComplexityScore:
    """Synthetic score used when the user pins a tier — no scoring done."""
    return ComplexityScore(score=0.0, bucket="moderate",
                           rationale="user override; complexity scoring skipped",
                           signals={})


def _override_entry(tier: Tier) -> SelectionEntry:
    return SelectionEntry(role="override", complexity="moderate",
                          preferred_tier=tier, fallback_tier=None,
                          cost_ceiling_usd=0.0,
                          rationale=f"user pinned tier={tier}")


def _delegate(req: TeamRouteRequest, tier: Tier,
              bundle: dict[str, Any] | None,
              db_url: str | None) -> RouteDecision:
    """Build a cost-router RouteRequest and dispatch."""
    return route(RouteRequest(
        project_id=req.project_id, phase=req.phase, role=req.role,
        intended_tier=tier,
        estimated_input_tokens=req.estimated_input_tokens,
        estimated_output_tokens=req.estimated_output_tokens,
        actor=req.actor), bundle=bundle, db_url=db_url)


# ── Public entry point ───────────────────────────────────────────────────────
def team_route(request: TeamRouteRequest, *,
               bundle: dict[str, Any] | None = None,
               table: SelectionTable | None = None,
               db_url: str | None = None) -> TeamRouteDecision:
    """Top-level auto-router. Algorithm:

      1. user_override_tier set?  → skip scoring; entry = override
      2. else: score complexity → bucket → table.lookup(role, bucket)
      3. dispatch to cost router with entry.preferred_tier
      4. if cost router blocks AND entry.fallback_tier exists,
         retry at fallback_tier — record fallback_used=True
      5. return TeamRouteDecision with full provenance

    Pure function: zero DB writes. Reads the active org bundle (and the
    org override table inside it) unless caller passes `bundle=` /
    `table=` explicitly.
    """
    bundle = bundle if bundle is not None else _load_active_bundle()
    table = table if table is not None else build_active_table(bundle)

    # ── Path A: user override — short-circuit scoring ────────────────────
    if request.user_override_tier is not None:
        tier = request.user_override_tier
        entry = _override_entry(tier)
        score = _override_score()
        decision = _delegate(request, tier, bundle, db_url)
        return TeamRouteDecision(
            selected_tier=decision.selected_tier,
            selected_model=decision.selected_model,
            complexity_score=score, selection_entry=entry,
            rationale=(f"user override → tier={tier}; "
                       f"cost-router: {decision.rationale}"),
            fallback_used=False, blocked=decision.blocked,
            cost_router_decision=decision)

    # ── Path B: score → lookup → delegate ────────────────────────────────
    ctx = _context_for(request)
    score = score_complexity(ctx)
    entry = table.lookup(request.role, score.bucket)

    decision = _delegate(request, entry.preferred_tier, bundle, db_url)
    fallback_used = False

    # If hard-capped at preferred AND a fallback is defined, try it.
    if (decision.blocked and entry.fallback_tier is not None
            and entry.fallback_tier != entry.preferred_tier):
        fb_decision = _delegate(request, entry.fallback_tier, bundle, db_url)
        if not fb_decision.blocked:
            decision = fb_decision
            fallback_used = True

    rationale = (f"auto-route: complexity={score.bucket} ({score.score:.2f}) "
                 f"→ preferred_tier={entry.preferred_tier}"
                 + (f" → fallback_tier={entry.fallback_tier} (used)"
                    if fallback_used else "")
                 + f"; cost-router: {decision.rationale}")

    return TeamRouteDecision(
        selected_tier=decision.selected_tier,
        selected_model=decision.selected_model,
        complexity_score=score, selection_entry=entry,
        rationale=rationale, fallback_used=fallback_used,
        blocked=decision.blocked, cost_router_decision=decision)


def would_block(request: TeamRouteRequest, *,
                bundle: dict[str, Any] | None = None,
                table: SelectionTable | None = None) -> bool:
    """Quick pre-flight: True iff team_route() would return blocked=True."""
    return team_route(request, bundle=bundle, table=table).blocked


__all__ = ["TeamRouteRequest", "TeamRouteDecision", "team_route",
           "would_block"]
