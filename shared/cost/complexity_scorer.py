"""Task-complexity scoring (STORY-3.3.1; REQ-INIT-1 FR-6 + EPIC-3.3).

Sits BELOW the team-of-models router (`team_router.py`) and ABOVE the
existing tier router (`router.py`). Given a `TaskContext` (role, phase,
directive text + light structural signals), emits a `ComplexityScore` in
[0.0, 1.0] bucketed into five named tiers used by the model-selection
table.

The scorer is **pure heuristic** — zero network, zero LLM calls — so it
costs nothing and runs in well under 5 ms per directive (target). The
per-turn classifier (`classifier.py`) handles in-phase escalation /
demotion; this scorer handles the higher-level "what kind of work is this
role being asked to do" question that the cost router needs to pick a
tier before classifier nuance even applies.

Cross-refs: `STORY-3.3.1`, `STORY-3.3.2`, `shared/cost/router.py`,
`shared/cost/classifier.py`, `default_model_selection.yaml`.
"""
from __future__ import annotations
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

_PYD_CONFIG = ConfigDict(protected_namespaces=())

ComplexityBucket = Literal["trivial", "simple", "moderate", "complex",
                           "very_complex"]

# Bucket cut-points (right-open intervals; the last is closed).
_BUCKETS: list[tuple[float, ComplexityBucket]] = [
    (0.20, "trivial"), (0.40, "simple"), (0.60, "moderate"),
    (0.80, "complex"), (1.01, "very_complex"),
]

# ── Heuristic vocab ──────────────────────────────────────────────────────────
# Each keyword in the body of a directive adds the listed weight. Case-
# insensitive; multi-hit capped at 3 per keyword to avoid run-away scores.
_KEYWORD_WEIGHTS: dict[str, float] = {
    "refactor": 0.12, "redesign": 0.15, "migrate": 0.14, "migration": 0.12,
    "investigate": 0.10, "security": 0.10, "performance": 0.08,
    "scalability": 0.10, "architecture": 0.10, "synthesize": 0.12,
    "synthesis": 0.12, "rewrite": 0.13, "design": 0.06, "audit": 0.08,
    "compliance": 0.08, "cross-cutting": 0.12,
}
# Trivial / clearly-cheap intents pull the score DOWN.
_TRIVIAL_WEIGHTS: dict[str, float] = {
    "typo": -0.20, "rename": -0.10, "format": -0.10, "lint": -0.10,
    "comment": -0.06, "docstring": -0.06, "bump version": -0.08,
    "whitespace": -0.12,
}

# Role × phase priors: how much weight to add purely from "who is doing
# what". Keys are (role.lower(), phase.lower()); * is a wildcard.
_ROLE_PHASE_PRIORS: dict[tuple[str, str], float] = {
    ("architect", "synthesis"): 0.30,
    ("architect", "plan_in_progress"): 0.25,
    ("architect", "*"): 0.10,
    ("product", "synthesis"): 0.20,
    ("product", "intake"): -0.05,
    ("planner", "decomposition"): 0.05,
    ("auditor", "*"): -0.05,             # mostly reads; cheap by default
    ("auditor", "cross-cutting"): 0.20,
    ("qa", "*"): 0.0,
    ("engineer", "typo"): -0.30,
    ("engineer", "build_in_progress"): 0.05,
    ("operator", "*"): -0.10,            # shell scripts; rarely needs Opus
    ("datawright", "*"): 0.15,           # data/ml synthesis-heavy
    ("ux", "*"): 0.0,
    ("conductor", "*"): -0.05,
    ("seer", "*"): -0.05,
}

# Artifact-type priors. TRD synthesis is the most expensive case in Spine.
_ARTIFACT_PRIORS: dict[str, float] = {
    "TRD": 0.35, "PRD": 0.20, "Roadmap": 0.15, "BuildArtifact": 0.05,
    "Findings": 0.0, "RFC": 0.20, "Spec": 0.15, "Design": 0.20,
    "Memo": -0.05, "Report": 0.0,
}

# Directive-length buckets → score contribution. Long directives are
# almost always more complex than short ones.
def _len_score(n: int) -> float:
    if n <= 80:        return -0.05
    if n <= 240:       return 0.0
    if n <= 600:       return 0.05
    if n <= 1500:      return 0.12
    if n <= 4000:      return 0.20
    return 0.28

# LOC buckets, per spec.
def _loc_score(loc: int) -> float:
    if loc <= 0:       return 0.0
    if loc < 100:      return 0.05
    if loc < 500:      return 0.15
    if loc < 2000:     return 0.28
    return 0.40

# File-count buckets.
def _files_score(n: int) -> float:
    if n <= 0:         return 0.0
    if n == 1:         return -0.05
    if n <= 3:         return 0.05
    if n <= 10:        return 0.15
    return 0.25

_WORD_RE = re.compile(r"[a-zA-Z][\w\-]*")


# ── Models ───────────────────────────────────────────────────────────────────
class TaskContext(BaseModel):
    """Inputs the scorer needs. Kept light so callers can build one in
    O(1) per directive — no DB lookups required."""
    model_config = _PYD_CONFIG
    role: str
    phase: str
    directive_text: str
    file_count_touched: int = Field(default=0, ge=0)
    estimated_loc: int = Field(default=0, ge=0)
    artifact_type: str | None = None
    prior_attempts: int = Field(default=0, ge=0)
    history_summary: str = ""


class ComplexityScore(BaseModel):
    model_config = _PYD_CONFIG
    score: float = Field(ge=0.0, le=1.0)
    bucket: ComplexityBucket
    rationale: str
    signals: dict[str, float]


# ── Scoring helpers ──────────────────────────────────────────────────────────
def _keyword_contribution(text: str, table: dict[str, float]) -> float:
    """Sum of (weight × min(3, hit_count)) per keyword in the table."""
    low = text.lower()
    total = 0.0
    for kw, w in table.items():
        # word-boundary count; cheap substring sum is good enough at this
        # scale (keyword tables are small).
        hits = low.count(kw)
        if hits:
            total += w * min(3, hits)
    return total


def _role_phase_prior(role: str, phase: str) -> float:
    r, p = (role or "").lower(), (phase or "").lower()
    return _ROLE_PHASE_PRIORS.get((r, p),
           _ROLE_PHASE_PRIORS.get((r, "*"), 0.0))


def _bucket_for(score: float) -> ComplexityBucket:
    for cutoff, name in _BUCKETS:
        if score < cutoff:
            return name
    return "very_complex"


# ── Public entry point ───────────────────────────────────────────────────────
def score_complexity(context: TaskContext) -> ComplexityScore:
    """Heuristic complexity scoring. Pure, deterministic, <5 ms.

    Combines six independent signal sources (length, keywords-up,
    keywords-down, file count, LOC estimate, role×phase prior,
    artifact-type prior, retry counter), each clamped, then sums into a
    score clipped to [0.0, 1.0]. The signal dict in the return value
    exposes each contribution so callers (and tests) can inspect *why*
    a directive landed in a given bucket.
    """
    text = context.directive_text or ""
    signals: dict[str, float] = {}

    # Length signal — long directives carry more requirements / context.
    signals["length"] = round(_len_score(len(text)), 4)

    # Keyword signals (split up/down for transparency).
    signals["keywords_up"] = round(_keyword_contribution(text,
                                                        _KEYWORD_WEIGHTS), 4)
    signals["keywords_down"] = round(_keyword_contribution(text,
                                                           _TRIVIAL_WEIGHTS), 4)

    # Structural signals: file count + LOC estimate.
    signals["files"] = round(_files_score(context.file_count_touched), 4)
    signals["loc"] = round(_loc_score(context.estimated_loc), 4)

    # Role × phase prior.
    signals["role_phase_prior"] = round(_role_phase_prior(context.role,
                                                          context.phase), 4)

    # Artifact prior — pulled out so callers see TRD/PRD pop in rationale.
    signals["artifact"] = round(_ARTIFACT_PRIORS.get(context.artifact_type
                                                     or "", 0.0), 4)

    # Each retry bumps complexity (compounding evidence the task is hard).
    # Cap at +0.20 so a stuck loop doesn't sky-rocket into premium.
    signals["retry"] = round(min(0.20, 0.05 * context.prior_attempts), 4)

    # Long history summary → harder reasoning context — small bump only.
    hist_words = len(_WORD_RE.findall(context.history_summary or ""))
    signals["history"] = round(min(0.10, hist_words / 2000.0), 4)

    raw = sum(signals.values())
    # Anchor to a baseline of 0.20 so a stripped-down directive sits in
    # "simple" rather than "trivial" by default. Trivial requires explicit
    # downward signal (typo/lint/format/etc).
    score = max(0.0, min(1.0, round(0.20 + raw, 4)))
    bucket = _bucket_for(score)

    # Build a readable rationale — top 3 (by absolute contribution) signals.
    top = sorted(signals.items(), key=lambda kv: abs(kv[1]), reverse=True)[:3]
    parts = [f"{k}={v:+.2f}" for k, v in top if v]
    rationale = (f"complexity={score:.2f} ({bucket}); top signals: "
                 + (", ".join(parts) if parts else "none — baseline"))
    return ComplexityScore(score=score, bucket=bucket, rationale=rationale,
                           signals=signals)


__all__ = ["ComplexityBucket", "TaskContext", "ComplexityScore",
           "score_complexity"]
