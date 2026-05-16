# pgvector image swap (wave-8 smoke-test fix F3)

The `postgres` service in `db/docker-compose.yml` is now
`pgvector/pgvector:pg16` (was `postgres:16-alpine`). Two migrations need
the `vector` extension:

- `V2__*` — KG embedding columns (`spine_kg.embeddings`)
- `V20__*` — Memory lessons embedding column (`spine_memory.lessons.embedding`)

Stock `postgres:16-alpine` has no pgvector, so V2 was skipped and V20
applied with the embedding column silently dropped. The pgvector image
ships Postgres 16 + the `vector` extension files; everything else
(config, data dir layout, defaults) is identical.

## Recreate procedure

```sh
cd db
make down     # docker compose down — stops, removes container, keeps volume
make up       # docker compose up -d — recreates container with new image
```

The named volume `spine_pgdata` survives `docker compose down`; only
`down -v` would wipe it. All existing data (lifecycle rows, audit, etc.)
is preserved across the recreate.

## Post-recreate verification

```sh
docker exec spine_postgres psql -U spine -c \
  "SELECT * FROM pg_available_extensions WHERE name='vector';"
```

Expect one row with `installed_version` populated after the V2
migration runs (V2 already issues `CREATE EXTENSION IF NOT EXISTS
vector` so no extra step needed).

If V2 was previously marked applied with a different checksum, run
`flyway repair` once (Tier-2 fix F2) before `flyway migrate`.
