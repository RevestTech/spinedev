-- V2: Spine Knowledge Graph (KG) schema — INIT-6 (STORY-6.1.1 / STORY-6.1.2).
--
-- Implements REQ-INIT-6 FR-1 (node + edge taxonomy), FR-2 (storage in existing
-- Postgres), NFR-1 (indexed for sub-second filter queries), NFR-6 (point-in-
-- time queries via valid_from/valid_to + commit_sha snapshot pattern).
--
-- The KG is foundational, cross-cutting infrastructure consumed by all three
-- Spine subsystems (Plan, Build, Verify). It stores parsed code (functions,
-- classes, calls, imports), parsed docs (REQs, PRDs, TRDs, ADRs, role memory),
-- and Spine flow entities (Initiatives, Epics, Stories) as a single hybrid
-- graph + vector store inside the existing Postgres instance (no Neo4j, no
-- separate vector DB — keeps with the single-Postgres principle of this repo).
--
-- Node/edge `type` columns are open strings (not ENUMs) so new node and edge
-- kinds can be added by the indexer without a schema migration; see README.

-- ─────────────────────────────────────────────────────────────────────
-- Schema + extensions
-- ─────────────────────────────────────────────────────────────────────

CREATE SCHEMA IF NOT EXISTS spine_kg;

-- pgvector for embedding storage (NFR-2: hybrid graph + vector retrieval).
CREATE EXTENSION IF NOT EXISTS vector;

COMMENT ON SCHEMA spine_kg IS
'Spine Knowledge Graph — parsed code, docs, and flow entities. See REQ-INIT-6.';

-- ─────────────────────────────────────────────────────────────────────
-- kg_node — every entity (code, doc, flow, ops) is a node
-- ─────────────────────────────────────────────────────────────────────

CREATE TABLE spine_kg.kg_node (
    id           bigserial   PRIMARY KEY,
    node_id      text        NOT NULL UNIQUE,
    type         text        NOT NULL,
    subtype      text,
    repo         text        NOT NULL,
    commit_sha   text        NOT NULL,
    path         text,
    name         text,
    properties   jsonb       NOT NULL DEFAULT '{}'::jsonb,
    created_at   timestamptz NOT NULL DEFAULT now(),
    valid_from   timestamptz NOT NULL DEFAULT now(),
    valid_to     timestamptz
);

COMMENT ON TABLE  spine_kg.kg_node IS
'Core KG entity. Open `type` taxonomy: File/Module/Class/Function/Method/'
'Variable/TypeDef/TestFile/TestCase/Document/Heading/Reference/Initiative/'
'Epic/Story/Directive/Report/Role/AuditEvent/Issue/PullRequest/Commit/Person/'
'CustomNode. New types are added by inserting rows — no schema change.';
COMMENT ON COLUMN spine_kg.kg_node.node_id IS
'Stable external ID (e.g., python:module:auth.session:Class:SessionManager). '
'Deterministic across re-indexes so upserts are idempotent.';
COMMENT ON COLUMN spine_kg.kg_node.subtype IS
'Refines `type` (e.g., Document subtype: REQ|PRD|TRD|ADR|Roadmap|README|'
'role-prompt|memory).';
COMMENT ON COLUMN spine_kg.kg_node.commit_sha IS
'Snapshot commit this node was parsed from. Pair with valid_from/valid_to for '
'point-in-time queries (NFR-6).';
COMMENT ON COLUMN spine_kg.kg_node.path IS
'For code/doc nodes, `file[:line]` within the repo.';
COMMENT ON COLUMN spine_kg.kg_node.properties IS
'Free-form attributes (signature, docstring, line ranges, owner, ...). '
'Hot filter keys should be denormalized into kg_node_property.';
COMMENT ON COLUMN spine_kg.kg_node.valid_to IS
'NULL means "currently valid". Set on supersede/delete so historical reads at '
'a prior timestamp still resolve cleanly.';

CREATE INDEX idx_kg_node_type_repo_commit
    ON spine_kg.kg_node (type, repo, commit_sha);
CREATE INDEX idx_kg_node_repo_valid
    ON spine_kg.kg_node (repo)
    WHERE valid_to IS NULL;
CREATE INDEX idx_kg_node_properties_gin
    ON spine_kg.kg_node USING gin (properties jsonb_path_ops);

-- ─────────────────────────────────────────────────────────────────────
-- kg_edge — typed relationships between nodes
-- ─────────────────────────────────────────────────────────────────────

CREATE TABLE spine_kg.kg_edge (
    id            bigserial   PRIMARY KEY,
    from_node_id  bigint      NOT NULL REFERENCES spine_kg.kg_node (id) ON DELETE CASCADE,
    to_node_id    bigint      NOT NULL REFERENCES spine_kg.kg_node (id) ON DELETE CASCADE,
    type          text        NOT NULL,
    commit_sha    text        NOT NULL,
    properties    jsonb       NOT NULL DEFAULT '{}'::jsonb,
    valid_from    timestamptz NOT NULL DEFAULT now(),
    valid_to      timestamptz
);

COMMENT ON TABLE  spine_kg.kg_edge IS
'Typed relationship between two kg_node rows. Open `type` taxonomy: CALLS, '
'IMPORTS, DEFINES, REFERENCES, OVERRIDES, EXTENDS, IMPLEMENTS, CONTAINS, '
'TESTS, COVERS, LINKS_TO, CITES, SUPERSEDES, DERIVED_FROM, APPROVED_BY, '
'TOUCHES, SATISFIES, DECIDED_BY, TESTED_BY, OWNED_BY, PRODUCED_BY, PART_OF, '
'PRODUCED, LOCKED_TO. Same point-in-time semantics as kg_node.';
COMMENT ON COLUMN spine_kg.kg_edge.commit_sha IS
'Snapshot commit at which this edge was observed (matches kg_node.commit_sha).';

CREATE INDEX idx_kg_edge_from_type ON spine_kg.kg_edge (from_node_id, type);
CREATE INDEX idx_kg_edge_to_type   ON spine_kg.kg_edge (to_node_id,   type);
CREATE INDEX idx_kg_edge_type_commit
    ON spine_kg.kg_edge (type, commit_sha);

-- ─────────────────────────────────────────────────────────────────────
-- kg_node_embedding — pgvector store (one row per node)
-- ─────────────────────────────────────────────────────────────────────

CREATE TABLE spine_kg.kg_node_embedding (
    node_id     bigint      PRIMARY KEY REFERENCES spine_kg.kg_node (id) ON DELETE CASCADE,
    model       text        NOT NULL,
    embedding   vector(768) NOT NULL,
    text_hash   text        NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE  spine_kg.kg_node_embedding IS
'Dense semantic embedding for a node. 768-dim default fits nomic-embed-text-v1 '
'and most BGE/MiniLM models; switch dimension by amending this column.';
COMMENT ON COLUMN spine_kg.kg_node_embedding.text_hash IS
'SHA-256 (or similar) of the source text. Lets the indexer skip re-embedding '
'when the text has not changed.';
COMMENT ON COLUMN spine_kg.kg_node_embedding.model IS
'Embedding model identifier (e.g., nomic-embed-text-v1). Multiple models for '
'the same node would require a composite PK — out of scope for v1.';

-- IVFFlat with cosine distance — good balance of recall and speed at our
-- expected corpus size (~ tens of thousands of nodes per repo).
CREATE INDEX idx_kg_embedding_ivfflat_cosine
    ON spine_kg.kg_node_embedding
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

-- ─────────────────────────────────────────────────────────────────────
-- kg_node_property — denormalized hot-key index
-- ─────────────────────────────────────────────────────────────────────

CREATE TABLE spine_kg.kg_node_property (
    node_id bigint NOT NULL REFERENCES spine_kg.kg_node (id) ON DELETE CASCADE,
    key     text   NOT NULL,
    value   text   NOT NULL,
    PRIMARY KEY (node_id, key)
);

COMMENT ON TABLE spine_kg.kg_node_property IS
'Denormalized projection of selected hot keys from kg_node.properties. The '
'indexer chooses which keys to project (e.g., owner, language, requirement). '
'The (key, value) index supports "find all nodes with key=X, value=Y" in O(log n).';

CREATE INDEX idx_kg_node_property_key_value
    ON spine_kg.kg_node_property (key, value);

-- ─────────────────────────────────────────────────────────────────────
-- kg_index_state — per-repo indexer cursor
-- ─────────────────────────────────────────────────────────────────────

CREATE TABLE spine_kg.kg_index_state (
    repo                     text        PRIMARY KEY,
    last_indexed_commit_sha  text        NOT NULL,
    last_indexed_at          timestamptz NOT NULL DEFAULT now(),
    node_count               integer     NOT NULL DEFAULT 0,
    edge_count               integer     NOT NULL DEFAULT 0,
    embedding_count          integer     NOT NULL DEFAULT 0
);

COMMENT ON TABLE spine_kg.kg_index_state IS
'Tracks the indexer''s last successful run per repo. Drives "what is stale?" '
'dashboards and lets the indexer resume from the prior commit.';

-- ─────────────────────────────────────────────────────────────────────
-- Default privileges — let the app role created in V1 use the new schema
-- ─────────────────────────────────────────────────────────────────────

GRANT USAGE ON SCHEMA spine_kg TO PUBLIC;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES    IN SCHEMA spine_kg TO PUBLIC;
GRANT USAGE,  SELECT, UPDATE         ON ALL SEQUENCES IN SCHEMA spine_kg TO PUBLIC;

ALTER DEFAULT PRIVILEGES IN SCHEMA spine_kg
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES    TO PUBLIC;
ALTER DEFAULT PRIVILEGES IN SCHEMA spine_kg
    GRANT USAGE,  SELECT, UPDATE         ON SEQUENCES TO PUBLIC;
