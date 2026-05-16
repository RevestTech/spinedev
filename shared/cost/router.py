"""Spine cost-aware tier router (REQ-INIT-1 FR-6).

Implements STORY-1.5.3 (model menu + budget enforcement); foundation for
STORY-1.5.1 (per-phase tier). Reads V16 unified ledger + shared/standards/
bundles. FR-6 mechanisms: (1) per-phase tier — DONE; (2) per-turn classifier
— TODO STORY-1.5.2; (3) menu+caps — DONE; (4) prompt cache — TODO
STORY-1.5.4; (5) override — DONE. psql via subprocess (no psycopg dep).
"""
from __future__ import annotations
import json, os, subprocess
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# `model_*` field names conflict with Pydantic's default protected namespace; we
# need them in the public contract so we suppress that warning globally.
_PYD_CONFIG = ConfigDict(protected_namespaces=())

Tier = Literal["low", "medium", "high", "premium"]
_TIER_RANK = {"low": 0, "medium": 1, "high": 2, "premium": 3}
DEFAULT_DB_URL = "postgresql://spine:spine@localhost:33000/spine"
SPINE_HOME = Path(os.environ.get("SPINE_HOME", str(Path.home() / ".spine")))
ACTIVE_POINTER = SPINE_HOME / "active" / "org"
BUNDLES_DIR = SPINE_HOME / "bundles"
ZERO = Decimal("0")
_QUANT = Decimal("0.0001")
_q = lambda d: d.quantize(_QUANT, rounding=ROUND_HALF_UP)
_now = lambda: datetime.now(timezone.utc)


class ModelInfo(BaseModel):
    model_config = _PYD_CONFIG
    model_id: str
    provider: str
    tier: Tier
    cost_per_1k_input_tokens: Decimal
    cost_per_1k_output_tokens: Decimal
    context_window: int = 0


class ModelOverride(BaseModel):
    """STORY-1.5.5: power-user pin per directive. Logged + counted vs budget."""
    model_config = _PYD_CONFIG
    model_id: str
    justification: str = Field(min_length=4)
    granted_by: str


class RouteRequest(BaseModel):
    project_id: int
    phase: str
    role: str
    intended_tier: Tier
    estimated_input_tokens: int = Field(ge=0)
    estimated_output_tokens: int = Field(ge=0)
    actor: str
    override: ModelOverride | None = None

    @field_validator("phase", "role", "actor")
    @classmethod
    def _nonempty(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("must be non-empty")
        return v


class RouteDecision(BaseModel):
    model_config = _PYD_CONFIG
    selected_model: str
    selected_tier: Tier
    rationale: str
    projected_cost_usd: Decimal
    would_exceed_budget: bool = False
    blocked: bool = False
    fallback_attempted: bool = False
    decided_at: datetime = Field(default_factory=_now)


class BudgetStatus(BaseModel):
    project_spent_today: Decimal = ZERO
    project_cap_today: Decimal = ZERO
    user_spent_today: Decimal = ZERO
    user_cap_today: Decimal = ZERO
    remaining_today: Decimal = ZERO

    @model_validator(mode="after")
    def _remaining(self) -> "BudgetStatus":
        cands = [c - s for s, c in (
            (self.project_spent_today, self.project_cap_today),
            (self.user_spent_today, self.user_cap_today)) if c > 0]
        if cands:
            self.remaining_today = _q(max(min(cands), ZERO))
        return self


def _load_active_bundle() -> dict[str, Any]:
    """~/.spine/active/org → bundles/<id>/v*/bundle.yaml. {} on miss (fail-closed)."""
    if not ACTIVE_POINTER.is_file():
        return {}
    bid = ACTIVE_POINTER.read_text().strip()
    base = (BUNDLES_DIR / bid) if bid else None
    vs = sorted(p for p in base.glob("v*") if p.is_dir()) if base and base.is_dir() else []
    f = (vs[-1] / "bundle.yaml") if vs else None
    return (yaml.safe_load(f.read_text()) or {}) if (f and f.is_file()) else {}


# Fallback registry (DB-unreachable). Mirrors R__2_model_pricing.sql.
# Each row: (model_id, provider, tier, $/1k in, $/1k out, ctx).
_FB: dict[str, ModelInfo] = {row[0]: ModelInfo(
    model_id=row[0], provider=row[1], tier=row[2],  # type: ignore[arg-type]
    cost_per_1k_input_tokens=Decimal(row[3]),
    cost_per_1k_output_tokens=Decimal(row[4]), context_window=row[5]) for row in [
    ("claude-opus-4-6", "anthropic", "high", "0.015", "0.075", 200000),
    ("claude-opus-4", "anthropic", "high", "0.015", "0.075", 200000),
    ("claude-sonnet-4-6", "anthropic", "medium", "0.003", "0.015", 200000),
    ("claude-sonnet-4", "anthropic", "medium", "0.003", "0.015", 200000),
    ("claude-haiku-3.5", "anthropic", "low", "0.001", "0.005", 200000),
    ("claude-haiku-4-5-20251001", "anthropic", "low", "0.001", "0.005", 200000),
    ("gpt-5", "openai", "high", "0.005", "0.020", 128000),
    ("gpt-4o", "openai", "medium", "0.0025", "0.010", 128000),
    ("gpt-4o-mini", "openai", "low", "0.00015", "0.0006", 128000),
]}


def _psql(sql: str, db_url: str | None) -> str | None:
    url = db_url or os.environ.get("SPINE_DB_URL", DEFAULT_DB_URL)
    try:
        r = subprocess.run(["psql", url, "-A", "-t", "-X", "-q", "-v", "ON_ERROR_STOP=1", "-c", sql],
                           capture_output=True, text=True, timeout=10, check=True)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return None
    return r.stdout.strip() or None


def _lookup_model(mid: str, db_url: str | None) -> ModelInfo | None:
    """DB → R__2 seed fallback. Normalises legacy 'med' tier name."""
    raw = _psql(
        "SELECT provider_id, default_tier_id, cost_in_usd_per_1k_tokens, "
        "cost_out_usd_per_1k_tokens, COALESCE(context_tokens,0) "
        f"FROM model WHERE model_id = '{mid}' LIMIT 1;", db_url)
    if raw:
        try:
            prov, tier, ci, co, ctx = raw.split("|")
            t: Tier = "medium" if tier in ("med", "") or tier not in _TIER_RANK else tier  # type: ignore[assignment]
            return ModelInfo(model_id=mid, provider=prov, tier=t,
                             cost_per_1k_input_tokens=Decimal(ci),
                             cost_per_1k_output_tokens=Decimal(co),
                             context_window=int(ctx or 0))
        except (ValueError, KeyError):
            pass
    return _FB.get(mid)


def list_allowed_models(bundle: dict[str, Any], tier: Tier | None = None) -> list[ModelInfo]:
    """bundle.cost.model_menu (allowed − disallowed) → ModelInfo, tier-filtered."""
    menu = ((bundle or {}).get("cost") or {}).get("model_menu") or {}
    disallowed = set(menu.get("disallowed") or [])
    infos = (_lookup_model(mid, None) for mid in (menu.get("allowed") or []) if mid not in disallowed)
    return [i for i in infos if i is not None and (tier is None or i.tier == tier)]


def _spend(where: str, db_url: str | None) -> Decimal:
    """Today's SUM(cost_usd) from V16 ledger with extra WHERE filter."""
    raw = _psql("SELECT COALESCE(SUM(cost_usd),0)::numeric FROM spine_recording.costs "
                f"WHERE ts >= date_trunc('day', NOW()) AND {where};", db_url)
    return Decimal(raw) if raw else ZERO


_esc = lambda s: s.replace("'", "''")


def get_budget_status(project_id: int, user: str, org: str | None = None,
                      db_url: str | None = None,
                      bundle: dict[str, Any] | None = None) -> BudgetStatus:
    """Today's spend + caps. Caps from bundle.cost.*; spend from V16 ledger.
    STORY-2.3.1 will add explicit per-user caps; daily_cap_usd is the proxy."""
    bundle = bundle if bundle is not None else _load_active_bundle()
    cost = (bundle or {}).get("cost") or {}
    return BudgetStatus(
        project_spent_today=_q(_spend(f"project_id = {int(project_id)}", db_url) if project_id else ZERO),
        project_cap_today=_q(Decimal(str(cost.get("per_project_cap_usd") or 0))),
        user_spent_today=_q(_spend(f"actor = '{_esc(user)}'", db_url) if user else ZERO),
        user_cap_today=_q(Decimal(str(cost.get("daily_cap_usd") or 0))),
    )


def estimate_phase_cost(project_id: int, phase: str, db_url: str | None = None) -> Decimal:
    """How much (project, phase) has spent today. For STORY-1.5.7 preview."""
    return _q(_spend(f"project_id = {int(project_id)} AND phase = '{_esc(phase)}'", db_url))


def _phase_cap(bundle: dict[str, Any], phase: str) -> Decimal:
    v = (((bundle or {}).get("cost") or {}).get("per_phase_caps") or {}).get(phase)
    return Decimal(str(v)) if v is not None else ZERO


def _project_cost(m: ModelInfo, in_tok: int, out_tok: int) -> Decimal:
    return _q((Decimal(in_tok) / 1000) * m.cost_per_1k_input_tokens
              + (Decimal(out_tok) / 1000) * m.cost_per_1k_output_tokens)


def _select_for_tier(menu: list[ModelInfo], tier: Tier) -> tuple[ModelInfo | None, Tier, bool]:
    """Cheapest in tier; on miss escalate up first (preserve intent), then demote."""
    rank = _TIER_RANK[tier]
    # exact, then higher (ascending), then lower (descending)
    order = [tier, *(t for t in ("medium", "high", "premium") if _TIER_RANK[t] > rank),
             *(t for t in ("high", "medium", "low") if _TIER_RANK[t] < rank)]
    for i, t in enumerate(order):
        ms = [m for m in menu if m.tier == t]
        if ms:
            return min(ms, key=lambda m: _project_cost(m, 1, 1)), t, (i > 0)  # type: ignore[return-value]
    return None, tier, True


def route(request: RouteRequest, bundle: dict[str, Any] | None = None,
          db_url: str | None = None) -> RouteDecision:
    """Decide which model to dispatch (or block). Pure; no DB writes. Algorithm:
    menu → override validation → tier pick → projected cost → cap check."""
    bundle = bundle if bundle is not None else _load_active_bundle()
    menu = list_allowed_models(bundle, tier=None)

    def _block(model_id: str, msg: str, fb_attempted: bool = False) -> RouteDecision:
        return RouteDecision(selected_model=model_id, selected_tier=request.intended_tier,
                             rationale=msg, projected_cost_usd=ZERO,
                             blocked=True, fallback_attempted=fb_attempted)

    if not menu:
        return _block("", "no models in active bundle menu (fail-closed)")

    if (ov := request.override) is not None:
        selected = next((m for m in menu if m.model_id == ov.model_id), None)
        if selected is None:
            return _block(ov.model_id, f"override blocked: model '{ov.model_id}' not in allowed menu")
        sel_tier, fb = selected.tier, False
        base = f"user override granted by {ov.granted_by} (justification: {ov.justification!r}); pinned tier={sel_tier}"
    else:
        selected, sel_tier, fb = _select_for_tier(menu, request.intended_tier)
        if selected is None:
            return _block("", f"no model in menu matches tier '{request.intended_tier}' or any fallback", True)
        base = (f"tier matched (intended={request.intended_tier}, selected={sel_tier})" if not fb
                else f"fallback used: intended '{request.intended_tier}' empty; shifted to '{sel_tier}'")

    projected = _project_cost(selected, request.estimated_input_tokens,
                              request.estimated_output_tokens)
    status = get_budget_status(request.project_id, request.actor, db_url=db_url, bundle=bundle)
    phase_cap = _phase_cap(bundle, request.phase)
    phase_spent = estimate_phase_cost(request.project_id, request.phase, db_url=db_url)

    def _b(label: str, s: Decimal, c: Decimal) -> str | None:
        return f"{label} spent ${s} of ${c} cap (+${projected} would exceed)" if c > 0 and s + projected > c else None
    breaches = [b for b in (
        _b("project today", status.project_spent_today, status.project_cap_today),
        _b("user today", status.user_spent_today, status.user_cap_today),
        _b(f"phase '{request.phase}' today", phase_spent, phase_cap)) if b]

    return RouteDecision(
        selected_model=selected.model_id, selected_tier=sel_tier,
        rationale=("hard cap exceeded: " + " | ".join(breaches)) if breaches
                  else f"{base}; under budget (projected ${projected})",
        projected_cost_usd=projected,
        would_exceed_budget=bool(breaches), blocked=bool(breaches),
        fallback_attempted=fb)


def would_violate(request: RouteRequest, bundle: dict[str, Any] | None = None) -> bool:
    """Quick pre-flight: True iff route() would return blocked=True."""
    return route(request, bundle=bundle).blocked


# TODO(STORY-1.5.2): per-turn escalation classifier runs BEFORE route(); it
# inspects the directive text and overrides RouteRequest.intended_tier
# (synthesis/decision → high; chitchat/clarification → low).


def _decision_to_dict(d: RouteDecision) -> dict[str, Any]:
    return json.loads(d.model_dump_json())


__all__ = ["Tier", "ModelInfo", "ModelOverride", "RouteRequest", "RouteDecision",
           "BudgetStatus", "route", "would_violate", "get_budget_status",
           "list_allowed_models", "estimate_phase_cost",
           "_decision_to_dict", "_load_active_bundle"]
