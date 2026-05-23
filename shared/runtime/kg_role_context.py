"""KG retrieve middleware — hybrid_search context before role dispatch (P1)."""

from __future__ import annotations

import logging
import os
from typing import Any

from shared.runtime.mcp_invoke import invoke_mcp_tool

logger = logging.getLogger("spine.runtime.kg_role_context")

_RETRIEVE_ENV = "SPINE_KG_RETRIEVE"


def kg_retrieve_enabled() -> bool:
    return os.environ.get(_RETRIEVE_ENV, "1").strip().lower() not in ("0", "false", "no")


def build_role_query(
    *,
    role: str,
    phase: str,
    directive: str,
    project_name: str = "",
) -> str:
    """Natural-language query seed for hybrid_search."""
    name_bit = f" for project {project_name}" if project_name else ""
    return (
        f"Relevant code, requirements, and architecture{ name_bit } "
        f"for {role} role during {phase} executing {directive}"
    )


def format_hybrid_search_block(data: dict[str, Any]) -> str:
    """Turn hybrid_search ToolResponse.data into markdown for LLM context."""
    results = data.get("results") or []
    if not results:
        return ""
    lines = ["## Knowledge graph context (hybrid_search)", ""]
    for row in results[:15]:
        if not isinstance(row, dict):
            continue
        path = row.get("path") or "?"
        name = row.get("name") or "?"
        ntype = row.get("type") or "?"
        node_id = row.get("node_id") or "?"
        rationale = row.get("rationale") or ""
        lines.append(f"- `{path}` — **{name}** ({ntype}, `{node_id}`): {rationale}")
    lines.append("")
    lines.append("_Cite node_id or path when referencing graph facts._")
    return "\n".join(lines)


def retrieve_kg_context_for_dispatch(
    *,
    project_id: str,
    repo: str,
    role: str,
    phase: str,
    directive: str,
    project_name: str = "",
    commit_sha: str | None = None,
    limit: int = 12,
) -> str:
    """Best-effort KG retrieval; returns empty string on miss (never raises)."""
    if not kg_retrieve_enabled() or not repo:
        return ""

    query = build_role_query(
        role=role,
        phase=phase,
        directive=directive,
        project_name=project_name,
    )
    payload: dict[str, Any] = {
        "project_id": project_id,
        "query": query,
        "repo": repo,
        "limit": limit,
        "semantic_weight": 0.55,
    }
    if commit_sha:
        payload["commit_sha"] = commit_sha

    try:
        raw = invoke_mcp_tool("hybrid_search", payload)
    except Exception as exc:  # noqa: BLE001
        logger.debug("kg_retrieve_invoke_failed", extra={"err": str(exc)})
        return ""

    if raw.get("status") != "ok":
        logger.debug(
            "kg_retrieve_empty",
            extra={"role": role, "status": raw.get("status")},
        )
        return ""

    block = format_hybrid_search_block(raw.get("data") or {})
    if block:
        logger.info(
            "kg_retrieve_ok",
            extra={"role": role, "repo": repo, "chars": len(block)},
        )
    return block


__all__ = [
    "build_role_query",
    "format_hybrid_search_block",
    "kg_retrieve_enabled",
    "retrieve_kg_context_for_dispatch",
]
