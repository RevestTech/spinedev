# Agent Team Protocol

The contract every agent in the team follows. Drop this file at `.planning/orchestration/AGENT_TEAM_PROTOCOL.md` in any project that adopts the pattern. It is the source of truth — every agent reads it before participating.

---

## 1. The team

Eight **manager** roles. Each has a daemon polling its own directive file. Each can spawn up to **10 worker** agents for parallel sub-work. Workers do NOT spawn further — the tree is exactly two levels deep.

### Core five (the workers of work)
| Role | Authority | Use for |
|---|---|---|
| `planner` | Multi-specialist orchestration. Writes directives to other managers. | High-level goals that span multiple specialists |
| `researcher` | Read-only — code reads, log greps, DB queries (SELECT only), web searches | Investigation, audit, diagnosis |
| `engineer` | Code/config edits, builds, tests | Implementing fixes, refactors, new features |
| `operator` | Docker, compose, deploy, env config, daemon control | Bringing services up/down, recreating containers |
| `datawright` | Inference at scale, training, batch data, OCR backfills, eval scoring | Anything that runs models over many documents |

### Meta-three (the workers of governance)
| Role | Authority | Use for |
|---|---|---|
| `seer` | Read-only across all team state. Writes a single status page. | Observability — "what's everyone doing?" without reading 50 files |
| `auditor` | Read-only verification. Re-runs other roles' claimed checks. | Catching reports that claimed things didn't actually happen |
| `memory` | Edits spine docs (DECISIONS, MASTER_TODO, SESSION_HANDOFF) and per-role memory files | Keeping knowledge coherent across sessions |

The **architect** sits above the planner — typically the human, or the assistant the human is talking to. The architect doesn't have a daemon; it's the human-facing layer.

---

## 2. File layout (per role)

```
.planning/orchestration/agent-handoff/teams/<role>/
├── directive.md          ← manager input/output (replaced with report when done)
├── role-prompt.md        ← system-style prompt loaded at agent invocation
├── workers/              ← worker directives (manager writes, workers reply in same files)
│   ├── 01-directive.md
│   └── ... up to 10
├── state/
│   ├── manager-LAST_HASH
│   ├── 01-LAST_HASH ... up to 10
│   └── costs.csv         ← cost log (timestamp, role, mode, slot, phase, tier, wall_s, rc)
├── scratch/              ← ephemeral per-invocation workspace (wiped on each new directive)
│   ├── manager/
│   └── 01/ ... up to 10
├── log/
│   ├── daemon.log
│   └── agent.log         ← cursor-agent stdout/stderr per invocation
└── memory.md             ← per-role lessons, prepended to every prompt
```

`/tmp/spine-<role>-<mgr|NN>/` is also created per daemon and wiped on every new directive — agents get an OS-level temp dir with the same lifecycle as `scratch/`.

---

## 3. Lifecycle of a directive

### 3a. Architect → manager
Architect writes a file to `teams/<role>/directive.md`. The first line MUST start with `# Directive`. Required sections:

- A clear goal statement
- Numbered tasks
- Hard constraints (e.g. "diagnosis only", "do not restart containers")
- Expected report format
- Optional: timeout guideline

### 3b. Manager picks up
Within 8s of the file appearing, the manager's daemon detects the new hash and invokes `cursor-agent` with the directive + role-prompt loaded.

The agent decides:
- **Single-shot**: small enough to do in one cursor-agent invocation. Execute, replace `directive.md` with `# Report`. Done.
- **Decompose**: split into N ≤ 10 worker tasks. Write each to `workers/NN-directive.md`. Then exit. Daemon will re-invoke when workers all finish.

A decomposed manager invocation MUST:
1. Write all worker directives in one batch
2. Write a `# Plan` file at `directive.md` (NOT `# Directive`, NOT `# Report`) signaling "I've spawned workers, waiting"
3. Exit cleanly. Do not poll inline.

### 3c. Workers execute
Each worker has its own daemon polling `workers/NN-directive.md`. When a worker file appears starting with `# Worker Directive`, the worker daemon invokes cursor-agent with the worker's content and the same role's role-prompt.

The worker executes its slice and replaces its file's content with `# Worker Report` followed by structured output. Then exits.

If a worker times out or fails, its file should still get replaced with `# Worker Report` containing failure details — never leave the file as a directive.

### 3d. Manager aggregates
The manager's daemon, while polling `directive.md`, also watches `workers/*.md`. When **all** worker files start with `# Worker Report`, the daemon re-invokes the manager's cursor-agent with a special "aggregate" prompt:

> "Your workers have all reported. Read each worker file. Synthesize their findings into a single manager report. Replace `directive.md` with `# Report — <task>` containing the synthesis. Move worker files to `workers/archive/<timestamp>/`."

After aggregation, the manager is idle until the next directive lands.

### 3e. Failure modes
- **Worker hangs** (>20 min default): manager's aggregate phase forcibly replaces stuck worker file with `# Worker Report` marking timeout
- **Worker crashes** (cursor-agent rc≠0): daemon retries up to 2 times before marking failed
- **Manager itself crashes**: daemon survives (defensive bash); next directive picked up cleanly
- **Stale state**: `team status` shows current state; `team down && team up` is the nuclear reset

---

## 4. Role boundaries (hard rules)

These are enforced by each role's `role-prompt.md`. Crossing them = the agent should refuse and report a boundary violation.

### `planner`
- Write directives to other managers' files
- Run light status commands
- May NOT directly edit code, run shell beyond status checks, or modify infrastructure

### `researcher`
- READ-ONLY: filesystem, DB (SELECT only), logs, web
- May NOT: edit files, INSERT/UPDATE/DELETE, restart anything

### `engineer`
- May edit source code, run lint + test, build
- Must run quality gates after non-trivial changes
- May NOT edit immutable historical records, binary files, or change infra

### `operator`
- May docker compose, edit env, restart containers, manage daemons
- May NOT edit application source code

### `datawright`
- May call inference endpoints at scale, run training scripts, bulk-update ML output tables
- May NOT edit application source code, change compose, restart services

---

## 5. Communication patterns

### Manager → manager
Only `planner` writes directly to other managers' directives. Other managers escalate through planner if they need cross-team coordination.

### Manager → architect
Architect reads the manager's report when it lands. Architect is the only consumer of raw final reports — synthesis bubbles up.

### Worker → worker
Workers within the same manager do NOT communicate directly. Dependencies are the manager's job to serialize.

### Inter-process safety
- All file writes are atomic-via-rename (`write to .tmp, mv to final`) — daemons never see half-written files
- Hash-based change detection (`shasum -a 256`) — daemons re-process only when content actually changes
- `state/<role>-LAST_HASH` files are the source of truth for "what have I already processed"

---

## 6. Worker decomposition guidance

When a manager fans out:
- **Embarrassingly parallel** — each worker handles disjoint input
- **Roughly balanced** — similar slice sizes
- **Independently reportable** — each worker's output makes sense alone
- **Bounded I/O** — if a service can't handle 10 concurrent calls, serialize or spawn fewer

Default cap: 10 workers. Override only with explicit architect approval.

---

## 7. Calling on the team — the architect's playbook

| Task shape | First directive |
|---|---|
| "What's the state of X?" | `researcher` |
| "Fix Y in code" | `engineer` |
| "Restart / deploy / config Z" | `operator` |
| "Run inference / train / process N items" | `datawright` |
| "Ship feature W end-to-end" | `planner` |
| Cross-team status / digest | `seer` |
| Independent verification of another role's report | `auditor` |
| Consolidate DECISIONS, MASTER_TODO, SESSION_HANDOFF, memory | `memory` |

For multi-step workflows, prefer `planner`.

---

## 8. Bring-up and shutdown

```bash
make team-up        # starts 8 manager daemons + 80 worker slots + watchdog
make team-status    # what's each manager doing
make team-down      # clean shutdown
```

---

## 9. Observability

```bash
# All daemons
tail -f .planning/orchestration/agent-handoff/teams/*/log/daemon.log

# A specific role
tail -f .planning/orchestration/agent-handoff/teams/datawright/log/{daemon,agent}.log
```

`make team-status` aggregates current directives + worker counts across all roles.

---

## 10. Versioning

This document revision is **v1.3** (tracks the SpineDevelopment template package — see `CHANGELOG.md` on the SpineDevelopment repo when matching installed behavior to release notes).

Changes **go through ADR** for project-specific adaptations. Agents should also read `.planning/orchestration/DECISIONS.md` when it exists — any ADR there may narrow or supersede generic protocol text **for this repository only**.

---

## 10b. Updating template knowledge without reinstalling scripts

Installed projects may pick up refreshed recipes, protocol text, ADR scaffolding, practice docs, and role prompts **without** replacing `scripts/*.sh` or the dashboard HTML:

```bash
bash install.sh . --pull-knowledge-only
```

Use `--force` with that flag if you intentionally want to overwrite in-repo recipes or role prompts already customized on disk.

---

## 11. Cost discipline (model tiering)

Every agent invocation has a tier hint. The daemon parses it from the directive's `## Tier hint` line and surfaces it to the agent so the agent self-selects the cheapest capable model. **This is mandatory** — runaway use of high-tier models is the most likely way for this system to blow your bill.

### Tiers
- **`low`** — cheapest model that can do the job. Haiku-class, GPT-4o-mini-class, Qwen-7B locally. Use for: read-only file work, log greps, status checks, summaries, mechanical edits, batch dispatch, audits, observability, memory consolidation.
- **`medium`** *(default if no hint)* — mid-tier. Sonnet-class, GPT-4o, Qwen-72B, etc. Use for: code edits with reasoning, prompt iteration, narrow architectural decisions, planner orchestration.
- **`high`** — top tier. Opus, GPT-5, Claude 4.5+. Use for: cross-cutting refactors, novel architecture, untangling subtle bugs across modules.

### Per-role defaults (when no `## Tier hint` is provided)
| Role | Default tier |
|---|---|
| seer | low |
| auditor | low |
| memory | low |
| operator | low |
| researcher | low |
| datawright | low |
| engineer | medium |
| planner | medium |

### Architect's responsibility
When you write a directive, set `## Tier hint: low/medium/high` explicitly if the work is non-default for the role. Planners must propagate or override the tier when spawning sub-directives. Cost discipline is upstream — fix it at the directive, not at the model invocation.

### Logging
Every invocation appends to `teams/<role>/state/costs.csv`: timestamp, role, mode, slot, phase, tier, wall_seconds, exit_code. Run `bash scripts/team.sh budget` to see totals + per-tier breakdown.

---

## 12. Memory (per-role, per-project, cross-project)

Three memory layers, in increasing scope:

### 12a. Per-role memory (`teams/<role>/memory.md`)
Loaded into every invocation of that role. Lives in this project. Content: durable lessons specific to this codebase ("OLLAMA_URL=localhost is wrong inside containers", "schema.ts says serial but DB is uuid").

Each agent appends to it before exit if it found something worth saving. The `memory` manager periodically prunes / consolidates.

### 12b. Spine docs (`.planning/orchestration/`)
- `DECISIONS.md` — ADRs, architectural decisions
- `MASTER_TODO.md` — task queue
- `SESSION_HANDOFF.md` — current state preamble for fresh sessions

The `memory` manager keeps these coherent across sessions by reading completed reports and updating the docs.

### 12c. Cross-project playbook (`~/.spine-development/playbook/<role>/lessons.md`)
Shared across every project that uses this template. Use for: lessons that generalize ("when the model's prompt doesn't match the DB taxonomy, the model echoes the prompt's wrong vocabulary"). Append with `bash scripts/team.sh learn "..." --role <role>`.

This is loaded INTO `teams/<role>/memory.md` on `team up` (the install hook concatenates if present).

---

## 13. Timeouts and stall detection

The daemon enforces two safety limits per invocation:

- **Hard timeout**: 25 minutes (configurable via `INVOCATION_TIMEOUT_S` env var). After this, the daemon kills the cursor-agent process. The directive file is left in whatever state it was in; you'll see a partial report or a lingering `# Plan` if it was decomposing.
- **Stall detection**: 8 minutes (configurable via `STALL_THRESHOLD_S`). If the agent's stdout log doesn't grow for this long, the daemon assumes the agent hung and kills it.

Either way, the daemon survives. Next directive picks up cleanly.

---

## 14. Conflict resolution for shared files

If two engineer workers both edit the same source file, last-write-wins corrupts the diff. The protocol requires the **manager** to declare per-worker file scope upfront when decomposing. Workers must respect that declared scope.

The simple version (built-in): managers split work by file. Workers stay within their declared file set.

The robust version (also built-in): `scripts/file-lock.sh acquire <path>` — atomic via `ln -s`, returns failure if the lock is already held. Workers can use this before editing files outside their primary scope.

---

## 15. File hygiene (don't leave junk behind)

AI agents are sloppy with files by default. They drop fixture data, scratch scripts, `.bak` copies, debug experiments, and one-off test files all over the repo. This protocol makes that disallowed and gives agents a sanctioned place to be sloppy.

### 15a. Sanctioned scratch space (per invocation)

Two ephemeral dirs exist for every running daemon:

- **`teams/<role>/scratch/<manager|NN>/`** — repo-local scratch dir
- **`/tmp/spine-<role>-<mgr|NN>/`** — OS-level temp dir (for tools that demand `/tmp`)

Both are wiped by the daemon on every NEW directive. Agents are TOLD this in their prompt. Anything written there is guaranteed to be cleaned up — agents should default to using these for any temp work, intermediate output, downloaded fixtures, generated test data, etc.

### 15b. Forbidden file patterns

Agents must NOT leave any of these behind in the repo:

- `*.bak`, `*.orig`, `*~`, `*.swp`, `*.swo`, `*.tmp` — editor/diff residue
- `tmp_*.py`, `debug_*.sh`, `test_one_off.*`, `scratch.*` — one-shot scripts
- `node_modules.bak/`, `dist.bak/`, `.venv-backup/` — backup directories
- Random files dropped at repo root that aren't part of the directive's deliverable

If an agent creates one of these, it must delete it before reporting. The auditor role can be invoked to verify.

### 15c. The "Files touched" report contract

Every `# Report` and `# Worker Report` MUST include a `## Files touched` section listing every file the agent created or modified OUTSIDE of the role's own team dir. Format:

```
## Files touched
- src/api/foo.ts (modified — added new route)
- tests/unit/foo.test.ts (created — covers new route)
- migrations/0042_add_foo.sql (created — schema for foo table)
```

If the list is empty, write `## Files touched\n- (none)`. The auditor cross-references this against `git status` / `git diff` output to catch omissions.

### 15d. Engineer-specific pre-flight

Before writing `# Report`, an engineer agent MUST:

1. Run `git status --short` (or equivalent for non-git repos) and review every untracked or modified path
2. Delete anything that isn't intentional
3. List every remaining changed file in the report's "Files touched" section

### 15e. Periodic cleanup (architect-invokable)

The architect can run `bash scripts/team.sh clean <mode>` at any time:

| Mode | Action |
|---|---|
| `scratch` | Wipe per-role scratch dirs and `/tmp/spine-*` (always safe) |
| `logs` | Truncate `.log` files larger than 5 MB |
| `archive` | Prune `workers/archive/` to last 50 batches per role |
| `all` | scratch + logs + archive (recommended periodic cleanup) |
| `costs` | Remove `costs.csv` (loses cost history — destructive) |
| `memory` | Remove `memory.md` (loses learned lessons — destructive) |
| `nuclear` | Everything except current `directive.md` files |
| `footprint` | Show on-disk usage per role |

The daemon also rotates logs internally (cap of 5 MB per log) on every poll cycle, so even without explicit cleanup the team's footprint can't grow unboundedly.

### 15f. What the daemon guarantees automatically

You don't have to remember any of this — the daemon does it for you:

1. Every new directive → `scratch/` and `/tmp/spine-*/` for that daemon are wiped
2. Every poll cycle → logs > 5 MB are truncated to last 5 MB
3. Cost CSV grows only by one row per invocation (text — won't bloat)
4. Worker archive grows by one timestamped dir per aggregate cycle, prune via `clean archive`

In short: scratch is safe, logs are bounded, archive is pruneable, and every report must declare what it touched. Sloppy file behavior becomes detectable instead of accumulating silently.


---

## 16. Architect approval gates

For directives that should NEVER auto-run while you're asleep (production deploys, schema migrations, destructive ops, anything that runs `rm -rf` or `docker compose down -v`), declare an approval gate:

```markdown
# Directive — <task>

## Tier hint: medium
## Requires approval: yes

<the directive body>
```

When the manager picks up a directive flagged `## Requires approval: yes`, it does NOT execute. Instead it:

1. Analyzes the directive and produces a concrete plan.
2. Replaces `directive.md` with `# Awaiting approval — <task>` containing:
   - `## Plan` — numbered actions, file paths, commands, expected effects
   - `## Risks` — what could go wrong, with severity
   - `## Rollback` — how to undo if something breaks
   - `## Original directive` — the architect's directive verbatim
3. Fires a notification ("[role] AWAITING APPROVAL").
4. Exits.

The architect reviews the plan and authorizes by appending a single line to the file:

```markdown
## Approved by: khash @ 2026-05-07
```

Within 8 seconds the daemon detects the new line and re-invokes the manager in execute-after-approval mode. The manager executes the plan as approved (it must NOT silently re-plan; if the plan turned out wrong, it should write `# Report — STOPPED: plan needs revision` and explain).

If you change your mind, replace the file with a fresh `# Directive — ...` to start over, or with `# Report — STOPPED: cancelled by architect` to abandon.

---

## 17. Engineer rollback

For every directive picked up by the engineer manager (or worker), the daemon takes a git snapshot before invoking the agent:

- HEAD sha
- Tracked changes via `git stash create` (a snapshot commit object that doesn't touch the stash list)
- Untracked files via tarball at `teams/engineer/state/rollback-snapshots/`

These are appended to `teams/engineer/state/rollback-stack.csv`. To roll back:

```bash
bash scripts/team.sh rollback engineer
# or: make team-rollback
```

The command shows the snapshot history (most recent first) and prompts you to pick one. On confirmation, it runs `git reset --hard <head>` then `git stash apply <snapshot>`, restoring the working tree to its pre-engineer state.

Snapshots persist until you `team.sh clean nuclear` — they're cheap (git objects + small tarballs) and history is more valuable than disk.

Rollback is engineer-only. Operator/datawright/etc don't modify code; their effects are tracked elsewhere (containers, databases, model artifacts).

---

## 18. Watchdog supervision

A single `watchdog.sh` process supervises all 8 manager daemons:

- Each manager `touch`es `teams/<role>/state/heartbeat` on every poll cycle (~ every 8 seconds).
- The watchdog wakes every 60s and checks each heartbeat's mtime.
- If `> 300s` old (5 min default, configurable via `HEARTBEAT_TIMEOUT_S`), the watchdog presumes the manager dead and re-spawns it.
- A restart fires a notification ("[watchdog] <role> manager auto-restarted").

The watchdog is started automatically by `team up` and stopped by `team down`. Its pid lives at `.planning/orchestration/agent-handoff/watchdog.pid` and its log at `.../watchdog.log`.

Workers are NOT directly supervised — the manager re-spawns workers as needed via the file bus. If a manager's worker dies, the manager re-issues a worker directive on the next aggregate cycle.

---

## 19. Notifications

The daemon calls `~/.spine-development/notify.sh "<title>" "<body>"` on these events:

- A manager directive completes (success / failure / awaiting-approval)
- An aggregate completes
- An approved plan completes
- The watchdog restarts a dead manager

The default `notify.sh` (installed by `install.sh`) supports four channels:

- macOS notification (via `osascript`) — always on if available
- Slack webhook — set `SLACK_WEBHOOK` env var
- Discord webhook — set `DISCORD_WEBHOOK` env var
- Email — set `NOTIFY_EMAIL_TO` env var (uses `mail` CLI)

All events are also appended to `~/.spine-development/notifications.log` regardless of channel availability — that log is your single source of truth for what completed and when.

The notification script lives in your home dir (not the repo) so you can customize freely without re-running install. The daemon never blocks on notification dispatch; failures are silent.

---

## 20. Health check (`team doctor`)

```bash
bash scripts/team.sh doctor
# or: make team-doctor
```

Verifies:
1. `cursor-agent` (or `cursor`) on PATH
2. Each of 8 managers: process alive AND heartbeat < 5 min old
3. Watchdog process alive
4. Notification hook installed
5. No runaway cursor-agent zombie processes (> 16 = warn)
6. Total team disk footprint (> 100 MB = suggest `clean all`)

Exits non-zero if any check fails — usable in CI / cron.

