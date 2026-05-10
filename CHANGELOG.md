# Changelog

## v1.3.4 — 2026-05-10

The **documentation, context, and portable template** pass: align multi-agent practice with how teams actually avoid drift, make the installer support **knowledge refresh** without touching daemons, and generalize role prompts for any project.

### Installer

- **`--pull-knowledge-only`** (alias `--knowledge-only`) — copies protocol, requirements, `recipes/`, `docs/` (practices + checklist + extensions), `templates/orchestration/` (ADR scaffolds), and `role-prompt.md` files. **Does not** replace `scripts/*.sh`, dashboard HTML, Makefile, notification hook, or modify `CLAUDE.md`. Skips host preflight.
- **Full install** now also copies **recipes** and **orchestration docs/templates** into `.planning/orchestration/` (same overwrite rules as other optional files — use `--force` to replace in-repo customized copies).
- **`err()` helper** added for consistent preflight failure messages.

### Documentation & scaffolding

- New **`docs/SPINE_PRACTICES.md`** — goals (parallel roles, drift control, durable context), context stack order, architect habits, trust boundary.
- New **`docs/IMPROVEMENT_CHECKLIST.md`** — maintainer backlog.
- New **`templates/orchestration/DECISIONS.md`** and **`ADR_TEMPLATE.md`** — append-only ADR log scaffold + standalone template.

### Portable role prompts & playbooks

- **`lib/role-prompts/operator.md`** and **`lib/role-prompts/datawright.md`** rewritten to be **repository-agnostic** (discover compose stack, inference endpoints, and tables from *this* project instead of hard-coded product names).
- **`lib/playbook-defaults/`** — minor wording generalized for the same reason.
- **`recipes/host-side-llm-pipeline.md`**, **`safe-db-script.md`**, **`investigate-bug.md`** — intro lines no longer cite a single codebase by name.

### Protocol & README

- **`PROTOCOL.md`** — §8 bring-up text fixed **(8 managers + 80 workers + watchdog)**; §7 playbook table extended with seer / auditor / memory; **§10** document revision bumped to **v1.3** with pointer to SpineDevelopment `CHANGELOG`; new **§10b** describing `--pull-knowledge-only`.
- **`README.md`** — version headline delegated to **`CHANGELOG`**; lineage and “what you get” tree updated for practices docs and in-repo recipes; install steps expanded.

### No daemon behavior change

Shell daemons unchanged in this release (same timeouts, hashing, watchdog integration). Adjust `INVOCATION_TIMEOUT_S` for long batch work per v1.3.3 playbook guidance until a future directive-level hint ships.

---

## v1.3.3 — 2026-05-08 (evening)

The "long-running batch jobs are different" pass. Triggered by a real datawright incident: an auto-labeling daemon was silently killed mid-run by the daemon's 25-minute `INVOCATION_TIMEOUT_S` while doing a ~46-minute full-archive labeling pass. Cursor exits cleanly under SIGTERM, so the daemon recorded `rc=0` even though the directive output was incomplete — a "successful failure" that's invisible without the watchdog.

### Operator playbook addition: long-running batch jobs

New section in `lib/playbook-defaults/operator.md` ("Long-running batch jobs (the 25-minute timeout trap)") with four lessons:

- **The 25-min `INVOCATION_TIMEOUT_S=1500` kills batch agent invocations.** Default is right for normal directives, wrong for full-archive labeling, large training runs, or per-doc enrichment of thousands of docs. Override per-process before kicking off: `INVOCATION_TIMEOUT_S=5400 nohup bash scripts/team-agent-daemon.sh <role> manager &`. Symptom of the trap: agent reports `rc=0` but the directive output is incomplete or absent.
- **A daemon killed silently is invisible without the watchdog.** Pre-v1.3 installs have no auto-restart. After bumping a timeout for batch work, also `bash scripts/team.sh status` periodically. v1.3+ projects: install `scripts/watchdog.sh` so dead managers get re-launched.
- **Design batch scripts to be resumable from checkpoint.** A 60-minute batch failing at the 55-min mark is wasted effort if the script can't resume. Pattern: per-N-row checkpoint markers, on script start read the marker and skip already-processed rows. The Kontract LABEL-AUTO-05 script had this and survived a daemon restart cleanly.
- **Schedule batch jobs around macOS sleep.** Laptop sleep mid-batch loses the host-side LLM, the worker container, and any host-side file-bus daemon. For overnight runs: `pmset -a sleep 0` (Mac plugged in, no sleep) before kicking off, restore after. Or run on a desktop / server.

### Validated by

The very incident that motivated this addition — a Kontract datawright daemon dying silently mid-run during LABEL-AUTO-05 (~1186 documents). The 25-min timeout assumption baked into v1.1 daemon hardening was correct for the v1.0 directive shape (one focused engineering task) but wrong for the v1.3 datawright batch shape. v1.3.3 captures the lesson so the next install starts knowing.

### No code changes

Pure playbook content. No daemon, executor, watchdog, or installer changes. Future v1.4 may consider a per-directive `## Tier hint: batch` mode that auto-bumps `INVOCATION_TIMEOUT_S` for the duration of the invocation, but that's a real change and goes through the v1.4 cycle.

---

## v1.3.2 — 2026-05-08 (later same day)

The "second-round dogfood lessons" pass. Added while running multiple parallel directives in the Kontract project (Capability B template auto-tag + LABEL-AUTO Qwen prompt design). Pure additive — no breaking changes.

### New recipe: `recipes/host-side-llm-pipeline.md`

Codifies the multi-step pattern for moving an LLM service from in-Docker (CPU-only on macOS) to host-side (Metal-accelerated) while keeping the rest of the stack containerized. The full Kontract Ollama-on-Metal migration took ~3 hours of debugging in real-time; the recipe makes it a 30-minute walkthrough for the next person. Ten concrete moves covering: platform check, install, hunting respawning watchdog apps, 0.0.0.0 binding, model cache locations (no iCloud!), `host.docker.internal` config, `--force-recreate` not `restart`, profile-gating the Docker fallback, volume cleanup. Variants for Linux/CUDA and production K8s.

### New playbook: `lib/playbook-defaults/datawright.md`

Default lessons for the data/ML role, seeded into `~/.spine-development/playbook/datawright/lessons.md` on install. Topics:

- Local LLM operation (Ollama, llama.cpp, vLLM): cold-start vs steady-state, `eval_duration` vs wall-clock, OCR text trimming, JSON validation patterns, temperature semantics
- Prompt design: vocabulary control, few-shot leverage, disambiguation rule placement, "uncertain" as a feature, prompt versioning
- Auto-labeling at scale: sample-first validation, incremental persistence, idempotency via prompt-version skipping, spot-checking disagreements
- Training + fine-tuning: minimum data thresholds, class imbalance, checkpoint storage paths (no iCloud), training run registry
- Cost discipline: budget extrapolation from samples, parallelization patterns (workers vs model instances vs vLLM batching)
- Reporting: aggregate metrics + raw samples, always include wall-clock + disk usage

### Installer change

`install.sh` now seeds three playbooks (engineer, operator, datawright) on fresh installs. Re-running install never overwrites user customizations.

### Validated by

Real-time hardening during a live multi-directive dogfood run — engineer Phase 1 + Phase 2 of Capability B and datawright LABEL-AUTO-03 + LABEL-AUTO-04 all running in parallel under the older Kontract team install. Lessons captured here are the ones that emerged in real-time as we wrote / ran / read agent reports.

---

## v1.3.1 — 2026-05-08

The "lessons from the first real dogfood run" pass. Pure additive — no breaking changes, no daemon/protocol updates. v1.3.1 takes the operational gotchas surfaced when running v1.3-style directives against a real Kontract project and bakes them into the template so future installs start with the wisdom built in.

### Pre-seeded playbook lessons (`lib/playbook-defaults/`)

New directory of default playbook lessons that the installer copies to `~/.spine-development/playbook/<role>/lessons.md` IF the user doesn't already have one. User customizations are never overwritten. Two seed files in this release:

- **engineer.md** — bash + psql gotchas (UUID command-tag capture, `ON CONFLICT` requires unique constraints, `--set ON_ERROR_STOP=on`, idempotency patterns, defensive bash, schema vs data separation, agent reporting style).
- **operator.md** — Docker on macOS (single-file mount inode bug, `restart` doesn't pick up env changes, `host.docker.internal` requires 0.0.0.0 binding, no Metal pass-through), respawning watchdog apps, compose hygiene, profile-gating opt-in services, iCloud-folder hostility to large local-only data.

These are battle-tested entries from real incidents (Kontract sponsor-archive linkage, Ollama Metal migration, dashboard mount-inode mystery). New projects starting fresh now inherit ~30 prevention rules instead of having to learn them by getting bitten.

### New recipe: `recipes/safe-db-script.md`

Codifies the script-hygiene patterns for any bash script that mutates a database. The cause of the 2026-05-08 sponsor-archive incident was a script that "looked right" — captured a UUID via `psql ... RETURNING id`, but the captured value also included `INSERT 0 1` on a separate line. The recipe enumerates seven required patterns:

1. `--set ON_ERROR_STOP=on` + check `$?` after every heredoc
2. Always extract returned values via shape-specific regex (UUID, integer, boolean)
3. `ON CONFLICT DO NOTHING` requires a real constraint — use SELECT-then-INSERT-if-empty otherwise
4. Idempotency MUST be tested by running the script twice
5. Pre-flight + post-flight counts as the cheapest correctness check
6. Quoting/escaping rules for shell-interpolated SQL (apostrophes break heredocs)
7. Defensive bash: no `set -e`, capture exit codes immediately, `set -uo pipefail` only

Engineer agents reading this recipe before writing a DB-interacting script avoid the entire class of bug.

### Installer change

`install.sh` now copies the playbook defaults during the cross-project playbook setup step (#4c). Idempotent — re-running install never overwrites user-edited lessons.

### Validated by

End-to-end dogfood through the v1.3 file-bus pattern in Kontract:
- Engineer daemon picked up a directive, executed a script, hit a bug, reported FAILED with clean diagnosis (no silent failure)
- Architect (chat) read the report, wrote a focused fix-it directive
- Engineer picked up the new directive, patched the script, cleaned up the orphaned data state, re-ran, verified, reported SUCCESS
- Two cycles, zero human babysitting on the actual fix work
- Surfaced the playbook entries above

This is the workflow we hoped the file-bus pattern would enable. v1.3.1 captures what we learned so v1.4 doesn't have to.

---

## v1.3 — 2026-05-06 (same evening)

The "what does my computer actually need" + "stop being Cursor-only" pass.

### Pluggable AI executor (`lib/executor.sh`)

The daemon no longer hardcodes Cursor. It writes the prompt to a temp file and dispatches via `executor.sh`, which auto-detects the first installed CLI from this priority order:

1. `cursor-agent` (Cursor Agent)
2. `cursor` (Cursor)
3. `claude` (Anthropic Claude Code CLI)
4. `aider` (Aider)
5. `opencode` (OpenCode)
6. `codex` (OpenAI Codex CLI)

Each CLI's invocation pattern is encoded in the executor — claude uses `-p`, aider uses `--message ... --yes`, the rest take prompt as argv[1]. Override the choice with `EXECUTOR_KIND=cursor|claude|aider|opencode|codex|generic` or point at any custom CLI with `EXECUTOR_CMD=/path/to/your-cli`. `EXECUTOR_KIND=generic` pipes the prompt to your command's stdin for full custom control.

### Preflight check (`lib/preflight.sh`)

`bash scripts/preflight.sh` (or `make team-preflight`, or `team.sh preflight`) reports:

- Platform (macOS / Linux / Linux-WSL / Windows-Git-Bash / unknown)
- Required tools: bash, git, curl, tar, find/awk/sed/grep, pgrep, shasum/sha256sum, ln
- Recommended tools: timeout/gtimeout, stat, du/wc, osascript (mac) / notify-send (linux)
- Notification env vars armed: NTFY_TOPIC, SLACK_WEBHOOK, DISCORD_WEBHOOK, PUSHOVER_USER+TOKEN, NOTIFY_EMAIL_TO
- AI CLI detection (cursor-agent, cursor, claude, aider, opencode, codex, EXECUTOR_CMD)
- Per-platform `apt install ...` / `brew install ...` hints for missing pieces
- Exit codes: 0 = good, 1 = required missing (or with --strict, optional missing also fails)
- `--quiet` flag emits a one-liner (`PREFLIGHT: OK (Linux, agent=claude)`) for cron / CI

`install.sh` now runs preflight as step 0 and refuses to install if required tools are missing.

### REQUIREMENTS.md

New top-level doc covering:

- Platform support matrix (macOS ✓, Linux ✓, Windows-via-WSL2 ✓, Windows-Git-Bash partial, native PowerShell not yet)
- Required tools with per-platform install commands
- Recommended tools and what you lose without each
- Notification channel setup
- Network requirements
- Resource footprint (idle vs active)
- Common troubleshooting

Installer copies it into the target project as `.planning/orchestration/AGENT_TEAM_REQUIREMENTS.md`.

### New `team.sh` subcommand and Make target

- `team.sh preflight [--quiet|--strict]` → calls preflight.sh
- `make team-preflight` → same

### Honest Windows answer

WSL2 is the supported Windows path today. Native PowerShell port is a real undertaking (~800–1000 lines) and remains a future TODO. Documented clearly in REQUIREMENTS.md.

---

## v1.2 — 2026-05-06 (later same day)

The "safe to leave it running while you sleep" pass. v1.1 made the team capable; v1.2 makes it accountable.

### Watchdog supervision (`lib/watchdog.sh`)

A single supervisor process auto-launched by `team up`. Each manager `touch`es `state/heartbeat` on every poll cycle (~8s). Watchdog wakes every 60s and checks heartbeat ages — if > 5 min stale, presumes manager dead and re-spawns it. Restarts fire a notification. Pid at `.planning/orchestration/agent-handoff/watchdog.pid`, log at `.../watchdog.log`. Tunables: `WATCHDOG_POLL_S`, `HEARTBEAT_TIMEOUT_S`.

### Architect approval gates

For directives that must NOT auto-run (prod deploys, schema migrations, destructive ops), declare `## Requires approval: yes` in the directive. Manager produces a Plan + Risks + Rollback document, marks the file `# Awaiting approval`, fires a notification, exits. Architect appends a `## Approved by: <name> @ <ts>` line to authorize. Daemon detects the new line, re-invokes manager in execute-after-approval mode. Plan must be executed as approved (no silent re-planning).

### Engineer rollback (`team.sh rollback engineer`)

Daemon takes a git snapshot before every engineer invocation: HEAD sha + `git stash create` of tracked changes + tarball of untracked files. All recorded to `teams/engineer/state/rollback-stack.csv`. Rollback command shows history, prompts for selection, runs `git reset --hard <head>` + `git stash apply <snapshot>` to restore. Snapshots are git-cheap (commit objects + tarballs); preserved until `team.sh clean nuclear`.

### Notification hook (`~/.spine-development/notify.sh`)

Default dispatcher installed to home dir. Channels: macOS notification (osascript), Slack webhook (`SLACK_WEBHOOK`), Discord webhook (`DISCORD_WEBHOOK`), email (`NOTIFY_EMAIL_TO`). Always appends to `~/.spine-development/notifications.log`. Customize freely — lives outside the repo. Daemon fires on: directive complete (success/failure), aggregate complete, awaiting-approval state, watchdog restart.

### Health check (`team.sh doctor` / `make team-doctor`)

Verifies: cursor-agent on PATH; each of 8 managers alive AND heartbeat fresh; watchdog up; notify hook installed; no cursor-agent runaway zombies (>16 = warn); team disk footprint (>100 MB = suggest clean). Exits non-zero if any check fails — usable in cron / CI.

### New Make targets

`team-doctor`, `team-rollback` added to the installer's Makefile snippet.

### PROTOCOL.md

Sections 16–20 added: approval gates, engineer rollback, watchdog, notifications, health check.

---

## v1.1 — 2026-05-06

The "make it production-grade" pass. v1 worked for one project (Kontract); v1.1 closes the gaps that surfaced after two weeks of real use.

### File hygiene (the "no junk left behind" pass)

The single most-requested cleanup. AI agents drop fixture files, scratch scripts, `.bak` backups, and debug experiments everywhere by default. v1.1 makes this disallowed and gives agents a sanctioned alternative.

- **Per-daemon scratch dir** at `teams/<role>/scratch/<slot>/` — wiped by the daemon on every new directive. Agents are told via the prompt to use it for any temp work.
- **Per-daemon OS temp dir** at `/tmp/spine-<role>-<slot>/` — same lifecycle, for tools that demand `/tmp`.
- **Forbidden file patterns** named in the prompt: `*.bak`, `*.orig`, `*~`, `*.swp`, `tmp_*`, `debug_*`, `scratch.*`, any backup directory.
- **`## Files touched` report contract** — every report (manager and worker) must end with a list of every file created/modified outside the team dir. Auditor cross-references against `git status`.
- **Engineer pre-flight** — engineer role-prompt now requires `git status --short` review and stray-file deletion before writing the report.
- **Auditor stray-file scan** — auditor role checks for forbidden patterns and unlisted changes during audits.
- **Daemon-enforced log rotation** — every poll cycle, any `.log` file > 5 MB is truncated to last 5 MB. Configurable via `LOG_MAX_BYTES`.
- **`scripts/team-clean.sh`** — new helper with modes: `scratch` / `logs` / `archive` / `all` (safe defaults — preserves directives, memory, costs); `costs` / `memory` / `nuclear` (destructive); `footprint` (read-only); `dry-run <mode>` for preview.
- **`bash scripts/team.sh clean <mode>`** — top-level subcommand that calls team-clean.sh.
- **`make team-clean` / `make team-footprint`** — Makefile targets installed by the installer.
- **PROTOCOL.md Section 15** — full file-hygiene contract documented.

### New roles (3)

- **seer** — read-only observability. Produces a single-page status across all manager directives. `lib/seer-tick.sh` writes "Refresh status" into `seer/directive.md` every 5 minutes when seer is idle, so the dashboard is never stale.
- **auditor** — verification. Re-runs claims made in another role's report (lint, tests, smoke endpoints, file existence) and writes a PASS/FAIL audit. Catches "tests pass" claims where tests didn't actually run.
- **memory** — spine maintenance. Owns `DECISIONS.md`, `SESSION_HANDOFF.md`, `MASTER_TODO.md` updates, and writes lessons into per-role `memory.md` and the cross-project playbook.

### Cost discipline (model tiering)

- Directives can declare `## Tier hint: low | medium | high`.
- Daemon parses the hint and injects tier guidance into the agent prompt: "Use cheapest competent model" / "default tier" / "most capable model — only when justified".
- Per-role defaults: planner/engineer → medium; researcher/operator/seer/auditor/memory → low; datawright → low (varies).
- Every invocation logs a row to `teams/<role>/state/costs.csv`: timestamp, role, mode, slot, phase, tier, wall-seconds, exit-code.
- New `make team-budget` aggregates costs across all roles and shows totals + per-tier breakdown.
- Planner role prompt now propagates tier discipline — when planners decompose into sub-directives, each sub-directive gets its own tier hint based on what the work actually needs.

### Memory

- Per-role `memory.md` file at `teams/<role>/memory.md` — read by the daemon on every invocation, prepended to the agent prompt.
- Memory role maintains spine docs (DECISIONS.md, SESSION_HANDOFF.md, MASTER_TODO.md).
- Cross-project playbook at `~/.spine-development/playbook/<role>/lessons.md` — lessons that apply to every project, not just this one.
- New `bash scripts/team.sh learn "lesson text" --role engineer` command appends to the playbook.

### Daemon hardening

- **Hard timeout**: default 25 minutes per invocation (override with `MAX_INVOCATION_S`). Uses `gtimeout`/`timeout` with `--kill-after`.
- **Stall detection**: if `AGENT_LOG` doesn't grow for 8 minutes (override with `STALL_THRESHOLD_S`), background watcher kills the process.
- **Tier guidance injection**: every prompt gets a `# COST GUIDANCE` block matching the directive's tier hint.
- **Memory injection**: every prompt gets a `# MEMORY (this role)` block with the contents of `memory.md`.
- **Defensive bash throughout**: inner failures never kill the daemon loop.

### Conflict resolution

- New `lib/file-lock.sh` provides atomic file locks via `ln -s` (fails if target exists). Workers can `acquire`, `release`, `holder` for any path before editing.
- Engineer role prompt now requires the manager to declare per-worker file scope when fanning out, and workers must take a lock before editing files in someone else's scope.

### Observability

- New `lib/dashboard.html` — self-contained HTML dashboard. Fetches each role's `directive.md`, classifies state (idle / directive / plan / report / worker-directive / report / error), refreshes every 8 seconds. No build, no server, no dependencies.
- Installer drops it at `.planning/orchestration/dashboard/index.html` — open in a browser or serve with `python3 -m http.server`.

### Recipes

Six ready-to-paste directive templates in `recipes/`:

- `postmortem.md` — incident postmortem orchestrated across researcher + engineer + operator + memory.
- `refactor-plan.md` — plan-before-doing refactor (researcher maps state, engineer designs strategies, architect approves before code).
- `dependency-bump.md` — safe dep upgrade (engineer, low tier, with stop conditions for major migrations).
- `security-audit.md` — five-surface audit (deps, secrets, auth, infra, logging).
- `performance-investigation.md` — measure-before-fix perf workflow.

### Protocol

`PROTOCOL.md` updated to v1.1. Sections 11 (cost discipline), 12 (memory), 13 (timeouts and stall detection), 14 (conflict resolution) are new. Section 1 expanded from 5 roles to 8.

### Installer

- `install.sh` now provisions all 8 roles, all 4 helper scripts, the dashboard, and the cross-project playbook directory.
- Idempotent — safe to re-run. Existing files are preserved unless `--force` is passed.

---

## v1.0 — 2026-04-22

Initial extraction from Kontract. Five-role topology (planner/researcher/engineer/operator/datawright) with the basic file-bus daemon pattern, manager + worker decomposition, and a thin install script.
