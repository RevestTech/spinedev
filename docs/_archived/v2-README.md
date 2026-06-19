# SpineDevelopment — Agent team template for multi-agent development

Current package releases and history live in **`CHANGELOG.md`**.

---

## Developing Spine itself (v2)

If you cloned this repo to work on Spine — not to install the agent team into
another project — bring the whole stack up with one command:

```bash
git clone <spine-repo> && cd SpineDevelopment
make bootstrap            # ~3–5 min cold;  re-runs are <30 s no-op
make doctor               # all green checks, or precise actionable failures
make smoke                # 78+ PASS  /  0 FAIL  ← the v2 acceptance gate
```

`make bootstrap` runs `tools/bootstrap.sh`, which: checks `docker` / `python3>=3.10` / `psql` / `make` are on PATH; creates `.venv` and `pip install -r requirements.txt`; brings up the Spine Postgres (`spine_postgres` on `127.0.0.1:33001`) and the TRON Postgres (`spine_tron_postgres` on `127.0.0.1:33010`); runs Flyway migrations (and reconciles the wave-9 F2 history drift); runs TRON's Alembic migrations; and finally runs the smoke test as the acceptance gate. Idempotent end-to-end.

To cold-start from a clean state: `make nuke && make bootstrap` (asks before destroying volumes + `.venv`). See `docs/STATUS.md §6` for the full v2 state, and `§8` for the dogfood "external implementer" workflow + the Claude Code subagent sandbox gotcha.

The rest of this README documents the v1 installer (`bash install.sh <target-project>`) for installing the agent team into a *different* project.

---

A reusable file-based agent team for any software project. **Every manager role in `scripts/roles.sh` (13 in the stock template after ADR-001) × up to 10 worker agents each = 130 parallel worker slots**, plus a watchdog, coordinating via a shared filesystem message bus. No SaaS orchestrator — bash daemons poll markdown directives and invoke your local CLI agent (Cursor, Claude Code, etc.) on demand.

Legacy **`engineering-backend`** / **`engineering-frontend`** top-level roles are **retired**; use **`engineer`** with worker fan-out (and optional discipline in directives) — see **`.planning/orchestration/DECISIONS.md` (ADR-001)** when installed, or **`lib/roles.sh`** in this package.

Derived from iterative production use and generalized so any repo can adopt the same **parallel roles, constrained authority, durable context** pattern.

For **why** and **how to avoid drift** when many agents touch one codebase, read **`docs/SPINE_PRACTICES.md`** (also copied into target projects under `.planning/orchestration/docs/` on install).

---

## What you get

```text
your-project/
├── .planning/orchestration/
│   ├── AGENT_TEAM_PROTOCOL.md     ← protocol (every agent reads)
│   ├── AGENT_TEAM_REQUIREMENTS.md ← host prerequisites
│   ├── DECISIONS.md               ← ADR log scaffold (when installed)
│   ├── ADR_TEMPLATE.md            ← copy-paste skeleton for ADRs
│   ├── docs/
│   │   ├── SPINE_PRACTICES.md     ← drift prevention & context habits
│   │   └── …
│   ├── program/               ← REQ templates, phase ledger, policy stub
│   ├── docs/PROGRAM_DELIVERY.md
│   ├── dashboard/index.html
│   └── agent-handoff/teams/
│       └── <role>/       ← one directory per ID in scripts/roles.sh (stock: product, planner,
│                           architect, conductor, researcher, engineer, ux, qa, operator,
│                           datawright, seer, auditor, memory)
├── scripts/
│   ├── roles.sh                 ← canonical role ID list (single source of truth)
│   ├── team-agent-daemon.sh
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

## Manager roles

The **canonical list** is `scripts/roles.sh` (`SPINE_TEAM_ROLES`). The stock template ships **13 managers**; each runs **one manager daemon** and up to **10 workers** (see `PROTOCOL.md` §1). Do not add `teams/<new>/` directories without updating `roles.sh` and reinstalling.

Top-level **`engineering-backend`** / **`engineering-frontend`** folders are **retired** (v2 targets a single **`engineer`** job family + worker decomposition); old prompts live under `lib/role-prompts/_archived/`.

### Program delivery & quality (v1.4+)

| Role | Authority | Default tier | Use for |
| --- | --- | --- | --- |
| **product** | Requirements, scope, acceptance — normative REQ artifacts | medium | Discover/specify; gates implementation without approved REQ |
| **architect** | Technical design, ADRs, cross-cutting constraints | medium | Architecture phase before locked build plans |
| **conductor** | Locks sprint-style directives to squads (cites approved REQ) | medium | Build orchestration vs planner's ad-hoc decomposition |
| **ux** | UX specs, design-system reviews (bounded write scope per prompt) | low–medium | Experience quality gate |
| **qa** | Test planning, evidence, quality narrative | low–medium | Pairs with **auditor** / CI expectations |

### Core execution roles

| Role | Authority | Default tier | Use for |
| --- | --- | --- | --- |
| **planner** | Decompose goals → directives for other managers | medium | Multi-specialist work ("ship feature X end-to-end") |
| **researcher** | Read-only: code, logs, DB, web | low | Investigation, audit, diagnosis |
| **engineer** | Code/config edits + lint/test | medium | Implementation (use **workers/** for parallel slices; state backend vs frontend scope in the directive) |
| **operator** | Docker, compose, env, deploy, daemons | low | Infrastructure ops |
| **datawright** | Inference at scale, training, batch data | varies | ML and data-pipeline work |

### Meta roles (observability & memory)

| Role | Authority | Default tier | Use for |
| --- | --- | --- | --- |
| **seer** | Read-only across manager directives | low | Team-wide status digest; **`seer-tick.sh`** nudges periodically. |
| **auditor** | Read-only verification | low | Re-runs claimed checks against another role's report. |
| **memory** | Spine docs + per-role `memory.md` + cross-project playbook | low | ADR/session hygiene, durable lessons |

Each active role is spelled out in `lib/role-prompts/<role>.md` (installed as each team's `role-prompt.md`).

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

Per-role tier defaults vary by prompt (each `lib/role-prompts/<role>.md` ends with **Tier hint default**). Override any default with `## Tier hint:` in the directive — the daemon passes it through to the agent.

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

The full hygiene contract is in [PROTOCOL.md Section 15](v1-PROTOCOL.md).

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

**Maintainers:** Shell helpers are authored and versioned under `lib/*.sh` in this package; `install.sh` copies them into a target project’s `scripts/` directory, which is what `Makefile` targets, daemons, and `bash scripts/…` invocations use at runtime. To publish changes, edit the `lib/` sources and run a **full** `install.sh` in consuming projects when you need refreshed scripts—`install.sh . --pull-knowledge-only` updates protocol text, recipes, and role prompts but intentionally skips replacing `scripts/*.sh` (see **Updating knowledge only** below), so use a normal install or manual copy from `lib/` when tooling behavior changes.

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
2. Creates team scaffolding under `.planning/orchestration/agent-handoff/teams/` for **every role** in `scripts/roles.sh`
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
make team-up        # starts every manager in roles.sh + 10 workers each + watchdog
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

# Visual dashboard (browser) — Spine Control Center
make dashboard
# → http://127.0.0.1:61105/dashboard/
# (Default 61105 — many Docker setups use 60005; override with SPINE_DASH_PORT.)
# Or: bash scripts/serve-dashboard.sh   (SPINE_DASH_PORT to change port)

# Manual equivalent:
cd .planning/orchestration && python3 -m http.server 61105
# Open http://127.0.0.1:61105/dashboard/

# If your *app API* returns JSON { "Route GET:/dashboard/ not found" } — that server
# does not host Spine static files; use make dashboard instead (different port/path).
```

The control center aggregates all manager `directive.md` files plus `state/costs.csv` per role, optional program and docs previews, rollback stacks, and a worker-slot grid (opened per role). Serve **`.planning/orchestration`** (not `dashboard/` alone) so the UI can reach `agent-handoff/`. Path presets, search/state chips, refresh interval, Help tab — see `.planning/orchestration/dashboard/`.

---

## Architecture in 30 seconds

- Each manager runs a `team-agent-daemon.sh <role> manager` daemon
- Each manager has 10 worker daemon slots: `team-agent-daemon.sh <role> worker 01..10`
- Daemons poll their assigned file every 8 seconds
- When a file's hash changes AND its first line is `# Directive`, the daemon parses tier hint, loads memory, invokes `cursor-agent` with the directive + role prompt + memory + tier guidance
- The daemon enforces a hard timeout (default **25 min**, overridable per file with **`## Long job:`** — see **`PROTOCOL.md`** §13) plus stall detection (scaled when long job is set)
- Every completion appends **`costs.csv`** with **`outcome`** (`completed`, `timeout`, `stall`, `killed`) alongside **`rc`** — trust **`outcome`** when diagnosing daemon reaps
- Cost row written to `state/costs.csv` on every invocation
- The agent does the work, replaces the file with `# Report — ...`
- For decomposition: manager writes worker directives, marks own file `# Plan`, exits. Workers run in parallel. When all workers report `# Worker Report`, daemon re-invokes manager in aggregate mode

The daemon is defensive bash — it never exits on inner failures. The agent invocation is sandboxed; if it crashes or times out, the daemon logs it and keeps polling.

---

## Files

| Path | Purpose |
| --- | --- |
| `README.md` | This file |
| `CHANGELOG.md` | Package history |
| `PROTOCOL.md` | Agent contract → installed as `AGENT_TEAM_PROTOCOL.md` |
| `docs/SPINE_PRACTICES.md` | Multi-agent habits, context stack, drift avoidance |
| `docs/IMPROVEMENT_CHECKLIST.md` | Maintainer checklist |
| `templates/orchestration/` | `DECISIONS.md` + `ADR_TEMPLATE.md` scaffolds |
| `docs/PROGRAM_DELIVERY.md` | SDLC orchestration: phases, gates, conductor |
| `templates/program/` | REQ / phase ledger / policy stub scaffolds |
| `lib/roles.sh` | `SPINE_TEAM_ROLES` canonical list (installed to `scripts/roles.sh`) |
| `install.sh` | Bootstrap; supports `--pull-knowledge-only` |
| `lib/spine-migrate.py` | v1 disk layout → v2 SQLite + `snapshot.json` for the Control Center (`make db-migrate`) |
| `lib/costs-csv.sh` | Atomic legacy **`costs.csv` → 9 columns** (sourced by daemon; exercised by **`make selftest`**) |
| `lib/tests/test-*.sh` | Package selftests — run **`make selftest`** (after install: tests live under **`lib/tests/`**) |
| `lib/team-agent-daemon.sh` | Daemon (manager + worker); tiers, memory, timeouts, outcomes, costs |
| `lib/team.sh` | up / down / status / budget / learn / clean / doctor |
| `lib/team-clean.sh` | Footprint cleanup |
| `lib/seer-tick.sh` | Periodic seer nudge |
| `lib/file-lock.sh` | Atomic locks for parallel edits |
| `lib/dashboard.html` | Static dashboard → `dashboard/index.html` |
| `lib/role-prompts/<role>.md` | System prompts for every `SPINE_TEAM_ROLES` entry |
| `lib/playbook-defaults/*.md` | Seeds for `~/.spine-development/playbook/` |
| `recipes/*.md` | Directive templates → `.planning/orchestration/recipes/` |
| `docs/EXTENSIONS.md` | Roadmap vs shipped template features |

---

## Lineage

Early versions centered on five execution roles; **v1.4+** adds explicit program-delivery roles (**product, architect, conductor, UX, QA**) and a single **`engineer`** implementation lane with worker fan-out; **`engineering-*` squad folders were retired** as top-level roles (ADR-001). See **`CHANGELOG.md`** and **`.planning/orchestration/DECISIONS.md`** when installed.

The **orchestration spine** (`DECISIONS.md`, `MASTER_TODO.md`, `SESSION_HANDOFF.md`) lives under `.planning/orchestration/`. The agent team sits on top so parallel work stays tied to documented decisions.
