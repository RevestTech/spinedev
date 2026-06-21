"""Tests for founder gate policy presets."""

from __future__ import annotations

from shared.runtime.gate_policy import (
    can_auto_ack,
    metadata_patch_for_create,
    resolve_gate_policy,
    resolve_pipeline_mode,
)


def test_default_mode_is_gate_checked() -> None:
    assert resolve_pipeline_mode({}) == "gate_checked"
    assert resolve_pipeline_mode({"pipeline_mode": "autonomous"}) == "autonomous"


def test_strict_preset_holds_release_gate() -> None:
    policy = resolve_gate_policy({"gate_policy_preset": "strict"})
    assert policy.can_auto_ack("prd_approval")
    assert policy.can_auto_ack("planner_approval")
    assert not policy.can_auto_ack("release_gate_approval")
    assert not policy.can_auto_ack("role_failure")


def test_full_auto_acks_release() -> None:
    policy = resolve_gate_policy({"gate_policy_preset": "full_auto"})
    assert policy.can_auto_ack("release_gate_approval")
    assert policy.can_auto_ack("deploy_status")


def test_gate_checked_never_auto_acks() -> None:
    policy = resolve_gate_policy({"gate_policy_preset": "gate_checked"})
    assert not can_auto_ack(
        "prd_approval",
        mode="gate_checked",
        policy=policy,
    )
    assert not can_auto_ack(
        "prd_approval",
        mode="autonomous",
        policy=policy,
    )


def test_autonomous_respects_explicit_hold_override() -> None:
    policy = resolve_gate_policy({
        "gate_policy_preset": "full_auto",
        "gate_policy": {"hold": ["prd_approval"]},
    })
    assert not policy.can_auto_ack("prd_approval")
    assert can_auto_ack("roadmap_approval", mode="autonomous", policy=policy)


def test_create_patch_defaults_strict_for_autonomous() -> None:
    patch = metadata_patch_for_create(
        pipeline_mode="autonomous",
        gate_policy_preset=None,
    )
    assert patch == {
        "pipeline_mode": "autonomous",
        "gate_policy_preset": "strict",
    }
