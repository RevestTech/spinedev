# `build/migration/` — daemon migration toolkit

> **Status:** Toolkit shipped. The actual move is an **operational** step run
> when the team is ready (mirrors `db/migrate-to-shared.sh` pattern). Stories
> `STORY-7.5.1` / `STORY-7.5.2` / `STORY-7.5.3` are "Done" when this toolkit
> lands; "executed" when the scripts have been run on `main`.

## Why this migration

`REQ-INIT-7 FR-5` (PRD §7.5) declares the v2 home for build-subsystem
daemons: `build/daemons/` for shell infra, `build/roles/<role>/prompt.md`
for role prompts, `build/workers/` for worker primitives. Today the same
files live at `lib/team-agent-daemon.sh`, `lib/*.sh`, and
`lib/role-prompts/*.md`.

The move is **opportunistic** per `docs/ARCHITECTURE.md §6 Phase 4`
("Drain legacy + thicken subsystems"). The bridge in `build/bridge/`
(Phase A) hides the seam from the v2 orchestrator, so the move is no
longer load-bearing for any in-flight feature — which is exactly why now
is the right time to do it.

## Files

| File | Lines | Role |
|---|---|---|
| `__init__.py` | ~12 | Package marker |
| `migrate_daemons.sh` | ~280 | Main migration driver — phases A→F |
| `compat_shim.sh` | ~120 | Legacy `lib/` symlink shim (install + remove) |
| `update_protocol_refs.sh` | ~120 | sed-edits docs + tests + makefiles |
| `migrate_inventory.md` | ~150 | Source of truth: what moves where + why |
| `migration_README.md` | this file | Operational runbook |

## Pre-flight checklist

- [ ] **Clean git** under `lib/`: `git status -- lib/` is empty. The driver
      refuses to run otherwise (exit 1).
- [ ] **No live daemons:** `make team-stop` first; `pgrep -f team-agent-daemon`
      returns nothing. The move uses `git mv` — a running daemon holding
      open file descriptors will continue running off the old inode, but
      restarts will fail until paths are restored.
- [ ] **Snapshot taken:** Phase A writes one to `/tmp/spine-daemon-migration-<ts>.tar`;
      keep a second copy if you're paranoid (`cp` to a backup dir).
- [ ] **Coordinate** with anyone on a long-lived branch touching `lib/` —
      they'll need to rebase after the move (`git mv` rewrites paths).
- [ ] **Bridge online:** `build/bridge/v1_dispatcher.sh` and
      `v1_report_collector.sh` continue to work via shim. Confirm both
      can still invoke and parse after migration (verification phase F).

## Phased approach (A through F)

| Phase | What it does | Idempotent? | Reversible? |
|---|---|---|---|
| **A — preparation** | Creates `build/daemons/`, `build/workers/`, `build/roles/<role>/` (incl. `_archived/`); snapshots `/tmp/spine-daemon-migration-<ts>.tar` | Yes (mkdir -p) | N/A — non-mutating |
| **B — daemon files** | `git mv lib/<file>.sh build/daemons/<file>.sh` for the list in `migrate_inventory.md §A` | Yes (skips if already moved or already symlink) | `git reset --hard <pre-migration>` |
| **C — role prompts** | `git mv lib/role-prompts/<role>.md build/roles/<role>/prompt.md` + `_archived/` merge | Yes | Same as B |
| **D — refs** | `update_protocol_refs.sh` sed-edits PROTOCOL/INSTALL/README/Makefile.v2/PRACTICES/eval-docs/skills/tests | Yes (sed pattern is a no-op on already-converted paths) | `--restore` flag uses `.bak` files |
| **E — shim** | `compat_shim.sh` installs relative symlinks at the legacy paths | Yes (replaces existing symlinks, refuses to clobber real files) | `--remove` flag |
| **F — verify** | Reachability check; runs `preflight.sh --version` (best-effort); greps for stale refs; `git status` summary | Yes | Read-only |

CLI:
```bash
build/migration/migrate_daemons.sh --dry-run            # preview everything
build/migration/migrate_daemons.sh --phase a            # just one phase
build/migration/migrate_daemons.sh --no-shim            # skip Phase E
build/migration/migrate_daemons.sh --rollback <snap>    # restore from tar
build/migration/migrate_daemons.sh                      # full run
```

Exit codes: `0` ok, `1` dirty git, `2` missing file, `3` verify failed,
`4` already migrated (idempotent skip), `64` unknown flag.

## Symlink shim: how it works

After Phase B+C, the legacy paths are gone. Phase E re-creates them as
relative symlinks pointing into `build/`:

```
lib/team-agent-daemon.sh           -> ../build/daemons/team-agent-daemon.sh
lib/role-prompts/engineer.md       -> ../../build/roles/engineer/prompt.md
```

Why relative: makes the repo movable (`git clone` to any path works). Why
all of them: any caller that imports a daemon helper by old path keeps
working — including the `scripts/*.sh` *installed* copies (those are
re-installed on the next `install.sh`, not symlinked themselves).

When to remove: see `STORY-7.5.3` retirement criteria in
`migrate_inventory.md §E`. Short version — one release cycle after move,
zero grep hits for the old paths, bridge retired.

## Verification: how to test post-migration

1. `build/migration/migrate_daemons.sh --phase f` — runs the verification
   pass on its own.
2. `make selftest` (if shipped — check Makefile.v2 target) — exercises
   `lib/tests/test-*.sh` against the new layout via shim.
3. `bash build/daemons/team-agent-daemon.sh datawright manager &`
   followed by `bash lib/tests/test-daemon-stub-smoke.sh` — smoke test
   the manager loop, exiting cleanly.
4. `bash build/bridge/v1_dispatcher.sh dispatch engineer test_directive proj_test v1.0.0` —
   confirms the bridge still routes via the shimmed daemon.

## Rollback

Snapshots land at `/tmp/spine-daemon-migration-<ts>.tar`. To undo:

```bash
build/migration/migrate_daemons.sh --rollback /tmp/spine-daemon-migration-<ts>.tar
build/migration/update_protocol_refs.sh --restore   # un-sed docs
build/migration/compat_shim.sh --remove             # drop symlinks
git checkout -- lib build PROTOCOL.md INSTALL.md README.md Makefile.v2
```

Or — preferred for a recent run — `git reset --hard <commit-before-migration>`
and re-extract the tar over the working tree.

## Cross-refs

- `docs/PRD.md` — `REQ-INIT-7` §7.5 FR-5 (target paths), OQ-4 (shim lifespan)
- `docs/BACKLOG.md` — `EPIC-7.5` (`STORY-7.5.1`, `STORY-7.5.2`, `STORY-7.5.3`)
- `docs/ARCHITECTURE.md` — §4 (build subsystem layout), §6 Phase 4 (drain)
- `build/README.md` — boundary doc for `build/`
- `build/bridge/bridge_README.md` — bridge Phase C aligns with shim removal
- `db/migrate-to-shared.sh` + `db/migrate-to-shared_README.md` — style/pattern reference
- `PROTOCOL.md` — file-bus contract the daemons implement (unchanged by move)
