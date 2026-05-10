# Recipe — Performance investigation (planner)

Drop into `teams/planner/directive.md`. For "the app got slow" or "this endpoint is timing out" — measure first, fix later.

---

```markdown
# Directive — Performance investigation of <SYMPTOM>

## Tier hint: medium

## Symptom
- What's slow: <endpoint / page / job>
- Observed latency: <p50 / p95 / p99 if known, otherwise "feels slow">
- Expected latency: <SLO or rough target>
- When it started: <date / "always" / "intermittent">
- Reproducibility: <every request / 1-in-N / under load only>

## Goal
Locate the bottleneck with measurements (not guesses) before proposing a fix. The output of this directive is a DIAGNOSIS, not a patch.

## Specialist plan
1. researcher → "Reproduce <symptom> with a measurable test — curl with timing, k6 script, or db query under EXPLAIN ANALYZE. Capture wall-clock numbers." (LOW tier)
2. researcher → "Check obvious culprits in parallel: slow query log, container CPU/memory limits being hit, network round-trips, N+1 query patterns. Quote the actual log/EXPLAIN/perf output." (LOW tier, parallel with #1)
3. operator → "Compare current container resource usage to what's allocated. Note any throttling (CPU credits, memory swap, network rate limits)." (LOW tier, parallel with #1)
4. engineer → "Given researcher + operator findings, identify the bottleneck with code-level precision: which function, which query, which loop. DO NOT fix yet — just locate." (MEDIUM tier)
5. engineer → "Propose 2-3 candidate fixes ranked by effort and risk. Include estimated impact (e.g. 'this index removes the seq scan, expected 50ms → 5ms')." (MEDIUM tier)
6. memory → "Capture the diagnosis as a perf-investigation note in DECISIONS.md (status=Diagnosis, no decision yet) so future regressions can compare." (LOW tier; runs last)

## Stop conditions
- If the bottleneck is in an external service (third-party API, managed DB), stop and report — fix is not in this codebase.
- If reproduction fails (can't make it slow on demand), report that as the finding — intermittent perf bugs need different tooling (APM, sampling profiler) than this directive provides.

## Report format (planner aggregate)
Replace this file with `# Report — perf investigation of <symptom>` containing:
- Reproduction recipe (so future-you can re-test after fix)
- Measurements: before-fix numbers (p50/p95/p99 or single-shot timings)
- Bottleneck: file/function/query, with EXPLAIN or profile evidence
- Why it's slow: 1-2 sentence root-cause explanation
- Candidate fixes: ranked, with effort + estimated impact + risk
- Recommended next directive (which fix to take)
- Pointer to DECISIONS.md diagnosis note
```
