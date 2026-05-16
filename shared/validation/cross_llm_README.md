# `shared/validation/` — Cross-LLM Validation

Generalizes TRON's `AuditManager` cross-validation pattern
(`verify/tron/agents/manager.py`) into a reusable service for **Plan**,
**Build**, and **Verify**. Implements `STORY-3.7.1` + `STORY-3.7.2`
(`docs/BACKLOG.md` EPIC-3.7).

## Why

LLMs hallucinate consistently — the same model asked the same question
often makes the same mistake. A *different* provider acting as an
independent verifier breaks the correlated-failure mode: two heads beat
one. This is the "honesty layer" called for in `docs/PRD.md` REQ-INIT-3
/ EPIC-3.7 (see PRD §"fragile contracts").

## Algorithm

```
primary_model produces content
   ↓
for each provider in {anthropic, openai, …} \ {primary_provider}:
   validator_prompt = "Independently verify this output. Reply {verdict, confidence, rationale}."
   ProviderResult ← call provider with strict JSON schema
   ↓
compute_consensus(primary_model, provider_results) →
   ConsensusResult{final_verdict, confidence_band, dissenting_providers}
   ↓
write audit row (subsystem=shared, action=cross_llm_validate)
```

`final_verdict` is the decision surface:

| verdict | meaning | caller action |
|---|---|---|
| `validated` | all secondaries agree, high avg confidence | ship |
| `needs_review` | partial agreement or any disagreement | human gate |
| `rejected` | strict majority disagrees | block + escalate |
| `indeterminate` | all abstained or all errored | retry or skip |

## Cost (STORY-3.7.4)

Cross-validation is **roughly 2× the LLM cost** for the affected output —
the secondary call is a separate completion that re-reads the artifact.
`CrossLLMValidationResult.total_cost_usd` surfaces the cost so the meter
in `shared/cost/router.py` can account for it. Phases that opt in inherit
the bill; gate it deliberately.

Trim aid: secondary input is capped at ~16k chars
(`_VALIDATOR_MAX_INPUT_CHARS`); the validator answers in strict JSON
(~200 tokens out) to keep cost bounded.

## Per-phase configuration (STORY-3.7.2)

`config.DEFAULT_CROSS_LLM_PHASES`:

| phase | default | reason |
|---|---|---|
| `discovery` | off | cheap intake; no synthesis to verify |
| `technical_review` | **on** | TRD synthesis is high-stakes |
| `decomposition` | off | mechanical work |
| `build` | **on** | gated at call site to security-critical changes |
| `verify` | **on** | critical / high findings (TRON behaviour) |
| `acceptance` | off | human-in-the-loop |

Overrides from the org bundle's `verify_overrides.cross_llm_validation_required`
(see `shared/standards/bundle-schema.yaml`) take precedence. `critical`
severity always triggers regardless of phase config.

## Single-key deployments (STORY-3.7.3)

When only one of `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` is set,
`cross_validate` **degrades gracefully**:

- skip the secondary call (it would just be the primary calling itself)
- return `final_verdict='indeterminate'`, `confidence_band='low'`
- set `effective_confidence_cap=0.7` so callers know not to over-trust
- record `skipped_reason` in the audit row

The SDKs themselves are **lazy optional imports** — a missing `anthropic`
or `openai` package yields a non-fatal `ProviderResult(verdict='error')`,
never a crash.

## Integration examples

**Plan — TRD synthesis:**

```python
from shared.validation import ValidationRequest, cross_validate

result = cross_validate(ValidationRequest(
    content=trd.to_markdown(), content_type="trd",
    primary_model=route_decision.selected_model,
    project_id=str(project.id), phase="technical_review", severity="high",
))
if result.consensus.final_verdict == "rejected":
    raise PlanRejected(result.consensus.dissenting_providers)
```

**Build — engineer daemon, security-critical change:**

```python
if change.touches_auth or change.touches_secrets:
    result = cross_validate(ValidationRequest(
        content=artifact.diff, content_type="code_change",
        primary_model=engineer_model, project_id=str(project.id),
        phase="build", severity="critical",
    ))
    artifact.cross_llm_validation_id = result.audit_id
```

**Verify — TRON `AuditManager` wraps this:**

TRON's `_validate_single_finding` (`verify/tron/agents/manager.py`)
already implements the pattern internally; the wrapper exists so Plan and
Build don't have to re-implement, *not* to displace TRON's specialized
finding-level path.

## Cross-references

- `docs/BACKLOG.md` EPIC-3.7: `STORY-3.7.1` (lift) · `STORY-3.7.2`
  (per-phase config) · `STORY-3.7.3` (graceful degradation) ·
  `STORY-3.7.4` (cost projection)
- `docs/PRD.md` REQ-INIT-3 — cross-LLM validation requirement
- `verify/tron/agents/manager.py` — source pattern (read-only reference)
- `shared/standards/bundle-schema.yaml` — `verify_overrides.cross_llm_validation_required`
- `shared/cost/router.py` — `RouteRequest` / `RouteDecision` (cost meter)
- `shared/audit/audit_record.py` — audit-row sink
