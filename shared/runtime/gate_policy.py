"""Founder pipeline mode and gate auto-ack policy.

Per-project ``metadata.pipeline_mode`` selects gate-checked (human acks)
vs autonomous (Hub PipelineRunner auto-acks per ``gate_policy``).
"""

from __future__ import annotations

from typing import Any, Literal

PipelineMode = Literal["gate_checked", "autonomous"]
GatePolicyPreset = Literal["gate_checked", "strict", "full_auto"]

# Card kinds the SDLC loop may surface. Hold list overrides auto.
_ALL_ACK_KINDS: frozenset[str] = frozenset({
    "intake_briefing",
    "prd_approval",
    "roadmap_approval",
    "trd_approval",
    "sprint_plan_approval",
    "code_approval",
    "code_review_pass",
    "code_review_blocked",
    "security_review_blocked",
    "devops_approval",
    "qa_approval",
    "qa_execution",
    "auditor_approval",
    "release_gate_approval",
    "local_deploy_prompt",
    "host_deploy_prompt",
    "host_deploy_instructions",
    "deploy_status",
    "operate_kickoff",
    "project_complete",
})

_NEVER_AUTO: frozenset[str] = frozenset({
    "orchestrator_gap",
    "role_failure",
    "master_daily_briefing",
})

_PRESETS: dict[str, dict[str, list[str]]] = {
    "gate_checked": {
        "auto": [],
        "hold": sorted(_ALL_ACK_KINDS),
    },
    "strict": {
        "auto": [
            "intake_briefing",
            "prd_approval",
            "roadmap_approval",
            "trd_approval",
            "sprint_plan_approval",
            "code_approval",
            "code_review_pass",
            "code_review_blocked",
            "security_review_blocked",
            "devops_approval",
            "qa_approval",
            "qa_execution",
            "auditor_approval",
            "local_deploy_prompt",
            "host_deploy_prompt",
            "host_deploy_instructions",
            "deploy_status",
            "operate_kickoff",
        ],
        "hold": [
            "release_gate_approval",
        ],
    },
    "full_auto": {
        "auto": sorted(_ALL_ACK_KINDS),
        "hold": [],
    },
}


class GatePolicy:
    """Resolved auto/hold lists for one project."""

    __slots__ = ("auto", "hold", "preset")

    def __init__(
        self,
        *,
        auto: frozenset[str],
        hold: frozenset[str],
        preset: str,
    ) -> None:
        self.auto = auto
        self.hold = hold
        self.preset = preset

    def can_auto_ack(self, kind: str) -> bool:
        if kind in _NEVER_AUTO:
            return False
        if kind in self.hold:
            return False
        if kind in self.auto:
            return True
        # Role runners enqueue ``{role}_approval`` cards (planner_approval, etc.)
        # while dispatch kinds stay canonical (prd_approval, roadmap_approval, …).
        if self.preset != "gate_checked" and kind.endswith("_approval"):
            return True
        return False


def resolve_pipeline_mode(metadata: dict[str, Any] | None) -> PipelineMode:
    raw = (metadata or {}).get("pipeline_mode", "gate_checked")
    if raw == "autonomous":
        return "autonomous"
    return "gate_checked"


def resolve_gate_policy(metadata: dict[str, Any] | None) -> GatePolicy:
    """Merge explicit metadata.gate_policy with a named preset."""
    md = metadata or {}
    preset = str(md.get("gate_policy_preset") or "strict").strip().lower()
    if preset not in _PRESETS:
        preset = "strict"

    base = _PRESETS[preset]
    explicit = md.get("gate_policy")
    auto_list: list[str] = list(base["auto"])
    hold_list: list[str] = list(base["hold"])
    if isinstance(explicit, dict):
        if isinstance(explicit.get("auto"), list):
            auto_list = [str(k) for k in explicit["auto"]]
        if isinstance(explicit.get("hold"), list):
            hold_list = [str(k) for k in explicit["hold"]]

    return GatePolicy(
        auto=frozenset(auto_list),
        hold=frozenset(hold_list),
        preset=preset,
    )


def can_auto_ack(
    kind: str,
    *,
    mode: PipelineMode,
    policy: GatePolicy,
) -> bool:
    if mode != "autonomous":
        return False
    return policy.can_auto_ack(kind)


def metadata_patch_for_create(
    *,
    pipeline_mode: PipelineMode | None,
    gate_policy_preset: GatePolicyPreset | None,
) -> dict[str, Any]:
    patch: dict[str, Any] = {}
    if pipeline_mode:
        patch["pipeline_mode"] = pipeline_mode
    if gate_policy_preset:
        patch["gate_policy_preset"] = gate_policy_preset
    elif pipeline_mode == "autonomous":
        patch["gate_policy_preset"] = "strict"
    return patch


__all__ = [
    "GatePolicy",
    "GatePolicyPreset",
    "PipelineMode",
    "can_auto_ack",
    "metadata_patch_for_create",
    "resolve_gate_policy",
    "resolve_pipeline_mode",
]
