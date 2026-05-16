"""Unified Spine MCP server package.

Single dispatch surface for the whole product: Plan, Build, Verify, and
Orchestrator primitives are exposed as MCP tools through one server.

See ``shared/mcp/README.md`` for the architecture overview and tool catalog.
"""

from __future__ import annotations

__version__: str = "0.1.0"
__all__: list[str] = ["__version__"]
