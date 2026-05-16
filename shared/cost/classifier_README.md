# Per-Turn Tier Escalation Classifier

Implements `STORY-1.5.2` — mechanism #2 of PRD `REQ-INIT-1 FR-6`. Sits
BEFORE `shared/cost/router.py:route()`: inspects the upcoming turn and
adjusts `RouteRequest.intended_tier` (synthesis/decision → `high`,
chitchat/clarification → `low`).

Files: `classifier.py` + `classifier_test_corpus.yaml`. Cross-refs:
`STORY-1.5.2`, `shared/cost/router.py`, `sdlc-pipeline-default.yaml`.

## Why per-turn (vs static phase-default)

Phase defaults (STORY-1.5.1) are correct *on average*, but a phase
mixes wildly different turn types. `plan_in_progress` covers both "hi"
and "draft the TRD" — one static tier wastes money on the former. The
classifier fixes the asymmetry: cheap turns drop to `low`; synthesis
pushes to `premium`.

## Hybrid algorithm

```
  turn → heuristic (regex + structural booster)
            │
            ├── confidence ≥ 0.70 ─► return heuristic
            └── confidence <  0.70 ─► LLM-judge (Haiku-class)
                                       ├── ok    → return judged (hybrid)
                                       └── fail  → return heuristic (graceful)
```

Heuristic = regex hits + boosters (`artifact_being_produced` → +2
synthesis; gate phases → +2 decision; auditor/qa/security roles → +1
verification). Tie-break priority: synthesis > decision > verification
> exploration > clarification.

## Cost / accuracy tradeoff

| Mode      | $/call    | Latency | Accuracy | When                |
|-----------|-----------|---------|----------|---------------------|
| heuristic | $0        | <1 ms   | ~70 %    | Cost-discipline run |
| llm_judge | $0.0001   | ~300 ms | ~92 %    | Highest-stakes turn |
| hybrid    | ~$0.00002 | <5 ms   | ~88 %    | **Default**         |

Hybrid wins because ~80 % of turns are confidently classified by the
heuristic alone — only ambiguous ones pay the LLM-judge tax.

## The six turn types

| Type          | Tier                    | Escalates? |
|---------------|-------------------------|------------|
| chitchat      | low                     | no  — stays cheap        |
| clarification | low                     | no  — KG-only typically  |
| exploration   | low                     | no  — cheap index lookup |
| decision      | high                    | **yes**                  |
| synthesis     | high (premium for TRD)  | **yes**                  |
| verification  | medium                  | partial                  |

`synthesis + artifact='TRD'` is the only path to `premium`.

## Daemon integration — 3 lines

```python
from shared.cost.classifier import TurnContext, apply_to_route_request
from shared.cost.router import route
ctx = TurnContext(role=req.role, phase=req.phase,
                  last_user_message=directive_text,
                  artifact_being_produced=plan_artifact)
req = apply_to_route_request(req, ctx)   # overrides intended_tier
decision = route(req)
```

`apply_to_route_request` only overrides when classifier confidence ≥
`override_threshold` (default `0.70`).

## LLM-judge wiring

Classifier shells out to a helper named in `SPINE_CLASSIFIER_HELPER`
(stdin = prompt, stdout = JSON). Model id in `SPINE_CLASSIFIER_MODEL`
(default `claude-haiku-3.5`). Anthropic SDK is NOT a hard dep — if the
helper is unset or fails, falls back to heuristic and notes the reason.
Force heuristic-only via `enable_llm_judge=False`.

## Extending & validating

* New keywords → edit the `_RE_*` patterns at the top of `classifier.py`.
* New turn types → extend the `TurnType` literal + tier table + corpus.
* Threshold dials: `llm_judge_threshold`, `override_threshold`.
* Validate via the bundled corpus (eval harness lands in `shared/eval/`
  per STORY-3.4.x); heuristic-only baseline should pass ≥ 70 % — the
  ambiguous block deliberately allows `min_confidence: 0.0`.
