# `shared/memory/` — vector-backed role memory

Implements **STORY-4.2.1/2/3** (INIT-4 EPIC-4.2): vector store + embedding
pipeline, per-role lesson retrieval at directive time, and cross-project
semantic recall from `~/.spine-development/playbook/`. See `docs/BACKLOG.md`.

## Why

Per-role `memory.md` is good but doesn't scale: when a role daemon
starts it sees the whole file regardless of relevance, and once a role
accumulates dozens of bullets the prompt budget goes to lessons the
directive doesn't need. Vector-backed retrieval injects only the top-K
relevant prior lessons. Lifted from **ruflo** and adapted to Spine's
Postgres-single-source-of-truth stance — lessons live in the
`spine_memory` schema (V20) and reuse the `vector(768)` shape from
`spine_kg.kg_node_embedding` (V2).

## Architecture

```
teams/<role>/memory.md      ~/.spine-development/playbook/<role>/lessons.md
       │   scope='project'                  │   scope='cross_project'
       ▼                                    ▼
       ┌──────────────────────────────────────┐
       │ LessonIndexer  (lesson_indexer.py)   │  parse bullets, SHA-256
       │   parse → INSERT (no embed yet)      │  dedupe, supersede on change
       └────────────────────┬─────────────────┘
                            ▼
                 spine_memory.lesson (V20)
                            │  first recall
                            ▼
       ┌──────────────────────────────────────┐
       │ LessonStore.recall  (lesson_store.py)│  lazy-embed missing,
       │   pgvector cosine search             │  union project+cross_project
       └────────────────────┬─────────────────┘
                            ▼
       RecallResult.lessons → format_for_prompt_injection(...)
                            ▼
              injected into role prompt at directive time
```

`PlaybookStore` (`playbook_store.py`) is a thin wrapper that indexes
`~/.spine-development/playbook/<role>/lessons.md` on first call
(idempotent, per process), recalls only `scope='cross_project'` rows,
and exposes `promote_to_playbook(lesson_id, rationale)`.

## Lazy embedding

Mirrors `build/kg/embeddings/embedder.py` (STORY-6.7.1): embeddings are
NOT computed at index time. On the first `recall_lessons(...)` call for
a (role, scope), any rows whose `embedding` column is still `NULL` are
embedded through the same `EmbedderRunner` / `select_provider()` chain
— so `SPINE_EMBEDDING_PROVIDER` and the org bundle override apply
uniformly across KG and memory. `text_hash` (SHA-256 of the lesson
text) lets the indexer skip unchanged rows; changed or removed lessons
are superseded (`valid_to = now()`) so history is preserved.

## Project vs cross-project scope

| Scope            | Source file                                              | `project_id` |
|------------------|----------------------------------------------------------|--------------|
| `project`        | `teams/<role>/memory.md`                                 | required     |
| `cross_project`  | `~/.spine-development/playbook/<role>/lessons.md`        | always NULL  |

`recall_lessons(..., include_cross_project=True)` unions both scopes
and applies a 0.85 distance multiplier to cross-project rows so
project-specific lessons win on ties.

## Promotion path

`promote_to_playbook(lesson_id, rationale)` appends a project lesson to
`~/.spine-development/playbook/<role>/lessons.md` under a "Promoted
from project memory" heading (with rationale in an HTML comment) and
re-indexes the file as `scope='cross_project'`. The on-disk file is the
source of truth — greppable, shareable across machines; the DB row is
a derived index used at recall time. Idempotent — re-promoting an
already-present lesson is a no-op.

## Integration (follow-up, NOT in this commit)

The role daemon will call

```python
from shared.memory import recall_lessons, format_for_prompt_injection
r = recall_lessons(role="engineer", query_text=directive_text,
                   project_id=PROJECT_ID, top_k=5)
prompt += "\n\n" + format_for_prompt_injection(r.lessons)
```

before invoking the role agent. Deferred so this commit is library-only.

## Cross-refs

- **STORY-4.2.1/2/3** — `docs/BACKLOG.md` INIT-4 EPIC-4.2.
- **STORY-4.2.4** — `v_eviction_candidates` view defined here; action
  is left for the follow-up story.
- **STORY-6.7.1** — lazy + cached embeddings (KG pattern reused).
- **ruflo** — origin of the per-role semantic recall idea.
- **`build/kg/embeddings/embedder.py`** — `EmbedderRunner` reused verbatim.
- **`db/flyway/sql/V20__spine_memory_schema.sql`** — backing schema.
