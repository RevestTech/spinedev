# Recipe — Batch process data at scale (datawright)

Drop into `teams/datawright/directive.md`. Datawright is built for embarrassingly parallel work — this is where the 10-worker fan-out shines.

---

```markdown
# Directive — Process <N> <ITEM TYPE> through <PIPELINE>

## Long job: 120

## What & why
<one paragraph: what each item gets, why we're doing this, what the output unlocks>

## Input set
- Source: <DB query / filesystem path / S3 prefix / etc>
- Estimated count: <N>
- Roughly balanced workload: yes / no — if no, plan for stragglers

## Per-item operation
1. <step 1, e.g. "Read OCR text from document_pages">
2. <step 2, e.g. "Call Qwen with prompt at prompts/X.md">
3. <step 3, e.g. "Parse JSON, validate against taxonomy">
4. <step 4, e.g. "Upsert to classification_examples">

## Decomposition
Spawn 10 workers. Each worker handles roughly N/10 items disjoint from the others. Use a deterministic split (e.g. `id % 10 == worker_index`) so reruns are idempotent. For slices that can exceed the default daemon wall clock (**25 min**), add **`## Long job: <minutes>`** (or `6h` / `2d`) to **each** heavy **`workers/NN-directive.md`** — the hint does not auto-copy from the manager directive (**`docs/_archived/v1-PROTOCOL.md`** §6).

## Resumability
The script MUST be safe to re-run — use unique constraints / ON CONFLICT semantics so partial progress is preserved across crashes.

## Per-worker checkpoints
Every 50 items processed, append a one-line summary to `outputs/batch-<run-id>/worker-<NN>.partial.md` so a crash mid-run doesn't lose visibility.

## Constraints
- Cap concurrent inference calls per service: <Tier-3=1, classifier=20, etc.>
- Never call public LLM APIs (privacy)
- If an item fails 3x, mark it as failed in the output and move on

## Report format (manager)
Replace `directive.md` with `# Report — <run name>` containing:
- Total processed / succeeded / failed / skipped
- Throughput (items/min)
- Failure breakdown by reason (top 5)
- Per-worker time distribution (was it balanced?)
- Sample successful outputs (5)
- Sample failures (5) for triage
- Recommendation for next run
```
