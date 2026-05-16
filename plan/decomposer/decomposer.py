"""Spine Roadmap Decomposer — PRD + TRD → roadmap-v1.

Implements STORY-1.3.1 from `docs/BACKLOG.md` and PRD §FR-4 from
`docs/PRD.md` (REQ-INIT-1). The `planner` role invokes `decompose()`
once both the PRD and the TRD have been signed. Output is a validated
`RoadmapV1` artifact (INIT → EPIC → STORY hierarchy with stable ids,
sized stories, declared inter-story dependencies, and a sprint plan).

Algorithm: (1) initiative shape from PRD goals (MUST→P0, SHOULD→P1,
COULD→P2); (2) epic candidates from TRD components/integrations/NFRs;
(3) story candidates per epic (single-PR scale); (4) stable id
allocation; (5) sizing; (6) dependency detection via KG impact_radius;
(7) topological sprint sequencing (≤8 stories × ≤3 sprints); (8) Pydantic
validation through `RoadmapV1`.

Incremental mode: when `existing_roadmap` is supplied, ids of unchanged
content are preserved; orphaned ids are surfaced via `metadata.created_by`
so the caller can drive a WontDo transition.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Iterable

from plan.artifacts._base import ArtifactMetadata, ArtifactStatus, Priority, Status
from plan.artifacts.prd_v1 import Goals, PRDv1
from plan.artifacts.roadmap_v1 import Epic, Initiative, RoadmapV1, Sprint, Story
from plan.artifacts.trd_v1 import (
    Component, Integration, NonFunctionalRequirements, TRDv1,
)

from .dependency_detection import StoryDependency, detect_dependencies
from .id_allocator import Allocation, allocate_ids, canonical_hash
from .sizing import estimate_size

logger = logging.getLogger(__name__)

_MAX_STORIES_PER_SPRINT = 8; _DEFAULT_SPRINT_COUNT = 3
_TIER_BY_PRIORITY = {Priority.P0: 1, Priority.P1: 2, Priority.P2: 3, Priority.P3: 4}


def decompose(
    prd: PRDv1, trd: TRDv1,
    existing_roadmap: RoadmapV1 | None = None,
    project_repo: str | None = None,
) -> RoadmapV1:
    """Produce a `roadmap-v1` artifact from the signed PRD + TRD."""
    if prd.project_id != trd.project_id:
        raise ValueError(
            f"PRD/TRD project_id mismatch: {prd.project_id} vs {trd.project_id}")
    shape = _initiatives_from_prd(prd, trd)
    alloc = allocate_ids(shape, existing_roadmap=existing_roadmap)
    initiatives = _materialise(shape, alloc, trd)
    stories = [s for i in initiatives for e in i.epics for s in e.stories]
    deps = detect_dependencies(stories, kg_available=True,
                               project_id=prd.project_id, repo=project_repo)
    _apply_dependencies(stories, deps)
    sprints = _sequence_sprints(stories, deps)
    created_by = "planner"
    if alloc.retired_ids:
        created_by = f"planner (retired={','.join(alloc.retired_ids)})"
    return RoadmapV1(
        project_id=prd.project_id, prd_ref=f"prd-v1:{prd.project_id}",
        trd_ref=f"trd-v1:{trd.project_id}", initiatives=initiatives,
        epics=[e for i in initiatives for e in i.epics],
        stories=stories, sprint_plan=sprints,
        metadata=ArtifactMetadata(created_by=created_by, status=ArtifactStatus.DRAFT))


# -- Step 1: initiative shape from PRD goals --------------------------------


def _initiatives_from_prd(prd: PRDv1, trd: TRDv1) -> list[dict]:
    """Cluster PRD goals into INIT candidates; populate with TRD epics."""
    g: Goals = prd.goals
    tiers: list[tuple[str, list, Priority]] = [
        ("MUST", g.must, Priority.P0), ("SHOULD", g.should, Priority.P1),
        ("COULD", g.could, Priority.P2),
    ]
    shape: list[dict] = []
    pool = _epic_candidates_from_trd(trd)
    cursor = 0
    nonempty = max(1, sum(1 for _, gs, _ in tiers if gs))
    for label, goals, prio in tiers:
        if not goals:
            continue
        clusters = _cluster_goals(goals, max_per_cluster=4)
        for cidx, cluster in enumerate(clusters, start=1):
            take = max(1, len(pool) // max(1, len(clusters) * nonempty))
            shape.append({
                "title": _initiative_title(label, cluster, cidx, len(clusters)),
                "why": _initiative_why(prd, cluster),
                "tier": _TIER_BY_PRIORITY[prio], "priority": prio,
                "epics": pool[cursor : cursor + take] or [],
            })
            cursor += take
    if (leftover := pool[cursor:]) and shape:
        shape[0]["epics"].extend(leftover)
    if not shape:
        shape.append({
            "title": f"{prd.project_name} delivery",
            "why": prd.problem_statement or "Initial decomposition.",
            "tier": 1, "priority": Priority.P0,
            "epics": pool or [_default_epic()]})
    return shape


def _cluster_goals(goals: list, max_per_cluster: int) -> list[list]:
    """Naive equal-chunk clustering. Future: NLP cluster by topic."""
    if len(goals) <= max_per_cluster:
        return [goals]
    return [goals[i : i + max_per_cluster] for i in range(0, len(goals), max_per_cluster)]


def _initiative_title(label: str, cluster: list, cidx: int, ctotal: int) -> str:
    head = (cluster[0].statement.split(".")[0][:60] or "initiative").strip()
    suffix = f" ({cidx}/{ctotal})" if ctotal > 1 else ""
    return f"[{label}] {head}{suffix}"


def _initiative_why(prd: PRDv1, cluster: list) -> str:
    return f"{prd.problem_statement} — covers: " + "; ".join(
        g.statement for g in cluster[:3]
    )


# -- Step 2: epic candidates from TRD --------------------------------------


def _epic_candidates_from_trd(trd: TRDv1) -> list[dict]:
    """One epic candidate per TRD architecture / integration / NFR concern."""
    out: list[dict] = [_epic_from_component(c) for c in trd.architecture.components]
    out += [_epic_from_integration(i) for i in trd.integrations]
    out += _epics_from_nfrs(trd.nfrs)
    return out or [_default_epic()]


def _epic_from_component(c: Component) -> dict:
    tech = f" ({c.technology})" if c.technology else ""
    stories = [
        {"title": f"Scaffold {c.name} module + interfaces"},
        {"title": f"Implement {c.name} core: {c.responsibility[:60].strip()}"},
        {"title": f"Add {c.name} unit + integration tests"}]
    if c.technology:
        stories.append({"title": f"Wire {c.name} to {c.technology}"})
    return {"title": f"Build {c.name}{tech}", "description": c.responsibility,
            "stories": stories, "_kind": "component"}


def _epic_from_integration(i: Integration) -> dict:
    return {"title": f"Integrate {i.name} ({i.direction.value})",
            "description": f"{i.protocol} integration, auth={i.auth}",
            "stories": [
                {"title": f"Wire {i.name} {i.direction.value} client + auth ({i.auth})"},
                {"title": f"Add {i.name} integration tests + retries"}],
            "_kind": "integration"}


def _epics_from_nfrs(nfrs: NonFunctionalRequirements) -> list[dict]:
    """One epic per non-empty NFR concern."""
    out: list[dict] = []
    for concern in ("performance", "security", "scalability", "observability", "cost"):
        val = (getattr(nfrs, concern, "") or "").strip()
        if not val:
            continue
        out.append({"title": f"NFR: {concern}", "description": val,
                    "stories": [
                        {"title": f"Implement {concern} controls — {val[:60]}"},
                        {"title": f"Add {concern} test/coverage and dashboards"}],
                    "_kind": "nfr"})
    return out


def _default_epic() -> dict:
    return {"title": "Initial scaffolding",
            "description": "Bootstrap repo, CI, and skeleton modules.",
            "stories": [{"title": "Bootstrap repository + CI pipeline"}],
            "_kind": "default"}


# -- Steps 4-5: materialise with stable ids + sizing -----------------------


def _materialise(shape: list[dict], alloc: Allocation, trd: TRDv1) -> list[Initiative]:
    out: list[Initiative] = []
    for init in shape:
        init_id = alloc.assigned[canonical_hash("init", init["title"], init["why"])]
        epics: list[Epic] = []
        for epic in init["epics"]:
            epic_id = alloc.assigned[canonical_hash(
                "epic", init_id, epic["title"], epic["description"])]
            stories: list[Story] = []
            for story in epic.get("stories", []):
                s_id = alloc.assigned[canonical_hash("story", epic_id, story["title"])]
                sz = estimate_size(story_text=story["title"],
                                   trd_section=_trd_slice_for(epic, trd), kg_impact=None)
                stories.append(Story(
                    id=s_id, title=story["title"], status=Status.BACKLOG,
                    priority=init["priority"], size=sz.size,
                    estimate_cost=sz.estimated_cost_usd,
                    estimate_duration=sz.estimated_duration_label, dependencies=[]))
            epics.append(Epic(id=epic_id, title=epic["title"],
                              description=epic["description"], stories=stories))
        out.append(Initiative(id=init_id, title=init["title"], tier=init["tier"],
                              priority=init["priority"], why=init["why"], epics=epics))
    return out


def _trd_slice_for(epic: dict, trd: TRDv1) -> dict:
    """Return the TRD sub-dict the sizing heuristic scans for keywords."""
    kind = epic.get("_kind")
    if kind == "component":
        return {"components": [c.model_dump() for c in trd.architecture.components]}
    if kind == "integration":
        return {"integrations": [i.model_dump() for i in trd.integrations]}
    if kind == "nfr":
        return {"nfrs": trd.nfrs.model_dump()}
    return {"architecture": trd.architecture.model_dump()}


# -- Steps 6-7: dependencies + sprint sequencing ---------------------------


def _apply_dependencies(stories: list[Story], edges: Iterable[StoryDependency]) -> None:
    """Mutate `Story.dependencies` in place from detected edges (skip cycles)."""
    by_id = {s.id: s for s in stories}
    for e in edges:
        if e.reason.startswith("cycle:"):
            logger.warning("decomposer_cycle_detected", extra={"reason": e.reason})
            continue
        tgt = by_id.get(e.to_story_id)
        if tgt is None or e.from_story_id not in by_id:
            continue
        if e.from_story_id not in tgt.dependencies:
            tgt.dependencies.append(e.from_story_id)


def _sequence_sprints(stories: list[Story], edges: list[StoryDependency]) -> list[Sprint]:
    """Topological sort → bucket into ≤3 sprints of ≤8 stories each."""
    in_deg: dict[str, int] = {s.id: 0 for s in stories}
    adj: dict[str, list[str]] = defaultdict(list)
    for e in edges:
        if e.reason.startswith("cycle:"):
            continue
        if e.from_story_id in in_deg and e.to_story_id in in_deg:
            in_deg[e.to_story_id] += 1
            adj[e.from_story_id].append(e.to_story_id)
    ready: list[str] = sorted(sid for sid, d in in_deg.items() if d == 0)
    ordered: list[str] = []
    while ready:
        nxt = ready.pop(0)
        ordered.append(nxt)
        for v in sorted(adj[nxt]):
            in_deg[v] -= 1
            if in_deg[v] == 0:
                ready.append(v)
                ready.sort()
    for s in stories:  # cycle survivors land at the end — lose no work
        if s.id not in ordered:
            ordered.append(s.id)
    sprints: list[Sprint] = []
    for i in range(_DEFAULT_SPRINT_COUNT):
        chunk = ordered[i * _MAX_STORIES_PER_SPRINT : (i + 1) * _MAX_STORIES_PER_SPRINT]
        if not chunk:
            break
        sprints.append(Sprint(
            number=i + 1, name=f"Sprint {i + 1}",
            goal=f"Deliver {len(chunk)} stories (slice {i + 1}/{_DEFAULT_SPRINT_COUNT}).",
            stories=chunk))
    if (tail := ordered[_DEFAULT_SPRINT_COUNT * _MAX_STORIES_PER_SPRINT :]):
        sprints.append(Sprint(
            number=len(sprints) + 1, name="Backlog overflow",
            goal=f"Stories beyond default {_DEFAULT_SPRINT_COUNT}-sprint horizon.",
            stories=tail))
    return sprints


__all__ = ["decompose"]
