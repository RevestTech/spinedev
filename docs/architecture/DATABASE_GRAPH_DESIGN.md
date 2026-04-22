# Tron Graph-Based Database Design in PostgreSQL

**Date:** April 11, 2026  
**Version:** 5.1  
**Approach:** PostgreSQL with Graph Modeling + Extensions

---

## Executive Summary

**Decision: Stay with PostgreSQL, but model data as a graph**

**Why NOT a pure graph database:**
- ❌ Adds operational complexity (another database to manage)
- ❌ Tron's core operations are OLTP (transactions), not pure graph traversal
- ❌ Most queries are simple joins, not deep graph traversals
- ❌ Graph databases have worse tooling for aggregations, time-series, and analytics
- ❌ PostgreSQL can handle graph-like queries efficiently with proper modeling

**Why PostgreSQL with Graph Features:**
- ✅ Single database (simpler operations)
- ✅ ACID transactions (critical for cost tracking, audit runs)
- ✅ Mature ecosystem (PgBouncer, replication, backups)
- ✅ Graph capabilities via Recursive CTEs, ltree, foreign keys
- ✅ Excellent for both transactional and analytical queries
- ✅ Can add Apache AGE extension for native graph if needed later

---

## Tron Domain as a Graph

### Natural Graph Relationships

```
Projects
    ↓
AuditRuns ←→ Workflows (Temporal)
    ↓
Findings
    ↓
CodeFiles ←→ Dependencies
    ↓
Rules ←→ Standards ←→ Categories

Cost Tracking:
Projects → LLMUsage → Operations → Workflows

Relationships:
Findings → RelatedFindings (duplicates, similar)
Standards → InheritanceChain (default → company → project)
CodeFiles → DependencyGraph (imports, requires)
```

### Graph Queries We Need

1. **"Find all findings in this file across all audits"**
   - Node: CodeFile
   - Traverse: CodeFile → Findings → AuditRuns

2. **"Trace standards inheritance chain"**
   - Node: ProjectStandards
   - Traverse: Project → Company → Default standards

3. **"Find all related findings (duplicates, similar)"**
   - Node: Finding
   - Traverse: Finding → RelatedFindings (many-to-many)

4. **"Trace cost for a workflow across all LLM calls"**
   - Node: Workflow
   - Traverse: Workflow → LLMUsage → aggregate cost

5. **"Find all files affected by a specific rule across projects"**
   - Node: Rule
   - Traverse: Rule → Findings → Files → Projects

6. **"Dependency graph for code files"**
   - Node: CodeFile
   - Traverse: File → Imports → transitive dependencies

---

## Enhanced Schema with Graph Features

### 1. Add Graph Extensions

```sql
-- Enable extensions for graph-like queries
CREATE EXTENSION IF NOT EXISTS ltree;        -- Hierarchical data
CREATE EXTENSION IF NOT EXISTS pg_trgm;      -- Similarity search
CREATE EXTENSION IF NOT EXISTS btree_gist;   -- For ltree indexing

-- Optional: Apache AGE for native graph (if needed later)
-- CREATE EXTENSION IF NOT EXISTS age;
```

---

### 2. Code Files & Dependencies (NEW)

```sql
-- Code files (nodes in the graph)
CREATE TABLE code_files (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    
    -- File identity
    file_path TEXT NOT NULL,
    file_hash VARCHAR(64) NOT NULL,  -- SHA-256 of content
    
    -- Language/type
    language VARCHAR(50),  -- python, typescript, go, etc.
    file_type VARCHAR(50),  -- source, test, config, etc.
    
    -- Metrics
    lines_of_code INT,
    complexity_score INT,
    
    -- Graph: Parent directory (ltree for hierarchical queries)
    directory_path ltree,  -- e.g., 'src.api.users'
    
    -- Timestamps
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- Unique constraint
    UNIQUE(project_id, file_path)
);

-- Indexes for graph queries
CREATE INDEX idx_code_files_project ON code_files(project_id);
CREATE INDEX idx_code_files_path ON code_files(file_path);
CREATE INDEX idx_code_files_hash ON code_files(file_hash);
CREATE INDEX idx_code_files_directory_gist ON code_files USING GIST (directory_path);
CREATE INDEX idx_code_files_directory_btree ON code_files USING BTREE (directory_path);

-- Similarity search on file paths
CREATE INDEX idx_code_files_path_trgm ON code_files USING GIN (file_path gin_trgm_ops);


-- File dependencies (edges in the graph)
CREATE TABLE file_dependencies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Source and target (directed edge)
    source_file_id UUID NOT NULL REFERENCES code_files(id) ON DELETE CASCADE,
    target_file_id UUID NOT NULL REFERENCES code_files(id) ON DELETE CASCADE,
    
    -- Dependency type
    dependency_type VARCHAR(50) NOT NULL,  -- import, require, include, inherit
    
    -- Import details
    import_statement TEXT,
    is_external BOOLEAN DEFAULT FALSE,  -- External library vs internal
    
    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- Prevent duplicate edges
    UNIQUE(source_file_id, target_file_id, dependency_type),
    
    -- Prevent self-loops (optional)
    CHECK (source_file_id != target_file_id)
);

-- Indexes for graph traversal
CREATE INDEX idx_file_deps_source ON file_dependencies(source_file_id);
CREATE INDEX idx_file_deps_target ON file_dependencies(target_file_id);
CREATE INDEX idx_file_deps_type ON file_dependencies(dependency_type);

-- Composite index for bidirectional traversal
CREATE INDEX idx_file_deps_both ON file_dependencies(source_file_id, target_file_id);
```

---

### 3. Update Findings to Link to Files

```sql
-- Add file_id to findings (was just file_path before)
ALTER TABLE findings
ADD COLUMN file_id UUID REFERENCES code_files(id) ON DELETE SET NULL;

-- Index for graph queries
CREATE INDEX idx_findings_file_id ON findings(file_id);

-- Keep file_path for backward compatibility, but file_id is source of truth
-- Trigger to keep them in sync (optional)
```

---

### 4. Related Findings (Many-to-Many Graph)

```sql
-- Finding relationships (edges)
CREATE TABLE finding_relationships (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Source and target findings
    finding_id UUID NOT NULL REFERENCES findings(id) ON DELETE CASCADE,
    related_finding_id UUID NOT NULL REFERENCES findings(id) ON DELETE CASCADE,
    
    -- Relationship type
    relationship_type VARCHAR(50) NOT NULL,
    -- Types: duplicate, similar, related, caused_by, fixes
    
    -- Confidence score (for ML-detected relationships)
    confidence DECIMAL(3,2) CHECK (confidence >= 0 AND confidence <= 1),
    
    -- Metadata
    reason TEXT,  -- Why are they related?
    detected_by VARCHAR(50),  -- rule, ml_model, user
    
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- Prevent duplicate relationships
    UNIQUE(finding_id, related_finding_id, relationship_type),
    
    -- Prevent self-relationships
    CHECK (finding_id != related_finding_id)
);

-- Indexes for graph traversal
CREATE INDEX idx_finding_rels_finding ON finding_relationships(finding_id);
CREATE INDEX idx_finding_rels_related ON finding_relationships(related_finding_id);
CREATE INDEX idx_finding_rels_type ON finding_relationships(relationship_type);
CREATE INDEX idx_finding_rels_confidence ON finding_relationships(confidence DESC);
```

---

### 5. Standards Inheritance (Hierarchical Graph)

```sql
-- Standards with ltree for inheritance
CREATE TABLE standards (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Hierarchy path using ltree
    -- Examples:
    --   'default' (root)
    --   'default.company_acme'
    --   'default.company_acme.project_website'
    hierarchy_path ltree NOT NULL UNIQUE,
    
    -- Level in hierarchy (computed)
    level INT GENERATED ALWAYS AS (nlevel(hierarchy_path)) STORED,
    
    -- Parent reference (denormalized for easy queries)
    parent_id UUID REFERENCES standards(id) ON DELETE CASCADE,
    
    -- Owner
    project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
    company_id UUID,  -- Future: when multi-tenant
    
    -- Standards content (JSONB for flexibility)
    rules JSONB NOT NULL,
    
    -- Metadata
    name VARCHAR(255) NOT NULL,
    description TEXT,
    version VARCHAR(50),
    
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for hierarchical queries
CREATE INDEX idx_standards_path_gist ON standards USING GIST (hierarchy_path);
CREATE INDEX idx_standards_path_btree ON standards USING BTREE (hierarchy_path);
CREATE INDEX idx_standards_parent ON standards(parent_id);
CREATE INDEX idx_standards_project ON standards(project_id);

-- GIN index for JSONB rules
CREATE INDEX idx_standards_rules ON standards USING GIN (rules);
```

---

## Graph Query Examples

### 1. Find All Findings in a File Across All Audits

```sql
-- Simple join (not really a graph traversal)
SELECT 
    f.id,
    f.title,
    f.severity,
    ar.created_at AS audit_date,
    ar.commit_hash
FROM findings f
JOIN audit_runs ar ON f.audit_run_id = ar.id
JOIN code_files cf ON f.file_id = cf.id
WHERE cf.file_path = '/src/api/users.py'
  AND f.project_id = 'project-uuid'
ORDER BY ar.created_at DESC;
```

### 2. Dependency Graph - Find All Files Depending on a File

```sql
-- Recursive CTE to find transitive dependencies
WITH RECURSIVE dependency_tree AS (
    -- Base case: direct dependencies
    SELECT 
        fd.source_file_id,
        fd.target_file_id,
        cf.file_path AS target_path,
        1 AS depth,
        ARRAY[fd.source_file_id] AS path
    FROM file_dependencies fd
    JOIN code_files cf ON fd.target_file_id = cf.id
    WHERE fd.source_file_id = 'file-uuid'
    
    UNION ALL
    
    -- Recursive case: transitive dependencies
    SELECT 
        fd.source_file_id,
        fd.target_file_id,
        cf.file_path AS target_path,
        dt.depth + 1,
        dt.path || fd.source_file_id
    FROM file_dependencies fd
    JOIN code_files cf ON fd.target_file_id = cf.id
    JOIN dependency_tree dt ON fd.source_file_id = dt.target_file_id
    WHERE dt.depth < 10  -- Prevent infinite loops
      AND NOT (fd.source_file_id = ANY(dt.path))  -- Prevent cycles
)
SELECT DISTINCT target_path, depth
FROM dependency_tree
ORDER BY depth, target_path;
```

### 3. Find Circular Dependencies

```sql
-- Detect cycles in the dependency graph
WITH RECURSIVE cycle_detection AS (
    SELECT 
        source_file_id,
        target_file_id,
        ARRAY[source_file_id, target_file_id] AS path,
        false AS is_cycle
    FROM file_dependencies
    
    UNION ALL
    
    SELECT 
        fd.source_file_id,
        fd.target_file_id,
        cd.path || fd.target_file_id,
        fd.target_file_id = ANY(cd.path[:array_length(cd.path, 1)-1])
    FROM file_dependencies fd
    JOIN cycle_detection cd ON fd.source_file_id = cd.target_file_id
    WHERE NOT cd.is_cycle
      AND array_length(cd.path, 1) < 50
)
SELECT 
    path,
    cf1.file_path AS start_file,
    cf2.file_path AS end_file
FROM cycle_detection
JOIN code_files cf1 ON path[1] = cf1.id
JOIN code_files cf2 ON path[array_length(path, 1)] = cf2.id
WHERE is_cycle = true;
```

### 4. Standards Inheritance Chain

```sql
-- Using ltree to query inheritance
-- Get effective standards for a project (merged from default → company → project)
WITH inheritance_chain AS (
    SELECT 
        s.id,
        s.hierarchy_path,
        s.level,
        s.rules
    FROM standards s
    WHERE 'default.company_acme.project_website' ~ (s.hierarchy_path::text || '.*')::lquery
    ORDER BY s.level DESC  -- Most specific first
)
SELECT * FROM inheritance_chain;

-- Alternative: Get all ancestors of a node
SELECT *
FROM standards
WHERE hierarchy_path @> 'default.company_acme.project_website'::ltree
ORDER BY level;

-- Get all descendants
SELECT *
FROM standards
WHERE hierarchy_path <@ 'default.company_acme'::ltree
ORDER BY level;
```

### 5. Related Findings Graph Traversal

```sql
-- Find all findings related to a specific finding (1 degree)
SELECT 
    f.id,
    f.title,
    f.severity,
    fr.relationship_type,
    fr.confidence
FROM finding_relationships fr
JOIN findings f ON fr.related_finding_id = f.id
WHERE fr.finding_id = 'finding-uuid'
  AND fr.confidence > 0.7
ORDER BY fr.confidence DESC;

-- Find all related findings recursively (up to 3 degrees)
WITH RECURSIVE related_findings AS (
    -- Base case: directly related
    SELECT 
        fr.finding_id,
        fr.related_finding_id,
        fr.relationship_type,
        1 AS depth,
        ARRAY[fr.finding_id] AS path
    FROM finding_relationships fr
    WHERE fr.finding_id = 'finding-uuid'
      AND fr.confidence > 0.7
    
    UNION ALL
    
    -- Recursive case: related to related
    SELECT 
        fr.finding_id,
        fr.related_finding_id,
        fr.relationship_type,
        rf.depth + 1,
        rf.path || fr.finding_id
    FROM finding_relationships fr
    JOIN related_findings rf ON fr.finding_id = rf.related_finding_id
    WHERE rf.depth < 3
      AND NOT (fr.finding_id = ANY(rf.path))  -- Prevent cycles
      AND fr.confidence > 0.7
)
SELECT DISTINCT
    f.id,
    f.title,
    f.severity,
    rf.relationship_type,
    rf.depth
FROM related_findings rf
JOIN findings f ON rf.related_finding_id = f.id
ORDER BY rf.depth, f.severity;
```

### 6. Files in Directory (Hierarchical Query with ltree)

```sql
-- Get all files in a directory and subdirectories
SELECT 
    file_path,
    lines_of_code,
    complexity_score
FROM code_files
WHERE directory_path <@ 'src.api'::ltree  -- All descendants
  AND project_id = 'project-uuid'
ORDER BY file_path;

-- Get direct children only (no subdirectories)
SELECT 
    file_path,
    lines_of_code
FROM code_files
WHERE directory_path ~ 'src.api.*{1}'::lquery  -- Exactly 1 level down
  AND project_id = 'project-uuid';
```

### 7. Find Impact of Changing a File

```sql
-- Find all files that depend on a file (direct and transitive)
-- AND all findings in those files
WITH RECURSIVE impacted_files AS (
    -- Base case: the file being changed
    SELECT 
        id AS file_id,
        file_path,
        0 AS depth
    FROM code_files
    WHERE file_path = '/src/api/users.py'
      AND project_id = 'project-uuid'
    
    UNION ALL
    
    -- Recursive: files that depend on impacted files
    SELECT 
        cf.id,
        cf.file_path,
        if.depth + 1
    FROM file_dependencies fd
    JOIN code_files cf ON fd.source_file_id = cf.id
    JOIN impacted_files if ON fd.target_file_id = if.file_id
    WHERE if.depth < 5  -- Limit depth
)
SELECT 
    if.file_path,
    if.depth,
    COUNT(f.id) AS findings_count,
    SUM(CASE WHEN f.severity = 'critical' THEN 1 ELSE 0 END) AS critical_findings
FROM impacted_files if
LEFT JOIN findings f ON f.file_id = if.file_id AND f.status = 'open'
GROUP BY if.file_path, if.depth
ORDER BY if.depth, critical_findings DESC;
```

---

## Performance Optimizations for Graph Queries

### 1. Materialized Views for Common Graph Queries

```sql
-- Materialized view: File dependency count
CREATE MATERIALIZED VIEW mv_file_dependency_stats AS
SELECT 
    cf.id AS file_id,
    cf.file_path,
    COUNT(DISTINCT fd_out.target_file_id) AS dependencies_count,
    COUNT(DISTINCT fd_in.source_file_id) AS dependents_count,
    COUNT(DISTINCT f.id) AS findings_count
FROM code_files cf
LEFT JOIN file_dependencies fd_out ON cf.id = fd_out.source_file_id
LEFT JOIN file_dependencies fd_in ON cf.id = fd_in.target_file_id
LEFT JOIN findings f ON cf.id = f.file_id AND f.status = 'open'
GROUP BY cf.id, cf.file_path;

-- Refresh strategy: hourly or after each audit
CREATE INDEX idx_mv_file_deps_stats ON mv_file_dependency_stats(file_id);

-- Refresh (run periodically)
REFRESH MATERIALIZED VIEW CONCURRENTLY mv_file_dependency_stats;
```

### 2. Graph Indexes

```sql
-- Covering index for dependency traversal
CREATE INDEX idx_file_deps_covering ON file_dependencies(source_file_id, target_file_id) 
    INCLUDE (dependency_type, created_at);

-- Partial index for external dependencies only
CREATE INDEX idx_file_deps_external ON file_dependencies(source_file_id)
    WHERE is_external = true;
```

### 3. Query Hints and Optimization

```sql
-- Use CTEs with MATERIALIZED hint for complex queries
WITH RECURSIVE MATERIALIZED dependency_tree AS (
    ...
)
SELECT * FROM dependency_tree;

-- Use parallel query for large graph traversals
SET max_parallel_workers_per_gather = 4;
```

---

## Comparison: PostgreSQL vs Neo4j

| Aspect | PostgreSQL + Graph | Neo4j (Pure Graph) |
|--------|-------------------|-------------------|
| **Deep Traversals** | Good (recursive CTEs) | Excellent (native) |
| **Transactional** | Excellent (ACID) | Good |
| **Aggregations** | Excellent | Moderate |
| **Time-Series** | Excellent | Poor |
| **Operational** | Simple (1 DB) | Complex (2 DBs) |
| **Ecosystem** | Mature | Growing |
| **Cost Tracking** | Excellent | Poor |
| **Graph Algorithms** | Limited | Excellent |
| **Our Use Case** | ✅ Perfect fit | ❌ Overkill |

**Recommendation:** Stay with PostgreSQL. If we need advanced graph algorithms (PageRank, community detection), we can:
1. Use Apache AGE extension (PostgreSQL)
2. Export to Neo4j/ArangoDB for analysis
3. Use in-memory graph processing (NetworkX in Python)

---

## Migration from Current Schema

### Step 1: Add Extensions

```sql
CREATE EXTENSION IF NOT EXISTS ltree;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS btree_gist;
```

### Step 2: Create New Tables

```sql
-- Run DDL for code_files, file_dependencies, finding_relationships, standards
-- (See sections above)
```

### Step 3: Migrate Existing Data

```sql
-- Populate code_files from existing findings.file_path
INSERT INTO code_files (project_id, file_path, file_hash, directory_path, first_seen_at, last_seen_at)
SELECT DISTINCT
    f.project_id,
    f.file_path,
    encode(digest(f.file_path, 'sha256'), 'hex') AS file_hash,
    text2ltree(replace(regexp_replace(f.file_path, '/[^/]+$', ''), '/', '.')) AS directory_path,
    MIN(f.created_at) AS first_seen_at,
    MAX(f.created_at) AS last_seen_at
FROM findings f
WHERE f.file_path IS NOT NULL
GROUP BY f.project_id, f.file_path
ON CONFLICT (project_id, file_path) DO NOTHING;

-- Update findings.file_id
UPDATE findings f
SET file_id = cf.id
FROM code_files cf
WHERE f.project_id = cf.project_id
  AND f.file_path = cf.file_path
  AND f.file_id IS NULL;
```

### Step 4: Backfill Dependencies (Optional)

```sql
-- Parse import statements from code and populate file_dependencies
-- This requires custom logic to parse actual source code
-- Can be done incrementally during audits
```

---

## Monitoring Graph Query Performance

```sql
-- Expensive recursive queries
SELECT 
    query,
    calls,
    total_exec_time,
    mean_exec_time,
    rows
FROM pg_stat_statements
WHERE query LIKE '%RECURSIVE%'
ORDER BY mean_exec_time DESC
LIMIT 10;

-- Graph table sizes
SELECT 
    schemaname,
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size,
    n_tup_ins + n_tup_upd + n_tup_del AS modifications
FROM pg_stat_user_tables
WHERE tablename IN ('code_files', 'file_dependencies', 'finding_relationships', 'standards')
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;
```

---

## When to Consider a Pure Graph Database

**Consider Neo4j/ArangoDB if:**
1. ✅ >50% of queries are deep graph traversals (>5 hops)
2. ✅ Need graph algorithms (PageRank, community detection, shortest path)
3. ✅ Graph data >> transactional data
4. ✅ Team has graph DB expertise
5. ✅ Can afford operational complexity of 2 databases

**For Tron:**
- ❌ Most queries are 1-2 hops (findings → files, projects → audits)
- ❌ Heavy transactional workload (cost tracking, audit runs)
- ❌ Time-series analytics (aggregations, trends)
- ✅ PostgreSQL recursive CTEs handle our needs well

---

## Summary

**Graph Capabilities Added to PostgreSQL:**
1. ✅ **ltree extension** for hierarchical standards
2. ✅ **Recursive CTEs** for dependency traversal
3. ✅ **Many-to-many** edges (file_dependencies, finding_relationships)
4. ✅ **Proper indexes** for graph queries (GiST, GIN)
5. ✅ **Materialized views** for common graph aggregations
6. ✅ **Cycle detection** and **transitive closure** queries

**Benefits:**
- ✅ Single database (simpler operations)
- ✅ ACID transactions (critical for Tron)
- ✅ Excellent for both graph queries AND analytics
- ✅ Mature ecosystem and tooling
- ✅ Can add Apache AGE later if needed

**Result:** PostgreSQL with graph modeling provides the scalability and searchability you need without the complexity of a separate graph database.

---

**Next Steps:**
1. Review graph schema design
2. Update `DATABASE_SCHEMA.md` with graph tables
3. Add graph query examples to API documentation
4. Implement graph endpoints in REST API
5. Add graph visualizations to Admin UI (Phase 2)

**Status:** ✅ Graph design complete, ready for implementation
