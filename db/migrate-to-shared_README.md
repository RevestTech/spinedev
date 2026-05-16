# migrate-to-shared.sh — `db/` → `shared/db/`

Helper script for **STORY-8.3.3**. Moves the `db/` directory under
`shared/db/`, then rewrites internal path references in `Makefile`,
`Makefile.v2`, and `docker-compose.yml`.

## Why this exists

`docs/ARCHITECTURE.md` §6 Phase 2 calls for consolidating all shared
infrastructure under `shared/`. Postgres (recording layer + Flyway + watcher
+ dashboard) currently lives at `/db/`; the canonical location going forward
is `/shared/db/`. The script:

1. Preserves git history (`git mv`, not `cp -r`).
2. Updates path references in build files so `make migrate`, `make lint`,
   `make lint-sql`, `make db-up`, etc. keep working from repo root.
3. Verifies the result (no stray `db/flyway` or `cd db` references).

The move itself is a separate **operational** step — this story ships only
the script + the plan. Run when the team is ready.

## Pre-flight checklist

- [ ] All `spine_postgres` / `spine_watcher` / `spine_dashboard` containers
      stopped (`docker compose -f db/docker-compose.yml down`).
- [ ] Repo is clean (`git status` empty under `db/`).
- [ ] All migrations applied (`make migrate` from inside `db/` shows
      V1..V21 OK).
- [ ] Backup taken (`pg_dump`).
- [ ] No active branches with in-flight changes to `db/` paths — coordinate
      with anyone who has a long-lived branch.

## Usage

```bash
# Dry-run: print everything the script would do, change nothing.
./db/migrate-to-shared.sh --dry-run

# Verify-only: no move, just check the current state.
./db/migrate-to-shared.sh --verify-only

# Real move:
./db/migrate-to-shared.sh

# Real move + legacy symlink (db -> shared/db) for callers we missed:
./db/migrate-to-shared.sh --leave-symlink
```

## What it does, step by step

1. **Pre-flight**: refuses to run if `spine_postgres` container is up; warns
   on uncommitted `db/` changes.
2. **Move**: `git mv db shared/db` (history preserved).
3. **Optional symlink**: `db -> shared/db` (for legacy callers we missed).
4. **Rewrite**: sed-edits Makefile, Makefile.v2, docker-compose.yml so
   `db/flyway`, `cd db`, `db/dashboard`, `db/watcher`, `db/docker-compose`,
   `db/Makefile`, `db/README` become `shared/db/...`. Anchored regex avoids
   double-rewriting paths that already include `shared/`.
5. **Verify**: greps for stale `db/` references and reports.

## Rollback

```bash
git restore -- Makefile Makefile.v2 docker-compose.yml
git mv shared/db db          # if move already happened
git restore --staged db/
```

Or simply: `git reset --hard HEAD` on the commit that ran the script.

## What breaks if you skip the path updates

- `make migrate` and `make db-up` fail because they `cd db` or reference
  `db/Makefile`.
- `make lint`, `make lint-sql`, `make lint-html` skip the moved files
  silently (no error, but stale lint baseline).
- `db/docker-compose.yml` reference in any wrapper script breaks.

## Cross-refs

- `db/migration-survey.md` — TRON Alembic → Flyway port survey (STORY-8.3.1).
- `db/multi-schema-layout.md` — canonical schema map (STORY-8.3.2).
- `db/flyway/sql/V21__spine_verify_schemas.sql` — verify schemas migration.
- `docs/ARCHITECTURE.md` §6 Phase 2 — "Move `db/` → `shared/db/`".
- `docs/BACKLOG.md` INIT-8 EPIC-8.3 STORY-8.3.3.
