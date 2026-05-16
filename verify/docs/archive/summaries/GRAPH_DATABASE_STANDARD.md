# Graph-Based Database Design Standard

**Version:** 1.0  
**Date:** April 11, 2026  
**Status:** Standard - Use for All Applications  
**Database:** PostgreSQL 15+ with Graph Extensions

---

## Purpose

This document defines the **standard approach** for implementing graph-based data models in PostgreSQL across all applications. Use this pattern when your application has **relationship-rich data** or requires **hierarchical queries, transitive closures, or dependency tracking**.

---

## When to Use This Pattern

### ✅ Use Graph-Based Design When:

1. **Relationships are first-class citizens** (not just joins)
   - Social networks (followers, friends)
   - Organization charts (reports-to)
   - File systems (directories, dependencies)
   - Product catalogs (categories, related products)

2. **You need transitive queries**
   - "Find all descendants" (recursive hierarchies)
   - "Who reports to this manager transitively?"
   - "All files that depend on this file (direct + indirect)"

3. **You need path finding**
   - Shortest path between entities
   - Detect circular references (deadlocks, circular dependencies)
   - Find connection between two nodes

4. **You need hierarchical data**
   - File/folder trees
   - Category trees
   - Organization hierarchies
   - Tag taxonomies

5. **You need similarity/clustering**
   - "Find related items"
   - "Group similar entities"
   - "Detect duplicates"

### ❌ Don't Use This Pattern When:

1. **Simple one-to-many relationships** (regular foreign keys are sufficient)
2. **Pure analytics/reporting** (use star schema instead)
3. **No relationship queries** (traditional RDBMS is simpler)
4. **Deep graph algorithms needed** (PageRank, community detection → use Neo4j)

---

## Standard Architecture

### Required PostgreSQL Extensions

```sql
-- Enable once per database
CREATE EXTENSION IF NOT EXISTS ltree;        -- Hierarchical data (paths, trees)
CREATE EXTENSION IF NOT EXISTS pg_trgm;      -- Similarity search (fuzzy matching)
CREATE EXTENSION IF NOT EXISTS btree_gist;   -- Advanced indexing for ltree
CREATE EXTENSION IF NOT EXISTS btree_gin;    -- Multi-column indexes

-- Optional: For advanced graph queries
-- CREATE EXTENSION IF NOT EXISTS age;       -- Apache AGE (native graph)
```

**Extension Purposes:**
- **ltree:** Hierarchical paths (e.g., `'root.parent.child'`)
- **pg_trgm:** Fuzzy text search, similarity matching
- **btree_gist/gin:** Efficient indexes for ltree and full-text search

---

## Standard Table Patterns

### Pattern 1: Node Table

**For entities that are graph nodes (users, files, products, etc.)**

```sql
CREATE TABLE {entity_name}_nodes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Business fields
    name TEXT NOT NULL,
    description TEXT,
    
    -- Graph metadata
    node_type VARCHAR(50),  -- For polymorphic nodes
    
    -- Hierarchical path (if applicable)
    path ltree,  -- e.g., 'root.parent.child'
    level INT GENERATED ALWAYS AS (nlevel(path)) STORED,
    
    -- Metrics/cached aggregations
    child_count INT DEFAULT 0,
    descendant_count INT DEFAULT 0,
    
    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- Soft delete
    deleted_at TIMESTAMPTZ
);

-- Standard indexes
CREATE INDEX idx_{entity}_path_gist ON {entity_name}_nodes USING GIST (path);
CREATE INDEX idx_{entity}_path_btree ON {entity_name}_nodes USING BTREE (path);
CREATE INDEX idx_{entity}_name_trgm ON {entity_name}_nodes USING GIN (name gin_trgm_ops);
CREATE INDEX idx_{entity}_type ON {entity_name}_nodes(node_type) WHERE deleted_at IS NULL;
```

### Pattern 2: Edge Table

**For relationships between nodes (follows, depends_on, related_to, etc.)**

```sql
CREATE TABLE {relationship_name}_edges (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Source and target (directed edge)
    source_id UUID NOT NULL REFERENCES {source_table}(id) ON DELETE CASCADE,
    target_id UUID NOT NULL REFERENCES {target_table}(id) ON DELETE CASCADE,
    
    -- Edge type (if multiple relationship types)
    edge_type VARCHAR(50) NOT NULL,
    
    -- Edge weight/strength (optional)
    weight DECIMAL(5,2) DEFAULT 1.0,
    confidence DECIMAL(3,2),  -- For ML-detected relationships
    
    -- Edge metadata (flexible)
    metadata JSONB,
    
    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- Constraints
    UNIQUE(source_id, target_id, edge_type),  -- No duplicate edges
    CHECK (source_id != target_id)  -- No self-loops (optional)
);

-- Standard indexes for graph traversal
CREATE INDEX idx_{rel}_source ON {relationship_name}_edges(source_id);
CREATE INDEX idx_{rel}_target ON {relationship_name}_edges(target_id);
CREATE INDEX idx_{rel}_type ON {relationship_name}_edges(edge_type);

-- Covering index for bidirectional traversal
CREATE INDEX idx_{rel}_covering ON {relationship_name}_edges(source_id, target_id) 
    INCLUDE (edge_type, weight);

-- Partial indexes (if applicable)
CREATE INDEX idx_{rel}_high_confidence ON {relationship_name}_edges(source_id)
    WHERE confidence > 0.8;
```

### Pattern 3: Hierarchical Table (ltree)

**For trees and hierarchies (categories, file paths, org charts)**

```sql
CREATE TABLE {entity_name}_hierarchy (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Hierarchical path
    path ltree NOT NULL UNIQUE,  -- e.g., 'electronics.computers.laptops'
    
    -- Level (computed)
    level INT GENERATED ALWAYS AS (nlevel(path)) STORED,
    
    -- Parent reference (denormalized for convenience)
    parent_id UUID REFERENCES {entity_name}_hierarchy(id) ON DELETE CASCADE,
    
    -- Business fields
    name TEXT NOT NULL,
    slug VARCHAR(100),
    
    -- Cached counts
    direct_children INT DEFAULT 0,
    all_descendants INT DEFAULT 0,
    
    -- Order within siblings
    sort_order INT DEFAULT 0,
    
    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Standard ltree indexes
CREATE INDEX idx_{entity}_path_gist ON {entity_name}_hierarchy USING GIST (path);
CREATE INDEX idx_{entity}_path_btree ON {entity_name}_hierarchy USING BTREE (path);
CREATE INDEX idx_{entity}_parent ON {entity_name}_hierarchy(parent_id);

-- Index for level-based queries
CREATE INDEX idx_{entity}_level ON {entity_name}_hierarchy(level, path);
```

---

## Standard Query Patterns

### Query 1: Find All Descendants (Transitive Closure)

```sql
-- Using Recursive CTE
WITH RECURSIVE descendants AS (
    -- Base case: direct children
    SELECT id, name, 1 AS depth
    FROM {entity_name}_nodes
    WHERE parent_id = :parent_id
    
    UNION ALL
    
    -- Recursive case: children of children
    SELECT n.id, n.name, d.depth + 1
    FROM {entity_name}_nodes n
    JOIN descendants d ON n.parent_id = d.id
    WHERE d.depth < :max_depth  -- Prevent infinite loops
)
SELECT * FROM descendants ORDER BY depth;

-- Alternative: Using ltree (faster for pure hierarchies)
SELECT *
FROM {entity_name}_hierarchy
WHERE path <@ :parent_path::ltree  -- All descendants
ORDER BY path;
```

### Query 2: Find All Ancestors (Bottom-Up)

```sql
-- Using Recursive CTE
WITH RECURSIVE ancestors AS (
    SELECT id, parent_id, name, 0 AS level
    FROM {entity_name}_nodes
    WHERE id = :child_id
    
    UNION ALL
    
    SELECT n.id, n.parent_id, n.name, a.level + 1
    FROM {entity_name}_nodes n
    JOIN ancestors a ON n.id = a.parent_id
)
SELECT * FROM ancestors ORDER BY level DESC;

-- Alternative: Using ltree
SELECT *
FROM {entity_name}_hierarchy
WHERE path @> :child_path::ltree  -- All ancestors
ORDER BY level;
```

### Query 3: Shortest Path Between Two Nodes

```sql
-- Bidirectional search (most efficient)
WITH RECURSIVE 
-- Forward search from source
forward AS (
    SELECT source_id, target_id, 1 AS depth, 
           ARRAY[source_id, target_id] AS path
    FROM {relationship_name}_edges
    WHERE source_id = :source_id
    
    UNION ALL
    
    SELECT e.source_id, e.target_id, f.depth + 1,
           f.path || e.target_id
    FROM {relationship_name}_edges e
    JOIN forward f ON e.source_id = f.target_id
    WHERE f.depth < 10
      AND NOT (e.target_id = ANY(f.path))  -- Prevent cycles
),
-- Backward search from target
backward AS (
    SELECT source_id, target_id, 1 AS depth,
           ARRAY[target_id, source_id] AS path
    FROM {relationship_name}_edges
    WHERE target_id = :target_id
    
    UNION ALL
    
    SELECT e.source_id, e.target_id, b.depth + 1,
           e.source_id || b.path
    FROM {relationship_name}_edges e
    JOIN backward b ON e.target_id = b.source_id
    WHERE b.depth < 10
      AND NOT (e.source_id = ANY(b.path))
)
-- Find shortest path where searches meet
SELECT 
    f.path || array_remove(b.path, f.target_id) AS full_path,
    f.depth + b.depth AS total_distance
FROM forward f
JOIN backward b ON f.target_id = b.source_id
ORDER BY total_distance
LIMIT 1;
```

### Query 4: Detect Circular Dependencies

```sql
WITH RECURSIVE cycle_detection AS (
    SELECT 
        source_id,
        target_id,
        ARRAY[source_id, target_id] AS path,
        false AS is_cycle
    FROM {relationship_name}_edges
    
    UNION ALL
    
    SELECT 
        e.source_id,
        e.target_id,
        cd.path || e.target_id,
        e.target_id = ANY(cd.path[:array_length(cd.path, 1)-1])
    FROM {relationship_name}_edges e
    JOIN cycle_detection cd ON e.source_id = cd.target_id
    WHERE NOT cd.is_cycle
      AND array_length(cd.path, 1) < 50  -- Max cycle length
)
SELECT DISTINCT path
FROM cycle_detection
WHERE is_cycle = true
ORDER BY array_length(path, 1);
```

### Query 5: All Siblings (Same Parent)

```sql
-- Using parent_id
SELECT *
FROM {entity_name}_nodes
WHERE parent_id = (
    SELECT parent_id FROM {entity_name}_nodes WHERE id = :node_id
)
AND id != :node_id;

-- Using ltree
SELECT *
FROM {entity_name}_hierarchy
WHERE path ~ (subpath(:node_path::ltree, 0, nlevel(:node_path::ltree) - 1)::text || '.*{1}')::lquery
  AND path != :node_path::ltree;
```

### Query 6: Find Related Entities by Similarity

```sql
-- Using pg_trgm for fuzzy matching
SELECT 
    id,
    name,
    similarity(name, :search_term) AS sim_score
FROM {entity_name}_nodes
WHERE name % :search_term  -- % is the similarity operator
ORDER BY sim_score DESC
LIMIT 10;

-- Alternative: Levenshtein distance
SELECT 
    id,
    name,
    levenshtein(name, :search_term) AS edit_distance
FROM {entity_name}_nodes
ORDER BY edit_distance
LIMIT 10;
```

---

## Standard Performance Patterns

### Pattern 1: Materialized Views for Aggregations

```sql
-- Cache expensive graph aggregations
CREATE MATERIALIZED VIEW mv_{entity}_graph_stats AS
SELECT 
    n.id,
    n.name,
    COUNT(DISTINCT e_out.target_id) AS outbound_edges,
    COUNT(DISTINCT e_in.source_id) AS inbound_edges,
    AVG(e_out.weight) AS avg_outbound_weight
FROM {entity_name}_nodes n
LEFT JOIN {relationship_name}_edges e_out ON n.id = e_out.source_id
LEFT JOIN {relationship_name}_edges e_in ON n.id = e_in.target_id
GROUP BY n.id, n.name;

-- Standard indexes on materialized view
CREATE INDEX idx_mv_{entity}_id ON mv_{entity}_graph_stats(id);
CREATE INDEX idx_mv_{entity}_outbound ON mv_{entity}_graph_stats(outbound_edges DESC);

-- Refresh strategy (choose one):
-- 1. After each transaction (slow but always fresh)
REFRESH MATERIALIZED VIEW CONCURRENTLY mv_{entity}_graph_stats;

-- 2. Scheduled (fast, slightly stale)
-- Run via cron: REFRESH MATERIALIZED VIEW CONCURRENTLY mv_{entity}_graph_stats;
```

### Pattern 2: Partial Indexes for Common Filters

```sql
-- Index only active/non-deleted nodes
CREATE INDEX idx_{entity}_active ON {entity_name}_nodes(id, name)
    WHERE deleted_at IS NULL;

-- Index only high-weight edges
CREATE INDEX idx_{rel}_strong ON {relationship_name}_edges(source_id, target_id)
    WHERE weight > 0.5;

-- Index only specific edge types
CREATE INDEX idx_{rel}_follows ON {relationship_name}_edges(source_id, target_id)
    WHERE edge_type = 'follows';
```

### Pattern 3: Covering Indexes

```sql
-- Include frequently accessed columns in index
CREATE INDEX idx_{entity}_covering ON {entity_name}_nodes(parent_id) 
    INCLUDE (name, created_at, node_type);

-- Eliminates table lookup for common queries
```

### Pattern 4: Denormalized Counts (Cache)

```sql
-- Add cached counts to node table
ALTER TABLE {entity_name}_nodes
ADD COLUMN cached_child_count INT DEFAULT 0,
ADD COLUMN cached_descendant_count INT DEFAULT 0;

-- Update via trigger
CREATE OR REPLACE FUNCTION update_cached_counts()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        UPDATE {entity_name}_nodes
        SET cached_child_count = cached_child_count + 1
        WHERE id = NEW.parent_id;
    ELSIF TG_OP = 'DELETE' THEN
        UPDATE {entity_name}_nodes
        SET cached_child_count = cached_child_count - 1
        WHERE id = OLD.parent_id;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_update_counts
AFTER INSERT OR DELETE ON {entity_name}_nodes
FOR EACH ROW EXECUTE FUNCTION update_cached_counts();
```

---

## Standard API Patterns

### REST Endpoints for Graph Operations

```python
# Standard graph endpoints

GET /api/{entities}/{id}/descendants?depth=5
# Returns all descendants up to N levels deep

GET /api/{entities}/{id}/ancestors
# Returns all ancestors up to root

GET /api/{entities}/{id}/siblings
# Returns all nodes with same parent

GET /api/{entities}/{id}/related?type=similar&limit=10
# Returns related entities by relationship type

GET /api/{entities}/{id}/path-to/{target_id}
# Returns shortest path between two nodes

GET /api/{entities}/search?q=term&fuzzy=true
# Fuzzy search using pg_trgm

GET /api/graph/{relationship}/cycles
# Detects and returns circular dependencies

POST /api/graph/{relationship}/analyze
# Runs graph algorithms (centrality, clustering, etc.)
```

### GraphQL Schema Pattern

```graphql
type Node {
  id: ID!
  name: String!
  path: String  # ltree path
  
  # Navigation
  parent: Node
  children(depth: Int = 1): [Node!]!
  ancestors: [Node!]!
  descendants(maxDepth: Int = 10): [Node!]!
  siblings: [Node!]!
  
  # Relationships
  outboundEdges(type: String): [Edge!]!
  inboundEdges(type: String): [Edge!]!
  related(type: String, limit: Int = 10): [Node!]!
  
  # Graph metrics
  degree: Int!  # Total edges
  inDegree: Int!  # Inbound edges
  outDegree: Int!  # Outbound edges
}

type Edge {
  id: ID!
  source: Node!
  target: Node!
  edgeType: String!
  weight: Float
  confidence: Float
}

type Query {
  node(id: ID!): Node
  shortestPath(sourceId: ID!, targetId: ID!): [Node!]!
  detectCycles: [[Node!]!]!
}
```

---

## Monitoring & Maintenance

### Standard Monitoring Queries

```sql
-- 1. Graph statistics
SELECT 
    'Nodes' AS entity,
    COUNT(*) AS total,
    COUNT(*) FILTER (WHERE deleted_at IS NULL) AS active,
    AVG(child_count) AS avg_children
FROM {entity_name}_nodes;

-- 2. Edge distribution
SELECT 
    edge_type,
    COUNT(*) AS edge_count,
    AVG(weight) AS avg_weight,
    MIN(weight) AS min_weight,
    MAX(weight) AS max_weight
FROM {relationship_name}_edges
GROUP BY edge_type
ORDER BY edge_count DESC;

-- 3. Hierarchy depth distribution
SELECT 
    level,
    COUNT(*) AS node_count
FROM {entity_name}_hierarchy
GROUP BY level
ORDER BY level;

-- 4. Orphaned nodes (no relationships)
SELECT COUNT(*)
FROM {entity_name}_nodes n
WHERE NOT EXISTS (
    SELECT 1 FROM {relationship_name}_edges WHERE source_id = n.id OR target_id = n.id
);

-- 5. Expensive recursive queries
SELECT 
    query,
    calls,
    mean_exec_time,
    max_exec_time
FROM pg_stat_statements
WHERE query LIKE '%RECURSIVE%'
ORDER BY mean_exec_time DESC
LIMIT 10;
```

### Maintenance Tasks

```sql
-- 1. Rebuild graph statistics (daily)
ANALYZE {entity_name}_nodes;
ANALYZE {relationship_name}_edges;
ANALYZE {entity_name}_hierarchy;

-- 2. Refresh materialized views (hourly)
REFRESH MATERIALIZED VIEW CONCURRENTLY mv_{entity}_graph_stats;

-- 3. Vacuum to reclaim space (weekly)
VACUUM ANALYZE {entity_name}_nodes;
VACUUM ANALYZE {relationship_name}_edges;

-- 4. Reindex for performance (monthly)
REINDEX INDEX CONCURRENTLY idx_{entity}_path_gist;
REINDEX INDEX CONCURRENTLY idx_{rel}_covering;

-- 5. Check for orphaned ltree paths
SELECT path FROM {entity_name}_hierarchy h1
WHERE NOT EXISTS (
    SELECT 1 FROM {entity_name}_hierarchy h2
    WHERE h1.path @> h2.path AND h1.path != h2.path
);
```

---

## Testing Standards

### Required Graph Tests

```sql
-- Test 1: No cycles in directed acyclic graphs (DAGs)
CREATE OR REPLACE FUNCTION test_no_cycles_in_{entity}()
RETURNS BOOLEAN AS $$
DECLARE
    cycle_count INT;
BEGIN
    WITH RECURSIVE cycle_check AS (
        SELECT source_id, target_id, ARRAY[source_id] AS path
        FROM {relationship_name}_edges
        UNION ALL
        SELECT e.source_id, e.target_id, c.path || e.source_id
        FROM {relationship_name}_edges e
        JOIN cycle_check c ON e.source_id = c.target_id
        WHERE NOT (e.source_id = ANY(c.path))
          AND array_length(c.path, 1) < 100
    )
    SELECT COUNT(*) INTO cycle_count
    FROM cycle_check
    WHERE target_id = ANY(path);
    
    RETURN cycle_count = 0;
END;
$$ LANGUAGE plpgsql;

-- Test 2: All ltree paths are valid
CREATE OR REPLACE FUNCTION test_valid_ltree_paths()
RETURNS BOOLEAN AS $$
DECLARE
    invalid_count INT;
BEGIN
    SELECT COUNT(*) INTO invalid_count
    FROM {entity_name}_hierarchy
    WHERE path IS NULL OR path::text = '';
    
    RETURN invalid_count = 0;
END;
$$ LANGUAGE plpgsql;

-- Test 3: Parent-child consistency
CREATE OR REPLACE FUNCTION test_parent_child_consistency()
RETURNS BOOLEAN AS $$
DECLARE
    inconsistent_count INT;
BEGIN
    SELECT COUNT(*) INTO inconsistent_count
    FROM {entity_name}_nodes n1
    WHERE parent_id IS NOT NULL
      AND NOT EXISTS (
          SELECT 1 FROM {entity_name}_nodes n2 WHERE n2.id = n1.parent_id
      );
    
    RETURN inconsistent_count = 0;
END;
$$ LANGUAGE plpgsql;

-- Run all tests
SELECT 
    'No Cycles' AS test,
    test_no_cycles_in_{entity}() AS passed
UNION ALL
SELECT 
    'Valid ltree Paths',
    test_valid_ltree_paths()
UNION ALL
SELECT 
    'Parent-Child Consistency',
    test_parent_child_consistency();
```

---

## Migration Checklist

### Phase 1: Setup (Week 1)
- [ ] Enable required PostgreSQL extensions
- [ ] Create node and edge tables
- [ ] Add standard indexes
- [ ] Implement basic CRUD operations

### Phase 2: Populate (Week 2)
- [ ] Migrate existing data to graph structure
- [ ] Build initial relationships/edges
- [ ] Populate ltree paths for hierarchies
- [ ] Validate data integrity

### Phase 3: Queries (Week 3)
- [ ] Implement standard graph queries
- [ ] Add materialized views for aggregations
- [ ] Create API endpoints for graph operations
- [ ] Add query performance monitoring

### Phase 4: Optimize (Week 4)
- [ ] Add covering indexes
- [ ] Create partial indexes for common filters
- [ ] Set up materialized view refresh schedule
- [ ] Implement denormalized counts/caches

### Phase 5: Test & Monitor (Ongoing)
- [ ] Run integrity tests (cycles, orphans, consistency)
- [ ] Monitor query performance
- [ ] Set up alerts for slow queries
- [ ] Document query patterns for team

---

## Decision Matrix

**When to use different graph storage approaches:**

| Requirement | PostgreSQL + Graph | Neo4j | NetworkX (Python) |
|-------------|-------------------|-------|-------------------|
| **Transactional integrity** | ✅ Excellent | ⚠️ Limited | ❌ None |
| **1-3 hop queries** | ✅ Excellent | ✅ Excellent | ✅ Excellent |
| **Deep traversal (5+ hops)** | ⚠️ Good | ✅ Excellent | ✅ Excellent |
| **Graph algorithms** | ❌ Limited | ✅ Excellent | ✅ Excellent |
| **Mixed workload (OLTP + graph)** | ✅ Excellent | ❌ Poor | ❌ None |
| **Operational simplicity** | ✅ Simple | ❌ Complex | ✅ Simple |
| **Scalability** | ✅ High | ✅ Very High | ⚠️ Medium |
| **Ecosystem maturity** | ✅ Excellent | ⚠️ Good | ✅ Excellent |

**Recommendation:** Start with PostgreSQL + graph extensions. Add Neo4j or NetworkX only if specific advanced graph algorithms are needed.

---

## Examples by Use Case

### Use Case 1: Social Network
- **Nodes:** users
- **Edges:** follows, blocks, friends
- **Queries:** "Who follows me?", "Mutual friends", "Suggested follows"

### Use Case 2: File System
- **Nodes:** files, directories (ltree)
- **Edges:** contains, depends_on
- **Queries:** "All files in /src/", "Files depending on X", "Circular imports"

### Use Case 3: Product Catalog
- **Nodes:** products, categories (ltree)
- **Edges:** related_to, frequently_bought_together
- **Queries:** "Category tree", "Related products", "Cross-sell recommendations"

### Use Case 4: Organization Chart
- **Nodes:** employees (ltree)
- **Edges:** reports_to, mentors
- **Queries:** "All reports (transitive)", "Management chain", "Peer group"

### Use Case 5: Knowledge Graph
- **Nodes:** entities, concepts
- **Edges:** related_to, caused_by, part_of
- **Queries:** "Related concepts", "Root causes", "Shortest path between ideas"

---

## Summary

**This standard provides:**
- ✅ Proven table patterns (nodes, edges, hierarchies)
- ✅ Standard query templates (recursive CTEs, ltree)
- ✅ Performance optimizations (indexes, materialized views)
- ✅ API patterns (REST, GraphQL)
- ✅ Testing strategies (integrity checks)
- ✅ Monitoring queries (statistics, slow queries)

**Result:** A scalable, searchable, relationship-rich database design that works for any application domain using PostgreSQL.

---

**Document Version:** 1.0  
**Last Updated:** April 11, 2026  
**Status:** ✅ Standard - Ready for Use Across All Applications
