---
name: harness-fix-wave
description: >-
  Harness Lite Phase 2 — write fan-out with exclusive file ownership per agent.
  Driven by audit findings; HIGH/CRITICAL first. ADR-008 fix after audit.
---

# Harness Fix Wave (Phase 2)

**WRITE phase.** Runs only after audit-wave findings exist. One agent = one
exclusive file scope per wave.

## When to invoke

- `state.json` wave is `fix`
- Audit findings present under `.spine/harness/findings/`
- User approved fix wave (or mode is `sprint-close` / `release-gate`)

## Preconditions

1. Phase 1 complete — findings JSON on disk
2. **Never** run fix without audit data (ADR-008 rule 1)
3. Read findings; sort by severity: critical → high → medium → low

## File partitioning (mandatory)

| Rule | Detail |
|------|--------|
| One agent = one file | No shared files in same wave |
| Scope in prompt | Explicit path list per agent |
| Builder type | `cavecrew-builder` for ≤2 file surgical edits |
| Word cap | 200–400 words per dispatch |

Build partition map from `owner_file` in findings. If missing, derive from
`location` (file portion before `:`).

## Dispatch pattern

```
Wave N (HIGH/CRITICAL only):
  Agent A → file1.ts
  Agent B → file2.py
  Agent C → docs/foo.md
```

Wait for wave completion before overlapping files in next wave.

## Agent selection

| Need | Use | Avoid |
|------|-----|-------|
| ≤2 file surgical edit | `cavecrew-builder` | whole-repo context |
| Docs only | doc-focused agent with Write | investigator |
| CI/shell | debug-specialist / cloud-architect | planner without Write |
| Security fix | security-reviewer | read-only types |

## After fixes

1. Do **not** re-run full audit inline — hand off to verify-wave
2. Update finding files with `fixed: true` or move to `findings/resolved/`
3. Set `state.json` wave → `verify`

## Prompt template (≤400 words)

```
Fix wave — exclusive scope: <single file or ≤2 files>.
Findings: <paste relevant rows from findings JSON>.
Severity focus: HIGH/CRITICAL.
Rules: surgical diff only; match surrounding style; no scope creep.
Output: brief receipt — files touched, issues addressed.
```

## References

- `docs/adr/ADR-008-sprint-cleanup-methodology.md` Phase 2
- `docs/adr/ADR-005-parallel-subagent-orchestration.md`
