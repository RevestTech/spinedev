# Harness Lite — portable SDLC harness inside Spine

Portable layer for mid-development on **any repo** without Hub/Postgres.
Full Spine mode still uses `orchestrator/` + Hub; Harness Lite reuses the
same ADR-008 wave patterns with a lighter runtime.

**Design:** [`Handoff.md`](../../Handoff.md) · [`docs/adr/ADR-008-sprint-cleanup-methodology.md`](../../docs/adr/ADR-008-sprint-cleanup-methodology.md)

## Quick start (no Hub)

```bash
# From repo root (or any target project)
bash tools/harness/spine-harness init --project .
bash tools/harness/spine-harness start feature
bash tools/harness/spine-harness status --markdown
bash tools/harness/spine-harness stop
```

Via orchestrator CLI (when `spine` is on PATH):

```bash
spine harness init --project .
spine harness start feature
spine harness status --markdown
spine harness stop
```

## Layout

```
tools/harness/
├── spine-harness          # CLI entry
├── loop-bridge.sh         # Cursor /loop AGENT_LOOP_WAKE sentinels
├── lib/
│   ├── harness_common.sh  # shared shell helpers
│   ├── harness_state.py   # state.json I/O + status markdown
│   ├── verify_wave.py     # Phase 3 charter evals + QA
│   └── audit_wave.py      # Phase 1 deterministic scanners
├── skills/                # portable playbooks (ADR-008 3-phase)
│   ├── harness-orchestrator/
│   ├── harness-audit-wave/
│   ├── harness-fix-wave/
│   └── harness-verify-wave/
└── templates/.spine/harness/
    ├── state.schema.json
    └── findings.schema.json
```

After `init`, target project gets:

```
.spine/harness/
├── state.json       # mode, wave, gate rollup, active loops
├── findings/        # per-gate structured JSON from audits
├── reports/         # human-readable rollups
└── loops/           # PID + sentinel registry
```

## Commands

| Command | Purpose |
|---------|---------|
| `init [--project PATH] [--symlink-skills]` | Scaffold `.spine/harness/` |
| `start <mode>` | Start harness mode (`bootstrap` \| `feature` \| `sprint-close` \| `release-gate` \| `watch`) |
| `loop <interval> <mode>` | Fixed-schedule loop (e.g. `5m release-gate`) |
| `status [--markdown]` | Gate rollup from `state.json` |
| `audit [--gates docs,drift,...] [--markdown]` | Phase 1 — deterministic drift scanners |
| `verify [--roles qa,auditor] [--run-qa] [--markdown]` | Phase 3 — charter evals + optional QA |
| `stop` | Kill all harness loops/watchers |

## Modes

| Mode | When | Loop cadence |
|------|------|--------------|
| `bootstrap` | New project | One-shot waves, then `watch` |
| `feature` | Mid-development | Dynamic — wake on commit / PR update |
| `sprint-close` | End of sprint | Full ADR-008 3-phase fan-out |
| `release-gate` | Pre-deploy | Fixed loop every N minutes until gates green |
| `watch` | Passive drift | Long heartbeat; event watchers primary |

## Dogfood on SpineDevelopment

```bash
bash tools/harness/dogfood.sh
bash tools/harness/spine-harness status --markdown
bash tools/harness/spine-harness stop   # when done
```

Full-mode dogfood (Hub required): `bash tools/spine-on-spine.sh`

## Implementation status

| Phase | Deliverable | Status |
|-------|-------------|--------|
| P2 | CLI skeleton — init, start, stop, status | **Scaffolded** |
| P3 | Templates + state I/O | **Scaffolded** |
| P4 | Skills (orchestrator, audit/fix/verify waves) | **Scaffolded** |
| P5 | Loop bridge — fixed + event watchers | **Scaffolded** |
| P6 | Dogfood via `dogfood.sh` | **Done** |
| P7 | Charter evals in verify-wave | **Done** |
| P8 | Automated audit-wave scanners (`spine harness audit`) | **Done** |
| P9 | Charter eval fixtures for green verify-wave offline | **Done** |
| P10 | Loop-bridge tests + sprint-close auto-audit + sentinel log redirect | **Done** |
