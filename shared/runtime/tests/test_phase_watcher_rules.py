"""Tests for the V3 slate #4 phase watcher rules.

The actual phase_watcher_tick reaches into the live DB pool; here we
only assert the rule table itself carries the three new transitions
in the right shape so the loop reaches operate. Integration coverage
lives in the existing smoke phase 6.
"""
from __future__ import annotations

from shared.runtime.phase_watcher import _WATCH_RULES


def test_watcher_rules_carry_post_verify_transitions() -> None:
    kinds = {kind for _phase, _pred, kind in _WATCH_RULES}
    expected = {"auditor_approval", "release_approval", "operate_kickoff"}
    assert expected.issubset(kinds), (
        "post-verify watcher rules missing; loop dead-ends at QA"
    )


def test_auditor_rule_fires_on_verify_approved_with_qa_md() -> None:
    rule = _find_rule_by_kind("auditor_approval")
    assert rule is not None
    phase, predicate, _ = rule
    assert phase == "verify_approved"
    assert "qa_md" in predicate
    assert "audit_md" in predicate


def test_release_rule_fires_on_acceptance_with_audit_md() -> None:
    rule = _find_rule_by_kind("release_approval")
    assert rule is not None
    phase, predicate, _ = rule
    assert phase == "acceptance"
    assert "audit_md" in predicate
    assert "release_gate_md" in predicate


def test_operate_rule_fires_on_released_with_deploy_result() -> None:
    rule = _find_rule_by_kind("operate_kickoff")
    assert rule is not None
    phase, predicate, _ = rule
    assert phase == "released"
    assert "deploy_result" in predicate
    assert "operate_started_at" in predicate


def test_operate_feature_request_rule() -> None:
    rule = _find_rule_by_kind("feature_request")
    assert rule is not None
    phase, predicate, _ = rule
    assert phase == "operate"
    assert "feature_requests" in predicate
    assert "requested" in predicate
    assert "feature_iteration_active" in predicate


def test_operate_code_approval_rule_after_feature_start() -> None:
    rule = _find_rule_by_kind("code_approval")
    operate_rules = [r for r in _WATCH_RULES if r[0] == "operate" and r[2] == "code_approval"]
    assert len(operate_rules) == 1
    phase, predicate, kind = operate_rules[0]
    assert phase == "operate"
    assert kind == "code_approval"
    assert "code_intro_md" in predicate
    assert "feature_iteration_active" in predicate


def test_each_rule_predicate_is_a_safe_jsonb_check() -> None:
    # All four post-verify rules must use the `metadata ? 'KEY'` pattern;
    # this catches accidental string interpolation that would open SQL
    # injection in _find_pending_work.
    for phase, predicate, kind in _WATCH_RULES:
        if kind not in {
            "auditor_approval", "release_approval", "operate_kickoff",
        }:
            continue
        assert "metadata ?" in predicate
        assert ";" not in predicate
        assert "--" not in predicate


def _find_rule_by_kind(kind: str):
    for r in _WATCH_RULES:
        if r[2] == kind:
            return r
    return None
