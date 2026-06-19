# Handoff — Harness Lite mode (from HarnessMan research session)

> **Created:** 2026-06-18  
> **Purpose:** Pick up research and design from the HarnessMan conversation without re-discovering context.  
> **Status:** P2–P7 implemented — Harness Lite dogfood + verify-wave live.

---

## Resume prompt (paste into new Spine session)

```
Read Handoff.md at repo root, then docs/SPINE_MASTER.md §2–§4 and
docs/adr/ADR-008-sprint-cleanup-methodology.md.

We're implementing Harness Lite inside Spine (NOT a separate HarnessMan project).

Scaffold tools/harness/:
- CLI: spine harness init | start | stop | status
- .spine/harness/ artifact layout (state, findings, reports, loops)
- Portable skills: audit-wave, fix-wave, verify-wave (ADR-008 3-phase pattern)
- Loop bridge for Cursor /loop sentinels + git/CI event watchers
- Token-optimized subagent dispatch (cavecrew output contracts, 200–400 word caps)

Dogfood on SpineDevelopment first via tools/spine-on-spine.sh.
Update this Handoff.md when milestones land.
```

---

## Decision log

| Decision | Outcome |
|----------|---------|
| Build HarnessMan as separate project? | **No** — empty `Utilities/HarnessMan` abandoned |
| Where does portable SDLC harness live? | **Spine** — expand with **Harness Lite mode** |
| Full Spine vs Lite? | **Both** — same patterns, different runtime weight |
| HarnessMan folder | Ignore, delete, or symlink to `tools/harness/` later |

---

## Original goal (what we were trying to build)

A comprehensive harness for managing projects across the full SDLC:

- Coding, testing, documenting, security, compliance
- **Loops** extensively (fixed schedule, dynamic self-pace, event-driven)
- **Multi-agent teams** (parallel audit fan-out, file-partitioned fixes)
- **Skills** as portable playbooks
- **Token optimization** while doing all of the above
- **Any AI agent** — Cursor, Claude Code, Codex, etc.
- **Any project phase** — new build, mid-development, end-of-sprint
- **Background execution** — harness runs while foreground agent keeps working with the user

---

## Why Spine (not HarnessMan)

Spine already implements ~80% of this vision. Building HarnessMan separately would duplicate:

| HarnessMan concept | Spine equivalent |
|--------------------|------------------|
| SDLC phases | `plan/artifacts/sdlc-pipeline-default.yaml` (11 phases) |
| Orchestration + gates | `orchestrator/` — `router.sh`, `gate.sh`, `phases.yaml` |
| Background loops | `shared/runtime/phase_watcher.py`, `master_briefing.py` |
| Multi-agent teams | `engineer_squad.py`, `architect_swarm_runner.py`, security-audit recipe |
| Verify / security / compliance | `verify/` (TRON), `charter_evals/harness.py`, 12-layer agent audit |
| Sprint audit → fix → verify | ADR-008 + `.cursor/commands/sprint-cleanup.md` |
| Token optimization | Caveman skills (`skills-lock.json`), `bounded_retrieval.py` |
| Agent-agnostic eval | `verify/charter_evals/harness.py` — injects `role_callable`, no direct LLM |
| Phase entry at any stage | Phase machine + `recipes/` (`ship-feature.md`, `security-audit.md`, etc.) |

**Authoritative Spine vision:** `docs/SPINE_MASTER.md`

---

## Gap analysis — what Spine still needs (Harness Lite)

The gap is **portability and lightness**, not missing SDLC capability.

| Gap | Spine today | Harness Lite adds |
|-----|-------------|-------------------|
| Runtime weight | Golden path needs Hub + Postgres + containers (`hub-up.sh`) | Works on any repo without Hub |
| Agent portability | Hub-orchestrated dispatch | Portable skill pack + CLI any agent can invoke |
| Background while user works | `phase_watcher` inside Hub lifespan | Loop bridge + Cursor `/loop` sentinels |
| Automatic wave scheduling | `/sprint-cleanup` is manual command | `spine harness start watch` — scheduled/event waves |
| Unified harness artifacts | `.spine/work/` for platform runs | `.spine/harness/` for target-repo state |

---

## Proposed architecture — Harness Lite mode

### Two modes, one codebase

| Mode | When | Runtime |
|------|------|---------|
| **Full Spine** | Customer products via Hub | Hub + Postgres + phase watcher + decision queue |
| **Harness Lite** | Mid-dev on any repo | `spine harness start <mode>` + skills + loops, no Hub |

### Target layout (to build)

```
SpineDevelopment/
├── orchestrator/              # existing — full mode phase machine
├── verify/                    # existing — TRON + charter evals (both modes)
├── shared/runtime/            # existing — phase_watcher, role_runtime (full mode)
└── tools/harness/             # NEW — portable layer
    ├── spine-harness          # CLI entry (or subcommand of orchestrator/bin/spine)
    ├── loop-bridge.sh         # AGENT_LOOP_WAKE_* sentinels for Cursor /loop
    ├── skills/
    │   ├── harness-orchestrator/SKILL.md
    │   ├── harness-audit-wave/SKILL.md
    │   ├── harness-fix-wave/SKILL.md
    │   └── harness-verify-wave/SKILL.md
    └── templates/
        └── .spine/harness/
            ├── state.schema.json
            └── findings.schema.json
```

### Target project after `spine harness init`

```
any-repo/
├── .spine/harness/
│   ├── state.json             # mode, wave, gate rollup, active loops
│   ├── findings/              # per-gate structured JSON from audits
│   ├── reports/               # human-readable rollups
│   └── loops/                 # PID + sentinel registry
└── .cursor/skills/            # optional symlink to tools/harness/skills
```

### Foreground + background flow

```
┌─────────────────────────────────────────────────────────────┐
│  User + foreground agent (feature work, questions, etc.)    │
└───────────────────────────┬─────────────────────────────────┘
                            │ reads status, approves gates
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  .spine/harness/state.json + findings/ + reports/           │
└───────────────────────────┬─────────────────────────────────┘
                            │ tick / git push / CI complete
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  tools/harness/ loop-bridge — schedules wakes               │
└───────────────────────────┬─────────────────────────────────┘
                            │ AGENT_LOOP_WAKE_* sentinel
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  Background tick — audit-wave → fix-wave → verify-wave      │
│  (parallel cavecrew investigators, file-partitioned fixes)│
└─────────────────────────────────────────────────────────────┘
```

---

## Harness Lite modes

| Mode | When | Loop cadence |
|------|------|--------------|
| `bootstrap` | New project | One-shot waves, then `watch` |
| `feature` | Mid-development | Dynamic — wake on commit / PR update |
| `sprint-close` | End of sprint | Full ADR-008 3-phase fan-out |
| `release-gate` | Pre-deploy | Fixed loop every N minutes until gates green |
| `watch` | Passive drift detection | Long heartbeat (30m–2h), event watchers primary |

---

## Multi-agent orchestration — reuse ADR-008

Do not invent a new wave pattern. Wire Harness Lite to existing sprint-cleanup methodology.

### Phase 1 — Audit (read-only, parallel)

- 1 subagent per audit dimension: tests, security, docs, drift, compliance, code-quality
- Output: structured drift table (not prose)

```
| Severity | File:line | Claim | Actual | Recommendation |
```

- Cap: **400 words per agent report**
- Use `cavecrew-investigator` for locate/drift; vanilla Explore only when prose needed

### Phase 2 — Fix (write, file-partitioned)

- 1 agent = 1 exclusive file scope per wave
- HIGH/CRITICAL first
- Use `cavecrew-builder` for ≤2 file surgical edits

### Phase 3 — Verify (read-only, last)

- Run QA commands from target project's `pm.config.json` (or Spine defaults)
- Output: `docs/SPRINT-N-CLEANUP-REPORT.md` or `.spine/harness/reports/latest.md`
- 6-gate bar from `docs/QA-READINESS-STANDARD.md`

**References:**

- `docs/adr/ADR-008-sprint-cleanup-methodology.md`
- `.cursor/commands/sprint-cleanup.md`
- `docs/QA-READINESS-STANDARD.md`

---

## Token optimization rules (mandatory)

| Technique | Application |
|-----------|-------------|
| Compressed output contracts | All subagents — caveman-style (`path:line: 🔴 critical: …`) |
| 200–400 word prompt caps | Every subagent dispatch |
| Structured findings JSON | Phase 1 — main thread reads summary, not raw reports |
| Progressive disclosure | SKILL.md < 500 lines; details in reference.md |
| File-partitioned fix agents | No duplicate file context across agents |
| State summaries | `state.json` gate rollup — skip re-audit of green gates |
| Investigator before builder | Don't pass whole repo to edit agents |
| Parallel scout | 2–3 investigators in one message, different angles |

**Existing Spine token tooling:**

- `skills-lock.json` — cavecrew + caveman skills
- `shared/runtime/bounded_retrieval.py`
- `docs/ECC_BORROWS.md` — B4 bounded retrieval, B6 pass@k evals

---

## Loop strategy

| Loop type | Use | Implementation |
|-----------|-----|----------------|
| Fixed | Release gate polling (`every 5m`) | `while sleep; emit sentinel` in loop-bridge |
| Dynamic | Feature mode — self-paced | Agent sets next delay after each tick |
| Event | Wake on git push, CI done, file change | CLI watcher → `AGENT_LOOP_WAKE_<purpose>` |
| Heartbeat fallback | Idle periods | Long sleep to avoid token-burning empty ticks |

**Cursor /loop integration** (from loop skill):

```bash
while true; do
  sleep <seconds>
  echo 'AGENT_LOOP_WAKE_harness {"prompt":"<wave skill to run>"}'
done
```

Rules:

- Unique sentinel per loop purpose
- Run prompt once immediately; first tick after first sleep
- Track PIDs; `spine harness stop` kills cleanly
- On wake: read JSON payload, execute skill playbook, re-arm

---

## CLI surface (proposed)

```bash
spine harness init [--project PATH]     # scaffold .spine/harness/ + optional skill symlink
spine harness start <mode>              # bootstrap | feature | sprint-close | release-gate | watch
spine harness loop <interval> <mode>    # fixed schedule, e.g. 5m release-gate
spine harness status [--markdown]       # gate rollup; reuse orchestrator/cli/status_markdown patterns
spine harness stop                      # kill all harness loops/watchers
```

May live as subcommands under existing `orchestrator/bin/spine` rather than a separate binary.

---

## Implementation phases

| Phase | Deliverable | Status |
|-------|-------------|--------|
| P1 | This handoff + artifact JSON schemas | **Done** |
| P2 | `tools/harness/` CLI skeleton — init, start, stop, status | **Scaffolded** (2026-06-18) |
| P3 | `.spine/harness/` templates + state I/O | **Scaffolded** (2026-06-18) |
| P4 | Skills: orchestrator, audit-wave, fix-wave, verify-wave | **Scaffolded** (2026-06-18) |
| P5 | Loop bridge — fixed + event watchers + heartbeat | **Scaffolded** (2026-06-18) |
| P6 | Dogfood on SpineDevelopment via `tools/harness/dogfood.sh` | **Done** (2026-06-19) |
| P7 | Wire TRON/charter evals into verify-wave | **Done** (2026-06-19) |
| P8 | Automated audit-wave scanners + findings JSON | **Done** (2026-06-19) |
| P10 | Loop-bridge tests, sprint-close auto-audit, background sentinel log | **Done** (2026-06-19) |

---

## Dogfood path

Spine already has spine-on-spine tooling:

```bash
bash tools/hub-up.sh --rebuild          # optional for full-mode tests
bash tools/spine-on-spine.sh "Improve phase watcher"
bash tools/golden-path-walkthrough.sh "Automated founder walkthrough"
```

Harness Lite dogfood should run **without Hub** first:

```bash
bash tools/harness/dogfood.sh
# optional evidence: bash tools/harness/dogfood.sh --smoke  # needs Postgres/Docker
```

Or manually:

```bash
spine harness init --project .
spine harness start feature
spine harness status --markdown
```

Engineer output for spine-on-spine lands in `.spine/dogfood/<uuid>/` by default. See `docs/SPINE_MASTER.md` §1 and §7.

---

## Related existing docs (read order)

| Order | Doc | Why |
|-------|-----|-----|
| 1 | `docs/SPINE_MASTER.md` | Vision, component registry, gap matrix |
| 2 | `docs/adr/ADR-008-sprint-cleanup-methodology.md` | 3-phase wave pattern to reuse |
| 3 | `.cursor/commands/sprint-cleanup.md` | Operational sprint-cleanup command |
| 4 | `docs/QA-READINESS-STANDARD.md` | 6-gate QA bar |
| 5 | `docs/adr/ADR-005-parallel-subagent-orchestration.md` | Parallel agent rules |
| 6 | `docs/MASTER_TODO.md` | Current operational queue (separate from this initiative) |
| 7 | `docs/SESSION_HANDOFF.md` | Live session state (SPA hang, etc.) — may overlap dates |
| 8 | `recipes/security-audit.md` | Example parallel specialist recipe |
| 9 | `verify/charter_evals/harness.py` | Provider-agnostic eval contract |
| 10 | `skills-lock.json` | Locked caveman/cavecrew skill versions |

---

## What NOT to do

- Do not build `Utilities/HarnessMan` as a separate codebase
- Do not duplicate orchestrator phase machine — Lite mode calls same patterns, lighter runtime
- Do not require Hub/Postgres for Harness Lite bootstrap
- Do not mix audit and fix in the same wave (ADR-008 rule)
- Do not spawn write agents without exclusive file scope
- Do not extend v1/v2 file-bus patterns — retired per SPINE_MASTER §5

---

## Open questions (resolve during implementation)

1. **CLI namespace** — `spine harness` subcommand vs standalone `spine-harness` binary?
2. **Skill install** — symlink into `.cursor/skills/` vs copy vs `.agents/skills/`?
3. **TRON in Lite mode** — Lite uses offline charter eval stub (`spine harness verify`); full TRON `verify_audit` stays Hub/full-mode.
4. **HarnessMan symlink** — optional `Utilities/HarnessMan → tools/harness` for naming?

---

## Changelog

| Date | Change |
|------|--------|
| 2026-06-18 | Initial handoff from HarnessMan research session. Decision: expand Spine, not new project. |
| 2026-06-18 | P2–P5 scaffolded: `tools/harness/` CLI, schemas, skills, loop-bridge; wired `spine harness` subcommand. |
| 2026-06-19 | P6 dogfood: `tools/harness/dogfood.sh` on SpineDevelopment. |
| 2026-06-19 | P9: charter eval fixtures; `spine harness verify` defaults to `--callable fixture` — all 6 gates green offline. |
| 2026-06-19 | P8: `spine harness audit` — deterministic scanners; findings under `.spine/harness/findings/`. |
| 2026-06-19 | Dogfood `--smoke` fix: accept JUnit `failures="0"` (not only human `FAIL=0`); `init` refreshes `project_root`. |
| 2026-06-19 | P10: loop-bridge tests; sprint-close runs `spine harness audit`; background ticks log to `.spine/harness/loops/sentinel.log`. |
