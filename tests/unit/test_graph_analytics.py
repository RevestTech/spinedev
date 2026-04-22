"""Unit tests for ``tron.services.graph_analytics``."""

from __future__ import annotations

from tron.services.graph_analytics import (
    SimpleEdge,
    impact_transitive_dependents,
    transitive_dependencies,
)


def test_transitive_dependencies_follows_internal_edges():
    paths = frozenset({"a.py", "b.py", "c.py"})
    edges = [
        SimpleEdge("a.py", "b.py", False),
        SimpleEdge("b.py", "c.py", False),
    ]
    seen, epairs = transitive_dependencies("a.py", paths, edges)
    assert seen == {"a.py", "b.py", "c.py"}
    assert epairs == {("a.py", "b.py"), ("b.py", "c.py")}


def test_transitive_skips_external_edges():
    paths = frozenset({"a.py", "b.py"})
    edges = [SimpleEdge("a.py", "b.py", True)]
    seen, epairs = transitive_dependencies("a.py", paths, edges)
    assert seen == {"a.py"}
    assert epairs == set()


def test_impact_collects_reverse_closure():
    paths = frozenset({"a.py", "b.py", "c.py"})
    edges = [
        SimpleEdge("a.py", "b.py", False),
        SimpleEdge("b.py", "c.py", False),
    ]
    seen, epairs = impact_transitive_dependents("c.py", paths, edges)
    assert seen == {"c.py", "b.py", "a.py"}
    assert epairs == {("b.py", "c.py"), ("a.py", "b.py")}
