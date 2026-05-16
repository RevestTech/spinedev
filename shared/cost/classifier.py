"""Per-turn tier escalation classifier (STORY-1.5.2; REQ-INIT-1 FR-6 §2).

Sits BEFORE `shared/cost/router.py:route()`. Reads the upcoming turn's
context (last user message + role/phase/artifact) and decides whether the
phase's default tier should be **escalated** (synthesis/decision → high)
or **demoted** (chitchat/clarification → low).

Two strategies, both shipped — callers pick:

* **Heuristic** — regex/keyword/structural rules. Zero cost, <1 ms,
  ~70 % accuracy on the bundled corpus.
* **LLM-judge** — cheap Haiku-class prompt (~$0.0001/call), ~92 %
  accuracy. Used only when the heuristic's confidence is below the
  threshold (default 0.70) → hybrid avg cost ≈ $0.00002/call.

The classifier produces a `TurnClassification`; the daemon-facing helper
`apply_to_route_request()` writes its `recommended_tier` back onto a
`RouteRequest` before dispatching to `route()` (no circular import — we
only borrow the `Tier` literal type).
"""
from __future__ import annotations
import json
import os
import re
import subprocess
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# Borrow the Tier literal from router; do NOT import route() (circular).
from shared.cost.router import RouteRequest, Tier

_PYD_CONFIG = ConfigDict(protected_namespaces=())

TurnType = Literal["chitchat", "clarification", "exploration", "decision",
                   "synthesis", "verification"]
ClassifierUsed = Literal["heuristic", "llm_judge", "hybrid"]

# Approximate cost of one classifier call (Haiku-class, ~150 in / ~30 out).
_LLM_JUDGE_COST_USD = Decimal("0.0001")
_ZERO_COST = Decimal("0")

# ── Heuristic patterns ───────────────────────────────────────────────────────
_RE_GREETING = re.compile(r"^\s*(hi|hello|hey|yo|ok|okay|thanks|thx|ty|sure|"
                          r"yes|no|nope|yep|cool|nice|great|got it|sounds good|"
                          r"\W*)[\s!.?]*$", re.IGNORECASE)
_RE_CLARIFY = re.compile(r"\b(what is|what's|what does|can you explain|"
                         r"could you explain|how does|why does|what do you mean|"
                         r"clarify)\b", re.IGNORECASE)
_RE_EXPLORE = re.compile(r"\b(show me|list( all| the)?|find|search|where is|"
                         r"where are|look up|fetch|get the)\b", re.IGNORECASE)
# RFC-2119 keywords (MUST/SHOULD/COULD/MAY) are case-sensitive; the
# rest are not. We compile two patterns and sum their hits.
_RE_DECISION = re.compile(r"\b(should we|let'?s decide|which approach|"
                          r"which option|approve|reject|pick (one|an option)|"
                          r"choose between|recommend|recommendation)\b",
                          re.IGNORECASE)
_RE_DECISION_RFC = re.compile(r"\b(MUST|SHOULD|COULD|MAY)\b")  # case-sensitive
_RE_SYNTHESIS = re.compile(r"\b(summari[sz]e|draft|compose|author|write (the|"
                           r"a|up) (PRD|TRD|Roadmap|spec|RFC|design|plan|"
                           r"report|memo|document|doc)|produce the|generate "
                           r"the (PRD|TRD|Roadmap|spec)|finalize the)\b",
                           re.IGNORECASE)
_RE_VERIFY = re.compile(r"\b(verify|audit|check (that|whether|if)|did the "
                        r"(engineer|architect|product|planner)|review (the|"
                        r"this)|validate)\b", re.IGNORECASE)

_DECISION_PHASES = {"plan_approved", "verify_approved", "acceptance"}
_VERIFY_ROLES = {"auditor", "qa", "security", "securityiso", "verifier"}
_PREMIUM_SYNTH_ARTIFACTS = {"TRD"}  # most expensive synthesis case


# ── Models ───────────────────────────────────────────────────────────────────
class TurnContext(BaseModel):
    """Everything the classifier needs to see — kept deliberately small so a
    daemon can build one in O(1) per turn."""
    model_config = _PYD_CONFIG
    role: str
    phase: str
    last_user_message: str
    prior_turn_summary: str | None = None
    artifact_being_produced: str | None = None
    turn_number_in_session: int = Field(default=1, ge=1)


class TurnClassification(BaseModel):
    model_config = _PYD_CONFIG
    turn_type: TurnType
    recommended_tier: Tier
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str
    classifier_used: ClassifierUsed
    classification_cost_usd: Decimal = _ZERO_COST


# ── Heuristic classifier ─────────────────────────────────────────────────────
def _score(pattern: re.Pattern[str], text: str) -> int:
    """Number of distinct matches (capped at 3 — diminishing returns)."""
    return min(3, len(pattern.findall(text)))


def _heuristic_classify(ctx: TurnContext) -> TurnClassification:
    """Pure regex/keyword/structural classification. <1 ms per call."""
    msg = (ctx.last_user_message or "").strip()
    msg_len = len(msg)

    # ── chitchat: short greeting / acknowledgement / pure punctuation
    if msg_len <= 30 and (_RE_GREETING.match(msg) or msg_len <= 3):
        return TurnClassification(
            turn_type="chitchat", recommended_tier="low", confidence=0.95,
            rationale=f"short greeting/ack (len={msg_len})",
            classifier_used="heuristic")

    # Aggregate signal scores; whichever scores highest wins. Tied scores
    # are broken by priority: synthesis > decision > verification >
    # exploration > clarification.
    signals: dict[TurnType, int] = {
        "synthesis": _score(_RE_SYNTHESIS, msg),
        "decision": min(3, _score(_RE_DECISION, msg)
                          + _score(_RE_DECISION_RFC, msg)),
        "verification": _score(_RE_VERIFY, msg),
        "exploration": _score(_RE_EXPLORE, msg),
        "clarification": _score(_RE_CLARIFY, msg),
    }

    # ── Structural boosters (phase / role / artifact override message-only).
    if ctx.artifact_being_produced:
        signals["synthesis"] += 2
    if ctx.phase in _DECISION_PHASES:
        signals["decision"] += 2
    if (ctx.role or "").lower() in _VERIFY_ROLES:
        signals["verification"] += 1

    priority: list[TurnType] = ["synthesis", "decision", "verification",
                                "exploration", "clarification"]
    best: TurnType = max(priority, key=lambda t: (signals[t],
                                                  -priority.index(t)))
    best_score = signals[best]

    # No signal at all → fall back to "exploration" at low confidence.
    # Caller can decide whether to escalate to LLM-judge.
    if best_score == 0:
        return TurnClassification(
            turn_type="exploration", recommended_tier="low", confidence=0.30,
            rationale="no heuristic signal matched; defaulting to exploration",
            classifier_used="heuristic")

    # Confidence model: one clean signal with no competition is already
    # informative (0.75); extra matches push higher; competing matches
    # push lower. Capped at 0.95, floored at 0.30.
    competing = sum(v for k, v in signals.items() if k != best)
    confidence = round(min(0.95, max(0.30,
                          0.75 + 0.05 * (best_score - 1) - 0.10 * competing)), 2)

    tier: Tier = {
        "chitchat": "low", "clarification": "low", "exploration": "low",
        "decision": "high", "synthesis": "high", "verification": "medium",
    }[best]

    # Premium escalation for the most expensive synthesis case.
    if best == "synthesis" and (ctx.artifact_being_produced or "") in _PREMIUM_SYNTH_ARTIFACTS:
        tier = "premium"

    rationale = (f"heuristic matched '{best}' (score={best_score}, "
                 f"signals={dict((k, v) for k, v in signals.items() if v)})")
    return TurnClassification(turn_type=best, recommended_tier=tier,
                              confidence=confidence, rationale=rationale,
                              classifier_used="heuristic")


# ── LLM-judge classifier ─────────────────────────────────────────────────────
_JUDGE_PROMPT = (
    "Given this Spine role turn, classify as one of: chitchat, clarification, "
    "exploration, decision, synthesis, verification. Recommend tier: low, "
    "medium, high, premium. Reply JSON only with keys: turn_type, "
    "recommended_tier, confidence (0-1), rationale.\n\n<context>\n"
)


def _llm_judge_classify(ctx: TurnContext,
                        heuristic_fallback: TurnClassification
                        ) -> TurnClassification:
    """Cheap Haiku-class classification. Raises on transport failure so the
    main wrapper can degrade gracefully."""
    model_id = os.environ.get("SPINE_CLASSIFIER_MODEL", "claude-haiku-3.5")
    helper = os.environ.get("SPINE_CLASSIFIER_HELPER", "")  # optional stub

    payload = ctx.model_dump_json()
    prompt = _JUDGE_PROMPT + payload + "\n</context>\n"

    if not helper:
        raise RuntimeError("SPINE_CLASSIFIER_HELPER not configured")

    # Stub helper contract: reads prompt on stdin, prints classification
    # JSON on stdout. Keeps the `anthropic` SDK out of this module.
    proc = subprocess.run([helper, "--model", model_id], input=prompt,
                          capture_output=True, text=True, timeout=10,
                          check=True)
    data = json.loads(proc.stdout.strip())

    return TurnClassification(
        turn_type=data["turn_type"], recommended_tier=data["recommended_tier"],
        confidence=float(data.get("confidence", 0.85)),
        rationale=f"llm_judge({model_id}): {data.get('rationale', 'n/a')} "
                  f"[heuristic was '{heuristic_fallback.turn_type}' @ "
                  f"{heuristic_fallback.confidence}]",
        classifier_used="llm_judge",
        classification_cost_usd=_LLM_JUDGE_COST_USD,
    )


# ── Main entry point ─────────────────────────────────────────────────────────
def classify_turn(context: TurnContext, *,
                  enable_llm_judge: bool = True,
                  llm_judge_threshold: float = 0.7) -> TurnClassification:
    """Hybrid classify. Returns the heuristic result if its confidence is
    ≥ threshold OR if LLM-judge is disabled; otherwise tries the LLM-judge
    and falls back to heuristic on any error (graceful degradation)."""
    heuristic = _heuristic_classify(context)
    if heuristic.confidence >= llm_judge_threshold or not enable_llm_judge:
        return heuristic
    try:
        judged = _llm_judge_classify(context, heuristic_fallback=heuristic)
        # Mark hybrid path so consumers can see both signals contributed.
        judged.classifier_used = "hybrid"
        return judged
    except Exception as e:  # noqa: BLE001 — any failure → graceful fallback
        heuristic.rationale += (f" (llm_judge unavailable: "
                                f"{type(e).__name__}: {e}; using heuristic)")
        return heuristic


# ── Router integration helper ────────────────────────────────────────────────
def apply_to_route_request(req: RouteRequest, context: TurnContext, *,
                           enable_llm_judge: bool = True,
                           llm_judge_threshold: float = 0.7,
                           override_threshold: float = 0.7
                           ) -> RouteRequest:
    """Run the classifier and OVERRIDE `req.intended_tier` when classifier
    confidence ≥ `override_threshold`. Returns a NEW `RouteRequest`
    (Pydantic v2 immutable-style copy) so the caller's original stays
    intact. Daemon wiring is then 3 lines:

        ctx = TurnContext(role=..., phase=..., last_user_message=...)
        req = apply_to_route_request(req, ctx)
        decision = route(req)
    """
    cls = classify_turn(context, enable_llm_judge=enable_llm_judge,
                        llm_judge_threshold=llm_judge_threshold)
    if cls.confidence < override_threshold:
        return req  # low confidence — keep the caller's intended_tier
    return req.model_copy(update={"intended_tier": cls.recommended_tier})


__all__ = ["TurnType", "ClassifierUsed", "TurnContext", "TurnClassification",
           "classify_turn", "apply_to_route_request"]
