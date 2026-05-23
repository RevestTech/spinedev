"""Tests for workspace artifact builder."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from plan.artifacts._base import ArtifactMetadata
from shared.schemas.build.build_artifact import (
    BuildArtifact,
    BuildCost,
    BuildRuntime,
    CodeChange,
    KGImpactNode,
)


def test_sealed_artifact_requires_kg_impact_with_code_changes() -> None:
    now = datetime.now(timezone.utc)
    try:
        BuildArtifact(
            directive_id="d1",
            project_id="p1",
            phase="build_in_progress",
            role="engineer",
            pipeline_version="1",
            status="sealed",
            rationale="test",
            code_changes=[
                CodeChange(
                    path="a.py", change_type="create",
                    diff_hash="0" * 64, lines_added=1, lines_removed=0,
                ),
            ],
            kg_impact=[],
            cost=BuildCost(
                tokens_input=0, tokens_output=0, model="m",
                cost_usd=Decimal("0"), tier="low",
            ),
            runtime=BuildRuntime(
                started_at=now, completed_at=now, duration_seconds=0,
            ),
            metadata=ArtifactMetadata(
                created_by="test", created_at=now, last_modified=now,
            ),
        )
        raised = False
    except ValueError:
        raised = True
    assert raised


def test_sealed_artifact_ok_with_kg_impact() -> None:
    now = datetime.now(timezone.utc)
    art = BuildArtifact(
        directive_id="d1",
        project_id="p1",
        phase="build_in_progress",
        role="engineer",
        pipeline_version="1",
        status="sealed",
        rationale="test",
        code_changes=[
            CodeChange(
                path="a.py", change_type="create",
                diff_hash="0" * 64, lines_added=1, lines_removed=0,
            ),
        ],
        kg_impact=[KGImpactNode(node_id="file:a.py", node_type="File", impact_distance=0)],
        cost=BuildCost(
            tokens_input=0, tokens_output=0, model="m",
            cost_usd=Decimal("0"), tier="low",
        ),
        runtime=BuildRuntime(
            started_at=now, completed_at=now, duration_seconds=0,
        ),
        metadata=ArtifactMetadata(
            created_by="test", created_at=now, last_modified=now,
        ),
    )
    assert art.status == "sealed"
