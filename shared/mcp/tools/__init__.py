"""Tool registry for the unified Spine MCP server.

Tool modules in this package register their tools via the :func:`register_tool`
decorator. The server walks the package on startup, imports every sibling
module, and collects everything decorated into :data:`TOOL_REGISTRY`.

Pattern (used by every ``tools/*.py`` module)::

    from pydantic import BaseModel
    from shared.mcp.schemas import ToolResponse
    from shared.mcp.tools import register_tool


    class MyInput(BaseModel):
        name: str


    @register_tool(name="my_tool", input_model=MyInput, story="STORY-X.Y.Z")
    def my_tool(payload: MyInput) -> ToolResponse:
        ...
"""

from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass, field
from typing import Any, Callable

from pydantic import BaseModel

ToolFn = Callable[[BaseModel], Any]
"""Signature every registered tool function must satisfy."""


@dataclass(frozen=True)
class ToolSpec:
    """Static description of one registered MCP tool.

    Attributes:
        name: Wire name exposed via MCP (e.g. ``"project_create"``).
        fn: The callable; receives the validated input model, returns ToolResponse.
        input_model: Pydantic model class used to validate the call payload.
        module: Dotted module path the tool was defined in.
        story: Implementing story ID (e.g. ``"STORY-9.9.1"``) for traceability.
        description: One-line human description (defaults to the fn docstring).
        tags: Optional labels for grouping/filtering in catalogs.
        requires_citation: When ``True`` the server's Cite-or-Refuse
            middleware (V3 #12) enforces that responses carry a
            non-empty ``citation`` field; missing → 422 refusal +
            audit event. Verify-class tools (auditor, qa, verify, iso)
            set this to ``True``.
    """

    name: str
    fn: ToolFn
    input_model: type[BaseModel]
    module: str
    story: str
    description: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)
    requires_citation: bool = False


TOOL_REGISTRY: dict[str, ToolSpec] = {}
"""Process-wide registry populated by the ``@register_tool`` decorator."""


def register_tool(
    *,
    name: str,
    input_model: type[BaseModel],
    story: str,
    description: str | None = None,
    tags: tuple[str, ...] = (),
    requires_citation: bool = False,
) -> Callable[[ToolFn], ToolFn]:
    """Decorate a tool function so it is discoverable by the server.

    Args:
        name: Wire name. Must be unique across the whole registry.
        input_model: Pydantic v2 ``BaseModel`` subclass used to validate input.
        story: Implementing story ID from ``docs/BACKLOG.md``.
        description: Optional one-line description; falls back to the docstring.
        tags: Optional labels (e.g. ``("kg",)``) for catalog filtering.

    Raises:
        ValueError: If ``name`` is already registered or ``input_model`` is
            not a Pydantic ``BaseModel`` subclass.
    """
    if not (isinstance(input_model, type) and issubclass(input_model, BaseModel)):
        raise ValueError(
            f"register_tool(name={name!r}): input_model must be a Pydantic BaseModel subclass"
        )

    def _wrap(fn: ToolFn) -> ToolFn:
        if name in TOOL_REGISTRY:
            existing = TOOL_REGISTRY[name]
            raise ValueError(
                f"Duplicate MCP tool name {name!r}: already registered by "
                f"{existing.module}.{existing.fn.__name__}"
            )
        spec = ToolSpec(
            name=name,
            fn=fn,
            input_model=input_model,
            module=fn.__module__,
            story=story,
            description=description or (fn.__doc__ or "").strip().splitlines()[0]
            if (description or fn.__doc__)
            else "",
            tags=tuple(tags),
            requires_citation=requires_citation,
        )
        TOOL_REGISTRY[name] = spec
        return fn

    return _wrap


def discover_tools(package: str = __name__) -> dict[str, ToolSpec]:
    """Import every sibling module so its ``@register_tool`` decorators fire.

    Idempotent: re-importing already-loaded modules is a no-op. Returns the
    full registry (callers usually just read :data:`TOOL_REGISTRY` directly).

    Per-module errors are logged + skipped so a single broken tool module
    doesn't truncate the rest of the registry (the old behavior caused the
    Hub to silently load only the first ~9 tools when one mid-list module
    blew up at import time — `project_create` and other downstream tools
    went missing without trace).
    """
    import logging as _logging

    _log = _logging.getLogger(__name__)
    pkg = importlib.import_module(package)
    for mod_info in pkgutil.iter_modules(pkg.__path__):
        if mod_info.name.startswith("_"):
            continue
        try:
            importlib.import_module(f"{package}.{mod_info.name}")
        except Exception as exc:  # noqa: BLE001
            _log.warning(
                "discover_tools_module_skipped",
                extra={"module": f"{package}.{mod_info.name}",
                       "error": f"{type(exc).__name__}: {exc}"[:200]},
            )
    return dict(TOOL_REGISTRY)


__all__: list[str] = [
    "TOOL_REGISTRY",
    "ToolFn",
    "ToolSpec",
    "discover_tools",
    "register_tool",
]
