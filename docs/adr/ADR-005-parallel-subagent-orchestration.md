# ADR-005 — Parallel Subagent Orchestration

**Status:** Accepted (YYYY-MM-DD)

## Context

Parallel AI agents speed delivery but cause merge conflicts and lost work when multiple agents edit the same files or shared infrastructure without coordination.

## Decision

Adopt explicit batch planning rules before any multi-agent wave.

## Rules (non-negotiable)

1. **One agent owns its files** — exclusive write scope per wave
2. **Hook + page wired by same agent** — don't split UI wiring across agents
3. **Shared infra = main thread only** — DbContext, registries, global config edited serially
4. **Cross-batch dependencies chain** — don't parallelize dependent work
5. **Tests for a surface = next batch** — after wiring lands
6. **Word-count cap prompts** — 200–400 words per agent brief
7. **Research agents don't write** — match agent type to capability

## Batch planning checklist

Before spawning a wave:

- [ ] File ownership map written (file → agent id)
- [ ] No file appears on two agents in same wave
- [ ] Shared files listed for main-thread edit first
- [ ] Dependency order documented
- [ ] Test batch scheduled after implementation batch

## Consequences

**Positives:** Scales to 50+ agents without merge chaos  
**Negatives:** Requires upfront planning; under-partitioning wastes parallel capacity

## References

- [docs/adr/ADR-008-sprint-cleanup-methodology.md](./ADR-008-sprint-cleanup-methodology.md)
- [docs/PARALLEL-BATCH-CHECKLIST.md](../PARALLEL-BATCH-CHECKLIST.md)
