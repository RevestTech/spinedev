"""Inter-story dependency detection for the Spine decomposer (STORY-1.3.3).

Deterministic upgrade promised by STORY-6.6.5 (KG replaces text-only
heuristic). Strategy: (1) if `shared.mcp.tools.kg.impact_radius` is
reachable + `SPINE_DB_URL` set, for each story extract code refs and
compute impact set — any other story whose refs sit in A's impact set
depends on A; (2) fall back to text overlap on identifiers (CamelCase,
snake_case, dotted/file paths), flagged `confidence='low'`; (3) DFS
cycle detection — circular deps surfaced as `reason='cycle: ...'` so
the planner resolves manually.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass

from plan.artifacts.roadmap_v1 import Story

logger = logging.getLogger(__name__)

# Identifier-ish tokens we treat as code refs in the fallback path.
_IDENT_RE = re.compile(
    r"(?:[A-Z][a-zA-Z0-9]+(?:\.[A-Z][a-zA-Z0-9]+)*)"          # CamelCase[.CamelCase]
    r"|(?:[a-z_][a-z0-9_]+(?:\.[a-z_][a-z0-9_]+)+)"           # dotted.snake.path
    r"|(?:[a-z_][a-z0-9_]{3,})"                                # snake_case ≥4 chars
    r"|(?:[\w/]+\.[a-z]{1,4})"                                 # path/to/file.py
)
_TEST_KW = re.compile(r"\b(test|spec|coverage|fixture)s?\b", re.IGNORECASE)
_SCHEMA_KW = re.compile(r"\b(schema|model|table|migration|entity)\b", re.IGNORECASE)


@dataclass(frozen=True)
class StoryDependency:
    """A discovered edge: `from_story_id` must complete before `to_story_id`."""

    from_story_id: str
    to_story_id: str
    reason: str
    confidence: str  # 'high' | 'medium' | 'low'


def detect_dependencies(
    stories: list[Story],
    kg_available: bool = True,
    project_id: str | None = None,
    repo: str | None = None,
) -> list[StoryDependency]:
    """Compute the dependency edge set for a flat list of stories."""
    if not stories:
        return []
    have_kg = kg_available and _kg_reachable()
    if not have_kg:
        logger.warning("decomposer_dependencies_text_only",
                       extra={"reason": "kg_unavailable", "story_count": len(stories)})
    refs: dict[str, set[str]] = {s.id: _extract_refs(s.title) for s in stories}
    edges: list[StoryDependency] = []
    for i, a in enumerate(stories):
        a_refs = refs[a.id]
        if not a_refs:
            continue
        a_impact = _kg_impact_for(a_refs, project_id, repo) if have_kg else set()
        for j, b in enumerate(stories):
            if i == j or not refs[b.id]:
                continue
            edge = _edge_between(a, b, a_refs, refs[b.id], a_impact, have_kg)
            if edge is not None:
                edges.append(edge)
    for cycle in _find_cycles(edges, [s.id for s in stories]):
        edges.append(StoryDependency(
            from_story_id=cycle[0], to_story_id=cycle[-1],
            reason=f"cycle: {' -> '.join(cycle)}", confidence="high"))
    return edges


def _edge_between(
    a: Story, b: Story, a_refs: set[str], b_refs: set[str],
    a_impact: set[str], have_kg: bool,
) -> StoryDependency | None:
    """Return a single A→B dependency edge if our heuristics fire, else None."""
    if a_impact and (hit := b_refs & a_impact):
        return StoryDependency(
            from_story_id=a.id, to_story_id=b.id,
            reason=f"kg_impact: {sorted(hit)[:3]}", confidence="high",
        )
    overlap = a_refs & b_refs
    if not overlap:
        return None
    conf = "high" if have_kg else "medium"
    if _TEST_KW.search(b.title) and not _TEST_KW.search(a.title):
        return StoryDependency(
            from_story_id=a.id, to_story_id=b.id,
            reason=f"b_tests_a: shared refs {sorted(overlap)[:3]}", confidence=conf,
        )
    if _SCHEMA_KW.search(a.title) and not _SCHEMA_KW.search(b.title):
        return StoryDependency(
            from_story_id=a.id, to_story_id=b.id,
            reason=f"b_uses_a_schema: shared refs {sorted(overlap)[:3]}", confidence=conf,
        )
    if not have_kg:
        return StoryDependency(
            from_story_id=a.id, to_story_id=b.id,
            reason=f"text_overlap: {sorted(overlap)[:3]}", confidence="low",
        )
    return None


def _extract_refs(text: str) -> set[str]:
    """Pull identifier-like tokens from free-text story title / brief."""
    if not text:
        return set()
    return {m.group(0).lower() for m in _IDENT_RE.finditer(text)}


def _kg_reachable() -> bool:
    """Conservative probe — we don't actually call the DB here."""
    if not os.environ.get("SPINE_DB_URL"):
        return False
    try:
        from shared.mcp.tools import kg as _kg  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


def _kg_impact_for(refs: set[str], project_id: str | None, repo: str | None) -> set[str]:
    """Call `impact_radius` per ref and union the resulting paths/symbols."""
    if not project_id or not repo:
        return set()
    try:
        from shared.mcp.tools.kg import ImpactRadiusInput, impact_radius
    except Exception:  # noqa: BLE001
        return set()
    out: set[str] = set()
    for ref in list(refs)[:8]:  # cap per-story KG calls
        try:
            resp = impact_radius(ImpactRadiusInput(
                project_id=project_id, target=ref, target_type="symbol",
                repo=repo, include_tests=True,
            ))
            for node in (resp.data or {}).get("impacted", []):  # type: ignore[union-attr]
                if isinstance(node, dict):
                    if (p := node.get("path")):
                        out.add(str(p).lower())
                    if (nid := node.get("node_id")):
                        out.add(str(nid).lower())
        except Exception as exc:  # noqa: BLE001
            logger.debug("kg_impact_call_failed", extra={"ref": ref, "err": str(exc)})
    return out


def _find_cycles(edges: list[StoryDependency], nodes: list[str]) -> list[list[str]]:
    """DFS-based cycle finder; returns one representative path per cycle."""
    graph: dict[str, list[str]] = {n: [] for n in nodes}
    for e in edges:
        if e.from_story_id in graph and e.to_story_id in graph:
            graph[e.from_story_id].append(e.to_story_id)
    cycles: list[list[str]] = []
    visiting: set[str] = set(); visited: set[str] = set(); stack: list[str] = []

    def dfs(u: str) -> None:
        visiting.add(u); stack.append(u)
        for v in graph[u]:
            if v in visiting:
                cycles.append(stack[stack.index(v):] + [v])
                continue
            if v not in visited:
                dfs(v)
        stack.pop(); visiting.discard(u); visited.add(u)

    for n in nodes:
        if n not in visited:
            dfs(n)
    return cycles


__all__ = ["detect_dependencies", "StoryDependency"]
