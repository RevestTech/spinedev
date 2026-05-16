# `auditor.py` — Pre-Verify hook for `BuildArtifact`

**Story:** `STORY-7.4.3`
**Spec:** `docs/PRD.md` REQ-INIT-7 §7.5 FR-7
**Tool:** `verify_build_artifact`

## Why this hook exists

REQ-INIT-7 FR-7 closes the "fragile contracts" gap mechanically: before the orchestrator dispatches a sealed `BuildArtifact` to Verify, we re-traverse the KG and confirm the engineer's claimed `kg_impact` matches the graph's actual blast radius for `code_changes`. Engineers historically under-report callers (and occasionally over-report); without this gate the survey-class failure mode is "build looked clean, verify-fail, expensive rerun, lost trust." Catching the contract violation at the cheapest possible point makes Verify-fail loops rarer and more diagnosable.

The hook is **purely additive** — it doesn't replace Verify, it triages the artifact so Verify only runs on artifacts whose self-description is internally consistent.

## What it checks

Three gates, in cheapest-first order:

1. **Schema validation** — re-runs `BuildArtifact.model_validate(...)` against the artifact's own dump. This catches anyone who hand-assembled the dict instead of going through the Pydantic constructor (skipping `refuse-to-seal`, `runtime_consistency`, `cost_non_negative`).
2. **Scope check (optional)** — when the orchestrator passes `directive_scope=[<glob>, ...]`, any `code_changes.path` outside the glob set fails `verdict="scope_violation"`.
3. **KG-impact diff** — calls `impact_radius(target=<path>, target_type="file", include_tests=True)` once per `code_changes.path`, unions the returned `node_id`s, and diffs against `{n.node_id for n in artifact.kg_impact}`.
   - **`missing_from_claim`** non-empty ⇒ `verdict="kg_impact_mismatch"` (engineer missed callers — the common failure)
   - **`extra_in_claim`** non-empty ⇒ also fails *iff* `strict=True` (rare; possible if engineer was overcautious)

First failing gate wins.

## Cost — why this is cheap

One `impact_radius` SQL call per changed file (typical directive: 1-5 files). NFR-1 budgets `impact_radius` at p95 ≤ 500 ms; the whole hook therefore lands inside ~1-3 seconds for typical artifacts. Compare to TRON Verify which can run 7 layers + ISO swarm + Docker sandbox over tens of seconds to minutes. The cost ratio justifies running this gate on every artifact even if only ~10% fail it.

The hook does **not** spend LLM tokens — pure Postgres traversal + local Pydantic re-validation.

## Where it sits in the flow

```
engineer-daemon emits BuildArtifact (sealed)
        │
        ▼  MCP call (registered as 'verify_build_artifact')
shared/mcp/tools/auditor.py::verify_build_artifact
        │   ├─ approved ───────▶ orchestrator dispatches to verify_audit (TRON)
        │   └─ <non-approved> ─▶ orchestrator re-dispatches to build with
        │                        remediation_directive as parent_directive_id
        ▼
spine_audit row (subsystem='shared', action='verify_build_artifact')
```

Router wiring lives in `orchestrator/lib/router.sh` and is a follow-up story (the spec for this story explicitly scopes the hook to the MCP layer; router integration is intentionally deferred so this can land independently).

## `strict` vs lenient mode

| Mode | Missing nodes | Extra nodes |
|---|---|---|
| `strict=True` (default) | **fail** | **fail** |
| `strict=False` | **fail** | report-only |

Lenient mode is the right choice when the engineer can justifiably over-claim — e.g., they listed every touched module while `impact_radius` only walks the typed CALLS/IMPORTS graph. Default to `strict` so the contract stays tight; switch to lenient with an explicit decision (and a memory lesson explaining why).

## Audit trail

One audit row per call:

- `subsystem='shared'`, `action='verify_build_artifact'`
- `subject_type='build_artifact'`, `subject_id=<artifact_uuid>`
- `metadata`: verdict, strict, directive_id, project_id, role, claimed_count, actual_count, missing_count, extra_count, scope_violation_count, schema_error_count, duration_ms

Best-effort write — audit failures log a warning but never block the verdict path.

## Cross-refs

- `shared/schemas/build/build_artifact.py` — `BuildArtifact` contract (`STORY-7.4.1`)
- `shared/mcp/tools/kg.py::impact_radius` — the underlying graph traversal (`STORY-6.5.5`)
- `shared/mcp/tools/verify.py::verify_audit` — the downstream Verify call this hook front-loads (`STORY-8.5.1`)
- `orchestrator/lib/router.sh` — wiring target (follow-up; do not modify in this story)
- `docs/PRD.md` REQ-INIT-7 §7.5 FR-7 — the spec
- `docs/BACKLOG.md` `STORY-7.4.3` — the story
