# PM dashboard — Spine integration

**Ticket:** SPINE-011  
**Hold:** H-PM (Sprint 1 — external fc-sdlc service path)  
**Status:** Config wired in-repo; live `:5190` service optional for customer ship

Spine ships **fc-sdlc process artifacts** (`todo/`, gates, traceability) and a **repo-local `pm.config.json`** so the FutureCapital Project Manager service can render a live dashboard when that sibling repo is present. The Hub product does **not** bundle the PM service; agents can still run SDLC loops via **Harness Lite** when PM is unavailable.

---

## What is wired in this repo

| Artifact | Purpose |
|----------|---------|
| [`pm.config.json`](../pm.config.json) | PM service config — port, backlog sources, QA command, gate thresholds |
| [`todo/BACKLOG.md`](../todo/BACKLOG.md) | Canonical backlog (PM reads; not Jira/Linear) |
| [`todo/gates/G*.md`](../todo/gates/) | Gate sign-off tables |
| [`docs/fc-sdlc-STATUS.md`](./fc-sdlc-STATUS.md) | fc-sdlc execution state (process SoT alongside [`docs/STATUS.md`](./STATUS.md)) |
| [`package.json`](../package.json) `pm:*` scripts | Dev/start/check-in wrappers → external fc-sdlc tree |
| [`.cursor/rules/project-manager.mdc`](../.cursor/rules/project-manager.mdc) | Agent check-in protocol when PM is running |

**Dashboard URL (when service is up):** http://localhost:5190 (`/api/dashboard`, SSE updates)

---

## `pm.config.json` (repo root)

The PM service mounts the workspace and reads markdown sources defined here.

| Field | Value | Notes |
|-------|-------|-------|
| `port` | `5190` | Binds `127.0.0.1:5190` by default |
| `sources.backlog` | `todo/BACKLOG.md` | Primary backlog |
| `sources.backlogAliases` | `todo/MasterTodo.md` | Legacy alias |
| `sources.gatesGlob` | `todo/gates/G*.md` | Gate files |
| `sources.traceability` | `todo/testing/traceability-matrix.md` | REQ ↔ test mapping |
| `sources.status` | `docs/fc-sdlc-STATUS.md` | Sprint / fc-sdlc headline |
| `sources.currentSprintRegex` | `Sprint\s+(\d+(?:\.\d+)?)` | Parsed from status doc |
| `parsers.backlogFormat` | `wave-table` | Wave/phase table in BACKLOG |
| `parsers.ticketIdPattern` | `[A-Z]{2,5}-\d{3,4}` | e.g. `SPINE-011` |
| `qa.command` | `tools/fc-sdlc/ci-test-full.sh` | Evidenced QA sweep for dashboard |
| `qa.intervalMinutes` | `2` | Auto QA poll when `PM_QA_AUTO=true` |
| `gates.g5Thresholds` | P0/API/data ≥ 90%, `fakeBrokenMax: 0` | Release-ready rollup |

Full schema reference: `$schema` in `pm.config.json` (`fc-sdlc-pm-config.v1.json`).

---

## External fc-sdlc PM service (not in Spine tree)

All `npm run pm:*` scripts resolve paths **relative to the Spine repo root**:

```
../../FutureCapital/Engineering/SDLC/
├── services/project-manager/   # pm:dev, pm:start, pm:up
└── scripts/
    ├── pm-checkin.mjs          # pm:checkin
    └── pm-qa.mjs               # pm:qa
```

That layout assumes Spine and FutureCapital share a parent directory, for example:

```
~/dev/SpineDevelopment
~/dev/FutureCapital/Engineering/SDLC/...
```

**On many machines this path does not exist.** Symptoms:

```text
Error: Cannot find module '.../FutureCapital/Engineering/SDLC/scripts/pm-checkin.mjs'
```

This is expected for customer ship and for contributors without the fc-sdlc monorepo checkout. Spine remains fully usable via Hub + Harness Lite; only the live `:5190` dashboard and `pm:checkin` HTTP posts are unavailable until the sibling tree is installed.

---

## Running the PM dashboard (when fc-sdlc is available)

1. Clone or symlink FutureCapital SDLC next to Spine (see path above).
2. Install PM service deps once:

   ```bash
   cd ~/dev/SpineDevelopment
   npm run pm:install
   ```

3. Start the dashboard (from repo root — `WORKSPACE_ROOT` must be this tree):

   ```bash
   npm run pm:dev
   ```

   Open http://127.0.0.1:5190. Process state and commands are also summarized in [`docs/fc-sdlc-STATUS.md`](./fc-sdlc-STATUS.md).

4. **Optional Docker:** `npm run pm:up` / `npm run pm:down` (compose file under FutureCapital SDLC).

5. **Agent check-in** (requires running PM service):

   ```bash
   npm run pm:checkin -- --agent <id> --role <role> --status in_progress \
     --task SPINE-011 --message "Starting …"

   npm run pm:checkin -- --agent <id> --role <role> --status completed \
     --task SPINE-011 --message "Done …" --deliverable docs/PM_DASHBOARD.md
   ```

   Override base URL if needed: `PM_URL=http://localhost:5190`.

6. **QA evidence** for verify-class agents:

   ```bash
   npm run pm:qa
   # equivalent to pm.config.json → tools/fc-sdlc/ci-test-full.sh
   npm run sdlc:run-qa:full
   ```

Set `PM_QA_AUTO=false` in `pm:dev` / `pm:start` scripts to avoid background QA polling during doc-only work.

---

## Harness Lite alternative (no PM service)

When `pm:checkin` fails or `:5190` is not running, use **Harness Lite** for portable SDLC state and agent waves without Hub or the PM HTTP API.

```bash
cd ~/dev/SpineDevelopment
bash tools/harness/spine-harness init --project .
bash tools/harness/spine-harness start feature    # or watch | release-gate | sprint-close
bash tools/harness/spine-harness status --markdown
bash tools/harness/spine-harness verify --run-qa   # evidenced QA without pm:qa
bash tools/harness/spine-harness stop
```

Via orchestrator CLI (when `spine` is on PATH): `spine harness …` (same subcommands).

| PM dashboard | Harness Lite |
|--------------|--------------|
| Live SSE dashboard at `:5190` | Markdown status from `.spine/harness/state.json` |
| `pm:checkin` HTTP events | Session protocol in [`.cursor/skills/spine-harness-session/SKILL.md`](../.cursor/skills/spine-harness-session/SKILL.md) |
| Backlog/gates from `todo/` | Same `todo/` sources; audit via `spine-harness audit` |
| `pm:qa` / `ci-test-full.sh` | `spine-harness verify --run-qa` |

See [`tools/harness/README.md`](../tools/harness/README.md) and [`Handoff.md`](../Handoff.md).

---

## H-PM — customer ship posture

| Aspect | Posture |
|--------|---------|
| **In-repo config** | Done — `pm.config.json`, `todo/`, fc-sdlc scripts under `tools/fc-sdlc/` |
| **PM HTTP service** | Optional / deferred — external vendor path; not required for Hub golden path |
| **Hold ID** | H-PM — tracked in [`todo/gates/G5-release-ready.md`](../todo/gates/G5-release-ready.md) and [`docs/product/REALITY-AUDIT-2026-06-19.md`](./product/REALITY-AUDIT-2026-06-19.md) |
| **Target** | Sprint 1 — vendor PM path or bundled substitute |
| **Agent default without PM** | Harness Lite + direct QA scripts; do not block on missing FutureCapital checkout |

Reality audit class: **PARTIAL** — wired configuration, service not guaranteed on every machine.

---

## Related docs

- [`docs/fc-sdlc-STATUS.md`](./fc-sdlc-STATUS.md) — fc-sdlc / PM commands and current sprint verdict
- [`docs/AI-INTEGRATION.md`](./AI-INTEGRATION.md) — agent integration summary
- [`LOCAL_DEV.md`](../LOCAL_DEV.md) — local URLs including `:5190`
- [`docs/PLAYBOOK.md`](./PLAYBOOK.md) — gate and backlog workflow
