# `build/kg/indexer/` — Spine KG incremental indexer

Implements `STORY-6.4.1`, `STORY-6.4.2`, `STORY-6.4.3` in `docs/BACKLOG.md`,
satisfying REQ-INIT-6 FR-5 (incremental indexer) with the performance
budget from NFR-1 (≤5min cold-start per 100k LOC, ≤5s for a 10-file
incremental commit).

## What it does

Fills `spine_kg.kg_node` and `spine_kg.kg_edge` (defined in
`db/flyway/sql/V2__spine_kg_schema.sql`) from the source repo.

Two modes:

| Mode | When | Cost |
|---|---|---|
| **Cold-start** | Once, at first install (or after a destructive reset). | O(repo size). |
| **Incremental** | After every git commit (post-commit hook OR watcher tick). | O(changed files). |

The diff engine (`diff_engine.py`) implements the V2 supersede pattern:
re-indexing a changed file does NOT delete the old node — it sets
`valid_to = now()` on the old row and inserts a fresh row carrying the
new `commit_sha`. Point-in-time queries ("what did the graph look like
at commit X?") remain cheap (see `V2__spine_kg_schema.README.md`
§point-in-time).

## Algorithm

### Cold-start (`cold_start_index`)
1. Read git HEAD; upsert it into `kg_index_state` BEFORE the walk (a
   crash mid-walk is recoverable — the next incremental run re-diffs
   anything that changed since).
2. Walk repo with `os.walk`, pruning `.git`, `__pycache__`,
   `node_modules`, `dist`, `build`, `.venv*`.
3. For each file, pick an extractor via `pick_extractor` (uses
   `file_filters.include_globs` / `exclude_globs`).
4. Parse via `parser_runtime.parse_file` (lazy tree-sitter; degrades to
   "file-root only" when the grammar is missing).
5. Batch nodes + edges (size 1000) into `BEGIN; INSERT...; COMMIT;`
   blocks via `psql` so a single bad row can't roll back unrelated batches.
6. Update `kg_index_state` totals.

### Incremental (`incremental_index`)
1. Read `last_indexed_commit_sha`. If missing → instruct caller to
   cold-start first; if equal to HEAD → no-op.
2. `git diff --name-status <last>..HEAD` → list of (status, path).
3. For each changed file:
   - `A`/added → parse new, INSERT.
   - `M`/modified → parse new, load old from DB by `(repo, path)`,
     `diff_file_index`, CLOSE old + INSERT new.
   - `D`/deleted → CLOSE all nodes/edges anchored at the path.
   - `R`/`C`/`T` (rename/copy/typechange) → collapse to `M`.
4. Update cursor + counts in one transaction.

### `reindex_file`
Force-reparse a single file. Used by tests and as a manual repair tool
when an extractor is updated mid-flight.

## Wiring

### Git hook (preferred — zero polling lag)
Run once at install:
```sh
python -c "from build.kg.indexer.watcher_extension import render_post_commit_hook; \
           print(render_post_commit_hook())" \
    > .git/hooks/post-commit
chmod +x .git/hooks/post-commit
```
The hook calls `python -m build.kg.indexer.cli incremental` in the
background and logs to `/tmp/spine-kg-index.log`. Hook failures never
block the commit (post-commit is informational).

### Watcher daemon (fallback when no hook installable)
The existing watcher in `db/watcher/spine_watcher.py` runs a 5-second
tick loop. Register `kg_tick` from `watcher_extension.py` as an
additional tick callback (the watcher is extension-friendly — we never
modified `spine_watcher.py`, just imported from it). On each tick
`kg_tick` checks HEAD against its local cursor; a moved HEAD triggers
`incremental_index`.

## Performance targets (REQ-INIT-6 NFR-1)

| Operation | Target | How we hit it |
|---|---|---|
| Cold-start | ≤5min per 100k LOC | Batched inserts (1000/txn), single psql roundtrip per batch, dirent pruning before parse. |
| Incremental | ≤5s for a 10-file commit | Parse only changed files; per-file DB queries are indexed by `(repo, path)` (V2 partial index `idx_kg_node_repo_valid`). |
| Reindex one file | ≤500ms typical | Single file parse + 1 SELECT + 1 transactional apply. |

## CLI

```
kg-index cold-start  [--repo PATH] [--languages py,ts,bash,md]
kg-index incremental [--repo PATH]
kg-index status                              # JSON: head, last_indexed, behind_by_commits
kg-index reindex-file <file_path> [--repo PATH]
kg-index extractors                          # JSON: every loaded extractor
```

Outputs JSON to stdout. Exit codes: 0 success/no-op, 1 work done with
per-file errors, 2 fatal config (missing `DATABASE_URL` etc.).

## Troubleshooting

- **"no kg_index_state row; run cold-start first"** — incremental
  needs a cursor. Run `kg-index cold-start`.
- **"no extractor for <path>"** — file extension isn't matched by any
  YAML in `build/kg/extractors/`. Add a config (see
  `extractors/README.md` §adding-a-new-language).
- **"tree_sitter grammar X unavailable"** — install the grammar:
  `pip install tree_sitter_<lang>`. Until then, the file gets a single
  file-root node tagged `degraded=true` so the path is still queryable.
- **Stale index after a force-push** — `kg-index incremental` follows
  `git diff` so a rewritten history is handled, but on a hard reset run
  cold-start to be safe.

## Cross-references

- Schema: `db/flyway/sql/V2__spine_kg_schema.sql` and its README.
- Extractors: `build/kg/extractors/*.yaml`, `extractors/README.md`.
- Watcher daemon: `db/watcher/spine_watcher.py` (we hook into it; we
  don't modify it).
- PRD: REQ-INIT-6 §6.5 FR-5, §6.6 NFR-1.
- Backlog: EPIC-6.4 (STORY-6.4.1, 6.4.2, 6.4.3).
