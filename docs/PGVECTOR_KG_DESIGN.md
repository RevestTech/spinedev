# Pgvector KG search — design note

> **Status:** Plan (no code). Owner: D1 (2026-05-29 parallel batch).
> Pairs with `MASTER_TODO.md` P3 row "pgvector for KG search — known
> separate issue" and unblocks the second half of `V3_DESIGN_DECISIONS.md`
> #20 (cloud breadth) wherever the underlying managed Postgres lacks the
> `vector` extension. Cross-references `V2__spine_kg_schema.sql`,
> `build/kg/embeddings/embedder.py`, `shared/runtime/kg_role_context.py`,
> and `shared/mcp/tools/kg.py::hybrid_search`.

## 1. Problem statement

The KG search path is wired end-to-end on paper — `hybrid_search` embeds
the query, calls `EmbedderRunner.cosine_search` against
`spine_kg.kg_node_embedding`, fuses with a structural BFS via RRF, and
returns ranked nodes. In practice three things are broken:

1. **Extension is not guaranteed present.** `tools/smoke-test.sh` phase 7
   already emits `opt.pgvector "pgvector unavailable (F3) — switch image
   to pgvector/pgvector:pg16"` whenever the managed PG image lacks the
   extension; phase 6 then *skips* the KG fixture rather than degrading.
   Customers on managed PG that does not ship `vector` get a silent
   no-result KG with no fallback.
2. **Embeddings are populated lazily and inconsistently.** The indexer
   (`build/kg/indexer/indexer.py`) writes nodes/edges; nothing in the
   indexer calls `EmbedderRunner.embed_batch`, so embeddings exist only
   for nodes that some other code path (the embedder CLI, sweep, or a
   direct test) has touched. `hybrid_search` therefore returns
   semantically-empty results for any node never embedded.
3. **DB creds are env-strings.** Both `EmbedderRunner` and the KG MCP
   tools read `SPINE_DB_URL` from the process env. That violates V3 #9
   (vault-only secrets) and must be remediated as part of any change we
   make to the cosine-search path.

`hybrid_search` has no documented degradation path: if the embedder
fails (no `vector` extension, no provider, no DB URL), it returns an
`error` `ToolResponse` and `kg_role_context.retrieve_kg_context_for_dispatch`
silently returns `""`. Roles end up dispatched **without** KG context,
which is exactly the failure mode `search-first` (V3 #7b) is supposed
to prevent.

The work is therefore not "introduce pgvector" — V2 already declares
`CREATE EXTENSION IF NOT EXISTS vector;` and an IVFFlat cosine index —
but: **harden the existing pgvector path, give it a real fallback, and
make it work across the 5+ cloud providers in V3 #20.**

## 2. Schema change

Two delta migrations, additive only, never rewriting V2:

1. **HNSW alongside IVFFlat.** IVFFlat is fine at 10⁴ nodes but degrades
   on recall once we cross ~10⁵ and requires `lists` retuning per
   corpus. pgvector 0.5+ ships `hnsw` with much better recall at the
   cost of one-time build time. We keep IVFFlat as the primary on
   pgvector ≤ 0.4 builds (Railway / DO still ship 0.4 at time of
   writing) and add HNSW conditionally on ≥ 0.5.

2. **Provider + dimension stored per row.** The V2 schema bakes
   `vector(768)` into the column. Adding a second model means a
   destructive `ALTER COLUMN TYPE`. We add a sibling table
   `kg_node_embedding_v2` only when a second model is actually
   introduced — out of scope for this change but documented as the
   migration path.

3. **Capability table.** New `spine_kg.kg_search_capability` (single
   row) records whether `vector` is present, the pgvector version, and
   which ANN index strategy was applied. Read by `hybrid_search` to
   decide whether to take the pgvector path or the fallback.

```sql
-- V40__pgvector_search_hardening.sql (proposed)

-- 1) Idempotent: re-affirm the extension. NOOPs if absent + extension
--    cannot be installed by the migration role (managed PG case).
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'vector') THEN
    CREATE EXTENSION IF NOT EXISTS vector;
  ELSE
    RAISE NOTICE 'pgvector unavailable on this Postgres — KG search will use the substring fallback path.';
  END IF;
END$$;

-- 2) Capability table — single row, read by the MCP layer at dispatch.
CREATE TABLE IF NOT EXISTS spine_kg.kg_search_capability (
    singleton boolean PRIMARY KEY DEFAULT true,
    pgvector_available boolean NOT NULL,
    pgvector_version text,
    ann_strategy text NOT NULL CHECK (ann_strategy IN ('hnsw','ivfflat','none')),
    detected_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT one_row CHECK (singleton)
);

-- 3) HNSW index only if the extension exists AND version >= 0.5.0.
DO $$
DECLARE v text;
BEGIN
  SELECT extversion INTO v FROM pg_extension WHERE extname = 'vector';
  IF v IS NULL THEN
    INSERT INTO spine_kg.kg_search_capability(pgvector_available, ann_strategy)
      VALUES (false, 'none')
      ON CONFLICT (singleton) DO UPDATE
        SET pgvector_available=false, ann_strategy='none', detected_at=now();
  ELSIF string_to_array(v, '.')::int[] >= ARRAY[0,5,0] THEN
    EXECUTE 'CREATE INDEX IF NOT EXISTS idx_kg_embedding_hnsw_cosine
             ON spine_kg.kg_node_embedding
             USING hnsw (embedding vector_cosine_ops)
             WITH (m = 16, ef_construction = 64)';
    INSERT INTO spine_kg.kg_search_capability(pgvector_available, pgvector_version, ann_strategy)
      VALUES (true, v, 'hnsw')
      ON CONFLICT (singleton) DO UPDATE
        SET pgvector_available=true, pgvector_version=v, ann_strategy='hnsw', detected_at=now();
  ELSE
    INSERT INTO spine_kg.kg_search_capability(pgvector_available, pgvector_version, ann_strategy)
      VALUES (true, v, 'ivfflat')
      ON CONFLICT (singleton) DO UPDATE
        SET pgvector_available=true, pgvector_version=v, ann_strategy='ivfflat', detected_at=now();
  END IF;
END$$;
```

Recommendation: **HNSW for ≥ 0.5, IVFFlat fallback for < 0.5, neither
for managed PG without `vector`** — recorded in `kg_search_capability`
so application code never has to re-probe.

## 3. Migration plan

- Filename: `db/flyway/sql/V40__pgvector_search_hardening.sql`
  (next free V## after `V37__project_role_log.sql`). README sibling
  `V40__pgvector_search_hardening.README.md` documenting rationale +
  per-provider behavior.
- **Idempotent enable.** The `DO $$ ... $$` block above never fails
  Flyway on managed PG without the extension; it records `none` in the
  capability row and proceeds.
- **No `ALTER COLUMN` on existing tables.** V2's `vector(768)` column
  remains untouched. Zero downtime; zero existing-row rewrite.
- **Provider matrix (V3 #20).**

  | Provider | `vector` ext | Notes |
  |---|---|---|
  | AWS RDS for PG ≥ 15.2 | yes (native) | Enable via parameter group + `CREATE EXTENSION`. |
  | Azure Database for PG (Flexible) | yes (≥ 15) | `azure.extensions = VECTOR` server param required first. |
  | GCP Cloud SQL for PG ≥ 15 | yes | Flag `cloudsql.enable_pgvector = on`. |
  | Railway | yes (image `pgvector/pgvector`) | Already our docker default. |
  | Fly.io | yes (managed image option) | Choose pgvector image at provisioning. |
  | DigitalOcean Managed PG | no on standard; yes on PG 16+ since Aug-2024 | Substring fallback or BYO unmanaged. |
  | Supabase / Neon | yes | Out of scope for v1.0 but flagged. |

## 4. Python client changes

Minimal-diff plan — code lands in a follow-up PR, not this note.

- **`build/kg/embeddings/embedder.py`**
  - `EmbedderRunner.__init__`: stop reading `SPINE_DB_URL` from env;
    accept a `db_url_provider: Callable[[], str]` whose default delegates
    to `shared.secrets.get_secret("db/spine/url")`.
  - Add `EmbedderRunner.capability() -> str` returning the cached
    `ann_strategy` from `spine_kg.kg_search_capability`.
  - `cosine_search`: short-circuit with `RuntimeError("pgvector_unavailable")`
    when capability is `'none'`; caller decides the fallback.

- **`shared/runtime/kg_role_context.py`**
  - New helper `_substring_fallback_block(repo, query)` that issues a
    bounded `kg_node`-only query via `shared.mcp.invoke_mcp_tool` against
    `graph_query` + JSONB / ILIKE on `name`, `path`, `properties->>'docstring'`.
    Same Markdown output shape as `format_hybrid_search_block` so the
    caller is provider-agnostic.
  - `retrieve_kg_context_for_dispatch`: on `hybrid_search` error
    `embedding_provider == "unknown"` OR `data.error.code == "pgvector_unavailable"`,
    invoke the substring fallback and label the block
    `## Knowledge graph context (substring fallback)`.

- **`shared/mcp/tools/kg.py::hybrid_search`**
  - Read `spine_kg.kg_search_capability` once per process (cache).
  - When `ann_strategy == 'none'`: skip embed, run the structural-only
    branch, return `status="degraded"` with `embedding_provider="none"`.
  - Otherwise unchanged; the cosine SQL already runs the right operator
    (`<=>`) regardless of HNSW vs IVFFlat.

Example cosine query the client will issue (unchanged distance op,
HNSW or IVFFlat handles the plan):

```sql
SELECT e.node_id, (e.embedding <=> $1::vector) AS dist
  FROM spine_kg.kg_node_embedding e
  JOIN spine_kg.kg_node n ON n.id = e.node_id
 WHERE (n.valid_to IS NULL OR n.valid_to > now())
   AND n.repo = $2
 ORDER BY e.embedding <=> $1::vector
 LIMIT 50;
```

## 5. Fallback contract

Decision rubric, in order:

1. `kg_search_capability.ann_strategy != 'none'` AND
   `EmbedderRunner.embed_one` succeeds → **vector path**.
2. Else if `n.name`/`n.path` substring on the structurally-relevant
   tokens of `query` returns ≥ 1 row → **substring fallback path**,
   block labeled accordingly, role still gets context.
3. Else → return `""`, role is dispatched without KG context, audit
   event `kg_retrieve_empty` already exists in `kg_role_context.py`.

The fallback NEVER raises; the contract is "best-effort, never break
dispatch." `retrieve_kg_context_for_dispatch` continues to swallow
exceptions per its current docstring.

## 6. Test plan

- **Unit (new) — `shared/runtime/tests/test_kg_role_context_fallback.py`**
  - Capability `'none'` → substring fallback block returned with
    the substring-labeled heading.
  - Capability `'hnsw'` + injected `invoke_mcp_tool` succeeding →
    hybrid_search block returned, no fallback invoked.
  - Capability `'hnsw'` + `invoke_mcp_tool` raising → fallback invoked,
    no exception propagates.

- **Unit (new) — `build/kg/embeddings/tests/test_capability.py`**
  - `EmbedderRunner.capability()` reads + caches one row; missing row
    returns `'none'` (defensive).

- **Smoke — extend `tools/smoke-test.sh` phase 6.**
  - New check `kg.hybrid_search.fallback_works`: with
    `SPINE_KG_FORCE_FALLBACK=1`, `hybrid_search` returns
    `status=degraded` + a non-empty `results` list when at least one
    node matches by substring. Skips cleanly when DB is unreachable
    (same pattern as the existing `kg.fixture` skip).

## 7. Cost / blast-radius

- **Row counts.** `kg_node_embedding` carries one row per current KG
  node — current Spine repo at ~10⁴ nodes; large customer repos will
  trend toward 10⁵. HNSW index build at 10⁵ × 768-dim ≈ 30–60 s and
  ~250 MB. IVFFlat builds faster (≤ 10 s) and is smaller.
- **Query latency.** Expected p50 ≤ 50 ms (HNSW) / ≤ 120 ms (IVFFlat) for
  top-50 at corpus ≤ 10⁵. Existing audit field `query_latency_ms`
  already records this — set an SLO of p99 ≤ 500 ms.
- **Freezes / downtime.** Migration is fully additive: no `ALTER TABLE`,
  no row rewrite, HNSW build is online (`CREATE INDEX ... CONCURRENTLY`
  if we want zero lock — TBD in step 8). No application downtime.
- **Storage delta.** HNSW index ≈ 1.5× the raw vector data. Negligible
  versus the embeddings themselves.

## 8. Decision asks

Before any code lands:

1. **HNSW concurrently?** Use `CREATE INDEX CONCURRENTLY` for HNSW so
   a re-index on a live customer DB never blocks writes. Concurrent
   builds cannot run inside a Flyway transaction — confirm we are OK
   with the split-script pattern (`-- noTransaction` Flyway directive).
2. **Capability table — singleton vs polled?** Should `hybrid_search`
   re-probe `pg_extension` on every dispatch (resilient to
   admin-installs-vector-later) or trust the migration-time snapshot
   in `kg_search_capability` (cheap)? Recommended: trust + emit a
   warn-level audit event nudging admins to re-run migration.
3. **Embedder vault integration.** Confirm the secret key path for the
   DB URL — proposed `db/spine/url`, matching the convention in
   `shared/notify/channels.py`.
4. **Indexer-side embedding hook.** Should `build/kg/indexer/indexer.py`
   call `EmbedderRunner.embed_batch` at the end of each index run, or
   keep embedding lazy via `indexer_sweep.py`? The lazy path is why
   `hybrid_search` is semantically thin today; an opt-in `--embed`
   flag on the indexer CLI is the cheapest fix.
5. **DigitalOcean carve-out.** DO Managed PG on older versions cannot
   install `vector` — do we treat DO as substring-fallback-only at v1.0
   and document it in `docs/V1_SHIP_CHECKLIST.md`, or block v1.0 GA on
   that gap?

---

*Filed 2026-05-29 by D1 in the parallel batch. No code written; this is
a plan. Implementation lands in a follow-up PR with `V40__` migration,
embedder vault refactor, and the substring-fallback path.*
