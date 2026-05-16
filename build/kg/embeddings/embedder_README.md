# `build/kg/embeddings/` — Spine KG embedding pipeline

Implements **STORY-6.7.1** (lazy + cached embeddings), **STORY-6.7.2**
(default local embedding model + org-bundle override), and the embedding
half of **STORY-6.7.3** (`hybrid_search` MCP tool — see `shared/mcp/tools/kg.py`).

## Architecture

```
                ┌──────────────────────┐
                │  HybridSearch /      │
                │  Indexer call site   │
                └──────────┬───────────┘
                           │
                    ┌──────▼───────┐
                    │ EmbedderRunner│   (lazy cache + cosine_search)
                    └──────┬───────┘
            ┌──────────────┼──────────────┐
            ▼              ▼              ▼
   LocalEmbeddingProvider  Anthropic…   OpenAI…
   (sentence-transformers)   (SDK)       (SDK)
            │
            └─ fallback: deterministic hashed BoW (stdlib only)
```

- `EmbeddingProvider` is a `typing.Protocol` — easy to swap LangChain
  `MultiVectorRetriever` in later per `memory/spine_tech_stack_decisions.md`.
- All optional deps (`sentence-transformers`, `anthropic`, `openai`) are
  imported **lazily** inside provider `__init__` so importing this module
  never pulls in ML weights or HTTP clients.
- DB I/O is `subprocess psql` (no psycopg), consistent with the rest of
  the KG subsystem (indexer, `shared/mcp/tools/kg.py`).

## Provider comparison

| Provider     | Default model              | Dim (native) | Cost / 1M tok | Latency | Notes                              |
|--------------|----------------------------|--------------|---------------|---------|------------------------------------|
| **local**    | `all-MiniLM-L6-v2`         | 384          | $0            | ~5–10ms | Default. Padded to 768.            |
| local (alt)  | `nomic-embed-text-v1`      | 768          | $0            | ~20ms   | Native 768 — no padding.           |
| anthropic    | `claude-embed-v1`          | 1024 (typ.)  | ~$0.10        | ~80ms   | Truncated to 768.                  |
| openai       | `text-embedding-3-small`   | 1536         | $0.02         | ~50ms   | Truncated to 768.                  |
| fallback     | hashed BoW (stdlib)        | 768          | $0            | <1ms    | Tests/CI only — NOT production.    |

## Switching providers

**Env override (highest precedence):**

```bash
export SPINE_EMBEDDING_PROVIDER=local      # or 'anthropic' / 'openai'
```

**Org bundle (`~/.spine/bundles/<id>/v*/bundle.yaml`):**

```yaml
embedding:
  provider: local
  model_id: nomic-embed-text-v1
```

Resolution: `SPINE_EMBEDDING_PROVIDER` env → `bundle['embedding']` → local default.

## Lazy embedding (STORY-6.7.1)

- Indexer does **not** embed at ingest time (too slow on cold-start).
- `hybrid_search` calls `EmbedderRunner.embed_node(node_id, text)` on
  first touch; the runner checks `kg_node_embedding.text_hash`:
  - **hit** → returns 0 (no work, cached vector reused).
  - **miss / changed text** → embed once, upsert via `ON CONFLICT (node_id)`.
- Subsequent searches read straight from the cached `vector(768)` column;
  cosine ranking happens entirely in Postgres via the IVFFlat index.

## Dimension handling

The V2 schema fixes the column at `vector(768)`. The runner calls
`_fit_dim(vec, 768)` on every write/query:

- `len(vec) == 768` — pass through.
- `len(vec) < 768` — right-pad zeros (e.g. MiniLM 384 → 768).
- `len(vec) > 768` — truncate **and** log `embedding_dim_truncated` warning.

Mismatches don't crash — the pipeline degrades to a workable
approximation so a misconfigured org bundle doesn't take search offline.

## Cross-refs

- **Schema:** `db/flyway/sql/V2__spine_kg_schema.sql`
  (`kg_node_embedding` + IVFFlat cosine index, lists=100).
- **MCP tool:** `shared/mcp/tools/kg.py` → `hybrid_search`
  (STORY-6.7.3 real impl).
- **Stories:** `STORY-6.7.1` (lazy + cached), `STORY-6.7.2` (default
  local + org override), `STORY-6.7.3` (hybrid_search consumer),
  `STORY-6.7.4` (PII/secrets redactor — backlog).
- **Tech decision:** `memory/spine_tech_stack_decisions.md` notes
  LangChain is the documented swap-in path; this module stays stdlib +
  pgvector to keep install minimal.
