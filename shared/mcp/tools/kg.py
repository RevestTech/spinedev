"""Knowledge-graph MCP tools.

Tools from REQ-INIT-6 FR-6 (EPIC-6.5) plus the hybrid retrieval tool from
FR-8 (EPIC-6.7). All tools are wired through to Postgres:
``graph_query`` (STORY-6.5.1 — typed escape hatch over kg_node/kg_edge),
``find_callers`` (STORY-6.5.2), ``impact_radius`` (STORY-6.5.5),
``trace_dependency`` (STORY-6.5.3), ``code_neighborhood`` (STORY-6.5.4),
``doc_for_region`` (STORY-6.5.6), ``who_owns`` (STORY-6.5.7),
``find_by_satisfies`` (STORY-6.5.8), and ``hybrid_search`` (STORY-6.7.3 —
embedding pipeline + RRF re-rank; see ``build/kg/embeddings/embedder_README.md``).

Tools registered: ``graph_query``, ``find_callers``, ``trace_dependency``,
``code_neighborhood``, ``impact_radius``, ``doc_for_region``, ``who_owns``,
``find_by_satisfies``, ``hybrid_search``.
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from shared.mcp.schemas import ToolError, ToolResponse, ToolStatus
from shared.mcp.tools import register_tool

logger = logging.getLogger(__name__)

_FORBID = ConfigDict(extra="forbid")

# Edge types we consider "callers" / "tests" / "importers" — see V2 README.
_CALLS = "CALLS"
_TESTS = ("TESTS", "COVERS")
_IMPORTS = "IMPORTS"

# Edge types whose source is a Document node and which connect to code
# (see V2 README + REQ-INIT-6 FR-6 doc_for_region).
_DOC_EDGE_TYPES = ("CITES", "OWNS", "TESTS", "TOUCHES", "DERIVED_FROM", "DECIDED_BY")

# Relevance ranking for doc_for_region — lower index = higher relevance.
_DOC_RELEVANCE_ORDER = {
    "OWNS": 0,
    "DECIDED_BY": 1,
    "CITES": 2,
    "TESTS": 3,
    "DERIVED_FROM": 4,
    "TOUCHES": 5,
}

# Edges treated as "satisfies"-flavoured for find_by_satisfies (incoming on a
# Spine-flow target node). TESTS/COVERS added per caller's include_tests.
_SATISFIES_EDGES = ("SATISFIES", "DECIDED_BY")
_TEST_EDGES = ("TESTS", "COVERS")
_SATISFIES_RELEVANCE_ORDER = {"SATISFIES": 0, "DECIDED_BY": 1, "TESTS": 2, "COVERS": 3}

# ID prefix → (node type, optional subtype). Unknown → type-agnostic lookup.
_ID_PREFIX_MAP: dict[str, tuple[str, str | None]] = {
    "INIT-": ("Initiative", None), "EPIC-": ("Epic", None), "STORY-": ("Story", None),
    "REQ-": ("Document", "REQ"), "ADR-": ("Document", "ADR"),
    "PRD-": ("Document", "PRD"), "TRD-": ("Document", "TRD"),
}

# psql column separator. Pipe `|` is psql's default for -A output but symbol
# names can legitimately contain it; use ASCII unit-separator instead.
_SEP = "\x1f"


def _log(tool: str, project_id: str) -> None:
    logger.info("mcp_tool_call", extra={"tool": tool, "project_id": project_id, "actor": "agent"})


# -- Input models (one per tool so the registry can introspect them) -------


class GraphQueryInput(BaseModel):
    """Inputs for ``graph_query`` (STORY-6.5.1).

    Generic escape-hatch over ``spine_kg.kg_node`` / ``kg_edge``. The 8 typed
    KG tools (``find_callers``, ``code_neighborhood``, ...) cover the named
    access patterns; this one exists so power users can run ad-hoc filtered
    lookups without dropping to psql. At least one of ``node_type`` /
    ``edge_type`` MUST be set — an unfiltered query would be a table scan.
    """

    model_config = _FORBID
    project_id: str = Field(..., min_length=1)
    node_type: str | None = Field(default=None,
        description="Filter nodes by `type` (e.g. 'Function', 'Document'). At least "
                    "one of node_type/edge_type is required.")
    where: dict[str, str] | None = Field(default=None,
        description="Property filters as {key: value} pairs against kg_node_property "
                    "(AND-joined). Keys are denormalized hot-key projections of "
                    "kg_node.properties.")
    edge_type: str | None = Field(default=None,
        description="When set, return edges of this type. If node_type is also set, "
                    "the edge's source node must also match node_type/where.")
    repo: str | None = Field(default=None,
        description="Optional repo scope; without this all repos are searched.")
    commit_sha: str | None = Field(default=None,
        description="Point-in-time snapshot (NFR-6); default = currently-valid rows.")
    limit: int = Field(default=50, ge=1, le=500,
        description="Cap on returned rows; max 500 (use a typed tool for large sweeps).")
    actor: str = Field(default="system", min_length=1,
        description="Role / subsystem invoking the query (audit attribution).")


class FindCallersInput(BaseModel):
    """Inputs for ``find_callers`` (STORY-6.5.2)."""

    model_config = _FORBID
    project_id: str = Field(..., min_length=1)
    symbol: str = Field(..., min_length=1, description="Qualified name like 'module.Class.method' or 'module:function'.")
    repo: str = Field(..., min_length=1, description="Repo to query; fail loud if missing (no implicit default).")
    depth: int = Field(default=1, ge=1, le=10, description="1 = direct callers; 2+ = transitive via intermediates.")
    commit_sha: str | None = Field(default=None, description="Point-in-time snapshot (NFR-6); default = current head.")
    limit: int = Field(default=100, ge=1, le=10000, description="Cap on returned callers.")


class TraceDependencyInput(BaseModel):
    """Inputs for ``trace_dependency`` (STORY-6.5.3)."""

    model_config = _FORBID
    project_id: str = Field(..., min_length=1)
    from_symbol: str = Field(..., min_length=1, description="Source symbol (qualified name or node_id).")
    to_symbol: str = Field(..., min_length=1, description="Target symbol (qualified name or node_id).")
    repo: str = Field(..., min_length=1, description="Repo to query; fail loud if missing.")
    max_depth: int = Field(default=5, ge=1, le=10, description="Cap search depth (hops).")
    edge_types: list[str] = Field(default_factory=lambda: ["CALLS", "IMPORTS"],
                                  description="Edge types to traverse.")
    commit_sha: str | None = Field(default=None, description="Point-in-time snapshot (NFR-6).")


class CodeNeighborhoodInput(BaseModel):
    """Inputs for ``code_neighborhood`` (STORY-6.5.4)."""

    model_config = _FORBID
    project_id: str = Field(..., min_length=1)
    target: str = Field(..., min_length=1, description="Symbol OR file path anchor.")
    repo: str = Field(..., min_length=1, description="Repo to query; fail loud if missing.")
    radius: int = Field(default=2, ge=1, le=5, description="N-hop subgraph radius.")
    edge_types: list[str] | None = Field(default=None,
                                         description="Edge types to traverse; None = all edges.")
    commit_sha: str | None = Field(default=None, description="Point-in-time snapshot (NFR-6).")
    limit: int = Field(default=200, ge=1, le=5000, description="Max nodes returned.")


class ImpactRadiusInput(BaseModel):
    """Inputs for ``impact_radius`` (STORY-6.5.5)."""

    model_config = _FORBID
    project_id: str = Field(..., min_length=1)
    target: str = Field(..., min_length=1, description="Symbol, file path, or 'file:lo-hi' region.")
    target_type: Literal["symbol", "file", "region"] = Field(default="symbol")
    repo: str = Field(..., min_length=1, description="Repo to query; fail loud if missing.")
    include_tests: bool = Field(default=True, description="Include TESTS/COVERS edges.")
    commit_sha: str | None = Field(default=None, description="Point-in-time snapshot (NFR-6).")


class DocForRegionInput(BaseModel):
    """Inputs for ``doc_for_region`` (STORY-6.5.6)."""

    model_config = _FORBID
    project_id: str = Field(..., min_length=1)
    file: str = Field(..., min_length=1, description="File path within the repo.")
    line_start: int | None = Field(default=None, ge=0,
                                   description="Optional line range start (1-indexed).")
    line_end: int | None = Field(default=None, ge=0,
                                 description="Optional line range end (1-indexed).")
    repo: str = Field(..., min_length=1, description="Repo to query; fail loud if missing.")
    commit_sha: str | None = Field(default=None, description="Point-in-time snapshot (NFR-6).")


class WhoOwnsInput(BaseModel):
    """Inputs for ``who_owns`` (STORY-6.5.7)."""

    model_config = _FORBID
    project_id: str = Field(..., min_length=1)
    target: str = Field(..., min_length=1, description="File path or symbol whose owners we want.")
    repo: str = Field(..., min_length=1, description="Repo to query; fail loud if missing.")
    commit_sha: str | None = Field(default=None, description="Point-in-time snapshot (NFR-6).")


class HybridSearchInput(BaseModel):
    """Inputs for ``hybrid_search`` (EPIC-6.7 / STORY-6.7.3)."""

    model_config = _FORBID
    project_id: str = Field(..., min_length=1)
    query: str = Field(..., min_length=1, description="Natural-language query.")
    repo: str = Field(..., min_length=1, description="Repo to query; fail loud if missing.")
    limit: int = Field(default=20, ge=1, le=200)
    semantic_weight: float = Field(default=0.5, ge=0.0, le=1.0,
        description="0.0 = pure structural; 1.0 = pure semantic.")
    structural_seed: str | None = Field(default=None,
        description="Symbol/file anchoring the structural walk (optional).")
    structural_radius: int = Field(default=2, ge=1, le=5)
    commit_sha: str | None = Field(default=None, description="Point-in-time (NFR-6).")


class FindBySatisfiesInput(BaseModel):
    """Inputs for ``find_by_satisfies`` (STORY-6.5.8)."""

    model_config = _FORBID
    project_id: str = Field(..., min_length=1)
    req_or_story_id: str = Field(..., min_length=1,
        description="Spine-flow ID like REQ-INIT-1, STORY-6.5.2, EPIC-7.4, ADR-005.")
    repo: str = Field(..., min_length=1, description="Repo to query; fail loud if missing.")
    commit_sha: str | None = Field(default=None, description="Point-in-time snapshot (NFR-6).")
    include_tests: bool = Field(default=True,
        description="Include TESTS/COVERS edges from test nodes (default true).")


# -- Output models (returned inside ToolResponse.data) ---------------------


class GraphQueryNode(BaseModel):
    """One node row from ``graph_query`` (when ``edge_type`` is unset)."""

    model_config = _FORBID
    node_id: str
    node_type: str
    name: str
    path: str
    properties: dict[str, str]


class GraphQueryEdge(BaseModel):
    """One edge row from ``graph_query`` (when ``edge_type`` is set)."""

    model_config = _FORBID
    edge_id: int
    edge_type: str
    from_node_id: str
    to_node_id: str
    from_node_type: str
    to_node_type: str


class GraphQueryOutput(BaseModel):
    """Structured payload for ``graph_query``. ``mode`` echoes which arm of
    the dispatcher ran so callers don't have to inspect both lists."""

    model_config = _FORBID
    status: str
    mode: Literal["nodes", "edges"]
    nodes: list[GraphQueryNode] = Field(default_factory=list)
    edges: list[GraphQueryEdge] = Field(default_factory=list)
    total_returned: int
    query_latency_ms: int
    audit_id: UUID


class CallerInfo(BaseModel):
    """One row of ``find_callers`` output."""

    model_config = _FORBID
    node_id: str
    name: str
    type: str
    path: str
    depth: int
    via: list[str] | None = None


class FindCallersOutput(BaseModel):
    """Structured payload for ``find_callers``."""

    model_config = _FORBID
    status: str
    symbol: str
    callers: list[CallerInfo]
    total_found: int
    query_latency_ms: int
    audit_id: UUID


class ImpactedNode(BaseModel):
    """One row of ``impact_radius`` output."""

    model_config = _FORBID
    node_id: str
    type: str
    path: str
    impact_distance: int
    impact_kind: Literal["caller", "test", "importer", "test_via_caller"]


class ImpactRadiusOutput(BaseModel):
    """Structured payload for ``impact_radius``."""

    model_config = _FORBID
    status: str
    target: str
    impacted: list[ImpactedNode]
    direct_caller_count: int
    direct_test_count: int
    importer_count: int
    total_impact: int
    query_latency_ms: int
    audit_id: UUID


class DependencyPath(BaseModel):
    """One path through the dependency graph for ``trace_dependency``."""

    model_config = _FORBID
    path: list[str]            # node IDs from source -> target (display names)
    edges: list[str]           # edge types along the path
    depth: int


class TraceDependencyOutput(BaseModel):
    """Structured payload for ``trace_dependency``."""

    model_config = _FORBID
    status: str
    from_symbol: str
    to_symbol: str
    paths_found: list[DependencyPath]
    no_path: bool
    query_latency_ms: int
    audit_id: UUID


class NeighborNode(BaseModel):
    """One node in the ``code_neighborhood`` subgraph."""

    model_config = _FORBID
    node_id: str
    name: str
    type: str
    path: str
    distance: int              # hops from target


class NeighborEdge(BaseModel):
    """One edge in the ``code_neighborhood`` subgraph."""

    model_config = _FORBID
    from_node_id: str
    to_node_id: str
    type: str


class CodeNeighborhoodOutput(BaseModel):
    """Structured payload for ``code_neighborhood``."""

    model_config = _FORBID
    status: str
    target: str
    nodes: list[NeighborNode]
    edges: list[NeighborEdge]
    query_latency_ms: int
    audit_id: UUID


class DocReference(BaseModel):
    """One document reference returned by ``doc_for_region``."""

    model_config = _FORBID
    doc_type: str              # REQ | ADR | PRD | TRD | Roadmap | MemoryLesson | README
    doc_id: str                # e.g. REQ-INIT-1, ADR-005
    title: str
    relevance: str             # CITES | OWNS | TESTS | TOUCHES | DERIVED_FROM | DECIDED_BY
    path: str                  # doc file path
    line_in_doc: int | None


class DocForRegionOutput(BaseModel):
    """Structured payload for ``doc_for_region``."""

    model_config = _FORBID
    status: str
    file: str
    region: str
    docs: list[DocReference]
    query_latency_ms: int
    audit_id: UUID


class Owner(BaseModel):
    """One owner returned by ``who_owns``."""

    model_config = _FORBID
    owner_type: str            # Role | Person | Team | ADR | Memory
    owner_id: str
    confidence: float
    via: str                   # OWNED_BY edge | inferred from git blame | from memory lesson


class WhoOwnsOutput(BaseModel):
    """Structured payload for ``who_owns``."""

    model_config = _FORBID
    status: str
    target: str
    owners: list[Owner]
    query_latency_ms: int
    audit_id: UUID


class SatisfyingRegion(BaseModel):
    """One code/test/doc region returned by ``find_by_satisfies``."""

    model_config = _FORBID
    node_id: str
    name: str
    type: str                  # Function | Method | Class | TestCase | Document
    path: str
    relevance: str             # SATISFIES | TESTS | DECIDED_BY | derived


class FindBySatisfiesOutput(BaseModel):
    """Structured payload for ``find_by_satisfies``."""

    model_config = _FORBID
    status: str
    target_id: str
    regions: list[SatisfyingRegion]
    coverage_count: int
    query_latency_ms: int
    audit_id: UUID


class HybridSearchResult(BaseModel):
    """One ``hybrid_search`` row. semantic/structural_score = 0-1 display;
    combined_score = RRF-blended; rationale = one-line "why this matched"."""

    model_config = _FORBID
    node_id: str
    name: str
    type: str
    path: str
    semantic_score: float
    structural_score: float
    combined_score: float
    rationale: str


class HybridSearchOutput(BaseModel):
    """Structured payload for ``hybrid_search``. semantic/structural_count = per-
    branch candidates; fused_count = post-RRF rows returned."""

    model_config = _FORBID
    status: ToolStatus
    query: str
    results: list[HybridSearchResult]
    semantic_count: int
    structural_count: int
    fused_count: int
    embedding_provider: str
    query_latency_ms: int
    audit_id: UUID


# -- Helpers ---------------------------------------------------------------


def _db_url() -> str:
    """Read SPINE_DB_URL; raise if absent (no implicit local fallback)."""
    url = os.environ.get("SPINE_DB_URL")
    if not url:
        raise RuntimeError("SPINE_DB_URL not set; KG tools require an explicit DB URL")
    return url


def _run_psql_query(sql: str, params: dict[str, Any]) -> list[dict[str, str]]:
    """Run a SELECT via ``psql`` and parse its tabular output into dicts.

    Params are bound via ``-v name=value``; the caller must reference them as
    ``:'name'`` (quoted) or ``:name`` (raw) in the SQL — same convention used
    elsewhere in this repo. Output is parsed as US-separated, header-led rows.
    """
    # `:var` substitution does NOT work with `psql -c "..."` — only with stdin
    # or `-f`. Pipe SQL via stdin so the -v bindings actually fire.
    cmd: list[str] = ["psql", _db_url(), "-A", "-X", "-q", "-v", "ON_ERROR_STOP=1",
                      "-F", _SEP, "--pset=footer=off"]
    for k, v in params.items():
        # Coerce to str; psql -v always takes string values.
        cmd.extend(["-v", f"{k}={v}"])
    try:
        proc = subprocess.run(cmd, input=sql, capture_output=True, text=True,
                              timeout=10, check=True)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"psql query failed: {e.stderr.strip()}") from e
    lines = [ln for ln in proc.stdout.splitlines() if ln]
    if not lines:
        return []
    headers = lines[0].split(_SEP)
    return [dict(zip(headers, ln.split(_SEP), strict=False)) for ln in lines[1:]]


def _commit_filter(commit_sha: str | None, table_alias: str) -> str:
    """SQL fragment that scopes a node/edge row to a point-in-time snapshot.

    With ``commit_sha`` set, scope strictly to that snapshot (NFR-6 semantics).
    Without, return only currently-valid rows.
    """
    if commit_sha:
        return f"{table_alias}.commit_sha = :'commit_sha'"
    return f"({table_alias}.valid_to IS NULL OR {table_alias}.valid_to > NOW())"


def _resolve_symbol_to_node_id(symbol: str, repo: str, commit_sha: str | None) -> int | None:
    """Look up a Function/Method node by qualified name; warn + take newest on tie."""
    sql = (
        "SELECT id, name, path FROM spine_kg.kg_node "
        "WHERE (name = :'symbol' OR node_id = :'symbol') "
        "AND type IN ('Function', 'Method') "
        "AND repo = :'repo' "
        f"AND {_commit_filter(commit_sha, 'kg_node')} "
        "ORDER BY created_at DESC LIMIT 10;"
    )
    params: dict[str, Any] = {"symbol": symbol, "repo": repo}
    if commit_sha:
        params["commit_sha"] = commit_sha
    rows = _run_psql_query(sql, params)
    if not rows:
        return None
    if len(rows) > 1:
        logger.warning("kg_symbol_ambiguous", extra={"symbol": symbol, "repo": repo,
                                                     "match_count": len(rows)})
    try:
        return int(rows[0]["id"])
    except (KeyError, ValueError):
        return None


def _resolve_target_to_node_ids(target: str, target_type: str, repo: str,
                                commit_sha: str | None) -> list[int]:
    """Resolve a symbol / file / region target to one or more starting node IDs."""
    if target_type == "symbol":
        nid = _resolve_symbol_to_node_id(target, repo, commit_sha)
        return [nid] if nid else []

    if target_type in ("file", "region"):
        path, line_lo, line_hi = target, None, None
        if target_type == "region" and ":" in target:
            path, _, rng = target.rpartition(":")
            if "-" in rng:
                try:
                    lo_s, hi_s = rng.split("-", 1)
                    line_lo, line_hi = int(lo_s), int(hi_s)
                except ValueError:
                    line_lo = line_hi = None
        # Find the File node + every node whose path starts with the file path
        # (i.e. members nested inside it, which the indexer stores as
        # `file.py:LINE` or similar — match by prefix).
        sql = (
            "SELECT id, path, properties FROM spine_kg.kg_node "
            "WHERE repo = :'repo' "
            "AND (path = :'path' OR path LIKE :'path_prefix') "
            f"AND {_commit_filter(commit_sha, 'kg_node')} "
            "LIMIT 5000;"
        )
        params: dict[str, Any] = {"repo": repo, "path": path, "path_prefix": f"{path}:%"}
        if commit_sha:
            params["commit_sha"] = commit_sha
        rows = _run_psql_query(sql, params)
        ids: list[int] = []
        for r in rows:
            if line_lo is not None and ":" in (r.get("path") or ""):
                try:
                    line = int(r["path"].rsplit(":", 1)[1])
                except ValueError:
                    line = -1
                if line >= 0 and not (line_lo <= line <= line_hi):
                    continue
            try:
                ids.append(int(r["id"]))
            except (KeyError, ValueError):
                continue
        return ids

    return []


def _resolve_any_to_node_id(target: str, repo: str,
                            commit_sha: str | None) -> int | None:
    """Resolve a symbol OR file path to a single node ID.

    Tries symbol match first (matches ``name`` or ``node_id`` against
    Function/Method/Class), then falls back to File path equality. Returns
    the most recently-created match on ambiguity (and warns).
    """
    # Symbol-style match first.
    sql_sym = (
        "SELECT id FROM spine_kg.kg_node "
        "WHERE (name = :'target' OR node_id = :'target') "
        "AND type IN ('Function', 'Method', 'Class') "
        "AND repo = :'repo' "
        f"AND {_commit_filter(commit_sha, 'kg_node')} "
        "ORDER BY created_at DESC LIMIT 10;"
    )
    params: dict[str, Any] = {"target": target, "repo": repo}
    if commit_sha:
        params["commit_sha"] = commit_sha
    rows = _run_psql_query(sql_sym, params)
    if rows:
        if len(rows) > 1:
            logger.warning("kg_target_ambiguous",
                           extra={"target": target, "repo": repo,
                                  "match_count": len(rows), "kind": "symbol"})
        try:
            return int(rows[0]["id"])
        except (KeyError, ValueError):
            pass

    # File path fallback.
    sql_file = (
        "SELECT id FROM spine_kg.kg_node "
        "WHERE path = :'target' "
        "AND type = 'File' "
        "AND repo = :'repo' "
        f"AND {_commit_filter(commit_sha, 'kg_node')} "
        "ORDER BY created_at DESC LIMIT 10;"
    )
    rows = _run_psql_query(sql_file, params)
    if not rows:
        return None
    if len(rows) > 1:
        logger.warning("kg_target_ambiguous",
                       extra={"target": target, "repo": repo,
                              "match_count": len(rows), "kind": "file"})
    try:
        return int(rows[0]["id"])
    except (KeyError, ValueError):
        return None


def _fetch_node_names(node_ids: list[int]) -> dict[int, str]:
    """Bulk lookup id -> display name for `via` chain enrichment."""
    if not node_ids:
        return {}
    # ANY(:'ids'::bigint[]) accepts a Postgres array literal like '{1,2,3}'.
    array_lit = "{" + ",".join(str(int(i)) for i in node_ids) + "}"
    sql = ("SELECT id, COALESCE(name, node_id) AS display "
           "FROM spine_kg.kg_node WHERE id = ANY(:'ids'::bigint[]);")
    rows = _run_psql_query(sql, {"ids": array_lit})
    out: dict[int, str] = {}
    for r in rows:
        try:
            out[int(r["id"])] = r.get("display", "")
        except (KeyError, ValueError):
            continue
    return out


def _fetch_node_info(node_ids: list[int]) -> dict[int, dict[str, str]]:
    """Bulk lookup id -> {node_id, name, type, path} for nodes by integer id."""
    if not node_ids:
        return {}
    array_lit = "{" + ",".join(str(int(i)) for i in node_ids) + "}"
    sql = ("SELECT id, node_id, COALESCE(name, node_id) AS name, type, "
           "COALESCE(path, '') AS path "
           "FROM spine_kg.kg_node WHERE id = ANY(:'ids'::bigint[]);")
    rows = _run_psql_query(sql, {"ids": array_lit})
    out: dict[int, dict[str, str]] = {}
    for r in rows:
        try:
            out[int(r["id"])] = {
                "node_id": r.get("node_id", ""),
                "name": r.get("name", ""),
                "type": r.get("type", ""),
                "path": r.get("path", ""),
            }
        except (KeyError, ValueError):
            continue
    return out


def _sanitize_edge_types(edge_types: list[str] | None) -> list[str] | None:
    """Strip non-alphanumeric/underscore characters; return None on None input.

    Edge type names in the schema are uppercase A-Z plus underscore. Reject
    anything else to keep SQL string-interpolation safe (we cannot use psql
    parameters inside ``IN (...)`` lists portably).
    """
    if edge_types is None:
        return None
    clean: list[str] = []
    for et in edge_types:
        if et and all(c.isalnum() or c == "_" for c in et):
            clean.append(et.upper())
    return clean


def _write_kg_audit(action: str, subject_id: str, metadata: dict[str, Any]) -> UUID:
    """Best-effort audit write; never blocks the query path on audit failure."""
    audit_uuid = uuid4()
    try:
        from shared.audit.audit_record import AuditRecord, chain_to_previous, write_via_psql
        rec = AuditRecord(role="agent", subsystem="shared", action=action,
                          actor="mcp", subject_type="kg_query", subject_id=subject_id,
                          metadata=metadata, event_uuid=audit_uuid)
        rec = chain_to_previous(rec, None)
        write_via_psql(rec)
    except Exception as exc:  # noqa: BLE001 — audit is best-effort
        logger.warning("kg_audit_write_failed", extra={"action": action, "err": str(exc)})
    return audit_uuid


# -- Tool functions --------------------------------------------------------


def _sanitize_identifier(value: str) -> str | None:
    """Allow A-Z a-z 0-9 underscore only; None if anything else slips in.

    Used for ``node_type`` / ``edge_type`` / property keys before string-
    interpolating into SQL (psql ``-v`` parameters can't help inside ``IN``
    lists or column names). Matches the upstream taxonomy in V2 — types are
    PascalCase, edge types SHOUTY_SNAKE_CASE, property keys snake_case.
    """
    if not value:
        return None
    if all(c.isalnum() or c == "_" for c in value):
        return value
    return None


@register_tool(name="graph_query", input_model=GraphQueryInput, story="STORY-6.5.1",
               description="Filtered escape-hatch query over kg_node/kg_edge for ad-hoc lookups.",
               tags=("kg",))
def graph_query(payload: GraphQueryInput) -> ToolResponse:
    """Open-ended KG lookup with mandatory ``node_type`` and/or ``edge_type``
    scoping. With only ``node_type`` (+ optional ``where``), returns matching
    nodes; with ``edge_type`` set, returns edges of that type whose source
    node also matches the node filter. ``where`` filters AND-join against
    ``spine_kg.kg_node_property`` (the denormalized hot-key projection).
    """
    _log("graph_query", payload.project_id)
    started = time.perf_counter()

    # Mandatory scoping: at least one of node_type/edge_type must be set.
    if payload.node_type is None and payload.edge_type is None:
        audit_id = _write_kg_audit("kg_query", payload.project_id,
                                   {"tool": "graph_query", "result": "no_filter"})
        return ToolResponse(status="error", audit_id=audit_id, error=ToolError(
            code="no_filter",
            message="graph_query requires at least one of node_type or edge_type; "
                    "an unfiltered sweep would table-scan kg_node. Use one of the "
                    "typed tools (find_callers, code_neighborhood, ...) for named "
                    "access patterns.",
            retryable=False))

    # Defense in depth: input model caps limit at 500 but a missing alias
    # could let a callsite pass a raw dict — re-check before we trust it.
    if payload.limit > 500:
        audit_id = _write_kg_audit("kg_query", payload.project_id,
                                   {"tool": "graph_query", "result": "limit_too_large",
                                    "requested_limit": payload.limit})
        return ToolResponse(status="error", audit_id=audit_id, error=ToolError(
            code="limit_too_large",
            message=f"limit={payload.limit} exceeds the 500-row cap.",
            retryable=False))

    node_type = _sanitize_identifier(payload.node_type) if payload.node_type else None
    edge_type = _sanitize_identifier(payload.edge_type) if payload.edge_type else None
    if (payload.node_type and node_type is None) or (payload.edge_type and edge_type is None):
        audit_id = _write_kg_audit("kg_query", payload.project_id,
                                   {"tool": "graph_query", "result": "invalid_identifier"})
        return ToolResponse(status="error", audit_id=audit_id, error=ToolError(
            code="invalid_identifier",
            message="node_type / edge_type must be alphanumeric + underscore only.",
            retryable=False))

    # Pre-validate property-filter keys — values are bound via psql params,
    # keys would be interpolated so they must pass the same gauntlet.
    where = payload.where or {}
    for k in where:
        if _sanitize_identifier(k) is None:
            audit_id = _write_kg_audit("kg_query", payload.project_id,
                                       {"tool": "graph_query", "result": "invalid_property_key",
                                        "key": k})
            return ToolResponse(status="error", audit_id=audit_id, error=ToolError(
                code="invalid_property_key",
                message=f"property key {k!r} must be alphanumeric + underscore only.",
                retryable=False))

    # Build the WHERE clauses for kg_node. node_type is interpolated (already
    # sanitised); repo/commit_sha go through the param channel.
    node_clauses: list[str] = [_commit_filter(payload.commit_sha, "n")]
    params: dict[str, Any] = {"limit": payload.limit}
    if node_type is not None:
        node_clauses.append(f"n.type = '{node_type}'")
    if payload.repo:
        node_clauses.append("n.repo = :'repo'")
        params["repo"] = payload.repo
    if payload.commit_sha:
        params["commit_sha"] = payload.commit_sha
    # AND-join one EXISTS subquery per property filter so the planner can use
    # the (key, value) index on kg_node_property.
    for i, (k, v) in enumerate(where.items()):
        pk = f"prop_v_{i}"
        node_clauses.append(
            f"EXISTS (SELECT 1 FROM spine_kg.kg_node_property p{i} "
            f"WHERE p{i}.node_id = n.id AND p{i}.key = '{k}' "
            f"AND p{i}.value = :'{pk}')"
        )
        params[pk] = v

    if edge_type is None:
        # NODE MODE — return nodes matching the filter set.
        sql = (
            "SELECT n.node_id, n.type, COALESCE(n.name, n.node_id) AS name, "
            "       COALESCE(n.path, '') AS path "
            "FROM spine_kg.kg_node n "
            f"WHERE {' AND '.join(node_clauses)} "
            "ORDER BY n.created_at DESC, n.id ASC "
            "LIMIT :limit;"
        )
        rows = _run_psql_query(sql, params)

        # Hydrate properties via the denormalised hot-key table — one batch
        # query keyed by node_id so we don't N+1 the DB.
        node_ids_str = [r.get("node_id", "") for r in rows if r.get("node_id")]
        props_by_node: dict[str, dict[str, str]] = {nid: {} for nid in node_ids_str}
        if node_ids_str:
            # node_id is a TEXT column; build a quoted SQL array literal.
            esc = lambda s: s.replace("'", "''")  # noqa: E731
            id_csv = ",".join(f"'{esc(nid)}'" for nid in node_ids_str)
            prop_sql = (
                "SELECT n.node_id, p.key, p.value "
                "FROM spine_kg.kg_node_property p "
                "JOIN spine_kg.kg_node n ON n.id = p.node_id "
                f"WHERE n.node_id IN ({id_csv}) "
                "LIMIT 5000;"
            )
            for pr in _run_psql_query(prop_sql, {}):
                nid = pr.get("node_id", "")
                k = pr.get("key", "")
                if nid and k and nid in props_by_node:
                    props_by_node[nid][k] = pr.get("value", "")

        nodes = [GraphQueryNode(
            node_id=r.get("node_id", ""),
            node_type=r.get("type", ""),
            name=r.get("name", ""),
            path=r.get("path", ""),
            properties=props_by_node.get(r.get("node_id", ""), {}),
        ) for r in rows]

        latency_ms = int((time.perf_counter() - started) * 1000)
        audit_id = _write_kg_audit("kg_query", payload.project_id,
                                   {"tool": "graph_query", "mode": "nodes",
                                    "node_type": node_type,
                                    "where_keys": sorted(where.keys()),
                                    "result_count": len(nodes),
                                    "latency_ms": latency_ms})
        out = GraphQueryOutput(status="ok", mode="nodes", nodes=nodes,
                               edges=[], total_returned=len(nodes),
                               query_latency_ms=latency_ms, audit_id=audit_id)
        return ToolResponse(status="ok", data=out.model_dump(mode="json"),
                            audit_id=audit_id)

    # EDGE MODE — return edges of `edge_type`. The node filter (if present)
    # constrains the FROM node; the TO node is hydrated for display only.
    edge_clauses: list[str] = [
        f"e.type = '{edge_type}'",
        _commit_filter(payload.commit_sha, "e"),
        _commit_filter(payload.commit_sha, "n"),
    ]
    # Reuse node_clauses (already includes the n.* commit filter) for the
    # FROM-side node restriction.
    for c in node_clauses:
        if c not in edge_clauses:
            edge_clauses.append(c)

    edge_sql = (
        "SELECT e.id AS edge_id, e.type AS edge_type, "
        "       n.node_id AS from_node_id, n.type AS from_node_type, "
        "       t.node_id AS to_node_id, t.type AS to_node_type "
        "FROM spine_kg.kg_edge e "
        "JOIN spine_kg.kg_node n ON n.id = e.from_node_id "
        "JOIN spine_kg.kg_node t ON t.id = e.to_node_id "
        f"WHERE {' AND '.join(edge_clauses)} "
        f"AND {_commit_filter(payload.commit_sha, 't')} "
        "ORDER BY e.id DESC "
        "LIMIT :limit;"
    )
    erows = _run_psql_query(edge_sql, params)
    edges: list[GraphQueryEdge] = []
    for r in erows:
        try:
            edges.append(GraphQueryEdge(
                edge_id=int(r.get("edge_id", "0")),
                edge_type=r.get("edge_type", ""),
                from_node_id=r.get("from_node_id", ""),
                to_node_id=r.get("to_node_id", ""),
                from_node_type=r.get("from_node_type", ""),
                to_node_type=r.get("to_node_type", ""),
            ))
        except (KeyError, ValueError):
            continue

    latency_ms = int((time.perf_counter() - started) * 1000)
    audit_id = _write_kg_audit("kg_query", payload.project_id,
                               {"tool": "graph_query", "mode": "edges",
                                "edge_type": edge_type, "node_type": node_type,
                                "where_keys": sorted(where.keys()),
                                "result_count": len(edges),
                                "latency_ms": latency_ms})
    out = GraphQueryOutput(status="ok", mode="edges", nodes=[], edges=edges,
                           total_returned=len(edges),
                           query_latency_ms=latency_ms, audit_id=audit_id)
    return ToolResponse(status="ok", data=out.model_dump(mode="json"),
                        audit_id=audit_id)


@register_tool(name="find_callers", input_model=FindCallersInput, story="STORY-6.5.2",
               description="Direct and transitive callers of a symbol with file:line context.", tags=("kg",))
def find_callers(payload: FindCallersInput) -> ToolResponse:
    """Resolve a symbol then return its direct (depth=1) or transitive callers via CALLS edges."""
    _log("find_callers", payload.project_id)
    started = time.perf_counter()

    target_id = _resolve_symbol_to_node_id(payload.symbol, payload.repo, payload.commit_sha)
    if target_id is None:
        latency_ms = int((time.perf_counter() - started) * 1000)
        audit_id = _write_kg_audit("kg_query", payload.symbol,
                                   {"tool": "find_callers", "result": "symbol_not_found",
                                    "repo": payload.repo})
        out = FindCallersOutput(status="ok", symbol=payload.symbol, callers=[],
                                total_found=0, query_latency_ms=latency_ms, audit_id=audit_id)
        return ToolResponse(status="ok", data=out.model_dump(mode="json"))

    params: dict[str, Any] = {"target_id": target_id, "depth": payload.depth,
                              "limit": payload.limit}
    if payload.commit_sha:
        params["commit_sha"] = payload.commit_sha

    if payload.depth == 1:
        sql = (
            "SELECT n.node_id, COALESCE(n.name, n.node_id) AS name, n.type, "
            "COALESCE(n.path, '') AS path, 1 AS d, ''::text AS path_chain "
            "FROM spine_kg.kg_edge e "
            "JOIN spine_kg.kg_node n ON n.id = e.from_node_id "
            f"WHERE e.to_node_id = :target_id AND e.type = '{_CALLS}' "
            f"AND {_commit_filter(payload.commit_sha, 'e')} "
            f"AND {_commit_filter(payload.commit_sha, 'n')} "
            "LIMIT :limit;"
        )
    else:
        sql = (
            "WITH RECURSIVE callers AS ( "
            "  SELECT e.from_node_id AS caller_id, 1 AS d, "
            "         ARRAY[e.from_node_id] AS path "
            "  FROM spine_kg.kg_edge e "
            f"  WHERE e.to_node_id = :target_id AND e.type = '{_CALLS}' "
            f"    AND {_commit_filter(payload.commit_sha, 'e')} "
            "  UNION ALL "
            "  SELECT e.from_node_id, c.d + 1, c.path || e.from_node_id "
            "  FROM callers c "
            "  JOIN spine_kg.kg_edge e ON e.to_node_id = c.caller_id "
            f"  WHERE c.d < :depth AND e.type = '{_CALLS}' "
            f"    AND {_commit_filter(payload.commit_sha, 'e')} "
            "    AND NOT (e.from_node_id = ANY(c.path)) "
            ") "
            "SELECT DISTINCT ON (n.id) n.node_id, "
            "       COALESCE(n.name, n.node_id) AS name, n.type, "
            "       COALESCE(n.path, '') AS path, c.d, "
            "       array_to_string(c.path[1:c.d-1], ',') AS path_chain "
            "FROM callers c "
            "JOIN spine_kg.kg_node n ON n.id = c.caller_id "
            f"WHERE {_commit_filter(payload.commit_sha, 'n')} "
            "ORDER BY n.id, c.d ASC "
            "LIMIT :limit;"
        )

    rows = _run_psql_query(sql, params)

    # Collect every intermediate id we need names for, in one shot.
    chain_ids: set[int] = set()
    for r in rows:
        chain = r.get("path_chain") or ""
        if chain:
            for x in chain.split(","):
                try:
                    chain_ids.add(int(x))
                except ValueError:
                    continue
    name_map = _fetch_node_names(sorted(chain_ids))

    callers: list[CallerInfo] = []
    for r in rows:
        try:
            depth_val = int(r.get("d", "1"))
        except ValueError:
            depth_val = 1
        via: list[str] | None = None
        if depth_val > 1 and r.get("path_chain"):
            via = [name_map.get(int(x), str(x)) for x in r["path_chain"].split(",") if x]
        callers.append(CallerInfo(
            node_id=r.get("node_id", ""),
            name=r.get("name", ""),
            type=r.get("type", ""),
            path=r.get("path", ""),
            depth=depth_val,
            via=via,
        ))

    latency_ms = int((time.perf_counter() - started) * 1000)
    audit_id = _write_kg_audit("kg_query", payload.symbol,
                               {"tool": "find_callers", "depth": payload.depth,
                                "repo": payload.repo, "result_count": len(callers),
                                "latency_ms": latency_ms})
    out = FindCallersOutput(status="ok", symbol=payload.symbol, callers=callers,
                            total_found=len(callers), query_latency_ms=latency_ms,
                            audit_id=audit_id)
    return ToolResponse(status="ok", data=out.model_dump(mode="json"), audit_id=audit_id)


@register_tool(name="trace_dependency", input_model=TraceDependencyInput, story="STORY-6.5.3",
               description="Shortest dependency paths between two symbols through CALLS/IMPORTS edges.",
               tags=("kg",))
def trace_dependency(payload: TraceDependencyInput) -> ToolResponse:
    """Resolve both endpoints and return up to 5 shortest paths between them.

    The recursive CTE walks forward from ``from_symbol`` through the supplied
    ``edge_types``, accumulating the path as an array and stopping as soon as
    ``to_symbol`` is reached or ``max_depth`` is exhausted. Cycles are blocked
    by checking ``NOT (next_id = ANY(path))``.
    """
    _log("trace_dependency", payload.project_id)
    started = time.perf_counter()

    from_id = _resolve_symbol_to_node_id(payload.from_symbol, payload.repo, payload.commit_sha)
    to_id = _resolve_symbol_to_node_id(payload.to_symbol, payload.repo, payload.commit_sha)
    if from_id is None or to_id is None:
        latency_ms = int((time.perf_counter() - started) * 1000)
        audit_id = _write_kg_audit("kg_query", f"{payload.from_symbol}->{payload.to_symbol}",
                                   {"tool": "trace_dependency", "result": "symbol_not_found",
                                    "repo": payload.repo,
                                    "from_resolved": from_id is not None,
                                    "to_resolved": to_id is not None})
        out = TraceDependencyOutput(status="ok", from_symbol=payload.from_symbol,
                                    to_symbol=payload.to_symbol, paths_found=[],
                                    no_path=True, query_latency_ms=latency_ms,
                                    audit_id=audit_id)
        return ToolResponse(status="ok", data=out.model_dump(mode="json"), audit_id=audit_id)

    edge_types = _sanitize_edge_types(payload.edge_types) or ["CALLS", "IMPORTS"]
    edge_types_sql = "(" + ",".join(f"'{t}'" for t in edge_types) + ")"

    # Forward BFS from `from_id`; we collect both the node-id chain and the
    # edge-type chain, stopping when we hit `to_id` or exceed max_depth.
    sql = (
        "WITH RECURSIVE walk AS ( "
        "  SELECT e.from_node_id AS src, e.to_node_id AS dst, 1 AS d, "
        "         ARRAY[e.from_node_id, e.to_node_id] AS node_path, "
        "         ARRAY[e.type::text] AS edge_path "
        "  FROM spine_kg.kg_edge e "
        f"  WHERE e.from_node_id = :from_id AND e.type IN {edge_types_sql} "
        f"    AND {_commit_filter(payload.commit_sha, 'e')} "
        "  UNION ALL "
        "  SELECT w.src, e.to_node_id, w.d + 1, "
        "         w.node_path || e.to_node_id, "
        "         w.edge_path || e.type::text "
        "  FROM walk w "
        "  JOIN spine_kg.kg_edge e ON e.from_node_id = w.dst "
        f"  WHERE w.d < :max_depth AND w.dst <> :to_id AND e.type IN {edge_types_sql} "
        f"    AND {_commit_filter(payload.commit_sha, 'e')} "
        "    AND NOT (e.to_node_id = ANY(w.node_path)) "
        ") "
        "SELECT d, array_to_string(node_path, ',') AS node_path, "
        "       array_to_string(edge_path, ',') AS edge_path "
        "FROM walk WHERE dst = :to_id "
        "ORDER BY d ASC LIMIT 5;"
    )
    params: dict[str, Any] = {"from_id": from_id, "to_id": to_id,
                              "max_depth": payload.max_depth}
    if payload.commit_sha:
        params["commit_sha"] = payload.commit_sha

    rows = _run_psql_query(sql, params)

    # Collect every id we need names for in a single batch.
    all_ids: set[int] = set()
    for r in rows:
        for x in (r.get("node_path") or "").split(","):
            try:
                all_ids.add(int(x))
            except ValueError:
                continue
    name_map = _fetch_node_names(sorted(all_ids))

    paths: list[DependencyPath] = []
    for r in rows:
        try:
            depth_val = int(r.get("d", "0"))
        except ValueError:
            depth_val = 0
        node_ids = [int(x) for x in (r.get("node_path") or "").split(",") if x]
        edge_types_chain = [t for t in (r.get("edge_path") or "").split(",") if t]
        paths.append(DependencyPath(
            path=[name_map.get(nid, str(nid)) for nid in node_ids],
            edges=edge_types_chain,
            depth=depth_val,
        ))

    latency_ms = int((time.perf_counter() - started) * 1000)
    audit_id = _write_kg_audit("kg_query", f"{payload.from_symbol}->{payload.to_symbol}",
                               {"tool": "trace_dependency", "repo": payload.repo,
                                "max_depth": payload.max_depth,
                                "path_count": len(paths), "latency_ms": latency_ms,
                                "edge_types": edge_types})
    out = TraceDependencyOutput(status="ok", from_symbol=payload.from_symbol,
                                to_symbol=payload.to_symbol, paths_found=paths,
                                no_path=(len(paths) == 0),
                                query_latency_ms=latency_ms, audit_id=audit_id)
    return ToolResponse(status="ok", data=out.model_dump(mode="json"), audit_id=audit_id)


@register_tool(name="code_neighborhood", input_model=CodeNeighborhoodInput, story="STORY-6.5.4",
               description="Subgraph within N hops of a code anchor.", tags=("kg",))
def code_neighborhood(payload: CodeNeighborhoodInput) -> ToolResponse:
    """Return an N-hop subgraph (nodes + edges) around a symbol or file anchor.

    Expansion is bidirectional: we treat the underlying directed graph as
    undirected for neighborhood purposes (every edge contributes a +1 hop in
    both directions). The result is capped at ``limit`` nodes.
    """
    _log("code_neighborhood", payload.project_id)
    started = time.perf_counter()

    target_id = _resolve_any_to_node_id(payload.target, payload.repo, payload.commit_sha)
    if target_id is None:
        latency_ms = int((time.perf_counter() - started) * 1000)
        audit_id = _write_kg_audit("kg_query", payload.target,
                                   {"tool": "code_neighborhood", "result": "target_not_found",
                                    "repo": payload.repo})
        out = CodeNeighborhoodOutput(status="ok", target=payload.target, nodes=[], edges=[],
                                     query_latency_ms=latency_ms, audit_id=audit_id)
        return ToolResponse(status="ok", data=out.model_dump(mode="json"), audit_id=audit_id)

    edge_types = _sanitize_edge_types(payload.edge_types)
    if edge_types is not None and edge_types:
        edge_filter = " AND e.type IN (" + ",".join(f"'{t}'" for t in edge_types) + ")"
    else:
        edge_filter = ""

    # Recursive bidirectional BFS up to `radius` hops. PostgreSQL only
    # supports UNION ALL in recursive CTEs, so dedup happens in `min_dist`.
    sql_nodes = (
        "WITH RECURSIVE hood AS ( "
        "  SELECT :target_id::bigint AS nid, 0 AS distance, "
        "         ARRAY[:target_id::bigint] AS visited "
        "  UNION ALL "
        "  SELECT CASE WHEN e.from_node_id = h.nid THEN e.to_node_id "
        "              ELSE e.from_node_id END AS nid, "
        "         h.distance + 1 AS distance, "
        "         h.visited || CASE WHEN e.from_node_id = h.nid THEN e.to_node_id "
        "                           ELSE e.from_node_id END "
        "  FROM hood h "
        "  JOIN spine_kg.kg_edge e "
        "    ON (e.from_node_id = h.nid OR e.to_node_id = h.nid) "
        f"  WHERE h.distance < :radius{edge_filter} "
        f"    AND {_commit_filter(payload.commit_sha, 'e')} "
        "    AND NOT ((CASE WHEN e.from_node_id = h.nid THEN e.to_node_id "
        "                   ELSE e.from_node_id END) = ANY(h.visited)) "
        "), "
        "min_dist AS ( "
        "  SELECT nid, MIN(distance) AS distance FROM hood GROUP BY nid "
        ") "
        "SELECT n.id, n.node_id, COALESCE(n.name, n.node_id) AS name, n.type, "
        "       COALESCE(n.path, '') AS path, m.distance "
        "FROM min_dist m "
        "JOIN spine_kg.kg_node n ON n.id = m.nid "
        f"WHERE {_commit_filter(payload.commit_sha, 'n')} "
        "ORDER BY m.distance ASC, n.id ASC "
        "LIMIT :limit;"
    )
    params: dict[str, Any] = {"target_id": target_id, "radius": payload.radius,
                              "limit": payload.limit}
    if payload.commit_sha:
        params["commit_sha"] = payload.commit_sha

    node_rows = _run_psql_query(sql_nodes, params)
    nodes: list[NeighborNode] = []
    int_id_to_node_id: dict[int, str] = {}
    for r in node_rows:
        try:
            int_id = int(r["id"])
            dist = int(r.get("distance", "0"))
        except (KeyError, ValueError):
            continue
        int_id_to_node_id[int_id] = r.get("node_id", "")
        nodes.append(NeighborNode(
            node_id=r.get("node_id", ""),
            name=r.get("name", ""),
            type=r.get("type", ""),
            path=r.get("path", ""),
            distance=dist,
        ))

    edges: list[NeighborEdge] = []
    if int_id_to_node_id:
        # Fetch edges where BOTH endpoints are in the returned node set.
        id_lit = "{" + ",".join(str(i) for i in int_id_to_node_id) + "}"
        sql_edges = (
            "SELECT e.from_node_id, e.to_node_id, e.type "
            "FROM spine_kg.kg_edge e "
            "WHERE e.from_node_id = ANY(:'ids'::bigint[]) "
            "  AND e.to_node_id = ANY(:'ids'::bigint[]) "
            f"  AND {_commit_filter(payload.commit_sha, 'e')}"
            f"{edge_filter} "
            "LIMIT 5000;"
        )
        edge_params: dict[str, Any] = {"ids": id_lit}
        if payload.commit_sha:
            edge_params["commit_sha"] = payload.commit_sha
        for r in _run_psql_query(sql_edges, edge_params):
            try:
                f_id = int(r["from_node_id"])
                t_id = int(r["to_node_id"])
            except (KeyError, ValueError):
                continue
            f_str = int_id_to_node_id.get(f_id)
            t_str = int_id_to_node_id.get(t_id)
            if f_str is None or t_str is None:
                continue
            edges.append(NeighborEdge(
                from_node_id=f_str, to_node_id=t_str, type=r.get("type", "")
            ))

    latency_ms = int((time.perf_counter() - started) * 1000)
    audit_id = _write_kg_audit("kg_query", payload.target,
                               {"tool": "code_neighborhood", "repo": payload.repo,
                                "radius": payload.radius,
                                "node_count": len(nodes), "edge_count": len(edges),
                                "latency_ms": latency_ms})
    out = CodeNeighborhoodOutput(status="ok", target=payload.target, nodes=nodes,
                                 edges=edges, query_latency_ms=latency_ms, audit_id=audit_id)
    return ToolResponse(status="ok", data=out.model_dump(mode="json"), audit_id=audit_id)


@register_tool(name="impact_radius", input_model=ImpactRadiusInput, story="STORY-6.5.5",
               description="Files and tests potentially affected by a change to the given symbol/region.", tags=("kg",))
def impact_radius(payload: ImpactRadiusInput) -> ToolResponse:
    """Compute blast radius: callers (1-3 hops), tests, importers, and tests via callers."""
    _log("impact_radius", payload.project_id)
    started = time.perf_counter()

    seed_ids = _resolve_target_to_node_ids(payload.target, payload.target_type,
                                           payload.repo, payload.commit_sha)
    if not seed_ids:
        latency_ms = int((time.perf_counter() - started) * 1000)
        audit_id = _write_kg_audit("kg_query", payload.target,
                                   {"tool": "impact_radius", "result": "target_not_found",
                                    "repo": payload.repo})
        out = ImpactRadiusOutput(status="ok", target=payload.target, impacted=[],
                                 direct_caller_count=0, direct_test_count=0,
                                 importer_count=0, total_impact=0,
                                 query_latency_ms=latency_ms, audit_id=audit_id)
        return ToolResponse(status="ok", data=out.model_dump(mode="json"))

    seed_lit = "{" + ",".join(str(int(i)) for i in seed_ids) + "}"
    test_types_sql = "(" + ",".join(f"'{t}'" for t in _TESTS) + ")"

    tests_branch = (
        "  UNION ALL "
        "  SELECT e.from_node_id AS nid, 1 AS impact_distance, 'test' AS kind "
        "  FROM spine_kg.kg_edge e "
        f"  WHERE e.to_node_id = ANY(:'seeds'::bigint[]) AND e.type IN {test_types_sql} "
        f"    AND {_commit_filter(payload.commit_sha, 'e')} "
    ) if payload.include_tests else ""

    test_via_caller_branch = (
        "  UNION ALL "
        "  SELECT e.from_node_id AS nid, 2 AS impact_distance, 'test_via_caller' AS kind "
        "  FROM spine_kg.kg_edge e "
        "  WHERE e.to_node_id IN (SELECT nid FROM caller_set) "
        f"    AND e.type IN {test_types_sql} "
        f"    AND {_commit_filter(payload.commit_sha, 'e')} "
    ) if payload.include_tests else ""

    sql = (
        "WITH RECURSIVE callers AS ( "
        "  SELECT e.from_node_id AS nid, 1 AS d, ARRAY[e.from_node_id] AS path "
        "  FROM spine_kg.kg_edge e "
        f"  WHERE e.to_node_id = ANY(:'seeds'::bigint[]) AND e.type = '{_CALLS}' "
        f"    AND {_commit_filter(payload.commit_sha, 'e')} "
        "  UNION ALL "
        "  SELECT e.from_node_id, c.d + 1, c.path || e.from_node_id "
        "  FROM callers c "
        "  JOIN spine_kg.kg_edge e ON e.to_node_id = c.nid "
        f"  WHERE c.d < 3 AND e.type = '{_CALLS}' "
        f"    AND {_commit_filter(payload.commit_sha, 'e')} "
        "    AND NOT (e.from_node_id = ANY(c.path)) "
        "), "
        "caller_set AS ( "
        "  SELECT DISTINCT ON (nid) nid, d FROM callers ORDER BY nid, d ASC "
        "), "
        "importers AS ( "
        "  SELECT e.from_node_id AS nid, 1 AS impact_distance, 'importer' AS kind "
        "  FROM spine_kg.kg_edge e "
        f"  WHERE e.to_node_id = ANY(:'seeds'::bigint[]) AND e.type = '{_IMPORTS}' "
        f"    AND {_commit_filter(payload.commit_sha, 'e')} "
        "  UNION ALL "
        "  SELECT e.from_node_id, 2, 'importer' "
        "  FROM spine_kg.kg_edge e "
        "  WHERE e.to_node_id IN (SELECT from_node_id FROM spine_kg.kg_edge "
        f"                        WHERE to_node_id = ANY(:'seeds'::bigint[]) AND type = '{_IMPORTS}') "
        f"    AND e.type = '{_IMPORTS}' "
        f"    AND {_commit_filter(payload.commit_sha, 'e')} "
        "), "
        "combined AS ( "
        "  SELECT nid, d AS impact_distance, 'caller' AS kind FROM caller_set "
        f"  {tests_branch}"
        "  UNION ALL "
        "  SELECT nid, impact_distance, kind FROM importers "
        f"  {test_via_caller_branch}"
        ") "
        "SELECT DISTINCT ON (n.id) n.node_id, n.type, COALESCE(n.path, '') AS path, "
        "       c.impact_distance, c.kind "
        "FROM combined c "
        "JOIN spine_kg.kg_node n ON n.id = c.nid "
        f"WHERE {_commit_filter(payload.commit_sha, 'n')} "
        "ORDER BY n.id, c.impact_distance ASC "
        "LIMIT 5000;"
    )
    params: dict[str, Any] = {"seeds": seed_lit}
    if payload.commit_sha:
        params["commit_sha"] = payload.commit_sha

    rows = _run_psql_query(sql, params)

    impacted: list[ImpactedNode] = []
    direct_callers = direct_tests = importers = 0
    for r in rows:
        try:
            dist = int(r.get("impact_distance", "0"))
        except ValueError:
            dist = 0
        kind = r.get("kind", "caller")
        if kind not in ("caller", "test", "importer", "test_via_caller"):
            continue
        impacted.append(ImpactedNode(
            node_id=r.get("node_id", ""),
            type=r.get("type", ""),
            path=r.get("path", ""),
            impact_distance=dist,
            impact_kind=kind,  # type: ignore[arg-type]
        ))
        if dist == 1 and kind == "caller":
            direct_callers += 1
        elif dist == 1 and kind == "test":
            direct_tests += 1
        elif kind == "importer":
            importers += 1

    latency_ms = int((time.perf_counter() - started) * 1000)
    audit_id = _write_kg_audit("kg_query", payload.target,
                               {"tool": "impact_radius", "repo": payload.repo,
                                "result_count": len(impacted), "latency_ms": latency_ms,
                                "target_type": payload.target_type})
    out = ImpactRadiusOutput(status="ok", target=payload.target, impacted=impacted,
                             direct_caller_count=direct_callers,
                             direct_test_count=direct_tests,
                             importer_count=importers,
                             total_impact=len(impacted),
                             query_latency_ms=latency_ms, audit_id=audit_id)
    return ToolResponse(status="ok", data=out.model_dump(mode="json"), audit_id=audit_id)


@register_tool(name="doc_for_region", input_model=DocForRegionInput, story="STORY-6.5.6",
               description="REQs, ADRs, and memory lessons touching the given code region.", tags=("kg",))
def doc_for_region(payload: DocForRegionInput) -> ToolResponse:
    """Return Document nodes whose edges land on code nodes in the given region.

    The walk has two halves: (1) collect code nodes whose path equals the file
    or whose path starts with ``file:`` (member nodes encoded as ``file.py:LINE``),
    optionally filtered to a line range; (2) find incoming edges of any
    Document-flavoured type from Document nodes. Results are deduplicated by
    (doc_id, relevance) and ordered by relevance rank then file proximity.
    """
    _log("doc_for_region", payload.project_id)
    started = time.perf_counter()

    # Region string for the response envelope.
    if payload.line_start is not None and payload.line_end is not None:
        region_str = f"{payload.file}:{payload.line_start}-{payload.line_end}"
    elif payload.line_start is not None:
        region_str = f"{payload.file}:{payload.line_start}"
    else:
        region_str = payload.file

    # 1) Resolve code nodes in the file (optionally filtered by line range).
    sql_codes = (
        "SELECT id, COALESCE(path, '') AS path FROM spine_kg.kg_node "
        "WHERE repo = :'repo' "
        "AND (path = :'file' OR path LIKE :'file_prefix') "
        f"AND {_commit_filter(payload.commit_sha, 'kg_node')} "
        "LIMIT 5000;"
    )
    code_params: dict[str, Any] = {"repo": payload.repo, "file": payload.file,
                                   "file_prefix": f"{payload.file}:%"}
    if payload.commit_sha:
        code_params["commit_sha"] = payload.commit_sha
    code_rows = _run_psql_query(sql_codes, code_params)

    code_ids: list[int] = []
    for r in code_rows:
        path = r.get("path") or ""
        if payload.line_start is not None and ":" in path:
            try:
                line = int(path.rsplit(":", 1)[1])
            except ValueError:
                line = -1
            hi = payload.line_end if payload.line_end is not None else payload.line_start
            if line >= 0 and not (payload.line_start <= line <= hi):
                continue
        try:
            code_ids.append(int(r["id"]))
        except (KeyError, ValueError):
            continue

    if not code_ids:
        latency_ms = int((time.perf_counter() - started) * 1000)
        audit_id = _write_kg_audit("kg_query", region_str,
                                   {"tool": "doc_for_region", "repo": payload.repo,
                                    "result": "no_code_nodes",
                                    "latency_ms": latency_ms})
        out = DocForRegionOutput(status="ok", file=payload.file, region=region_str, docs=[],
                                 query_latency_ms=latency_ms, audit_id=audit_id)
        return ToolResponse(status="ok", data=out.model_dump(mode="json"), audit_id=audit_id)

    # 2) Fetch incoming doc-style edges where from_node is a Document node.
    code_id_lit = "{" + ",".join(str(i) for i in code_ids) + "}"
    edge_types_sql = "(" + ",".join(f"'{t}'" for t in _DOC_EDGE_TYPES) + ")"
    sql_docs = (
        "SELECT DISTINCT ON (d.id, e.type) "
        "       d.node_id, COALESCE(d.subtype, d.type) AS doc_type, "
        "       COALESCE(d.name, d.node_id) AS title, e.type AS relevance, "
        "       COALESCE(d.path, '') AS path, "
        "       d.properties->>'line' AS line_in_doc "
        "FROM spine_kg.kg_edge e "
        "JOIN spine_kg.kg_node d ON d.id = e.from_node_id "
        "WHERE e.to_node_id = ANY(:'code_ids'::bigint[]) "
        f"  AND e.type IN {edge_types_sql} "
        "  AND d.type = 'Document' "
        "  AND d.repo = :'repo' "
        f"  AND {_commit_filter(payload.commit_sha, 'e')} "
        f"  AND {_commit_filter(payload.commit_sha, 'd')} "
        "ORDER BY d.id, e.type, d.created_at DESC "
        "LIMIT 500;"
    )
    doc_params: dict[str, Any] = {"code_ids": code_id_lit, "repo": payload.repo}
    if payload.commit_sha:
        doc_params["commit_sha"] = payload.commit_sha
    doc_rows = _run_psql_query(sql_docs, doc_params)

    docs: list[DocReference] = []
    seen: set[tuple[str, str]] = set()
    for r in doc_rows:
        doc_id = r.get("node_id", "")
        relevance = r.get("relevance", "")
        key = (doc_id, relevance)
        if key in seen:
            continue
        seen.add(key)
        raw_line = r.get("line_in_doc") or ""
        try:
            line_val: int | None = int(raw_line) if raw_line else None
        except ValueError:
            line_val = None
        docs.append(DocReference(
            doc_type=r.get("doc_type", "Document"),
            doc_id=doc_id,
            title=r.get("title", ""),
            relevance=relevance,
            path=r.get("path", ""),
            line_in_doc=line_val,
        ))

    # Order by relevance rank first, then by line_in_doc proximity (NULLs last).
    docs.sort(key=lambda d: (_DOC_RELEVANCE_ORDER.get(d.relevance, 99),
                             d.line_in_doc if d.line_in_doc is not None else 10**9,
                             d.doc_id))

    latency_ms = int((time.perf_counter() - started) * 1000)
    audit_id = _write_kg_audit("kg_query", region_str,
                               {"tool": "doc_for_region", "repo": payload.repo,
                                "doc_count": len(docs), "code_node_count": len(code_ids),
                                "latency_ms": latency_ms})
    out = DocForRegionOutput(status="ok", file=payload.file, region=region_str,
                             docs=docs, query_latency_ms=latency_ms, audit_id=audit_id)
    return ToolResponse(status="ok", data=out.model_dump(mode="json"), audit_id=audit_id)


@register_tool(name="who_owns", input_model=WhoOwnsInput, story="STORY-6.5.7",
               description="Roles, lessons, and ADRs claiming ownership of the given node.", tags=("kg",))
def who_owns(payload: WhoOwnsInput) -> ToolResponse:
    """Return owners of a file or symbol.

    Resolution order: (1) explicit ``OWNED_BY`` edges; (2) fall back to
    ``MemoryLesson`` nodes connected to the target via any edge type; (3) if
    nothing is found, return an empty list. We never fabricate owners.
    """
    _log("who_owns", payload.project_id)
    started = time.perf_counter()

    target_id = _resolve_any_to_node_id(payload.target, payload.repo, payload.commit_sha)
    if target_id is None:
        latency_ms = int((time.perf_counter() - started) * 1000)
        audit_id = _write_kg_audit("kg_query", payload.target,
                                   {"tool": "who_owns", "result": "target_not_found",
                                    "repo": payload.repo})
        out = WhoOwnsOutput(status="ok", target=payload.target, owners=[],
                            query_latency_ms=latency_ms, audit_id=audit_id)
        return ToolResponse(status="ok", data=out.model_dump(mode="json"), audit_id=audit_id)

    owners: list[Owner] = []
    seen: set[tuple[str, str]] = set()

    # 1) Explicit OWNED_BY edges (incoming or outgoing -- ownership can be modelled
    #    either as target -OWNED_BY-> owner or owner -OWNED_BY-> target depending
    #    on indexer convention; check both directions).
    sql_owned_by = (
        "SELECT n.node_id, n.type, COALESCE(n.name, n.node_id) AS name "
        "FROM spine_kg.kg_edge e "
        "JOIN spine_kg.kg_node n "
        "  ON n.id = CASE WHEN e.from_node_id = :target_id THEN e.to_node_id "
        "                 ELSE e.from_node_id END "
        "WHERE (e.from_node_id = :target_id OR e.to_node_id = :target_id) "
        "  AND e.type = 'OWNED_BY' "
        f"  AND {_commit_filter(payload.commit_sha, 'e')} "
        f"  AND {_commit_filter(payload.commit_sha, 'n')} "
        "LIMIT 100;"
    )
    params: dict[str, Any] = {"target_id": target_id}
    if payload.commit_sha:
        params["commit_sha"] = payload.commit_sha

    for r in _run_psql_query(sql_owned_by, params):
        n_type = r.get("type", "")
        owner_type = n_type if n_type in ("Role", "Person", "Team", "ADR") else "Role"
        key = (owner_type, r.get("node_id", ""))
        if key in seen:
            continue
        seen.add(key)
        owners.append(Owner(
            owner_type=owner_type,
            owner_id=r.get("node_id", ""),
            confidence=1.0,
            via="OWNED_BY edge",
        ))

    # 2) Memory-lesson fallback: any MemoryLesson document with an edge to target.
    sql_memory = (
        "SELECT DISTINCT d.node_id, COALESCE(d.name, d.node_id) AS name "
        "FROM spine_kg.kg_edge e "
        "JOIN spine_kg.kg_node d "
        "  ON d.id = CASE WHEN e.from_node_id = :target_id THEN e.to_node_id "
        "                 ELSE e.from_node_id END "
        "WHERE (e.from_node_id = :target_id OR e.to_node_id = :target_id) "
        "  AND d.type = 'Document' "
        "  AND (d.subtype = 'memory' OR d.subtype = 'MemoryLesson') "
        f"  AND {_commit_filter(payload.commit_sha, 'e')} "
        f"  AND {_commit_filter(payload.commit_sha, 'd')} "
        "LIMIT 100;"
    )
    for r in _run_psql_query(sql_memory, params):
        key = ("Memory", r.get("node_id", ""))
        if key in seen:
            continue
        seen.add(key)
        owners.append(Owner(
            owner_type="Memory",
            owner_id=r.get("node_id", ""),
            confidence=0.5,
            via="from memory lesson",
        ))

    latency_ms = int((time.perf_counter() - started) * 1000)
    audit_id = _write_kg_audit("kg_query", payload.target,
                               {"tool": "who_owns", "repo": payload.repo,
                                "owner_count": len(owners), "latency_ms": latency_ms})
    out = WhoOwnsOutput(status="ok", target=payload.target, owners=owners,
                        query_latency_ms=latency_ms, audit_id=audit_id)
    return ToolResponse(status="ok", data=out.model_dump(mode="json"), audit_id=audit_id)


@register_tool(name="find_by_satisfies", input_model=FindBySatisfiesInput,
               story="STORY-6.5.8",
               description="Code/test regions claiming to satisfy a given REQ/STORY/EPIC (inverse of doc_for_region).",
               tags=("kg",))
def find_by_satisfies(payload: FindBySatisfiesInput) -> ToolResponse:
    """Inverse of ``doc_for_region``: resolve a Spine-flow node from its ID prefix
    (REQ/STORY/EPIC/INIT/ADR/PRD/TRD) then pull every incoming SATISFIES /
    DECIDED_BY edge (plus TESTS / COVERS when ``include_tests=True``). Source
    nodes are typically Functions/Methods/Classes/TestCases/Documents.
    Deduplicated by (node_id, relevance); ordered by relevance rank.
    """
    _log("find_by_satisfies", payload.project_id)
    started = time.perf_counter()
    tid = payload.req_or_story_id

    # 1) Resolve target node (ID-prefix-aware; falls back to type-agnostic).
    prefix = next((p for p in _ID_PREFIX_MAP if tid.startswith(p)), None)
    resolve_params: dict[str, Any] = {"target": tid, "repo": payload.repo}
    if payload.commit_sha:
        resolve_params["commit_sha"] = payload.commit_sha
    type_clause = subtype_clause = ""
    if prefix is not None:
        ntype, sub = _ID_PREFIX_MAP[prefix]
        type_clause = f"AND type = '{ntype}' "
        if sub:
            subtype_clause = "AND LOWER(COALESCE(subtype, '')) = LOWER(:'subtype') "
            resolve_params["subtype"] = sub
    resolve_rows = _run_psql_query(
        "SELECT id FROM spine_kg.kg_node "
        "WHERE (node_id = :'target' OR name = :'target') "
        f"{type_clause}{subtype_clause}AND repo = :'repo' "
        f"AND {_commit_filter(payload.commit_sha, 'kg_node')} "
        "ORDER BY created_at DESC LIMIT 10;",
        resolve_params,
    )
    target_id: int | None = None
    if resolve_rows:
        if len(resolve_rows) > 1:
            logger.warning("kg_satisfies_target_ambiguous",
                           extra={"target": tid, "repo": payload.repo,
                                  "match_count": len(resolve_rows)})
        try:
            target_id = int(resolve_rows[0]["id"])
        except (KeyError, ValueError):
            target_id = None

    if target_id is None:
        latency_ms = int((time.perf_counter() - started) * 1000)
        audit_id = _write_kg_audit("kg_query", tid,
                                   {"tool": "find_by_satisfies",
                                    "result": "target_not_found",
                                    "repo": payload.repo})
        out = FindBySatisfiesOutput(status="ok", target_id=tid, regions=[],
                                    coverage_count=0, query_latency_ms=latency_ms,
                                    audit_id=audit_id)
        return ToolResponse(status="ok", data=out.model_dump(mode="json"),
                            audit_id=audit_id)

    # 2) Pull incoming satisfies-flavoured edges. include_tests toggles
    # TESTS/COVERS; all values are constants -> safe to interpolate.
    edge_types = list(_SATISFIES_EDGES) + (list(_TEST_EDGES) if payload.include_tests else [])
    edge_types_sql = "(" + ",".join(f"'{t}'" for t in edge_types) + ")"
    sql = (
        "SELECT DISTINCT ON (n.id, e.type) "
        "       n.node_id, COALESCE(n.name, n.node_id) AS name, n.type, "
        "       COALESCE(n.path, '') AS path, e.type AS relevance "
        "FROM spine_kg.kg_edge e "
        "JOIN spine_kg.kg_node n ON n.id = e.from_node_id "
        f"WHERE e.to_node_id = :target_id AND e.type IN {edge_types_sql} "
        "  AND n.repo = :'repo' "
        f"  AND {_commit_filter(payload.commit_sha, 'e')} "
        f"  AND {_commit_filter(payload.commit_sha, 'n')} "
        "ORDER BY n.id, e.type, n.created_at DESC LIMIT 1000;"
    )
    params: dict[str, Any] = {"target_id": target_id, "repo": payload.repo}
    if payload.commit_sha:
        params["commit_sha"] = payload.commit_sha
    rows = _run_psql_query(sql, params)

    regions: list[SatisfyingRegion] = []
    seen: set[tuple[str, str]] = set()
    for r in rows:
        key = (r.get("node_id", ""), r.get("relevance", ""))
        if key in seen:
            continue
        seen.add(key)
        regions.append(SatisfyingRegion(
            node_id=r.get("node_id", ""), name=r.get("name", ""),
            type=r.get("type", ""), path=r.get("path", ""),
            relevance=r.get("relevance", "")))
    regions.sort(key=lambda x: (_SATISFIES_RELEVANCE_ORDER.get(x.relevance, 99),
                                x.path, x.node_id))

    latency_ms = int((time.perf_counter() - started) * 1000)
    audit_id = _write_kg_audit("kg_query", tid,
                               {"tool": "find_by_satisfies", "repo": payload.repo,
                                "result_count": len(regions),
                                "include_tests": payload.include_tests,
                                "latency_ms": latency_ms})
    out = FindBySatisfiesOutput(status="ok", target_id=tid, regions=regions,
                                coverage_count=len(regions),
                                query_latency_ms=latency_ms, audit_id=audit_id)
    return ToolResponse(status="ok", data=out.model_dump(mode="json"),
                        audit_id=audit_id)


def _structural_walk(target_id: int, radius: int,
                     commit_sha: str | None) -> list[tuple[int, int]]:
    """N-hop undirected BFS from ``target_id``; flat ``[(node_id, dist), ...]``."""
    nxt = "CASE WHEN e.from_node_id = h.nid THEN e.to_node_id ELSE e.from_node_id END"
    sql = (f"WITH RECURSIVE hood AS (SELECT :target_id::bigint AS nid, 0 AS distance, "
           f"ARRAY[:target_id::bigint] AS visited UNION ALL "
           f"SELECT {nxt} AS nid, h.distance + 1, h.visited || {nxt} FROM hood h "
           f"JOIN spine_kg.kg_edge e ON (e.from_node_id = h.nid OR e.to_node_id = h.nid) "
           f"WHERE h.distance < :radius AND {_commit_filter(commit_sha, 'e')} "
           f"AND NOT (({nxt}) = ANY(h.visited))) "
           "SELECT nid, MIN(distance) AS d FROM hood WHERE nid <> :target_id "
           "GROUP BY nid ORDER BY d ASC, nid ASC LIMIT 500;")
    params: dict[str, Any] = {"target_id": target_id, "radius": radius}
    if commit_sha:
        params["commit_sha"] = commit_sha
    out: list[tuple[int, int]] = []
    for r in _run_psql_query(sql, params):
        try:
            out.append((int(r["nid"]), int(r["d"])))
        except (KeyError, ValueError):
            continue
    return out


def _infer_seed_from_query(query: str, repo: str,
                           commit_sha: str | None) -> int | None:
    """Longest identifier-shaped token resolved as a symbol/file; None on miss."""
    import re as _re
    toks = sorted(set(_re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", query)),
                  key=len, reverse=True)
    for tok in toks[:5]:
        if (nid := _resolve_any_to_node_id(tok, repo, commit_sha)) is not None:
            return nid
    return None


@register_tool(name="hybrid_search", input_model=HybridSearchInput, story="STORY-6.7.3",
               description="Hybrid graph + vector retrieval over the KG with RRF re-rank.",
               tags=("kg", "rag"))
def hybrid_search(payload: HybridSearchInput) -> ToolResponse:
    """Vector + graph retrieval with Reciprocal Rank Fusion. (1) Embed query
    via configured provider (lazy ``build.kg.embeddings``); semantic
    candidates = ``cosine_search`` (3× ``limit``). (2) Structural = N-hop BFS
    from ``structural_seed`` or token inferred from query. (3) RRF fusion:
    ``sem_w/(60+r_sem) + (1-sem_w)/(60+r_struct)``."""
    _log("hybrid_search", payload.project_id)
    started = time.perf_counter()
    try:  # Lazy import keeps ML deps out of MCP server's hot-import path.
        from build.kg.embeddings import EmbedderRunner, select_provider  # type: ignore
        provider = select_provider({})
        runner = EmbedderRunner(provider, _db_url())
        q_vec = provider.embed_one(payload.query)
    except Exception as exc:  # noqa: BLE001
        logger.warning("hybrid_search_embed_failed", extra={"err": str(exc)[:200]})
        latency_ms = int((time.perf_counter() - started) * 1000)
        audit_id = _write_kg_audit("kg_query", payload.query,
            {"tool": "hybrid_search", "result": "embed_failed",
             "repo": payload.repo, "err": str(exc)[:200]})
        out = HybridSearchOutput(status="error", query=payload.query, results=[],
            semantic_count=0, structural_count=0, fused_count=0,
            embedding_provider="unknown", query_latency_ms=latency_ms, audit_id=audit_id)
        return ToolResponse(status="error", data=out.model_dump(mode="json"), audit_id=audit_id)

    # 1) Semantic branch — top-3× candidates for fusion headroom.
    sem_hits = runner.cosine_search(q_vec, limit=max(payload.limit * 3, 30),
                                    repo=payload.repo)
    sem_rank = {nid: r for r, (nid, _) in enumerate(sem_hits)}
    sem_dist = dict(sem_hits)

    # 2) Structural branch — explicit seed > inferred token > skip.
    seed_id = (_resolve_any_to_node_id(payload.structural_seed, payload.repo,
                                       payload.commit_sha)
               if payload.structural_seed
               else _infer_seed_from_query(payload.query, payload.repo, payload.commit_sha))
    struct_hits = (_structural_walk(seed_id, payload.structural_radius,
                                    payload.commit_sha) if seed_id is not None else [])
    struct_rank = {nid: r for r, (nid, _) in enumerate(struct_hits)}
    struct_dist = dict(struct_hits)

    # 3) RRF fusion. Cosine distance ∈ [0, 2]; display score = 1 - dist/2.
    k, w_s, w_g = 60.0, payload.semantic_weight, 1.0 - payload.semantic_weight
    radius = max(payload.structural_radius, 1)
    scored = sorted(
        ((nid,
          max(0.0, 1.0 - sem_dist.get(nid, 2.0) / 2.0) if nid in sem_rank else 0.0,
          max(0.0, 1.0 - struct_dist.get(nid, radius) / radius) if nid in struct_rank else 0.0,
          (w_s / (k + sem_rank[nid]) if nid in sem_rank else 0.0) +
          (w_g / (k + struct_rank[nid]) if nid in struct_rank else 0.0))
         for nid in set(sem_rank) | set(struct_rank)),
        key=lambda r: r[3], reverse=True)
    top = scored[: payload.limit]

    # 4) Hydrate metadata + build per-row rationale.
    info = _fetch_node_info([nid for nid, *_ in top])
    def _why(nid: int) -> str:
        s, g = nid in sem_rank, nid in struct_rank
        if s and g:
            return f"both — semantic rank {sem_rank[nid]+1}, structural rank {struct_rank[nid]+1}"
        return (f"matched semantically (rank {sem_rank[nid]+1})" if s
                else f"in code neighborhood (rank {struct_rank[nid]+1})")
    results = [HybridSearchResult(
        node_id=(m := info.get(nid, {})).get("node_id", str(nid)),
        name=m.get("name", ""), type=m.get("type", ""), path=m.get("path", ""),
        semantic_score=round(sd, 4), structural_score=round(gd, 4),
        combined_score=round(c, 6), rationale=_why(nid))
        for nid, sd, gd, c in top]

    latency_ms = int((time.perf_counter() - started) * 1000)
    audit_id = _write_kg_audit("kg_query", payload.query,
        {"tool": "hybrid_search", "repo": payload.repo,
         "semantic_count": len(sem_hits), "structural_count": len(struct_hits),
         "fused_count": len(results), "semantic_weight": payload.semantic_weight,
         "embedding_provider": provider.model_name, "latency_ms": latency_ms})
    out = HybridSearchOutput(status="ok", query=payload.query, results=results,
        semantic_count=len(sem_hits), structural_count=len(struct_hits),
        fused_count=len(results), embedding_provider=provider.model_name,
        query_latency_ms=latency_ms, audit_id=audit_id)
    return ToolResponse(status="ok", data=out.model_dump(mode="json"), audit_id=audit_id)


__all__: list[str] = [
    "CallerInfo", "CodeNeighborhoodInput", "CodeNeighborhoodOutput",
    "DependencyPath", "DocForRegionInput", "DocForRegionOutput", "DocReference",
    "FindBySatisfiesInput", "FindBySatisfiesOutput",
    "FindCallersInput", "FindCallersOutput", "GraphQueryEdge", "GraphQueryInput",
    "GraphQueryNode", "GraphQueryOutput",
    "HybridSearchInput", "HybridSearchOutput", "HybridSearchResult",
    "ImpactedNode", "ImpactRadiusInput", "ImpactRadiusOutput",
    "NeighborEdge", "NeighborNode", "Owner", "SatisfyingRegion",
    "TraceDependencyInput", "TraceDependencyOutput", "WhoOwnsInput", "WhoOwnsOutput",
    "code_neighborhood", "doc_for_region", "find_by_satisfies", "find_callers",
    "graph_query", "hybrid_search", "impact_radius", "trace_dependency", "who_owns",
]
