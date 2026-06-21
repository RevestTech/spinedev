"""Unit tests for PipelineRunner policy gating (no live DB)."""

from __future__ import annotations

from shared.runtime.gate_policy import resolve_gate_policy, resolve_pipeline_mode
from shared.runtime.pipeline_runner import _card_belongs, pipeline_runner_enabled


class _FakeCard:
    def __init__(
        self,
        *,
        decision_id: str,
        project_id: str | None = None,
        kind: str = "prd_approval",
        title: str = "test",
    ) -> None:
        self.decision_id = decision_id
        self.project_id = project_id
        self.title = title
        self.metadata = {"kind": kind}
        if project_id:
            self.metadata["project_uuid"] = project_id


def test_card_belongs_by_project_id() -> None:
    card = _FakeCard(decision_id="d1", project_id="uuid-1")
    assert _card_belongs(card, "uuid-1")
    assert not _card_belongs(card, "uuid-2")


def test_strict_policy_blocks_release_for_autonomous() -> None:
    md = {"pipeline_mode": "autonomous", "gate_policy_preset": "strict"}
    mode = resolve_pipeline_mode(md)
    policy = resolve_gate_policy(md)
    assert mode == "autonomous"
    assert policy.can_auto_ack("sprint_plan_approval")
    assert not policy.can_auto_ack("release_gate_approval")


def test_pipeline_runner_enabled_default_on() -> None:
    assert pipeline_runner_enabled() is True
