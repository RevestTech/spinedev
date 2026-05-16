-- V20: Spine vector-backed role memory — INIT-4 EPIC-4.2 (STORY-4.2.1/2/3).
--
-- Per-role lesson store with project + cross_project scope, lazy 768-dim
-- pgvector embeddings (matches V2 spine_kg.kg_node_embedding), and a
-- retrieval_log for analytics + future eviction (STORY-4.2.4). Embedding
-- dimension intentionally matches kg_node_embedding so the same
-- EmbedderRunner provider pipeline is reused without padding mismatch.

CREATE SCHEMA IF NOT EXISTS spine_memory;
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;  -- gen_random_uuid()

COMMENT ON SCHEMA spine_memory IS
'Vector-backed per-role + cross-project lessons. See EPIC-4.2 and shared/memory/.';

-- ─────────────────────────────────────────────────────────────────────
-- lesson — one row per durable lesson; supersede via valid_from/valid_to
-- ─────────────────────────────────────────────────────────────────────

CREATE TABLE spine_memory.lesson (
    id               bigserial   PRIMARY KEY,
    lesson_uuid      uuid        NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    role             text        NOT NULL,
    scope            text        NOT NULL CHECK (scope IN ('project', 'cross_project')),
    project_id       bigint,
    lesson_text      text        NOT NULL,
    source_path      text        NOT NULL,
    line_in_source   integer,
    tags             text[]      NOT NULL DEFAULT '{}',
    created_at       timestamptz NOT NULL DEFAULT now(),
    last_retrieved   timestamptz,
    retrieval_count  integer     NOT NULL DEFAULT 0,
    embedding        vector(768),
    text_hash        text        NOT NULL,
    valid_from       timestamptz NOT NULL DEFAULT now(),
    valid_to         timestamptz,
    CONSTRAINT lesson_scope_project_consistency CHECK (
        (scope = 'cross_project' AND project_id IS NULL)
        OR (scope = 'project')
    )
);

COMMENT ON TABLE  spine_memory.lesson IS
'Individual lesson from teams/<role>/memory.md (project) or '
'~/.spine-development/playbook/<role>/lessons.md (cross_project). Embedding '
'is lazy-populated on first retrieval (matches STORY-6.7.1). valid_to=NULL '
'means current; supersede pattern on text change preserves history.';

CREATE INDEX idx_lesson_role_scope_valid
    ON spine_memory.lesson (role, scope)
    WHERE valid_to IS NULL;
CREATE INDEX idx_lesson_project
    ON spine_memory.lesson (project_id)
    WHERE valid_to IS NULL;
CREATE INDEX idx_lesson_tags_gin
    ON spine_memory.lesson USING gin (tags);
CREATE INDEX idx_lesson_text_hash
    ON spine_memory.lesson (text_hash);
CREATE INDEX idx_lesson_embedding_ivfflat_cosine
    ON spine_memory.lesson
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 50)
    WHERE embedding IS NOT NULL;

-- ─────────────────────────────────────────────────────────────────────
-- retrieval_log — every recall for analytics + future eviction policy
-- ─────────────────────────────────────────────────────────────────────

CREATE TABLE spine_memory.retrieval_log (
    id               bigserial   PRIMARY KEY,
    recall_at        timestamptz NOT NULL DEFAULT now(),
    role             text        NOT NULL,
    project_id       bigint,
    query_text       text        NOT NULL,
    lessons_returned bigint[]    NOT NULL DEFAULT '{}',
    top_k            integer     NOT NULL
);

COMMENT ON TABLE spine_memory.retrieval_log IS
'Per-recall audit; feeds eviction (STORY-4.2.4) and observability.';
CREATE INDEX idx_retrieval_log_role_time
    ON spine_memory.retrieval_log (role, recall_at DESC);

-- ─────────────────────────────────────────────────────────────────────
-- Views — freshness + eviction candidates (STORY-4.2.4 read shape)
-- ─────────────────────────────────────────────────────────────────────

CREATE VIEW spine_memory.v_lesson_freshness AS
SELECT  l.id, l.lesson_uuid, l.role, l.scope, l.project_id,
        l.retrieval_count, l.last_retrieved, l.created_at,
        EXTRACT(EPOCH FROM (now() - l.created_at)) / 86400.0 AS age_days,
        CASE WHEN l.last_retrieved IS NULL THEN NULL
             ELSE EXTRACT(EPOCH FROM (now() - l.last_retrieved)) / 86400.0
        END AS days_since_last_retrieval
FROM    spine_memory.lesson l
WHERE   l.valid_to IS NULL;

COMMENT ON VIEW spine_memory.v_lesson_freshness IS
'Per-lesson retrieval count + age + days-since-last-retrieval for stats CLI.';
CREATE VIEW spine_memory.v_eviction_candidates AS
SELECT  l.id, l.lesson_uuid, l.role, l.scope, l.project_id,
        l.lesson_text, l.created_at,
        EXTRACT(EPOCH FROM (now() - l.created_at)) / 86400.0 AS age_days
FROM    spine_memory.lesson l
WHERE   l.valid_to IS NULL
  AND   l.retrieval_count = 0
  AND   l.created_at < (now() - INTERVAL '90 days');

COMMENT ON VIEW spine_memory.v_eviction_candidates IS
'Lessons never retrieved + older than 90d. Read-only here; STORY-4.2.4 will '
'add an action that supersedes (sets valid_to) on these rows.';

-- ─────────────────────────────────────────────────────────────────────
-- Default privileges — mirror V2 grants
-- ─────────────────────────────────────────────────────────────────────

GRANT USAGE ON SCHEMA spine_memory TO PUBLIC;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES    IN SCHEMA spine_memory TO PUBLIC;
GRANT USAGE,  SELECT, UPDATE         ON ALL SEQUENCES IN SCHEMA spine_memory TO PUBLIC;
ALTER DEFAULT PRIVILEGES IN SCHEMA spine_memory
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES    TO PUBLIC;
ALTER DEFAULT PRIVILEGES IN SCHEMA spine_memory
    GRANT USAGE,  SELECT, UPDATE         ON SEQUENCES TO PUBLIC;
