# V2 — Spine Knowledge Graph schema

Implements `STORY-6.1.1` (schema design) and `STORY-6.1.2` (Flyway migration)
from `docs/BACKLOG.md`, satisfying REQ-INIT-6 FR-1 / FR-2 / NFR-1 / NFR-6.

## Why these node and edge types

REQ-INIT-6 FR-1 says the KG must cover three worlds: parsed code, parsed
docs, and Spine flow entities. The type taxonomy on `kg_node` and `kg_edge`
is the union of those three:

- **Code**: `File`, `Module`, `Class`, `Function`, `Method`, `Variable`,
  `TypeDef`, `TestFile`, `TestCase`.
- **Docs**: `Document` (with subtype `REQ|PRD|TRD|ADR|Roadmap|README|role-prompt|memory`),
  `Heading`, `Reference`.
- **Flow / ops**: `Initiative`, `Epic`, `Story`, `Directive`, `Report`,
  `Role`, `AuditEvent`, `Issue`, `PullRequest`, `Commit`, `Person`,
  `CustomNode`.

Edges (`CALLS`, `IMPORTS`, `DEFINES`, `SATISFIES`, `TESTS`, `COVERS`,
`SUPERSEDES`, `PRODUCED_BY`, ...) connect the worlds — e.g., a `Story`
`SATISFIES` a `REQ`, a `TestCase` `TESTS` a `Function`, a `PullRequest`
`TOUCHES` a `File`, a `Document` `CITES` another `Document`.

Both columns are plain `text`, not enums, so the indexer can introduce new
types (FR-1 explicitly calls out `CustomNode`) without a schema migration.

## Point-in-time queries (NFR-6)

Every node and edge carries `commit_sha`, `valid_from`, and a nullable
`valid_to`. Re-indexing a changed file does not delete the old node — it
sets the old row's `valid_to = now()` and inserts a new row with a fresh
`commit_sha`. A query "what did the graph look like at commit X" becomes:

```sql
SELECT * FROM spine_kg.kg_node
WHERE commit_sha = $1
  AND (valid_to IS NULL OR valid_to > $2);
```

The partial index `idx_kg_node_repo_valid` (where `valid_to IS NULL`) keeps
the steady-state "current view" cheap; the full `(type, repo, commit_sha)`
index covers historical lookups.

## Why pgvector, not a separate vector DB

The Spine project commits to a single-Postgres operational footprint (see
`db/README.md`). Pulling in Qdrant / Weaviate / Pinecone would double the
infrastructure that an installer has to manage and would split transactional
boundaries — a node insert and its embedding insert want to be atomic.
`pgvector` with an IVFFlat cosine index gives sub-second top-k recall at our
expected corpus size (~10⁴–10⁵ nodes per repo) and stays inside the existing
backup / replication story.

The embedding dimension is fixed at 768 (fits `nomic-embed-text-v1` and most
BGE / MiniLM variants). Switching dimension is a small follow-up migration.

## Adding a new node type

No schema change. The indexer:

1. Picks a new string for `kg_node.type` (e.g., `Diagram`, `MetricRule`).
2. Inserts rows with that `type` plus a stable `node_id`.
3. (Optional) Adds extractor config so other indexer passes know about it.
4. (Optional) Projects hot filter keys into `kg_node_property`.

The same applies to edge types and `Document` subtypes.

## Example query: "what calls function X?"

```sql
SELECT caller.node_id, caller.path, caller.name
FROM spine_kg.kg_node       AS callee
JOIN spine_kg.kg_edge       AS e      ON e.to_node_id   = callee.id
JOIN spine_kg.kg_node       AS caller ON caller.id      = e.from_node_id
WHERE callee.node_id = 'python:module:auth.session:Function:rotate_token'
  AND e.type        = 'CALLS'
  AND callee.valid_to IS NULL
  AND caller.valid_to IS NULL;
```

Add `AND e.commit_sha = $commit_sha` to scope to a specific snapshot.
