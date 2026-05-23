"""Build a sealed ``BuildArtifact`` from a Hub project workspace."""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

from plan.artifacts._base import ArtifactMetadata
from shared.schemas.build.build_artifact import (
    BuildArtifact,
    BuildCost,
    BuildRuntime,
    CodeChange,
    KGImpactNode,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SKIP_DIRS = {".next", "node_modules", ".git", ".claude", "__pycache__"}


def _workspace_root() -> Path:
    if raw := os.environ.get("SPINE_PROJECTS_ROOT"):
        return Path(raw).expanduser()
    hub_mount = Path("/var/lib/spine/projects")
    if hub_mount.is_dir():
        return hub_mount
    return _REPO_ROOT / ".spine" / "work"


def _guess_language(path: str) -> str | None:
    ext = Path(path).suffix.lower()
    return {
        ".py": "python", ".ts": "typescript", ".tsx": "typescript",
        ".js": "javascript", ".jsx": "javascript", ".go": "go",
        ".rs": "rust", ".java": "java", ".sql": "sql",
    }.get(ext)


def build_sealed_artifact_from_workspace(
    *,
    project_id: str,
    project_uuid: str,
    phase: str,
    pipeline_version: str,
    directive_id: str | None = None,
    actor: str = "engineer",
    metadata: dict[str, Any] | None = None,
) -> BuildArtifact:
    """Scan workspace files and emit a sealed artifact for ``verify_audit``."""
    from shared.runtime.project_workspace import resolve_code_dir  # noqa: PLC0415

    root = resolve_code_dir(project_uuid, metadata).resolve()
    now = datetime.now(timezone.utc)
    did = directive_id or f"dir_{uuid4().hex[:12]}"
    changes: list[CodeChange] = []
    kg_nodes: list[KGImpactNode] = []

    if root.is_dir():
        for f in sorted(root.rglob("*")):
            if not f.is_file():
                continue
            rel = str(f.relative_to(root))
            if any(part in _SKIP_DIRS for part in Path(rel).parts):
                continue
            try:
                content = f.read_bytes()
            except OSError:
                continue
            diff_hash = hashlib.sha256(content).hexdigest()
            lines = content.count(b"\n") + (1 if content else 0)
            changes.append(CodeChange(
                path=rel,
                change_type="create",
                diff_hash=diff_hash,
                lines_added=lines,
                lines_removed=0,
                language=_guess_language(rel),
            ))
            kg_nodes.append(KGImpactNode(
                node_id=f"file:{rel}",
                node_type="File",
                impact_distance=0,
            ))

    return BuildArtifact(
        directive_id=did,
        project_id=project_id,
        phase=phase,
        role="engineer",
        pipeline_version=pipeline_version,
        code_changes=changes,
        kg_impact=kg_nodes,
        cost=BuildCost(
            tokens_input=0,
            tokens_output=0,
            model=os.environ.get("SPINE_INTAKE_MODEL", "claude-sonnet-4-6"),
            cost_usd=Decimal("0"),
            tier="medium",
        ),
        runtime=BuildRuntime(
            started_at=now,
            completed_at=now,
            duration_seconds=0,
            worker_id=actor,
        ),
        rationale=f"Hub workspace snapshot ({len(changes)} files) for verify",
        status="sealed",
        metadata=ArtifactMetadata(created_by=actor, created_at=now, last_modified=now),
    )


def persist_build_artifact(project_id: str, artifact: BuildArtifact) -> None:
    from build.runtime.build_dispatcher import _load_project, _merge_metadata  # noqa: PLC0415

    row = _load_project(project_id)
    _merge_metadata(int(row["id"]), {"build_artifact": artifact.model_dump(mode="json")})


__all__ = ["build_sealed_artifact_from_workspace", "persist_build_artifact"]
