# Spine Recording Database

This directory contains the Postgres-backed recording layer for the Spine
multi-agent orchestration system.

## What this is

Spine is primarily a file-based system: directives, reports, costs, and other
artifacts live as markdown and CSV files on disk under the team workspaces.
This database does NOT replace that file layout — it RECORDS every interaction
alongside the files so we can query history, build dashboards, and reason
about cost and throughput across teams and workers.

In other words: the filesystem remains the source of truth for human-edited
content; the database is the source of truth for structured queries.

## Local vs central-server mode

- **Local mode (today)**: Postgres runs in Docker on the developer's machine.
  A watcher process (added in a later step) tails the workspace files and
  upserts rows. This directory ships everything needed for that mode.
- **Central-server mode (roadmap)**: the same schema runs on a shared
  Postgres instance (managed RDS / Cloud SQL / self-hosted) with multiple
  workers pointing at it. The migrations in `flyway/sql/` are the canonical
  schema for both modes — only the `FLYWAY_URL` and credentials change.

## How to run

Prerequisites: Docker, Docker Compose, GNU Make.

```sh
cp .env.example .env       # adjust if you like; defaults work for dev
make up                    # start Postgres on 127.0.0.1:33000
make migrate               # run Flyway migrations (idempotent)
make psql                  # open a psql shell to verify
```

The Spine Postgres binds to host port **33000** by default — well out of
the way of any system Postgres on 5432 or 5433. Override with
`POSTGRES_HOST_PORT=<port>` in `.env` if you need a different port. From
inside the docker network the watcher and flyway services still talk to
`postgres:5432` unchanged.

Common operations:

- `make info` — show Flyway migration status
- `make validate` — validate applied migrations against the SQL files
- `make down` — stop containers (data persists in the volume)
- `make nuke` — stop AND delete the data volume (asks for confirmation)

## Schema layout

The schema is versioned via Flyway. Migrations live in `flyway/sql/` and are
applied in lexical order.

- `V1__init_core_schema.sql` — the 19-table core. Groups:
  - **Lookups**: `job_family`, `discipline`, `level`, `tier`, `provider`,
    `model`, `role`. Small, mostly read-only; seeded by V2.
  - **Org**: `team`, `worker` (parent_worker_id forms the supervision tree).
  - **Work loop**: `task`, `prompt`, `prompt_version`, `assignment`,
    `directive` (1:1 with active assignments), `report` (1:1 with closed
    assignments), `artifact`, `review`, `handoff`.
  - **Cost**: `cost_row` (token-level, PK on `(assignment_id, ts)`).
  - **Memory**: `team_memory`, `worker_memory`.
  - **Operational**: `rollback_entry`, `event` (append-only audit log).
- `V2__seed_lookups.sql` — seeds tiers, levels, disciplines, job families,
  and default roles. Idempotent via `ON CONFLICT DO NOTHING`.

### Postgres-specific choices (vs. the SQLite draft in `.planning/`)

- Primary keys are `UUID` with `DEFAULT gen_random_uuid()` (via `pgcrypto`).
  Lookup tables keep their text natural keys (e.g., `'low'`, `'engineer'`).
- All timestamps are `TIMESTAMPTZ DEFAULT now()`.
- JSON columns are `JSONB` with `'{}'::jsonb` defaults.
- Closed status sets use real `ENUM` types: `worker_status`, `task_status`,
  `assignment_status`, `review_status`, `artifact_kind`.
- A partial unique index enforces "one active assignment per worker":
  `CREATE UNIQUE INDEX assignment_one_active_per_worker ON assignment(worker_id) WHERE status = 'active';`
- `updated_at` columns on the hot tables (`worker`, `task`, `assignment`,
  `directive`, `report`) are maintained by a shared `set_updated_at()`
  trigger function.

## Layout

```
db/
  README.md
  Makefile
  docker-compose.yml
  .env.example
  .gitignore
  flyway/
    conf/flyway.toml
    sql/
      V1__init_core_schema.sql
      V3__multi_host.sql
      R__seed_lookups.sql
  watcher/
    Dockerfile
    requirements.txt
    spine_watcher.py
```

## Watcher

The watcher service drains per-role `outbox.jsonl` files into Postgres. It is
Pass B of the integration: the daemon keeps writing `costs.csv` as before
(source of truth) and additionally appends a JSON line per cost row to
`teams/<role>/state/outbox.jsonl`. The watcher reads each file from its byte
offset cursor, ingests each line in a single transaction (team + worker +
assignment + cost_row + IngestedCostRow event), and advances the cursor only
on success.

### Running it

```sh
make watch          # start the watcher (in background)
make watch-logs     # follow the watcher's logs
make watch-down     # stop the watcher (postgres keeps running)
make watch-rebuild  # rebuild the image after editing watcher code
```

`make watch` depends on `make up` and `make migrate` having succeeded (the
compose dependency chain enforces this: the watcher waits for Postgres to be
healthy and Flyway to complete).

### Inspecting cursors

In the docker-compose setup, the team workspace is mounted **read-only** and
cursors live in a separate named volume (`spine_cursors`). To inspect:

```sh
docker compose exec watcher ls -la /spine-cursors
docker compose exec watcher cat /spine-cursors/engineer.cursor
```

If you run the watcher outside docker (no `CURSOR_BASE` env var), cursors
fall back to next-to-the-outbox at
`teams/<role>/state/outbox.cursor` and you can `cat` them directly.

### Failure model

- The daemon **never** blocks on the watcher or the DB. If the watcher is
  down, the broken-Pg case, or the disk is full, `costs.csv` still grows
  normally. `outbox.jsonl` keeps accumulating; the watcher catches up on
  restart from the last advanced cursor offset.
- A malformed JSON line, an unknown role, or a DB constraint violation
  stops cursor advancement at that line. The line stays in the outbox so
  an operator can inspect and fix; subsequent lines wait until the bad
  line is resolved (delete the line, fix the schema, etc.).
- Connection drops trigger an exponential backoff reconnect inside the
  watcher (1s, 2s, 4s, ... capped at 60s) and the tick resumes.
- The watcher is **read-only** on `outbox.jsonl`. It only writes the
  cursor file. The daemon owns the JSONL file exclusively.

### Schema notes

- `team` rows are deterministic UUIDs of `https://spine.local/team/<name>`
  with name `default` for the initial drop-in.
- `worker.handle` is `<role>-<slot>` (or `<role>-manager` for managers).
- `assignment` is one per `(worker, day)` so we don't manufacture an
  assignment per cost row. This is a Pass B simplification; richer
  assignment lifecycles will land when the daemon emits
  `directive_written` / `report_written` events in a future pass.

### Multi-machine fleet

Pass N adds a two-command flow for joining multiple machines to one shared
Postgres hub. The dashboard's Fleet card lights up with one row per joined
machine — each laptop runs its own watcher against its own local outbox.

**On Machine A (hub):**

```sh
# 1. Open Postgres to the LAN (edit db/.env)
sed -i.bak 's/^POSTGRES_BIND_HOST=.*/POSTGRES_BIND_HOST=0.0.0.0/' db/.env
make -C db down && make -C db up && make -C db migrate

# 2. Print the paste-ready env block for Machine B
make -C db share-pg
```

**On Machine B (joiner):** copy/paste the env block, then:

```sh
bash scripts/spine-connect.sh
```

That's it. The script verifies the connection (auto-installs `psycopg`),
launches a standalone watcher reading this machine's local outbox files,
and runs `team.sh up`. Refresh the hub dashboard and a new instance row
appears in **Fleet**. To stop: `bash scripts/spine-disconnect.sh`.

Network requirements:

- Machine A's port (default `33000`) reachable from Machine B over the LAN.
- Machine A's firewall must allow inbound on that port (macOS: System Settings
  > Network > Firewall; Linux: `ufw allow 33000/tcp` or equivalent).
- For anything beyond a trusted LAN, front Postgres with a reverse proxy
  that terminates TLS, or use an SSH tunnel:
  `ssh -L 33000:127.0.0.1:33000 hub.host` (then point Machine B at
  `127.0.0.1:33000`).

How to verify it worked:

```sh
make -C db snapshot   # refresh the dashboard's JSON
# then reload the browser — Fleet shows N instances
```

Where Machine B's outbox lives: its own filesystem at
`.planning/orchestration/agent-handoff/teams/<role>/state/outbox.jsonl`.
That's why Machine B needs its own watcher — the watcher reads local outbox
files. Postgres (the projection) is what's shared, not the outboxes.

If you bootstrap a joiner from scratch, you can also bake the hub URL in
at install time:

```sh
bash install.sh ~/projects/joiner --hub "postgresql://spine:spine_dev_only@HUB_IP:33000/spine"
cd ~/projects/joiner
bash scripts/spine-connect.sh    # picks up the URL from .planning/orchestration/.hub-url
```

### Fleet / Spine Hub

Pass H adds an instance registry on top of the watcher. Each laptop or
host that runs `team.sh up` against this Postgres registers itself in
`spine_instance` as one logical "instance" per `team.sh up` invocation:

- `team.sh up`     mints (or loads) `SPINE_GROUP_ID`, exports it to every
  daemon it spawns, and emits an `InstanceStarted` event to the top-level
  outbox at `.planning/orchestration/agent-handoff/.instance-outbox.jsonl`.
  It also starts `heartbeat.sh`, a tiny background loop that emits an
  `InstanceHeartbeat` every `SPINE_HEARTBEAT_INTERVAL_S` (default 60s).
- `team.sh down`   stops the heartbeat (via `heartbeat.pid`), shuts down
  the daemons, then emits a final `InstanceStopped` event.
- The watcher drains the instance outbox just like the per-role
  outboxes (cursor at `_instance.cursor`) and routes events into
  `spine_instance`. The `v_active_instances` view derives
  `effective_status` (`alive` / `stale` / `lost` / `stopped`) from
  `last_seen_at` on every read, so no background expirer is needed.
- The dashboard's **Fleet** section renders the view; the **Live
  instances** KPI is the count of `effective_status = 'alive'`.

The schema is intentionally hub-ready: point `DATABASE_URL` at a shared
Postgres and every laptop that runs `team.sh up` becomes one row in the
same table. No code change required.

#### Machine vitals (Pass M)

Every `InstanceHeartbeat` now carries a small JSON `vitals` block in its
payload — total host CPU%, memory used/total, disk used/total, load
averages, and the **Spine-attributed totals** (CPU% and RSS summed across
all `spine_*` daemons, plus the count of those processes). This lets
admins and devops see how Spine is impacting the host across the fleet
without having to SSH into individual machines.

The capture is opt-in via running `heartbeat.sh` — which is on by default
when you invoke `team.sh up`. The helper at `lib/vitals.sh` prefers
`psutil` for clean cross-platform metrics; if psutil is not installed it
falls back to platform-specific CLI parsing (`vm_stat` / `top` / `df` /
`uptime` on macOS, `/proc/meminfo` / `/proc/stat` / `df` on Linux). On any
failure the helper emits `{}` and the heartbeat proceeds — vitals never
block or crash the daemon.

V13 introduces two persistence layers:

- `spine_instance` gains 12 vital columns (`cpu_pct`, `mem_used_mb`,
  `mem_total_mb`, `disk_used_gb`, `disk_total_gb`, `load_avg_1m/5m/15m`,
  `spine_cpu_pct`, `spine_mem_mb`, `spine_proc_count`, `vitals_at`).
  These hold the **latest** snapshot for fast dashboard reads.
- `instance_vitals` is the **append-only time-series**: one row per
  heartbeat. Retention is the operator's choice (e.g., a cron job that
  deletes rows older than 30 days). The view
  `v_instance_vitals_latest` joins the materialized current values with
  computed `mem_used_pct`, `disk_used_pct`, and `spine_share_pct`
  (Spine's CPU% as a percentage of the host's busy CPU%).

The dashboard renders the latest snapshot as colored bars on each
Machines card (green < 50%, amber 50-80%, red > 80%, Spine's share
overlaid on the CPU bar), and `machines.html` adds a Vitals section with
three side-by-side sparklines (CPU host vs Spine, Memory%, Load avg) plus
a small current-values table.

### Spine Hub Pillar 2 — code distribution (Pass L)

Pass H gave us Pillar 1: telemetry (heartbeats, cost projection, fleet
view). Pass L adds Pillar 2: **code distribution**. SpineDevelopment is a
*templating* project — every installation consumes it. An admin should be
able to update the template once and have every fleet member pick up the
new scripts, role prompts, and recipes on their next tick.

V12 introduces:

- `spine_release` — one row per (channel, commit_sha) promotion. Channels
  are `stable`, `beta`, `canary`. Releases are soft-deleted via
  `archived_at` so an admin can roll back by archiving the bad release;
  fleet members fall back to the next-newest non-archived one.
- `v_release_heads` — latest known-good commit per channel. The updater
  daemon queries this view to decide which commit to fast-forward to.
- `v_instance_drift` — per-instance comparison of
  `spine_instance.version_sha` against the head of its declared channel.
  Status values: `current`, `drifted`, `unversioned`, `unknown_channel`.

The dashboard exposes:

- `POST /api/releases` — promote a commit to a channel.
- `GET  /api/releases[?channel=stable]` — release history (latest 20).
- `POST /api/releases/<release_id>/archive` — soft-delete a release.
- `/versions.html` — release channels per channel + the drift table.

The updater daemon (`lib/updater.sh` → `scripts/updater.sh`) is **opt-in**.
It is started by `team.sh up` only when `SPINE_UPDATE_ENABLED=1`. Modes:

- `pull` — periodically `git fetch && git pull --ff-only` on
  `SPINE_UPDATE_TEMPLATE_DIR` (a local clone of SpineDevelopment).
- `pull-pin` (default) — fast-forward to the commit pinned by the hub
  (`v_release_heads` for the configured channel). Falls back to plain
  `pull` when `SPINE_DB_URL` is unset.

Safety: the updater only `git fetch` + fast-forwards the template clone.
It does **not** replace files in the consuming project's `scripts/` tree
and does **not** restart running daemons — mid-engagement restarts are
deliberately out of scope.

To turn it on on a laptop:

```sh
export SPINE_UPDATE_ENABLED=1
export SPINE_UPDATE_TEMPLATE_DIR=~/code/SpineDevelopment
export SPINE_UPDATE_MODE=pull-pin              # or pull
export SPINE_UPDATE_CHANNEL=stable             # stable | beta | canary
export SPINE_UPDATE_INTERVAL_S=300             # 5 minutes
bash scripts/team.sh up
```

Pre-V12 databases continue to work; the dashboard's Versions tab renders
an empty placeholder and `team.sh up` is unaffected.

## Dashboard

The `dashboard/` directory contains a single-page HTML dashboard that
visualizes the recording layer: KPIs, recent invocations, cost by
role/model, active workers, and the event stream. It runs in two modes:

1. **Live mode** (default) — a small Python HTTP server (`serve.py`) backs a
   `/pg-snapshot.json` endpoint with a fresh-on-demand query into Postgres.
   The page auto-refreshes every 5s, animates KPIs and tables in place, and
   exposes interactive filters (time range, role, terminal type).
2. **File mode** (fallback / scripting path) — `build-snapshot.py` writes a
   one-shot `pg-snapshot.json` to disk. Open `index.html` via `file://` and
   it falls back to fetching the local file. Good for capturing a fixed
   snapshot to share or archive.

### Live mode

```sh
make dashboard                    # http://127.0.0.1:33002/
```

This starts `dashboard/serve.py`, which connects lazily to Postgres on the
first browser request (so it won't crash at startup if Postgres is down —
you'll see a "Snapshot server unreachable" banner instead, and the page
recovers automatically once the DB is back).

What the page gives you:

- **Auto-refresh:** off/on toggle plus interval selector (3s / 5s / 10s /
  30s / 60s). Both are persisted to `localStorage`. A small Live dot pulses
  green while polling, dims to grey when paused, and turns red on a failed
  fetch. A "Last update: Ns ago" ticker updates every second between polls.
- **Filters:** three chip groups between the header and KPIs.
  - *Time range* (single-select): Last 1h / 24h / 7d / All.
  - *Role* (multi-select): one chip per role found in the snapshot, with
    invocation counts on each chip.
  - *Terminal* (multi-select): ReportWritten / PlanWritten /
    AggregateCompleted / WorkerCompleted / Reaped / in-flight.

  Filters are entirely client-side — they don't change the queries
  Postgres runs. Active filter state is persisted to `localStorage` AND
  reflected in the URL query string (`?t=`, `?r=`, `?x=`) so you can share a
  filtered view. Press <kbd>Esc</kbd> or click "Clear all" to reset.
- **Smooth updates:** KPIs animate from old to new value (300ms easeOutQuad);
  table rows reconcile by stable key — new rows fade in green, removed rows
  fade out, changed cells flash; Chart.js datasets update in place without a
  full redraw.

Stop the server:

```sh
make dashboard-stop               # kills whatever's listening on $DASHBOARD_PORT
```

### File mode (fallback)

```sh
make snapshot                     # writes db/dashboard/pg-snapshot.json
make watch-snapshot               # re-runs `make snapshot` every 30s
```

Then open `db/dashboard/index.html` directly via `file://`. The page detects
that fetch is hitting the local file, polls just like in live mode (it
re-reads the file on each interval — useful when paired with
`make watch-snapshot`), and shows a clear "Snapshot file not found" banner
if no snapshot has been built yet.

### Environment

- `DASHBOARD_PORT` — bind port for `make dashboard`. Default `33002`.
  Override with `DASHBOARD_PORT=33099 make dashboard` if it's taken.
- `DASHBOARD_HOST` — bind address. Default `127.0.0.1`.
- `SNAPSHOT_TTL_S` — TTL for the in-memory snapshot cache on the server,
  so multiple browser tabs don't hammer Postgres on every poll. Default `2.0`.
- `SPINE_DB_URL`, `PG*`, `db/.env` — same connection-precedence chain as
  `make snapshot` and `team.sh budget-db`.

### Limitations

- No websockets. The page polls over plain HTTP.
- `pg-snapshot.json` is git-ignored (see `dashboard/.gitignore`); each
  developer's snapshot reflects their own DB.
- `serve.py` requires `psycopg[binary]` on the host Python. If it's missing,
  it prints the install hint and exits 2.

## Queries / dashboards

Once `make migrate` has applied `V4__views.sql`, five read-side views are
available for ad-hoc queries, dashboards, and the `team.sh budget-db`
subcommand:

- `v_cost_by_role_day` — daily per-role rollups (invocations, wall-seconds,
  tokens in/out, USD).
- `v_cost_by_model` — per-model totals alongside each model's per-1k
  pricing for sanity-checking actuals.
- `v_active_workers` — workers not yet archived, with lifetime cost,
  lifetime invocations, and the most recent cost row's timestamp.
- `v_recent_events` — the last 200 lifecycle events, with team/role/worker
  handles flattened in so you don't have to remember the joins.
- `v_cost_by_outcome` — invocations bucketed by an rc-derived outcome
  (`completed` / `failed` / `unknown`). For finer-grained reap
  classification (timeout / stall / killed), query the `event` table
  directly with `type = 'Reaped'`.

`make views` runs `\d+` on all five at once — useful right after
`make migrate` to confirm they materialized.

### `team.sh budget-db`

```sh
bash scripts/team.sh budget-db
```

Prints four sections, each its own `psql -c` so a single bad query won't
abort the rest of the report:

1. Cost by role, last 7 days (from `v_cost_by_role_day`).
2. Top 20 models by cost (from `v_cost_by_model`).
3. Top 20 active workers by lifetime cost (from `v_active_workers`).
4. Last 20 reaped invocations (`type = 'Reaped'` rows from `v_recent_events`).

Connection info is read from `db/.env` if present, otherwise from libpq env
vars (`PGUSER`, `PGPASSWORD`, `PGDATABASE`, `PGHOST`, `PGPORT`) or
`SPINE_DB_URL`. The command prefers a host-installed `psql`; if none is
on PATH it falls back to `docker compose -f db/docker-compose.yml exec`
against the postgres service.

### Ad-hoc psql

```sh
psql "postgresql://spine:spine_dev_only@127.0.0.1:5432/spine"
```

…or just `make -C db psql` to drop straight into the running container.

## Safety notes

The credentials in `.env.example` are dev-only (`spine` / `spine_dev_only`)
and are intended for a Postgres instance bound to localhost. Do not reuse
them for anything that touches a network you don't control. For central
mode, generate strong credentials and inject them via your secrets manager.
