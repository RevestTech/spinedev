"""Tests for Hub → orchestrator role dispatch bridge."""

from __future__ import annotations

from shared.api.routes._role_dispatch_bridge import (
    KIND_ROLE_DISPATCH,
    RoleDispatchSpec,
    _build_payload,
)


def test_kind_role_dispatch_covers_plan_build_chain() -> None:
    assert KIND_ROLE_DISPATCH["prd_approval"] == RoleDispatchSpec("plan", "planner", "PRODUCE_ROADMAP")
    assert KIND_ROLE_DISPATCH["sprint_plan_approval"].subsystem == "build"
    assert KIND_ROLE_DISPATCH["sprint_plan_approval"].role == "engineer"
    assert KIND_ROLE_DISPATCH["code_approval"].subsystem == "verify"
    assert KIND_ROLE_DISPATCH["local_deploy_prompt"].role == "devops_release"


def test_build_payload_plan_dispatch_router_shape() -> None:
    payload = _build_payload(
        tool="plan_dispatch",
        project_id="00000000-0000-0000-0000-000000000001",
        role="planner",
        directive="PRODUCE_ROADMAP",
        pipeline_version="1",
        actor="user@example.com",
    )
    assert payload["role"] == "planner"
    assert payload["directive"] == "PRODUCE_ROADMAP"
    assert payload["phase"] == "plan_in_progress"


def test_build_payload_passes_extra_context() -> None:
    payload = _build_payload(
        tool="build_dispatch",
        project_id="42",
        role="engineer",
        directive="REMEDIATE_FROM_REVIEW",
        pipeline_version="1",
        actor="user",
        extra={"extra_context": "fix SQL injection"},
    )
    assert payload["extra_context"] == "fix SQL injection"
