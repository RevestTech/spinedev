# SpineDevelopment — Agent team template for multi-agent development

Current package releases and history live in **`CHANGELOG.md`**.

A reusable file-based agent team for any software project. **Eight role-specialized managers + up to 80 worker agents**, coordinating via a shared filesystem message bus. No SaaS orchestrator — bash daemons poll markdown directives and invoke your local CLI agent (Cursor, Claude Code, etc.) on demand.

Derived from iterative production use and generalized so any repo can adopt the same **parallel roles, constrained authority, durable context** pattern.

For **why** and **how to avoid drift** when many agents touch one codebase, read **`docs/SPINE_PRACTICES.md`** (also copied into target projects under `.planning/orchestration/docs/` on install).

---

## What you get

```
your-project/
├── .planning/orchestration/
│   ├── AGENT_TEAM_PROTOCOL.md     ← protocol (every agent reads)
│   ├── AGENT_TEAM_REQUIREMENTS.md ← host prerequisites
│   ├── DECISIONS.md               ← ADR log scaffold (when installed)
│   ├── ADR_TEMPLATE.md            ← copy-paste skeleton for ADRs
│   ├── docs/
│   │   ├── SPINE_PRACTICES.md     ← drift prevention & context habits
│   │   └── …
│   ├── recipes/                   ← pasted templates from this package (on install)
│   ├── dashboard/index.html
│   └── agent-handoff/teams/
│       ├── planner/      ← high-level goals, orchestration
│       ├── researcher/   ← read-only investigation
│       ├── engineer/     ← code/config edits + tests
│       ├── operator/     ← docker, env, deploy, infra
│       ├── datawright/   ← inference, training, batch data
│       ├── seer/         ← read-only observability digest
│       ├── auditor/      ← verification of other roles' reports
│       └── memory/       ← spine docs + per-role learning
├── scripts/
│   ├── team-agent-daemon.sh    ← the daemon (parameterized)
│   ├── team.sh                  ← entry point: up / down / status / budget / learn
│   ├── seer-tick.sh             ← periodic observability nudge
│   └── file-lock.sh             ← atomic locks for shared-file edits
└── Makefile                     ← `make team-up`, `make team-budget`, etc.

~/.spine-development/playbook/<role>/lessons.md  ← cross-project lessons (per role)
```

You write `# Directive — ...` into a manager's `directive.md` file, optionally with `## Tier hint: low|medium|high` to control model spend. The daemon polls every 8 seconds, fires up your local agent CLI with the directive + role prompt + per-role memory, and the agent does the work and replaces the file with `# Report — ...` when done. Each invocation logs cost (wall-clock, tier, exit code) to `state/costs.csv`.

If the work is parallelizable, the manager fans out to up to 10 workers (`workers/01-directive.md` through `workers/10-directive.md`), each with its own daemon. When all workers report back, the manager re-aggregates into one consolidated report.

---

## Why this exists

Without this, you sit in a single chat session with one AI, typing prompts one at a time, waiting for answers, copy-pasting between conversations. With this:

- **Parallelism.** A datawright manager can run 10 inference workers concurrently. Six hours of serial work → 40 minutes parallel.
- **Specialization.** Each role has hard boundaries: researchers can't write code, operators can't edit application source, engineers can't restart docker. Mistakes get caught at the role boundary instead of mid-execution.
- **Asynchrony.** Drop a directive, walk away. Come back to a structured report. No babysitting.
- **Persistence.** State survives across sessions. Future-you (or future-Claude in a fresh session) reads the directive/report files and knows exactly what's in flight. Per-role memory means the team gets smarter project-by-project.
- **Cost discipline.** Tier hints tell agents to pick cheap models for low-stakes work. `make team-budget` shows what every directive cost. Runaway loops surface immediately.
- **No leftover sloppy files.** Every daemon gets a sanctioned scratch dir (`teams/<role>/scratch/<slot>/`) and an OS-level temp dir (`/tmp/spine-<role>-<slot>/`), both auto-wiped on every new directive. Agents are TOLD to use them. Reports must declare every file touched outside the team dir, the auditor cross-checks against `git status`, and `make team-clean` gives you an architect-side reset button. See "File hygiene" below.
- **Honesty.** Reports are written in a fixed format. Workers report what actually happened, including failures. The auditor role can re-verify any claim. No glossy summaries hiding bugs.
- **Composable.** Multiple managers run in parallel via the planner. Want to investigate something + fix code + restart services + run inference? Drop one directive into planner; it fans out to specialists.

---

## The eight roles

### Five execution roles
| Role | Authority | Default tier | Use for |
|---|---|---|---|
| **planner** | Decompose goals → directives for other managers | medium | Multi-specialist work ("ship feature X end-to-end") |
| **researcher** | Read-only: code, logs, DB, web | low | Investigation, audit, diagnosis |
| **engineer** | Code/config edits + lint/test | medium | Implementing fixes, refactors, features |
| **operator** | Docker, compose, env, deploy, daemons | low | Infrastructure ops |
| **datawright** | Inference at scale, training, batch data | varies | ML and data-pipeline work |

### Three meta roles (new in v1.1)
| Role | Authority | Default tier | Use for |
|---|---|---|---|
| **seer** | Read-only across all manager directives | low | "What's happening?" — produces a single-page status across the team. `seer-tick.sh` nudges it every 5 minutes. |
| **auditor** | Read-only verification | low | Re-runs claimed checks (lint, tests, smoke) against another role's report. "Did engineer's tests actually pass?" |
| **memory** | Spine docs (DECISIONS.md, SESSION_HANDOFF.md, MASTER_TODO.md) + per-role memory.md + cross-project playbook | low | After significant decisions, after incidents, when a lesson is worth keeping. |

Each is described in detail in `lib/role-prompts/<role>.md`. Those become the system prompts loaded at agent invocation.

---

## Cost discipline (model tiering)

Every directive can declare a tier hint:

```markdown
## Tier hint: low
```

The daemon parses this and tells the agent in its prompt:

- **low** — "Use the cheapest model that can do the job competently (haiku-class, 7B-class, qwen-7b). Do not reach for an expensive model."
- **medium** — "Default-tier model. Sonnet-class / 13–34B-class is appropriate."
- **high** — "Use the most capable model available — only justified for deep architecture, complex refactors, or subtle bugs."

Per-role defaults if a hint isn't given:
- planner / engineer → medium
- researcher / operator / seer / auditor / memory → low
- datawright → low (inference) but escalates to high for prompt design

Cost log lives at `teams/<role>/state/costs.csv`. `make team-budget` aggregates across all roles and shows totals + per-tier breakdown.

---

## File hygiene (no agent-dropped junk)

AI agents are sloppy with files by default. They drop fixture data, scratch scripts, `.bak` copies, debug experiments, and one-off test files all over the repo. This template makes that disallowed in three layers:

**Sanctioned scratch space.** Every running daemon gets two ephemeral dirs:
- `teams/<role>/scratch/<slot>/` — repo-local scratch dir
- `/tmp/spine-<role>-<slot>/` — OS-level temp dir

Both are wiped automatically by the daemon every time a new directive arrives. The agent is told this in its prompt and instructed to use these dirs for any temp work.

**Forbidden file patterns.** Agents may not leave `.bak`, `.orig`, `~`, `.swp`, `.tmp`, `tmp_*`, `debug_*`, `scratch.*`, or any backup directory anywhere in the repo. Before writing `# Report`, agents run `git status` and verify each changed file was intentional.

**The "Files touched" report contract.** Every report ends with a `## Files touched` section listing every file the agent created or modified outside the team directory. The auditor role re-runs `git status` and flags any discrepancy.

**Architect-side cleanup.** Run any time:

```bash
make team-clean          # scratch + logs + archive (safe — keeps directives, memory, costs)
make team-footprint      # show disk usage per role
bash scripts/team.sh clean scratch    # just scratch
bash scripts/team.sh clean logs       # truncate > 5MB logs
bash scripts/team.sh clean archive    # prune workers/archive to last 50 batches
bash scripts/team.sh clean nuclear    # everything except current directives
bash scripts/team.sh clean dry-run all  # preview without changes
```

**Auto-bounded growth.** The daemon truncates logs > 5MB on every poll cycle, so even without explicit cleanup the team's footprint can't grow unboundedly. Costs are 1 row of CSV per invocation (text — won't bloat). Worker archive grows by one timestamped dir per aggregate cycle and is pruned on demand.

The full hygiene contract is in [PROTOCOL.md Section 15](PROTOCOL.md).

---

## Memory

Three layers, loaded automatically into every agent invocation:

1. **Per-role memory** — `teams/<role>/memory.md`. Lessons specific to this project + this role. Agents read it on every invocation, append to it when they learn something durable.
2. **Spine docs** — `DECISIONS.md`, `SESSION_HANDOFF.md`, `MASTER_TODO.md` at `.planning/orchestration/`. Maintained by the memory role. Loaded by anyone who needs context.
3. **Cross-project playbook** — `~/.spine-development/playbook/<role>/lessons.md`. Lessons that apply across every project you use this template on. Append with:
   ```bash
   bash scripts/team.sh learn "lesson text" --role engineer
   ```

This is how the team gets smarter: corrections that used to live only in your head now persist for the next directive, the next session, and every future project.

---

## Install

Two paths:

### Fresh project

```bash
cd ~/projects/your-new-project
bash /path/to/SpineDevelopment/install.sh .
```

### Existing project

```bash
cd ~/projects/existing-project
bash /path/to/SpineDevelopment/install.sh .
```

Either way, the full installer:

1. Copies `lib/*.sh` helpers into your project's `scripts/` (daemon, team.sh, watchdog, executor, …)
2. Creates team scaffolding under `.planning/orchestration/agent-handoff/teams/` for all eight roles
3. Installs `role-prompt.md` per role from `lib/role-prompts/`
4. Copies **`PROTOCOL.md`** and **`REQUIREMENTS.md`** into `.planning/orchestration/`
5. Copies **`recipes/`**, **`docs/`** (practices + checklist + extensions), and **`templates/orchestration/`** (ADR scaffolds) into `.planning/orchestration/`
6. Installs the dashboard HTML at `.planning/orchestration/dashboard/index.html`
7. Seeds `~/.spine-development/playbook/` without overwriting existing lesson files
8. Either creates or amends a `Makefile` with team targets
9. Optionally appends a short note to `CLAUDE.md`
10. Prints next-step instructions

**Updating knowledge only** (protocol, recipes, prompts, practice docs — not `scripts/` or dashboard):

```bash
bash /path/to/SpineDevelopment/install.sh . --pull-knowledge-only
```

Then:

```bash
make team-up        # starts 8 manager daemons + 80 worker slots + watchdog
make team-status    # shows what each is working on
make team-budget    # cost report (wall-clock, tier breakdown)
make team-down      # clean shutdown
```

---

## First use

Drop a directive in the right manager's file. Smallest example — a researcher investigation:

```bash
cat > .planning/orchestration/agent-handoff/teams/researcher/directive.md <<'EOF'
# Directive — Investigate why X happens

## Tier hint: low

Read the codebase at src/foo/, find every place that calls bar.baz(), and
report the call sites + their context. Read-only.

## Report format
Replace this file with `# Report — X investigation` containing:
- File paths + line numbers
- Per-site context (what function calls bar.baz, why)
- Anything surprising
EOF
```

Within 8 seconds, the researcher daemon picks it up. A few minutes later, the file's content flips to `# Report — X investigation` with structured findings. Done.

For multi-step work, use the planner — same pattern, but the planner writes sub-directives (one per specialist) and they run in parallel.

See `.planning/orchestration/recipes/` after install (or `recipes/` in this repo) for templates: postmortem, refactor-plan, dependency-bump, security-audit, performance-investigation, ship-feature, investigate-bug, batch-process-data, safe-db-script, host-side-llm-pipeline, and more.

---

## Watching the team work

```bash
# CLI status (one shot)
make team-status

# Live log tail of a single role
tail -f .planning/orchestration/agent-handoff/teams/engineer/log/manager.log

# Visual dashboard (browser)
open .planning/orchestration/dashboard/index.html
# OR serve it: cd .planning/orchestration/dashboard && python3 -m http.server 60005
```

The dashboard reads each manager's `directive.md` directly via fetch, classifies its state (idle / directive / plan / report / worker-directive / etc), and refreshes every 8 seconds.

---

## Architecture in 30 seconds

- Each manager runs a `team-agent-daemon.sh <role> manager` daemon
- Each manager has 10 worker daemon slots: `team-agent-daemon.sh <role> worker 01..10`
- Daemons poll their assigned file every 8 seconds
- When a file's hash changes AND its first line is `# Directive`, the daemon parses tier hint, loads memory, invokes `cursor-agent` with the directive + role prompt + memory + tier guidance
- The daemon enforces a hard timeout (default 25 min) and stall detection (default 8 min no stdout)
- Cost row written to `state/costs.csv` on every invocation
- The agent does the work, replaces the file with `# Report — ...`
- For decomposition: manager writes worker directives, marks own file `# Plan`, exits. Workers run in parallel. When all workers report `# Worker Report`, daemon re-invokes manager in aggregate mode

The daemon is defensive bash — it never exits on inner failures. The agent invocation is sandboxed; if it crashes or times out, the daemon logs it and keeps polling.

---

## Files

| Path | Purpose |
|---|---|
| `README.md` | This file |
| `CHANGELOG.md` | Package history |
| `PROTOCOL.md` | Agent contract → installed as `AGENT_TEAM_PROTOCOL.md` |
| `docs/SPINE_PRACTICES.md` | Multi-agent habits, context stack, drift avoidance |
| `docs/IMPROVEMENT_CHECKLIST.md` | Maintainer checklist |
| `templates/orchestration/` | `DECISIONS.md` + `ADR_TEMPLATE.md` scaffolds |
| `install.sh` | Bootstrap; supports `--pull-knowledge-only` |
| `lib/team-agent-daemon.sh` | Daemon (manager + worker); tiers, memory, timeouts, costs |
| `lib/team.sh` | up / down / status / budget / learn / clean / doctor |
| `lib/team-clean.sh` | Footprint cleanup |
| `lib/seer-tick.sh` | Periodic seer nudge |
| `lib/file-lock.sh` | Atomic locks for parallel edits |
| `lib/dashboard.html` | Static dashboard → `dashboard/index.html` |
| `lib/role-prompts/<role>.md` | Eight role system prompts |
| `lib/playbook-defaults/*.md` | Seeds for `~/.spine-development/playbook/` |
| `recipes/*.md` | Directive templates → `.planning/orchestration/recipes/` |
| `docs/EXTENSIONS.md` | Optional future work |

---

## Lineage

Early versions centered on five execution roles; current releases add meta roles (seer, auditor, memory), cost hygiene, watchdog supervision, and safe knowledge refresh (`--pull-knowledge-only`). See `CHANGELOG.md` for timelines.

The **orchestration spine** (`DECISIONS.md`, `MASTER_TODO.md`, `SESSION_HANDOFF.md`) lives under `.planning/orchestration/`. The agent team sits on top so parallel work stays tied to documented decisions.
