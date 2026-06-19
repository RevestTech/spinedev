"""Golden path E2E contract tests — approval chain + phase watcher alignment."""

from __future__ import annotations

from shared.api.routes._role_dispatch_bridge import KIND_ROLE_DISPATCH
from shared.runtime.phase_watcher import _WATCH_RULES


# User-facing approval kinds in golden path order (post-intake).
GOLDEN_PATH_APPROVAL_KINDS: tuple[str, ...] = (
    "prd_approval",
    "roadmap_approval",
    "trd_approval",
    "sprint_plan_approval",
    "code_approval",
    "code_review_pass",
    "devops_approval",
    "qa_approval",
    "local_deploy_prompt",
)


def test_golden_path_kinds_have_orchestrator_bridge() -> None:
    """Every post-intake approval step routes through the orchestrator bridge."""
    missing = [k for k in GOLDEN_PATH_APPROVAL_KINDS if k not in KIND_ROLE_DISPATCH]
    assert missing == [], f"missing bridge mappings: {missing}"


def test_golden_path_role_sequence() -> None:
    """Roles fire in SDLC order through the bridge."""
    roles = [KIND_ROLE_DISPATCH[k].role for k in GOLDEN_PATH_APPROVAL_KINDS]
    assert roles == [
        "planner",
        "architect",
        "conductor",
        "engineer",
        "auditor",
        "devops",
        "qa",
        "release_manager",
        "devops_release",
    ]


def test_phase_watcher_covers_plan_and_build_gates() -> None:
    """Watcher rules align with metadata gates before user ack cards."""
    kinds = {rule[2] for rule in _WATCH_RULES}
    assert "prd_approval" in kinds
    assert "sprint_plan_approval" in kinds
    assert "code_approval" in kinds


def test_phase_watcher_kinds_have_orchestrator_bridge() -> None:
    """Every phase_watcher dispatch_kind routes through KIND_ROLE_DISPATCH."""
    watcher_kinds = {rule[2] for rule in _WATCH_RULES}
    missing = sorted(k for k in watcher_kinds if k not in KIND_ROLE_DISPATCH)
    assert missing == [], f"missing bridge mappings: {missing}"


def test_post_verify_watcher_kinds_map_to_expected_roles() -> None:
    assert KIND_ROLE_DISPATCH["auditor_approval"].role == "auditor"
    assert KIND_ROLE_DISPATCH["release_approval"].role == "release_manager"
    assert KIND_ROLE_DISPATCH["operate_kickoff"].role == "devops"


def test_code_review_remediate_path_exists() -> None:
    assert KIND_ROLE_DISPATCH["code_review_blocked"].role == "engineer"
    assert "REMEDIATE" in KIND_ROLE_DISPATCH["code_review_blocked"].directive
