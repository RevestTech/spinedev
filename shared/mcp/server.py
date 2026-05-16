"""Unified Spine MCP server entry point.

Single dispatch surface for Plan, Build, Verify, Orchestrator, KG, and
Standards primitives. Two transports:

* ``stdio`` — AI agent harnesses (Claude Code, Codex, Cursor).
* ``http``  — dashboard, REST callers, external services.

Run::

    python -m shared.mcp.server --transport stdio
    python -m shared.mcp.server --transport http --port 8765

Tool registration uses the decorator pattern from ``shared.mcp.tools``;
:func:`SpineMcpServer.load_tools` walks ``shared/mcp/tools/*.py`` and adds
every ``@register_tool``-decorated function to the MCP runtime. The actual
``mcp`` SDK is imported **lazily** inside the transport methods so this module
remains importable in environments without the SDK.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass
from typing import Any

from shared.mcp.tools import TOOL_REGISTRY, ToolSpec, discover_tools

logger = logging.getLogger(__name__)


# -- Logging — JSON formatter, no secrets ever in the rendered record. -----

_SECRET_KEYS: frozenset[str] = frozenset(
    {"approval_token", "token", "api_key", "secret", "password", "hmac_key"}
)


class _JsonFormatter(logging.Formatter):
    """Minimal JSON log formatter; redacts known-sensitive keys from ``extra``."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        std_attrs = set(logging.LogRecord("", 0, "", 0, "", None, None).__dict__)
        std_attrs.update({"message", "asctime"})
        for key, value in record.__dict__.items():
            if key in std_attrs:
                continue
            payload[key] = "[REDACTED]" if key in _SECRET_KEYS else value
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: int = logging.INFO) -> None:
    """Install the JSON formatter on the root logger (idempotent)."""
    root = logging.getLogger()
    root.setLevel(level)
    if any(
        isinstance(h, logging.StreamHandler) and isinstance(h.formatter, _JsonFormatter)
        for h in root.handlers
    ):
        return
    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(_JsonFormatter())
    root.addHandler(handler)


# -- Server wrapper --------------------------------------------------------


@dataclass
class SpineMcpServer:
    """Thin wrapper around the MCP runtime.

    Owns tool discovery + the tool catalog. The underlying MCP server is
    instantiated lazily inside :meth:`serve` so tests can construct this
    wrapper without importing the ``mcp`` SDK.
    """

    name: str = "spine"
    version: str = "0.1.0"

    def __post_init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def load_tools(self) -> dict[str, ToolSpec]:
        """Import every tool module so its ``@register_tool`` decorators fire."""
        self._tools = discover_tools("shared.mcp.tools")
        logger.info(
            "mcp_tools_loaded",
            extra={"tool_count": len(self._tools), "tools": sorted(self._tools)},
        )
        return self._tools

    @property
    def tools(self) -> dict[str, ToolSpec]:
        """Return the currently-loaded tool catalog."""
        return dict(self._tools or TOOL_REGISTRY)

    def serve(self, transport: str, host: str = "127.0.0.1", port: int = 8765) -> None:
        """Boot the underlying MCP runtime on the requested transport."""
        if not self._tools:
            self.load_tools()
        if transport not in ("stdio", "http"):
            raise ValueError(f"Unknown transport: {transport!r}; expected 'stdio' or 'http'")
        try:
            from mcp.server.fastmcp import FastMCP  # type: ignore
        except ImportError as exc:  # pragma: no cover - runtime-only path
            raise RuntimeError(
                "The 'mcp' Python SDK is required to run the MCP server. "
                "Install it before starting."
            ) from exc

        app = FastMCP(self.name)
        for spec in self._tools.values():
            self._register_one(app, spec)

        if transport == "stdio":
            logger.info("mcp_serve_stdio", extra={"name": self.name, "version": self.version})
            app.run()
        else:
            logger.info(
                "mcp_serve_http",
                extra={"name": self.name, "version": self.version, "host": host, "port": port},
            )
            # FastMCP's HTTP transport signature may evolve upstream; wrapper isolates it.
            app.run(transport="http", host=host, port=port)  # type: ignore[call-arg]

    @staticmethod
    def _register_one(app: Any, spec: ToolSpec) -> None:
        """Wrap a single tool so FastMCP can call it with a validated payload."""
        input_model = spec.input_model
        fn = spec.fn

        def _adapter(**raw: Any) -> dict[str, Any]:
            payload = input_model.model_validate(raw)
            response = fn(payload)
            if hasattr(response, "model_dump"):
                return response.model_dump(mode="json")
            return dict(response)

        _adapter.__name__ = spec.name
        _adapter.__doc__ = spec.description or fn.__doc__
        app.tool(name=spec.name, description=spec.description)(_adapter)


# -- CLI -------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="shared.mcp.server", description="Unified Spine MCP server.")
    p.add_argument("--transport", choices=("stdio", "http"), default="stdio")
    p.add_argument("--host", default="127.0.0.1", help="HTTP bind host (http transport only).")
    p.add_argument("--port", type=int, default=8765, help="HTTP bind port (http transport only).")
    p.add_argument("--log-level", default="INFO", help="Python logging level.")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    configure_logging(level=getattr(logging, args.log_level.upper(), logging.INFO))
    server = SpineMcpServer()
    server.load_tools()
    server.serve(transport=args.transport, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
