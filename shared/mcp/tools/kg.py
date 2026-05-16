"""Knowledge-graph MCP tools.

Tools from REQ-INIT-6 FR-6 (EPIC-6.5) plus the hybrid retrieval tool from
FR-8 (EPIC-6.7). Real implementations live behind the ``spine_kg`` schema and
LangChain ``GraphRetriever`` / ``MultiVectorRetriever`` wrappers; ``find_callers``
and ``impact_radius`` are wired through to Postgres (STORY-6.5.2 / STORY-6.5.5);
the rest remain scaffolding pending their own stories.

Tools registered: ``graph_query``, ``find_callers``, ``code_neighborhood``,
``impact_radius``, ``doc_for_region``, ``who_owns``, ``hybrid_search``.
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from shared.mcp.schemas import ToolResponse
from shared.mcp.tools import register_tool

logger = logging.getLogger(__name__)

_FORBID = ConfigDict(extra="forbid")

# Edge types we consider "callers" / "tests" / "importers" — see V2 README.
_CALLS = "CALLS"
_TESTS = ("TESTS", "COVERS")
_IMPORTS = "IMPORTS"

# psql column separator. Pipe `|` is psql's default for -A output but symbol
# names can legitimately contain it; use ASCII unit-separator instead.
_SEP = "\x1f"


def _log(tool: str, project_id: str) -> None:
    logger.info("mcp_tool_call", extra={"tool": tool, "project_id": project_id, "actor": "agent"})


def _stub(data: dict) -> ToolResponse:
    return ToolResponse(status="stub_implementation", data=data)


# -- Input models (one per tool so the registry can introspect them) -------


class GraphQueryInput(BaseModel):
    """Inputs for ``graph_query``."""

    model_config = _FORBID
    project_id: str = Field(..., min_length=1)
    query: str = Field(..., min_length=1, description="Raw cypher-like or SQL query against spine_kg.")


class FindCallersInput(BaseModel):
    """Inputs for ``find_callers`` (STORY-6.5.2)."""

    model_config = _FORBID
    project_id: str = Field(..., min_length=1)
    symbol: str = Field(..., min_length=1, description="Qualified name like 'module.Class.method' or 'module:function'.")
    repo: str = Field(..., min_length=1, description="Repo to query; fail loud if missing (no implicit default).")
    depth: int = Field(default=1, ge=1, le=10, description="1 = direct callers; 2+ = transitive via intermediates.")
    commit_sha: str | None = Field(default=None, description="Point-in-time snapshot (NFR-6); default = current head.")
    limit: int = Field(default=100, ge=1, le=10000, description="Cap on returned callers.")


class CodeNeighborhoodInput(BaseModel):
    """Inputs for ``code_neighborhood``."""

    model_config = _FORBID
    project_id: str = Field(..., min_length=1)
    node: str = Field(..., min_length=1, description="File path or symbol anchor.")
    radius: int = Field(default=2, ge=1, le=5, description="Hops to expand from the anchor.")


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
    """Inputs for ``doc_for_region``."""

    model_config = _FORBID
    project_id: str = Field(..., min_length=1)
    region: str = Field(..., min_length=1, description="file:lines selector, e.g. 'auth/session.py:1-50'.")


class WhoOwnsInput(BaseModel):
    """Inputs for ``who_owns``."""

    model_config = _FORBID
    project_id: str = Field(..., min_length=1)
    node: str = Field(..., min_length=1, description="File or symbol whose owners we want.")


class HybridSearchInput(BaseModel):
    """Inputs for ``hybrid_search`` (EPIC-6.7 / STORY-6.7.3)."""

    model_config = _FORBID
    project_id: str = Field(..., min_length=1)
    query: str = Field(..., min_length=1, description="Natural-language query.")
    top_k: int = Field(default=10, ge=1, le=100)


# -- Output models (returned inside ToolResponse.data) ---------------------


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
    cmd: list[str] = ["psql", _db_url(), "-A", "-X", "-q", "-v", "ON_ERROR_STOP=1",
                      "-F", _SEP, "--pset=footer=off"]
    for k, v in params.items():
        # Coerce to str; psql -v always takes string values.
        cmd.extend(["-v", f"{k}={v}"])
    cmd.extend(["-c", sql])
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10, check=True)
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


@register_tool(name="graph_query", input_model=GraphQueryInput, story="STORY-6.5.1",
               description="Raw KG query escape hatch for power users.", tags=("kg",))
def graph_query(payload: GraphQueryInput) -> ToolResponse:
    """Stub. TODO STORY-6.5.1: real implementation."""
    _log("graph_query", payload.project_id)
    return _stub({"rows": []})


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


@register_tool(name="code_neighborhood", input_model=CodeNeighborhoodInput, story="STORY-6.5.4",
               description="Subgraph within N hops of a code anchor.", tags=("kg",))
def code_neighborhood(payload: CodeNeighborhoodInput) -> ToolResponse:
    """Stub. TODO STORY-6.5.4: real implementation."""
    _log("code_neighborhood", payload.project_id)
    return _stub({"nodes": [], "edges": []})


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
    """Stub. TODO STORY-6.5.6: real implementation."""
    _log("doc_for_region", payload.project_id)
    return _stub({"docs": []})


@register_tool(name="who_owns", input_model=WhoOwnsInput, story="STORY-6.5.7",
               description="Roles, lessons, and ADRs claiming ownership of the given node.", tags=("kg",))
def who_owns(payload: WhoOwnsInput) -> ToolResponse:
    """Stub. TODO STORY-6.5.7: real implementation."""
    _log("who_owns", payload.project_id)
    return _stub({"owners": []})


@register_tool(name="hybrid_search", input_model=HybridSearchInput, story="STORY-6.7.3",
               description="LangChain-backed hybrid graph + vector retrieval over the KG.", tags=("kg", "rag"))
def hybrid_search(payload: HybridSearchInput) -> ToolResponse:
    """Stub. TODO STORY-6.7.3: real implementation."""
    _log("hybrid_search", payload.project_id)
    return _stub({"results": []})


__all__: list[str] = [
    "CallerInfo", "CodeNeighborhoodInput", "DocForRegionInput", "FindCallersInput",
    "FindCallersOutput", "GraphQueryInput", "HybridSearchInput", "ImpactedNode",
    "ImpactRadiusInput", "ImpactRadiusOutput", "WhoOwnsInput",
    "code_neighborhood", "doc_for_region", "find_callers", "graph_query",
    "hybrid_search", "impact_radius", "who_owns",
]
