# Parallel batch planning checklist

Use before spawning any multi-agent implementation or fix wave.

## Pre-flight

- [ ] File ownership map: `file → agent-id` (no duplicates in same wave)
- [ ] Shared infrastructure files assigned to **main thread** only
- [ ] Dependency graph: parallel only where independent
- [ ] Test-writing batch scheduled **after** wiring batch
- [ ] Agent prompts capped at 200–400 words
- [ ] Write-capable agents assigned to edit tasks (not research-only types)

## During wave

- [ ] Agents check in via PM protocol (`in_progress` / `completed` / `blocked`)
- [ ] No agent edits outside assigned file scope
- [ ] Blockers escalated in STATUS within same session

## Post-wave

- [ ] Merge or integrate before next parallel wave on overlapping areas
- [ ] Run targeted tests for touched surfaces
- [ ] Update traceability matrix for completed items

## References

- [docs/adr/ADR-005-parallel-subagent-orchestration.md](./adr/ADR-005-parallel-subagent-orchestration.md)
- [docs/PLAYBOOK.md](./PLAYBOOK.md)
