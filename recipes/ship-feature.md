# Recipe — Ship a feature end-to-end (planner)

Drop this into `teams/planner/directive.md`. The planner will decompose into directives for the right specialists.

---

```markdown
# Directive — Ship <FEATURE NAME>

## Goal
<one paragraph: what the feature does, who it's for, success criterion>

## Acceptance criteria
- [ ] <observable behavior 1>
- [ ] <observable behavior 2>
- [ ] Tests pass (existing baseline + new tests for the feature)
- [ ] Lint clean

## What I think it touches
<your best guess at affected files / services / DB changes — even rough — saves the planner discovery time>

## Phases (planner: decompose into sub-directives)

1. **Researcher**: audit existing code paths the feature will touch. Output: which files/functions need changes, which migrations needed, integration test surface.
2. **Engineer**: implement the changes per researcher's findings. Test-driven where possible.
3. **Operator** (if applicable): rebuild/restart relevant containers, run smoke checks.
4. **Datawright** (if applicable): regenerate any data artifacts the feature depends on.

## Constraints
- Do NOT introduce new dependencies without flagging
- Backwards compatibility unless I've explicitly waived it
- ADR if any architectural decision is non-obvious

## Report format (planner)
Replace this file with `# Plan — <feature>` while specialists work, then aggregate to `# Report — <feature>` containing:
- What shipped: per-specialist summary
- Test results
- Any compromises made vs. acceptance criteria
- Open follow-ups
```
