# Recipe — Plan a refactor before doing one (planner)

Drop into `teams/planner/directive.md`. The planner orchestrates research → design → cost-estimate → architect approval, BEFORE engineer touches code.

---

```markdown
# Directive — Refactor plan for <SCOPE>

## Tier hint: medium

## Goal
<one paragraph: what's wrong, what better looks like, what success means>

## What I think the scope is
<your best guess — files, modules, services. Saves the planner discovery time.>

## Specialist plan
1. researcher → "Map the current state: every file, function, type that touches <scope>. Quote actual code." (LOW tier)
2. researcher → "Survey how the codebase uses <scope> — every call site, every test that depends on it, every API consumer." (LOW tier, parallel with #1)
3. engineer → "Given researcher's map, design 2-3 alternative refactor strategies. For each: scope of change, risk, test coverage cost, rollout strategy. DO NOT implement." (MEDIUM tier)
4. operator → (if applicable) "Identify any infra changes the refactor implies (compose, env, deploy)" (LOW tier)
5. memory → "Write the refactor plan as an ADR draft and stash in DECISIONS.md (status=Proposed)" (MEDIUM tier)

## Stop condition
Architect approval required before ANY engineer-level work begins. The output of this directive is a PLAN, not code.

## Report format (planner aggregate)
Replace this file with `# Report — refactor plan for <scope>` containing:
- Current state map (researcher output)
- Strategy options with pros/cons (engineer output)
- Recommended strategy
- ADR pointer (memory output)
- Architect decision needed: which strategy to pursue
- Estimated effort (per strategy): worker-hours, commits, test risk
```
