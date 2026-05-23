"""Build a minimal ``PRDv1`` from Hub project metadata + ``prd_md``."""

from __future__ import annotations

from plan.artifacts._base import (
    AcceptanceCriterion,
    ArtifactMetadata,
    ArtifactStatus,
    Goal,
    OpenQuestion,
    ProjectType,
)
from plan.artifacts.prd_v1 import Goals, PRDv1, Stakeholder

_WORK_ITEM_TO_SWARM: dict[str, str] = {
    "feature": "web_app",
    "bug": "internal_tool",
    "incident": "api_service",
    "support": "internal_tool",
    "refactor": "internal_tool",
    "infra": "data_pipeline",
    "compliance": "internal_tool",
}


def swarm_project_type(project: dict) -> str:
    """Map DB ``work_item_type`` / ``project_type`` to swarm YAML key."""
    raw = (
        project.get("project_type")
        or (project.get("metadata") or {}).get("project_type")
        or "feature"
    )
    return _WORK_ITEM_TO_SWARM.get(str(raw), "web_app")


def _coerce_project_type(value: str) -> ProjectType:
    normalized = value.replace("-", "_")
    for pt in ProjectType:
        if pt.value == normalized:
            return pt
    return ProjectType.CUSTOM


def prd_from_project(project: dict) -> PRDv1:
    """Synthesize a draft PRD object for swarm input."""
    meta = project.get("metadata") or {}
    project_uuid = str(project.get("project_uuid") or project.get("id") or "unknown")
    name = str(project.get("name") or "Untitled")
    prd_md = str(meta.get("prd_md") or "").strip()
    description = str(meta.get("description") or "").strip()

    problem = description or prd_md[:800] or f"Deliver {name} per approved product brief."
    if len(problem) < 20 and prd_md:
        problem = prd_md.split("\n", 1)[0][:800] or problem

    pt = _coerce_project_type(swarm_project_type(project))
    return PRDv1(
        project_id=project_uuid,
        project_name=name,
        project_type=pt,
        problem_statement=problem,
        users_stakeholders=[
            Stakeholder(name="Primary user", needs=f"Use {name} to solve the stated problem."),
        ],
        goals=Goals(must=[
            Goal(id="G-1", statement=f"Ship MVP for {name} matching approved PRD scope."),
        ]),
        in_scope=["MVP features described in the approved PRD markdown."],
        out_of_scope=["Non-MVP enhancements deferred to post-v1."],
        acceptance_criteria=[
            AcceptanceCriterion(
                id="AC-1",
                given="The MVP is deployed",
                when="A primary user completes the core workflow",
                then="The PRD desired outcome is demonstrably met",
            ),
        ],
        open_questions=[
            OpenQuestion(
                id="OQ-1",
                question="Any unresolved scope from PRD markdown?",
                recommendation="Default to MVP cut in TRD build sequence.",
            ),
        ],
        metadata=ArtifactMetadata(status=ArtifactStatus.DRAFT, created_by="architect_swarm"),
    )


__all__ = ["prd_from_project", "swarm_project_type"]
