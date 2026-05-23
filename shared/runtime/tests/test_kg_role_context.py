"""Tests for KG retrieve middleware."""

from __future__ import annotations

from shared.runtime.kg_role_context import (
    build_role_query,
    format_hybrid_search_block,
    kg_retrieve_enabled,
    retrieve_kg_context_for_dispatch,
)


def test_build_role_query_includes_role_and_directive() -> None:
    q = build_role_query(
        role="planner",
        phase="plan_in_progress",
        directive="PRODUCE_ROADMAP",
        project_name="Acme",
    )
    assert "planner" in q
    assert "PRODUCE_ROADMAP" in q
    assert "Acme" in q


def test_format_hybrid_search_block_empty() -> None:
    assert format_hybrid_search_block({"results": []}) == ""


def test_format_hybrid_search_block_renders_rows() -> None:
    block = format_hybrid_search_block({
        "results": [
            {
                "path": "src/main.py",
                "name": "main",
                "type": "Function",
                "node_id": "fn:main",
                "rationale": "matched semantically (rank 1)",
            },
        ],
    })
    assert "Knowledge graph context" in block
    assert "src/main.py" in block
    assert "fn:main" in block


def test_retrieve_disabled_returns_empty(monkeypatch) -> None:
    monkeypatch.setenv("SPINE_KG_RETRIEVE", "0")
    assert kg_retrieve_enabled() is False
    assert retrieve_kg_context_for_dispatch(
        project_id="1",
        repo="demo",
        role="engineer",
        phase="build",
        directive="PRODUCE_CODE",
    ) == ""
