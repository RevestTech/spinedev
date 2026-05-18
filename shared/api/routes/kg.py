"""``/api/v2/kg`` — REST front-end over the 9 KG MCP tools (V3 Wave 3 part 2).

Drift audit Finding (Wave 3 part 2): ``shared/api/routes/`` had no ``kg.py``
even though the SPA's kg-search panel needs HTTP. The 9 existing KG MCP tools
in ``shared.mcp.tools.kg`` (graph_query, find_callers, impact_radius, …) stay
as the source of truth; this module is a thin HTTP adapter so the SPA + any
non-MCP client can hit them over plain Bearer-auth'd REST.

Endpoints (all Bearer-auth via ``current_user``; mobile-friendly per #28):

* ``GET /api/v2/kg/search?q=...&repo=...&project_id=...&limit=...``
    Wraps ``hybrid_search`` — natural-language search across the KG.
* ``GET /api/v2/kg/node/{node_id}?project_id=...&repo=...&radius=...``
    Wraps ``graph_query`` + ``code_neighborhood`` for one node + neighbours.
* ``GET /api/v2/kg/callers/{symbol}?project_id=...&repo=...&depth=...``
    Wraps ``find_callers``.
* ``GET /api/v2/kg/impact/{file}?project_id=...&repo=...&target_type=...``
    Wraps ``impact_radius``.
* ``GET /api/v2/kg/owners/{path}?project_id=...&repo=...``
    Wraps ``who_owns``.

Per #12 (Cite-or-Refuse): every response carries a ``citations`` array of
KG node IDs that satisfied the query. The KG node IS the citation — that
is the v1.0 contract per the design decision.

Per #9 (no-secrets): the KG never holds secret values; only node IDs and
paths, so no redaction is required at this layer.

Note: this is REST, NOT MCP. The 9 existing MCP tools remain registered
via ``@register_tool`` in ``shared.mcp.tools.kg`` and are NOT duplicated
here. ``EXPECTED_TOOLS_BY_MODULE`` is unchanged.

Dependencies: ``fastapi``, ``pydantic`` (already required).
"""

from __future__ import annotations

import logging
import time
from typing import Annotated, Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, ConfigDict, Field

from shared.api.dependencies import current_user
from shared.identity.models import User
from shared.mcp.schemas.envelopes import Citation, ToolResponse
from shared.mcp.tools import kg as _kg

logger = logging.getLogger("spine.api.kg")
router = APIRouter(prefix="/api/v2/kg", tags=["kg"])


# ---------------------------------------------------------------------------
# Shared response shapes
# ---------------------------------------------------------------------------


class KgResult(BaseModel):
    """One row in the search-result list (also reused by neighborhood/callers)."""

    model_config = ConfigDict(extra="forbid")
    node_id: str
    name: str
    node_type: str
    path: str
    score: float = Field(default=0.0, ge=0.0, le=1.0,
        description="Relevance score 0..1; 0 if the source tool didn't supply one.")
    rationale: Optional[str] = None


class KgSearchResponse(BaseModel):
    """``GET /kg/search`` envelope. Per #12 carries citations."""

    model_config = ConfigDict(extra="forbid")
    ok: bool = True
    query: str
    results: list[KgResult]
    total: int
    query_latency_ms: int
    citations: list[Citation] = Field(default_factory=list)


class KgEdge(BaseModel):
    """One edge in a node's neighborhood."""

    model_config = ConfigDict(extra="forbid")
    from_node_id: str
    to_node_id: str
    edge_type: str


class KgNodeDetail(BaseModel):
    """``GET /kg/node/{node_id}`` envelope — node + 1-hop neighbours."""

    model_config = ConfigDict(extra="forbid")
    ok: bool = True
    node_id: str
    node: Optional[KgResult] = None
    neighbors: list[KgResult] = Field(default_factory=list)
    edges: list[KgEdge] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)


class KgCaller(BaseModel):
    """One caller returned by ``find_callers``."""

    model_config = ConfigDict(extra="forbid")
    node_id: str
    name: str
    node_type: str
    path: str
    depth: int


class KgCallersResponse(BaseModel):
    """``GET /kg/callers/{symbol}`` envelope."""

    model_config = ConfigDict(extra="forbid")
    ok: bool = True
    symbol: str
    callers: list[KgCaller]
    total: int
    citations: list[Citation] = Field(default_factory=list)


class KgImpactNode(BaseModel):
    """One impacted node from ``impact_radius``."""

    model_config = ConfigDict(extra="forbid")
    node_id: str
    node_type: str
    path: str
    impact_distance: int
    impact_kind: str


class KgImpactResponse(BaseModel):
    """``GET /kg/impact/{file}`` envelope."""

    model_config = ConfigDict(extra="forbid")
    ok: bool = True
    target: str
    impacted: list[KgImpactNode]
    direct_caller_count: int
    direct_test_count: int
    importer_count: int
    total_impact: int
    citations: list[Citation] = Field(default_factory=list)


class KgOwner(BaseModel):
    """One owner returned by ``who_owns``."""

    model_config = ConfigDict(extra="forbid")
    owner_type: str
    owner_id: str
    confidence: float
    via: str


class KgOwnersResponse(BaseModel):
    """``GET /kg/owners/{path}`` envelope."""

    model_config = ConfigDict(extra="forbid")
    ok: bool = True
    target: str
    owners: list[KgOwner]
    citations: list[Citation] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _http_err(code: int, ec: str, msg: str) -> HTTPException:
    """Structured HTTPException matching the audit-route convention."""
    return HTTPException(status_code=code, detail={"error_code": ec, "message": msg})


def _run_tool(tool_callable: Any, payload: Any, *, label: str) -> ToolResponse:
    """Call an MCP tool, mapping infra failures to HTTP and tool errors to 422.

    The KG tools raise ``RuntimeError`` if ``SPINE_DB_URL`` is unset or psql
    fails (per kg.py ``_db_url`` / ``_run_psql_query``). We translate that to
    a 503 so the SPA can show a friendly "KG not configured" empty state.

    Tool-level errors (status='error' inside the envelope) become 422.
    """
    try:
        resp: ToolResponse = tool_callable(payload)
    except RuntimeError as exc:  # SPINE_DB_URL missing or psql failure
        logger.warning("kg.tool_unavailable", extra={"tool": label, "err": str(exc)[:200]})
        raise _http_err(503, "kg_unavailable", f"KG backend unavailable: {exc}") from exc
    except Exception as exc:  # noqa: BLE001 — surface other bugs as 500
        logger.exception("kg.tool_crashed", extra={"tool": label})
        raise _http_err(500, "kg_internal_error",
                        f"unexpected KG error: {type(exc).__name__}") from exc
    if resp.status == "error":
        ec = resp.error.code if resp.error else "tool_error"
        msg = resp.error.message if resp.error else "tool returned error"
        raise _http_err(422, ec, msg)
    return resp


def _cite(node_ids: list[str], excerpt: Optional[str] = None) -> list[Citation]:
    """Build a Cite-or-Refuse citation list (per #12) keyed by KG node IDs.

    The KG node IS the citation surface — this is the v1.0 contract for the
    kg/* routes per design decision #12. Empty inputs produce an empty list;
    callers tag verify-class endpoints so the SPA always has something to
    render a chip from when there IS a result.
    """
    return [Citation(type="kg_node", ref=nid, excerpt=excerpt) for nid in node_ids]


# ---------------------------------------------------------------------------
# GET /api/v2/kg/search
# ---------------------------------------------------------------------------


@router.get("/search", response_model=KgSearchResponse)
async def kg_search(
    user: Annotated[User, Depends(current_user)],
    q: str = Query(..., min_length=1, description="Natural-language query."),
    project_id: str = Query(..., min_length=1),
    repo: str = Query(..., min_length=1),
    limit: int = Query(default=20, ge=1, le=200),
    semantic_weight: float = Query(default=0.5, ge=0.0, le=1.0),
) -> KgSearchResponse:
    """Hybrid (semantic + structural) KG search.

    Per #12, citations are the matched KG node IDs. SPA renders one
    ``<CitationChip />`` per result so a verify-class consumer can audit
    which graph node satisfied which row.
    """
    started = time.perf_counter()
    payload = _kg.HybridSearchInput(
        project_id=project_id, query=q, repo=repo, limit=limit,
        semantic_weight=semantic_weight,
    )
    resp = _run_tool(_kg.hybrid_search, payload, label="hybrid_search")
    rows = (resp.data or {}).get("results", [])
    results = [KgResult(
        node_id=r.get("node_id", ""),
        name=r.get("name", ""),
        node_type=r.get("type", ""),
        path=r.get("path", ""),
        score=float(r.get("combined_score", 0.0) or 0.0),
        rationale=r.get("rationale"),
    ) for r in rows]
    latency_ms = int((time.perf_counter() - started) * 1000)
    return KgSearchResponse(
        query=q,
        results=results,
        total=len(results),
        query_latency_ms=latency_ms,
        citations=_cite([r.node_id for r in results if r.node_id]),
    )


# ---------------------------------------------------------------------------
# GET /api/v2/kg/node/{node_id}
# ---------------------------------------------------------------------------


@router.get("/node/{node_id}", response_model=KgNodeDetail)
async def kg_node(
    user: Annotated[User, Depends(current_user)],
    node_id: str = Path(..., min_length=1),
    project_id: str = Query(..., min_length=1),
    repo: str = Query(..., min_length=1),
    radius: int = Query(default=1, ge=1, le=3,
        description="Neighborhood radius in hops (capped at 3 for response size)."),
) -> KgNodeDetail:
    """Fetch a node + its 1..3-hop neighborhood (via ``code_neighborhood``).

    The node-id passed by the caller is also the canonical citation, plus
    every neighbour we surface — the SPA can hyperlink back to itself.
    """
    payload = _kg.CodeNeighborhoodInput(
        project_id=project_id, target=node_id, repo=repo, radius=radius,
    )
    resp = _run_tool(_kg.code_neighborhood, payload, label="code_neighborhood")
    data = resp.data or {}
    raw_nodes = data.get("nodes", []) or []
    raw_edges = data.get("edges", []) or []

    self_node: Optional[KgResult] = None
    neighbors: list[KgResult] = []
    for n in raw_nodes:
        nid = n.get("node_id", "")
        kr = KgResult(
            node_id=nid,
            name=n.get("name", ""),
            node_type=n.get("type", ""),
            path=n.get("path", ""),
            score=0.0,
        )
        if nid == node_id and self_node is None:
            self_node = kr
        else:
            neighbors.append(kr)
    edges = [KgEdge(
        from_node_id=e.get("from_node_id", ""),
        to_node_id=e.get("to_node_id", ""),
        edge_type=e.get("edge_type", ""),
    ) for e in raw_edges]
    cite_ids = [node_id] + [n.node_id for n in neighbors if n.node_id]
    return KgNodeDetail(
        node_id=node_id,
        node=self_node,
        neighbors=neighbors,
        edges=edges,
        citations=_cite(cite_ids),
    )


# ---------------------------------------------------------------------------
# GET /api/v2/kg/callers/{symbol}
# ---------------------------------------------------------------------------


@router.get("/callers/{symbol:path}", response_model=KgCallersResponse)
async def kg_callers(
    user: Annotated[User, Depends(current_user)],
    symbol: str = Path(..., min_length=1,
        description="Qualified symbol like 'module.Class.method'."),
    project_id: str = Query(..., min_length=1),
    repo: str = Query(..., min_length=1),
    depth: int = Query(default=1, ge=1, le=5),
    limit: int = Query(default=100, ge=1, le=1000),
) -> KgCallersResponse:
    """Find direct (depth=1) or transitive (depth>=2) callers of ``symbol``."""
    payload = _kg.FindCallersInput(
        project_id=project_id, symbol=symbol, repo=repo, depth=depth, limit=limit,
    )
    resp = _run_tool(_kg.find_callers, payload, label="find_callers")
    raw = (resp.data or {}).get("callers", []) or []
    callers = [KgCaller(
        node_id=c.get("node_id", ""),
        name=c.get("name", ""),
        node_type=c.get("type", ""),
        path=c.get("path", ""),
        depth=int(c.get("depth", 0) or 0),
    ) for c in raw]
    return KgCallersResponse(
        symbol=symbol,
        callers=callers,
        total=len(callers),
        citations=_cite([c.node_id for c in callers if c.node_id]),
    )


# ---------------------------------------------------------------------------
# GET /api/v2/kg/impact/{file}
# ---------------------------------------------------------------------------

TargetType = Literal["symbol", "file", "region"]


@router.get("/impact/{target:path}", response_model=KgImpactResponse)
async def kg_impact(
    user: Annotated[User, Depends(current_user)],
    target: str = Path(..., min_length=1,
        description="Symbol, file path, or 'file:lo-hi' region."),
    project_id: str = Query(..., min_length=1),
    repo: str = Query(..., min_length=1),
    target_type: TargetType = Query(default="file"),
    include_tests: bool = Query(default=True),
) -> KgImpactResponse:
    """Compute the impact-radius of changing ``target`` (callers + tests + importers)."""
    payload = _kg.ImpactRadiusInput(
        project_id=project_id, target=target, target_type=target_type,
        repo=repo, include_tests=include_tests,
    )
    resp = _run_tool(_kg.impact_radius, payload, label="impact_radius")
    data = resp.data or {}
    raw = data.get("impacted", []) or []
    impacted = [KgImpactNode(
        node_id=n.get("node_id", ""),
        node_type=n.get("type", ""),
        path=n.get("path", ""),
        impact_distance=int(n.get("impact_distance", 0) or 0),
        impact_kind=n.get("impact_kind", "caller"),
    ) for n in raw]
    return KgImpactResponse(
        target=target,
        impacted=impacted,
        direct_caller_count=int(data.get("direct_caller_count", 0) or 0),
        direct_test_count=int(data.get("direct_test_count", 0) or 0),
        importer_count=int(data.get("importer_count", 0) or 0),
        total_impact=int(data.get("total_impact", len(impacted)) or 0),
        citations=_cite([n.node_id for n in impacted if n.node_id]),
    )


# ---------------------------------------------------------------------------
# GET /api/v2/kg/owners/{path}
# ---------------------------------------------------------------------------


@router.get("/owners/{path:path}", response_model=KgOwnersResponse)
async def kg_owners(
    user: Annotated[User, Depends(current_user)],
    path: str = Path(..., min_length=1, description="File path or symbol."),
    project_id: str = Query(..., min_length=1),
    repo: str = Query(..., min_length=1),
) -> KgOwnersResponse:
    """Return ownership (role / person / team / ADR / memory) for ``path``."""
    payload = _kg.WhoOwnsInput(project_id=project_id, target=path, repo=repo)
    resp = _run_tool(_kg.who_owns, payload, label="who_owns")
    raw = (resp.data or {}).get("owners", []) or []
    owners = [KgOwner(
        owner_type=o.get("owner_type", ""),
        owner_id=o.get("owner_id", ""),
        confidence=float(o.get("confidence", 0.0) or 0.0),
        via=o.get("via", ""),
    ) for o in raw]
    # who_owns surfaces owner_ids that may not be KG node IDs; we still emit
    # the queried path as a citation so the SPA has a chip to render.
    citations = _cite([path])
    return KgOwnersResponse(
        target=path,
        owners=owners,
        citations=citations,
    )


__all__ = [
    "router",
    "KgResult",
    "KgEdge",
    "KgSearchResponse",
    "KgNodeDetail",
    "KgCaller",
    "KgCallersResponse",
    "KgImpactNode",
    "KgImpactResponse",
    "KgOwner",
    "KgOwnersResponse",
]
