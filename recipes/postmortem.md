# Recipe — Postmortem (planner)

After an incident or production surprise. Drop into `teams/planner/directive.md`.

---

```markdown
# Directive — Postmortem of <INCIDENT>

## Tier hint: medium

## Incident
- What happened: <one paragraph>
- When: <start ISO timestamp> to <end ISO timestamp> (or "still ongoing")
- Customer impact: <yes/no, severity, scope>
- First detected by: <human / alert / customer>

## Goal
Produce a structured postmortem doc that future sessions can reference. The team should:
1. Researcher: reconstruct the timeline from logs + git history + DB state
2. Engineer: identify the root cause in code (with line numbers)
3. Operator: capture the infra side (config drift, recent deploys, capacity events)
4. Memory: append the lesson(s) to spine ADRs and per-role memory files

## Specialist plan (planner: write these sub-directives)
1. researcher → "Reconstruct timeline of <incident> from logs + git history" (LOW tier)
2. engineer → "Identify code-level root cause given researcher's timeline" (MEDIUM tier)
3. operator → "Capture infra context — recent deploys, container restart history, env changes" (LOW tier)
4. memory → "Synthesize all three into a postmortem ADR + add lessons to per-role memory" (MEDIUM tier; runs last)

## Report format (planner aggregate)
Replace this file with `# Report — postmortem of <incident>` containing:
- Headline: 2-sentence summary
- Timeline: minute-by-minute reconstruction
- Root cause: technical, organizational, or both
- What went well (response, detection, etc)
- What went poorly
- Action items (engineer / operator / longer-term)
- Lessons captured: pointer to the ADR and per-role memory entries
```
