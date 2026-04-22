"""Pure graph helpers for dependency / impact analysis (used by graph API routes)."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class SimpleEdge:
    source: str
    target: str
    is_external: bool


def _internal_adjacency(
    edges: Iterable[SimpleEdge],
    allowed_paths: frozenset[str],
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Forward (source→target) and reverse adjacency for internal edges only."""
    out: dict[str, list[str]] = defaultdict(list)
    rev: dict[str, list[str]] = defaultdict(list)
    for e in edges:
        if e.is_external:
            continue
        if e.source not in allowed_paths or e.target not in allowed_paths:
            continue
        out[e.source].append(e.target)
        rev[e.target].append(e.source)
    return dict(out), dict(rev)


def transitive_dependencies(
    root_path: str,
    paths: frozenset[str],
    edges: Iterable[SimpleEdge],
    *,
    max_nodes: int = 5000,
) -> tuple[set[str], set[tuple[str, str]]]:
    """All nodes reachable from ``root_path`` following import direction (source imports target)."""
    if root_path not in paths:
        return set(), set()
    out_adj, _ = _internal_adjacency(edges, paths)
    seen: set[str] = {root_path}
    q: deque[str] = deque([root_path])
    used_edges: set[tuple[str, str]] = set()
    while q and len(seen) < max_nodes:
        u = q.popleft()
        for v in out_adj.get(u, ()):
            used_edges.add((u, v))
            if v not in seen:
                seen.add(v)
                q.append(v)
    return seen, used_edges


def impact_transitive_dependents(
    target_path: str,
    paths: frozenset[str],
    edges: Iterable[SimpleEdge],
    *,
    max_nodes: int = 5000,
) -> tuple[set[str], set[tuple[str, str]]]:
    """All sources that transitively depend on ``target_path`` (reverse of import edges)."""
    if target_path not in paths:
        return set(), set()
    _, rev_adj = _internal_adjacency(edges, paths)
    seen: set[str] = {target_path}
    q: deque[str] = deque([target_path])
    used_edges: set[tuple[str, str]] = set()
    while q and len(seen) < max_nodes:
        t = q.popleft()
        for s in rev_adj.get(t, ()):
            used_edges.add((s, t))
            if s not in seen:
                seen.add(s)
                q.append(s)
    return seen, used_edges
