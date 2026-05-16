"""Spine Roadmap Decomposer package.

Implements STORY-1.3.1 / STORY-1.3.2 / STORY-1.3.3 from `docs/BACKLOG.md`
and PRD §FR-4 from `docs/PRD.md` (REQ-INIT-1). The `planner` role invokes
`decompose()` after the signed PRD + TRD become available and emits a
`roadmap-v1` artifact (INIT/EPIC/STORY hierarchy + sprint plan).

See `decomposer_README.md` for the algorithm + integration contract.
"""

from .decomposer import decompose
from .dependency_detection import detect_dependencies, StoryDependency
from .id_allocator import allocate_ids
from .sizing import estimate_size, SizingResult

__all__ = [
    "decompose",
    "detect_dependencies",
    "StoryDependency",
    "allocate_ids",
    "estimate_size",
    "SizingResult",
]
