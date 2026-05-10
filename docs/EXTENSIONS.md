# Extensions — what to add as you grow

The base template ships the minimum that works: 5 managers, file-based message bus, parameterized daemon. These are real upgrades worth adding as your team usage scales.

Each section: **why you need it** → **rough sketch** → **how invasive**.

---

## 1. Cross-team aggregation for planner *(small, high value)*

**Why.** Planner currently spawns directives in OTHER managers' folders, then gets stuck in `# Plan` state because its own daemon only watches its own `workers/` dir. Manual aggregation by the architect today.

**Sketch.** Planner writes a `state/manifest.txt` listing the manager paths it spawned to. Daemon also watches those files. When all manifest entries flip to `# Report`, daemon re-invokes planner in aggregate mode.

**Invasiveness.** ~30 lines in `team-agent-daemon.sh`. Compatible with current planner role-prompt.

---

## 2. "Seer" / observability role *(small, high value)*

**Why.** When 5 managers + workers are running in parallel, the human can't track all of them. "What's everyone working on?" requires reading 50 files.

**Sketch.** Sixth role: `seer`. Read-only. Polls every 5 minutes. Reads each manager's `directive.md`, picks out current state and last activity from logs, writes a single-page status to `teams/seer/status.md` with traffic-light indicators per manager.

**Invasiveness.** New role + role-prompt. Reuses existing daemon. Add to `team.sh ROLES=()`.

---

## 3. Auditor / QA role *(medium, high value)*

**Why.** Reports sometimes claim things that didn't happen — "tests pass" when they weren't run, "deploy succeeded" when a container is still restarting. Self-reporting is unreliable.

**Sketch.** Seventh role: `auditor`. Runs after each manager produces a report. Reads the report, verifies claims by running independent checks (e.g. if engineer says "1075 tests pass", auditor runs `npm test` and counts). Writes pass/fail to `teams/<role>/audit.md`.

**Invasiveness.** New role + audit-trigger logic in daemon (poll for new reports, dispatch auditor). The audit prompt itself is the hard part — has to know what claims to verify per role.

---

## 4. "Memory" role *(medium, high value over time)*

**Why.** Spine docs (DECISIONS.md, SESSION_HANDOFF.md, MASTER_TODO.md) drift across sessions. Today the human keeps them coherent.

**Sketch.** Eighth role: `memory`. Triggered after each significant report. Reads the report + the spine docs. Updates: appends ADRs, updates SESSION_HANDOFF, marks tasks done in MASTER_TODO. Boundaries: only edits spine docs, never application code.

**Invasiveness.** New role + spine-touching prompt. Worth doing once you have ≥3 sessions of state to maintain.

---

## 5. Per-worker timeouts enforced by daemon *(small, mostly bulletproofing)*

**Why.** Worker hangs on a slow inference for 30+ minutes, blocking manager aggregation. Currently no enforcement.

**Sketch.** Daemon tracks worker start time (file mtime when it flipped to `# Worker Directive`). If still in directive state >20 min, daemon writes a `# Worker Report — TIMEOUT` itself, freeing manager aggregation.

**Invasiveness.** ~15 lines in worker-mode daemon loop.

---

## 6. Heartbeat / liveness *(small, occasional save)*

**Why.** cursor-agent rarely just hangs (we saw it once during the auto-label work). Right now the daemon waits forever.

**Sketch.** Daemon kills the cursor-agent process if no stdout activity for N minutes (default 10). Re-invokes from scratch.

**Invasiveness.** Simpler than #5. Use `timeout` command around cursor-agent invocation.

---

## 7. Cost / budget tracking *(medium, becomes critical at scale)*

**Why.** Local Qwen is "free" but costs CPU/RAM. If you wire in cloud LLMs (Claude, GPT-4) per-team, runaway loops can become expensive fast.

**Sketch.** Each agent invocation logs `<role> <tokens> <wall_time>` to a daily CSV. A `team budget` subcommand sums it. Optional hard cap that triggers daemon pause.

**Invasiveness.** Logging is one line. Hard caps are a few more.

---

## 8. Conflict resolution for shared files *(medium, critical at high parallelism)*

**Why.** If two engineer workers both want to edit `src/api/route.ts`, currently no protection. Last-write-wins, possibly garbled.

**Sketch.** Workers acquire a file-lock before edit (`.lock` file with their slot id, atomic create). Manager decomposition has to ensure non-overlapping file sets per worker.

**Invasiveness.** File-lock helper in daemon. Manager prompt update to declare file scope upfront.

---

## 9. Web dashboard *(big, optional but elegant)*

**Why.** "What's everyone doing?" answered visually instead of by tail-f.

**Sketch.** Tiny static HTML dashboard served locally. Reads `teams/*/directive.md` headers + recent log lines. Auto-refreshes on an interval. Shows: per-manager state (idle / executing / planning / aggregating), current directive title, recent log excerpt, worker count. A fuller UI with drawers and host metrics belongs in an optional Tier-1 uplift (pair HTML with read-only endpoints if adding live actions).

**Invasiveness.** Standalone — doesn't change protocol. ~200 lines of HTML+JS+a small Python or Node server.

---

## 10. Cross-project knowledge sharing *(big, becomes valuable when you have ≥3 projects)*

**Why.** Lessons learned in one project (e.g. "OLLAMA_URL=localhost is a footgun") are lost when you start the next.

**Sketch.** A shared directory at `~/.spine-development/playbook/` with role-keyed lessons (`engineer/lessons.md`, `operator/gotchas.md`). Each role's role-prompt includes "Before starting, read your role's playbook entries from `~/.spine-development/playbook/<role>/`". Update with `team learn "<lesson>"`.

**Invasiveness.** Just a convention + a tiny CLI. The role-prompts already get loaded at invocation time, so plumbing is trivial.

---

## 11. Auto-summarization for the architect *(small, life-improving)*

**Why.** Reports get long. Reading 500 lines of structured findings before deciding next move is friction.

**Sketch.** Each manager appends a `## TL;DR` section (≤ 5 lines) at the top of every report. Enforced via role-prompt + maybe a post-hook that complains if missing.

**Invasiveness.** Pure prompt-engineering. No code change.

---

## 12. Pattern library of recipes *(small, compounds over time)*

**Why.** This template ships 3 recipes. After a few projects you'll have 20.

**Sketch.** Build out `recipes/` with templates for: postmortem, dependency-bump, security-audit, performance-investigation, refactor-plan, hiring-screen, etc. Each is a copy-paste-ready directive shape that produces consistent reports.

**Invasiveness.** Just markdown. Add as you encounter new shapes.

---

## Suggested order of adoption

1. Now: ship the base template
2. After first multi-session use: add #1 (planner aggregation) and #11 (TL;DR sections)
3. After 5+ runs: add #2 (seer) — the human is now the bottleneck, not the agents
4. After first "agent claimed X but X was false" incident: add #3 (auditor)
5. After 3+ projects: add #10 (cross-project knowledge)
6. When budget bites: add #7 (cost tracking)
7. Whenever it actually causes pain: #5, #6, #8

Don't pre-build any of these. Real usage reveals which gap matters first.
