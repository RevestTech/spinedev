"""Knowledge-graph MCP tools.

Tools from REQ-INIT-6 FR-6 (EPIC-6.5) plus the hybrid retrieval tool from
FR-8 (EPIC-6.7). Real implementations live behind the ``spine_kg`` schema and
LangChain ``GraphRetriever`` / ``MultiVectorRetriever`` wrappers; these are
scaffolding only.

Tools registered: ``graph_query``, ``find_callers``, ``code_neighborhood``,
``impact_radius``, ``doc_for_region``, ``who_owns``, ``hybrid_search``.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, ConfigDict, Field

from shared.mcp.schemas import ToolResponse
from shared.mcp.tools import register_tool

logger = logging.getLogger(__name__)

_FORBID = ConfigDict(extra="forbid")


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
    """Inputs for ``find_callers``."""

    model_config = _FORBID
    project_id: str = Field(..., min_length=1)
    symbol: str = Field(..., min_length=1, description="Fully-qualified symbol, e.g. 'pkg.mod.func'.")
    depth: int = Field(default=1, ge=1, le=10, description="Caller graph traversal depth.")


class CodeNeighborhoodInput(BaseModel):
    """Inputs for ``code_neighborhood``."""

    model_config = _FORBID
    project_id: str = Field(..., min_length=1)
    node: str = Field(..., min_length=1, description="File path or symbol anchor.")
    radius: int = Field(default=2, ge=1, le=5, description="Hops to expand from the anchor.")


class ImpactRadiusInput(BaseModel):
    """Inputs for ``impact_radius``."""

    model_config = _FORBID
    project_id: str = Field(..., min_length=1)
    target: str = Field(..., min_length=1, description="Symbol or file:lines region whose blast radius to compute.")


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


# -- Tool functions — all stubs --------------------------------------------


@register_tool(name="graph_query", input_model=GraphQueryInput, story="STORY-6.5.1",
               description="Raw KG query escape hatch for power users.", tags=("kg",))
def graph_query(payload: GraphQueryInput) -> ToolResponse:
    """Stub. TODO STORY-6.5.1: real implementation."""
    _log("graph_query", payload.project_id)
    return _stub({"rows": []})


@register_tool(name="find_callers", input_model=FindCallersInput, story="STORY-6.5.2",
               description="Direct and transitive callers of a symbol with file:line context.", tags=("kg",))
def find_callers(payload: FindCallersInput) -> ToolResponse:
    """Stub. TODO STORY-6.5.2: real implementation."""
    _log("find_callers", payload.project_id)
    return _stub({"callers": []})


@register_tool(name="code_neighborhood", input_model=CodeNeighborhoodInput, story="STORY-6.5.4",
               description="Subgraph within N hops of a code anchor.", tags=("kg",))
def code_neighborhood(payload: CodeNeighborhoodInput) -> ToolResponse:
    """Stub. TODO STORY-6.5.4: real implementation."""
    _log("code_neighborhood", payload.project_id)
    return _stub({"nodes": [], "edges": []})


@register_tool(name="impact_radius", input_model=ImpactRadiusInput, story="STORY-6.5.5",
               description="Files and tests potentially affected by a change to the given symbol/region.", tags=("kg",))
def impact_radius(payload: ImpactRadiusInput) -> ToolResponse:
    """Stub. TODO STORY-6.5.5: real implementation."""
    _log("impact_radius", payload.project_id)
    return _stub({"files": [], "tests": []})


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
    "CodeNeighborhoodInput", "DocForRegionInput", "FindCallersInput", "GraphQueryInput",
    "HybridSearchInput", "ImpactRadiusInput", "WhoOwnsInput",
    "code_neighborhood", "doc_for_region", "find_callers", "graph_query",
    "hybrid_search", "impact_radius", "who_owns",
]
