"""In-process MCP tool invocation (mirrors orchestrator/lib/router.sh)."""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def invoke_mcp_tool(tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Validate payload, call a registered MCP tool, return parsed JSON dict."""
    from shared.mcp.tools import TOOL_REGISTRY, discover_tools  # noqa: PLC0415

    discover_tools()
    spec = TOOL_REGISTRY.get(tool_name)
    if spec is None:
        return {"status": "error", "error": {"code": "unknown_tool", "message": tool_name}, "data": {}}

    try:
        validated = spec.input_model.model_validate(payload)
        result = spec.fn(validated)
    except Exception as exc:  # noqa: BLE001
        logger.warning("mcp_invoke_failed", extra={"tool": tool_name, "error": str(exc)})
        return {"status": "error", "error": {"code": "invoke_failed", "message": str(exc)}, "data": {}}

    if hasattr(result, "model_dump"):
        return result.model_dump(mode="json")
    if isinstance(result, dict):
        return result
    return json.loads(json.dumps(result, default=str))
