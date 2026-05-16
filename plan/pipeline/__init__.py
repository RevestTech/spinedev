"""Spine SDLC pipeline customization runtime — flexibility principle in code.

Implements `EPIC-1.7` from `docs/BACKLOG.md` (stories 1.7.2/3/4/5): capability
grants, override hierarchy enforcement, manifest versioning + required-rationale
git commits, and project-lock-to-pipeline-version at project start. Backs PRD
REQ-INIT-1 FR-7 (customization authority) + FR-8 (versioning, locking, audit)
in `docs/PRD.md`. See `pipeline_README.md` for the runtime model.
"""
from __future__ import annotations

from .capability_checker import (
    CapabilityDenied,
    check_capability,
    list_grants,
    require_capability,
)
from .manifest_loader import PipelineManifest, load_pipeline
from .project_lock import (
    MigrationResult,
    get_locked_pipeline,
    is_pipeline_drifted,
    lock_project_to_pipeline,
    migrate_locked_project,
)
from .versioning import (
    CommitResult,
    PipelineEdit,
    commit_pipeline_edit,
    compute_pipeline_version,
    pipeline_history,
)

__all__ = [
    "CapabilityDenied",
    "CommitResult",
    "MigrationResult",
    "PipelineEdit",
    "PipelineManifest",
    "check_capability",
    "commit_pipeline_edit",
    "compute_pipeline_version",
    "get_locked_pipeline",
    "is_pipeline_drifted",
    "list_grants",
    "load_pipeline",
    "lock_project_to_pipeline",
    "migrate_locked_project",
    "pipeline_history",
    "require_capability",
]
