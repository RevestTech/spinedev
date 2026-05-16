# Daemon migration inventory — `lib/` → `build/`

Authoritative list for `STORY-7.5.{1,2,3}` per `REQ-INIT-7 FR-5` (PRD §7.5)
and `docs/ARCHITECTURE.md §6 Phase 4`. Anything not in these tables stays
where it is; the migration is opportunistic, not big-bang.

The toolkit (`migrate_daemons.sh`, `compat_shim.sh`, `update_protocol_refs.sh`)
operationalises these tables. Edit this file first when a daemon moves —
the script reads the same list, so divergence will produce stale state.

## A. Daemon shell files — `lib/*.sh` → `build/daemons/*.sh`

| Old path | New path | Status | Why | Affected callers |
|---|---|---|---|---|
| `lib/team-agent-daemon.sh` | `build/daemons/team-agent-daemon.sh` | Move | FR-5; core manager/worker daemon (ARCHITECTURE §4, build subsystem boundary) | `scripts/team-agent-daemon.sh` (installed copy), `Makefile.v2`, `PROTOCOL.md`, `README.md`, `lib/tests/test-daemon-stub-smoke.sh`, `build/bridge/v1_dispatcher.sh` (READ-ONLY ref in comment) |
| `lib/file-lock.sh` | `build/daemons/file-lock.sh` | Move | Daemon support — file-bus lock primitive (PROTOCOL §3a) | `team-agent-daemon.sh`, `watchdog.sh`, `heartbeat.sh` |
| `lib/heartbeat.sh` | `build/daemons/heartbeat.sh` | Move | Daemon liveness ticker | `team.sh`, watchdog |
| `lib/watchdog.sh` | `build/daemons/watchdog.sh` | Move | Restarts crashed managers (PROTOCOL §18) | `team.sh`, install.sh |
| `lib/seer-tick.sh` | `build/daemons/seer-tick.sh` | Move | Periodic seer digest (PRACTICES §seer) | `team.sh`, dashboard |
| `lib/executor.sh` | `build/daemons/executor.sh` | Move | Subprocess wrapper invoked by manager | `team-agent-daemon.sh`, tests |
| `lib/notify.sh` | `build/daemons/notify.sh` | Move | Notification side-channel | `team-agent-daemon.sh` |
| `lib/costs-csv.sh` | `build/daemons/costs-csv.sh` | Move | Cost-row writer (CHANGELOG v1.4.4) | `team-agent-daemon.sh`, db-outbox |
| `lib/usage-parsers.sh` | `build/daemons/usage-parsers.sh` | Move | Pass C parser (tokens/cost from agent log) | `team-agent-daemon.sh` |
| `lib/engagement-hook.sh` | `build/daemons/engagement-hook.sh` | Move | Approval/engagement bridge | tests, executor |
| `lib/db-outbox.sh` | `build/daemons/db-outbox.sh` | Move | Forwards cost rows to spine_recording | `team-agent-daemon.sh`, watcher tests |
| `lib/vitals.sh` | `build/daemons/vitals.sh` | Move | Per-role vitals snapshot | dashboard, tests |
| `lib/preflight.sh` | `build/daemons/preflight.sh` | Move | Pre-boot sanity (run pre-`team start`) | `Makefile.v2`, install.sh, tests |

**Not moving in this story** (stay under `lib/` for now; revisit on next
touch per Phase 4):
- `lib/roles.sh` — single source of truth for role IDs; consumed by both `lib/team.sh` and the migrated daemons via `SCRIPT_DIR`. Move once `build/daemons/team-agent-daemon.sh` is comfortable resolving roles from `build/`.
- `lib/team.sh` / `lib/team-clean.sh` — orchestration wrappers; belong with `scripts/team.sh`. Out of `build/` scope (control surface, not daemon).
- `lib/spine-connect.sh` / `lib/spine-disconnect.sh` / `lib/share-pg.sh` — shared/db wiring; candidates for `shared/db/` per ARCHITECTURE §6 Phase 2 (post `STORY-8.3.3`).
- `lib/serve-dashboard.sh` — `shared/db/dashboard/` candidate; ships with Control Center.
- `lib/updater.sh` — install-side, stays with installer.
- `lib/verify.sh` — `verify/` candidate (REQ-INIT-8).
- `lib/run-standalone-watcher.sh` — `shared/db/watcher/` candidate.
- `lib/spine-migrate.py` — installer-side python; not a daemon.

## B. Role prompts — `lib/role-prompts/<role>.md` → `build/roles/<role>/prompt.md`

| Old path | New path | Status | Why | Affected callers |
|---|---|---|---|---|
| `lib/role-prompts/product.md` | `build/roles/product/prompt.md` | Move | FR-5 + STORY-1.1.1 anchor | `install.sh`, `shared/skills/.../brainstorming/SKILL.md`, `shared/reproducibility/manifest.py` |
| `lib/role-prompts/planner.md` | `build/roles/planner/prompt.md` | Move | FR-5 | `plan/decomposer/decomposer_README.md` |
| `lib/role-prompts/architect.md` | `build/roles/architect/prompt.md` | Move | FR-5 | `plan/swarm/swarm_README.md` |
| `lib/role-prompts/conductor.md` | `build/roles/conductor/prompt.md` | Move | FR-5 | `README.md` |
| `lib/role-prompts/researcher.md` | `build/roles/researcher/prompt.md` | Move | FR-5 | swarm_README, eval |
| `lib/role-prompts/engineer.md` | `build/roles/engineer/prompt.md` | Move | FR-5 + FR-3 KG hook owner | `shared/eval/runner_README.md` (×5), `shared/eval/README.md`, `shared/skills/.../verification-before-completion/SKILL.md`, `build/runtime/*`, `manifest.py` |
| `lib/role-prompts/ux.md` | `build/roles/ux/prompt.md` | Move | FR-5 | tests |
| `lib/role-prompts/qa.md` | `build/roles/qa/prompt.md` | Move | FR-5 | tests, eval |
| `lib/role-prompts/operator.md` | `build/roles/operator/prompt.md` | Move | FR-5 + FR-4 `who_owns()` caller | `build/runtime/runtime_README.md`, kg_caller |
| `lib/role-prompts/datawright.md` | `build/roles/datawright/prompt.md` | Move | FR-5 + FR-4 `kg_register_document` caller | `build/runtime/`, `lib/tests/test-daemon-stub-smoke.sh` |
| `lib/role-prompts/seer.md` | `build/roles/seer/prompt.md` | Move | FR-5 (PRACTICES §seer) | seer-tick, dashboard |
| `lib/role-prompts/auditor.md` | `build/roles/auditor/prompt.md` | Move | FR-5 + FR-7 verification hook | bridge, audit |
| `lib/role-prompts/memory.md` | `build/roles/memory/prompt.md` | Move | FR-5 | memory subsystem |
| `lib/role-prompts/_archived/engineering-backend.md` | `build/roles/_archived/engineering-backend.md` | Move | Preserve archive (ADR-001) | `lib/roles.sh` comment, README footnote |
| `lib/role-prompts/_archived/engineering-frontend.md` | `build/roles/_archived/engineering-frontend.md` | Move | Preserve archive (ADR-001) | same |

## C. Worker primitives — placeholder

`build/workers/` is created empty by Phase A. Worker decomposition arrives
post-migration in `EPIC-7.3` (per PRD §7.4 NFR-1: 10 workers/manager). No
files in scope for `STORY-7.5.x`.

## D. Symlink shim strategy

Per `REQ-INIT-7 OQ-4` (recommend: one release cycle). After Phase B+C
relocate the files, Phase E installs symlinks at the legacy paths:

```
lib/team-agent-daemon.sh   → ../build/daemons/team-agent-daemon.sh
lib/file-lock.sh           → ../build/daemons/file-lock.sh
... (every entry in §A)
lib/role-prompts/engineer.md → ../../build/roles/engineer/prompt.md
... (every entry in §B)
```

Consequences:
- v1 callers (`scripts/team.sh`, the bridge `v1_dispatcher.sh` comment ref,
  consuming projects on `--pull-knowledge-only`) keep working.
- Downstream-installed copies under `scripts/*.sh` are untouched — those
  are *installed*, not symlinked back; consumers re-install to pick up
  upstream changes per `INSTALL.md`.
- `git status` shows symlinks (not as moves) because `git mv` was already
  performed in Phase B+C; the symlinks are net-new artifacts.

## E. Retirement plan — `STORY-7.5.3`

Trigger when **all** of the following are true:
1. One release cycle has elapsed since shim install (OQ-4).
2. No grep hits for `lib/team-agent-daemon.sh` or `lib/role-prompts/` in
   any subsystem source (CHANGELOG / archive comments excluded).
3. `build/bridge/` has been retired per its `Phase C` plan (bridge README).
4. Downstream consumers have run a full `install.sh` (not just
   `--pull-knowledge-only`) since the move.

Execute via:
```bash
build/migration/compat_shim.sh --remove
git rm -r lib/role-prompts lib/team-agent-daemon.sh ...  # only the shims
```

After retirement, `lib/` retains only the non-daemon files listed under
§A "Not moving" until their own opportunistic migration.

## Cross-refs

- `docs/PRD.md` REQ-INIT-7 §7.5 FR-5, OQ-4
- `docs/BACKLOG.md` EPIC-7.5 (STORY-7.5.1 / 7.5.2 / 7.5.3)
- `docs/ARCHITECTURE.md` §4 (build subsystem boundary), §6 Phase 4 (drain)
- `build/README.md` (target sub-structure)
- `build/bridge/bridge_README.md` Phase A/B/C (bridge retirement aligns with shim removal)
- `db/migrate-to-shared_README.md` (style/pattern reference)
