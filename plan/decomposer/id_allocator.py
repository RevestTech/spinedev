"""Stable INIT/EPIC/STORY id allocation for the decomposer.

Implements the id-stability requirement of STORY-1.3.1: two `decompose()`
runs over the same PRD + TRD must produce the same id set. We canonicalise
each candidate's content into a stable hash key and allocate slot numbers
from a deterministic ordering. When an `existing_roadmap` is supplied we
preserve known ids and only mint new ones for new candidates; orphaned
ids are returned in `retired_ids` so the caller can WontDo them.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Mapping, Sequence

from plan.artifacts.roadmap_v1 import RoadmapV1


@dataclass
class Allocation:
    """`assigned`: hash → spine id. `retired_ids`: ids no longer claimed."""

    assigned: dict[str, str] = field(default_factory=dict)
    retired_ids: list[str] = field(default_factory=list)


def canonical_hash(*parts: str) -> str:
    """Stable sha256 over content parts (case-insensitive, trimmed)."""
    joined = "\x1f".join((p or "").strip().lower() for p in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def _existing_index(existing: RoadmapV1 | None) -> dict[str, str]:
    """Re-derive `hash -> id` from an existing roadmap so we preserve ids."""
    if existing is None:
        return {}
    out: dict[str, str] = {}
    for init in existing.initiatives:
        out[canonical_hash("init", init.title, init.why)] = init.id
        for epic in init.epics:
            out[canonical_hash("epic", init.id, epic.title, epic.description)] = epic.id
            for story in epic.stories:
                out[canonical_hash("story", epic.id, story.title)] = story.id
    return out


def _max_index(prior: dict[str, str], prefix: str) -> int:
    """Largest existing slot index for a given id prefix (0 if none)."""
    out = 0
    for sid in prior.values():
        if not sid.startswith(prefix):
            continue
        try:
            out = max(out, int(sid[len(prefix):].split(".")[0]))
        except ValueError:
            continue
    return out


def allocate_ids(
    initiatives: Sequence[Mapping[str, object]],
    existing_roadmap: RoadmapV1 | None = None,
) -> Allocation:
    """Mint stable INIT-{N}/EPIC-{N}.{M}/STORY-{N}.{M}.{K} ids."""
    prior = _existing_index(existing_roadmap)
    seen: set[str] = set()
    assigned: dict[str, str] = {}
    next_init = _max_index(prior, "INIT-") + 1
    for init in initiatives:
        ih = canonical_hash("init", str(init.get("title", "")), str(init.get("why", "")))
        seen.add(ih)
        init_id = prior.get(ih) or f"INIT-{next_init}"
        if ih not in prior:
            next_init += 1
        assigned[ih] = init_id
        n = init_id.split("-")[1]
        next_epic = _max_index(prior, f"EPIC-{n}.") + 1
        for epic in init.get("epics", []) or []:  # type: ignore[arg-type]
            eh = canonical_hash("epic", init_id,
                                str(epic.get("title", "")), str(epic.get("description", "")))
            seen.add(eh)
            epic_id = prior.get(eh) or f"EPIC-{n}.{next_epic}"
            if eh not in prior:
                next_epic += 1
            assigned[eh] = epic_id
            n2, m = epic_id.split("-")[1].split(".")
            next_story = _max_index(prior, f"STORY-{n2}.{m}.") + 1
            for story in epic.get("stories", []) or []:  # type: ignore[arg-type]
                sh = canonical_hash("story", epic_id, str(story.get("title", "")))
                seen.add(sh)
                sid = prior.get(sh) or f"STORY-{n2}.{m}.{next_story}"
                if sh not in prior:
                    next_story += 1
                assigned[sh] = sid
    retired = [sid for h, sid in prior.items() if h not in seen]
    return Allocation(assigned=assigned, retired_ids=retired)


__all__ = ["allocate_ids", "canonical_hash", "Allocation"]
