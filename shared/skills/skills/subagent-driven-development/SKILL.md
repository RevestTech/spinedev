# Skill — subagent-driven development

The directive in front of you is **too big for one agent invocation**, or
the work is naturally parallel. Don't grind through it in a single
linear pass — decompose, dispatch sub-directives to parallel
sub-agents, and aggregate. One agent has limited context and is prone
to tunnel vision on multi-step work; N focused subagents in parallel
solve a wider problem faster and with cleaner per-piece reasoning.

## The 5 moves

### Move 1 — Plan the decomposition
Write a short Plan with each sub-directive as a bullet. State for each
one: (a) the scope, (b) the inputs, (c) the expected
output/artifact type. If you can't write the bullets cleanly, the work
isn't ready to decompose — keep planning, don't dispatch yet.

### Move 2 — Verify isolation
Each sub-directive **must be independent**: no shared mutable state,
no "Worker 2 reads what Worker 1 wrote mid-flight." Inputs are fixed
at dispatch time; outputs are read-only artifacts the aggregator
consumes. If two sub-directives share state, they aren't sub-directives
— they're a sequence; run them serially or re-decompose.

### Move 3 — Dispatch in parallel
Use the existing dispatch primitives:
- `router.sh route_dispatch_to_subsystem` for cross-subsystem work
- MCP `build_dispatch` (one call per worker) for build-side fan-out
- `plan/swarm/swarm_engine.py` for read-only investigation swarms

If you're touching code in ≥2 sub-directives, also fire the
`using-git-worktrees` skill — each worker gets its own worktree so
they can commit without colliding.

### Move 4 — Wait + collect
Wait for **all** workers to complete (or hit timeout). Collect their
artifacts — `BuildArtifact`, `ResearchArtifact`, or whatever the
sub-directive contract specified. A partial collection is a
partial result; report it as such rather than synthesizing over a
missing worker.

### Move 5 — Aggregate
Synthesize the per-worker outputs into a single response/report. Three
common patterns:

- **Reduce** — combine N artifacts into one summary (most common; e.g.
  N research findings → one Tech Review report).
- **Map** — transform N artifacts in parallel and pass through
  unchanged (e.g. N file-rewrites → N PRs).
- **Merge** — deduplicate + reconcile cross-worker findings (e.g.
  N investigators each turn up an overlapping list of suspect files —
  union, dedupe, rank by hit count).

State the aggregation pattern at the top of your final report so the
reader (and the auditor) can see how you got from N outputs to 1.

## When to use

- Multi-file refactors (one worker per file)
- Multi-component features (one worker per component)
- Multi-language work (one worker per language, e.g. Python core +
  TypeScript dashboard)
- Cross-cutting investigations (one worker per area, then merge
  findings)

## When NOT to use

- **Tightly coupled changes** with sequential dependencies — run them
  serially in one worker; parallel dispatch will just produce N
  conflicting drafts.
- **Trivial single-file work** — the overhead (dispatch + wait +
  aggregate) is greater than the saved time.
- **Cost-sensitive budgets** — N subagents = N × invocation cost. The
  cost ledger tracks per-skill follow-on cost; if the budget is tight,
  pick serial.

## Integration

This skill is the playbook behind Spine's existing planner → manager →
workers pattern *and* the Tech Review Swarm primitive
(`plan/swarm/swarm_engine.py`). Conductor squads already operate this
way; this skill makes the decomposition discipline explicit at
dispatch time instead of leaving it as folklore.

## Cross-refs

- `REQ-INIT-1 §1.5 FR-3` — decomposition discipline for complex
  directives
- `plan/swarm/swarm_engine.py` — read-only swarm dispatch primitive
- `build/daemons/team-agent-daemon.sh` — build-side worker dispatch
- `obra/superpowers` — `subagent-driven-development` skill (pattern
  origin)
- `using-git-worktrees` skill — fires alongside this one when
  sub-directives touch code
