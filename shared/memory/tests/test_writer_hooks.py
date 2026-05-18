"""Writer-hook contract tests — Wave 1 substrate wiring (V3 #27).

Verifies:
  * All 7 canonical event keys are registered with default extractors.
  * Dispatch on each event-key shape produces exactly one LessonDraft.
  * Non-trigger audit rows produce no drafts (no false fires).
  * Extractor exceptions are isolated; dispatch never raises.
  * flush_pending() drains drafts to the injected writer.
  * Custom hooks can register and fire alongside defaults.

No real DB / no real audit row writes — pure unit tests with a fake
writer + in-memory queue.
"""
from __future__ import annotations

import unittest
from typing import Any

from shared.memory import writer_hooks
from shared.memory.writer_hooks import (
    EVENT_KEYS, LessonDraft, clear_hooks, dispatch, flush_pending,
    pending_drafts, register_hook,
)


def _verify_pass_record(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "event_uuid": "00000000-0000-0000-0000-000000000001",
        "project_id": 42,
        "role": "verify",
        "subsystem": "verify",
        "action": "verify_audit",
        "actor": "verify",
        "metadata": {
            "pass_fail": "pass",
            "artifact_uuid": "abcdef1234567890",
            "calibration_band": "high_precision",
            "critical_count": 0,
            "high_count": 0,
        },
    }
    base.update(overrides)
    return base


def _verify_fail_record() -> dict[str, Any]:
    return {
        "event_uuid": "00000000-0000-0000-0000-000000000002",
        "project_id": 42,
        "role": "verify",
        "subsystem": "verify",
        "action": "verify_audit",
        "actor": "verify",
        "metadata": {
            "pass_fail": "fail",
            "artifact_uuid": "deadbeefcafef00d",
            "reason_class": "security_finding",
            "critical_count": 2,
            "high_count": 1,
        },
    }


def _approval_granted_record() -> dict[str, Any]:
    return {
        "event_uuid": "00000000-0000-0000-0000-000000000003",
        "project_id": 7,
        "role": "approver",
        "subsystem": "orchestrator",
        "action": "approval_granted",
        "actor": "khash",
        "subject_id": "approval-uuid-xyz",
        "rationale": "Risk acceptable; rollback plan documented.",
        "metadata": {},
    }


def _approval_rejected_record() -> dict[str, Any]:
    return {
        "event_uuid": "00000000-0000-0000-0000-000000000004",
        "project_id": 7,
        "role": "approver",
        "subsystem": "orchestrator",
        "action": "approval_rejected",
        "actor": "khash",
        "subject_id": "approval-uuid-abc",
        "rationale": "Cost estimate exceeds threshold.",
        "metadata": {},
    }


def _phase_advanced_record() -> dict[str, Any]:
    return {
        "event_uuid": "00000000-0000-0000-0000-000000000005",
        "project_id": 11,
        "role": "orchestrator",
        "subsystem": "orchestrator",
        "action": "phase_advanced",
        "actor": "orchestrator",
        "metadata": {
            "from_phase": "plan",
            "to_phase": "build",
            "status": "success",
            "metrics": {"duration_ms": 1500, "cost_usd": "0.05"},
        },
    }


def _build_completed_record() -> dict[str, Any]:
    return {
        "event_uuid": "00000000-0000-0000-0000-000000000006",
        "project_id": 11,
        "role": "engineer",
        "subsystem": "build",
        "action": "build_completed",
        "actor": "engineer",
        "subject_id": "artifact-uuid-123",
        "metadata": {
            "artifact_uuid": "artifact-uuid-12345678",
            "quality_signals": {"tests_passed": 42, "coverage": "94.2%"},
        },
    }


def _incident_resolved_record() -> dict[str, Any]:
    return {
        "event_uuid": "00000000-0000-0000-0000-000000000007",
        "project_id": 99,
        "role": "operator",
        "subsystem": "orchestrator",
        "action": "incident_resolved",
        "actor": "operator",
        "subject_id": "INC-2026-0042",
        "metadata": {
            "root_cause": "DB connection pool exhausted; raised pool size.",
            "severity": "P1",
        },
    }


_ALL_TRIGGER_RECORDS = {
    "verify.passed": _verify_pass_record,
    "verify.failed": _verify_fail_record,
    "approval.granted": _approval_granted_record,
    "approval.rejected": _approval_rejected_record,
    "phase.advance.success": _phase_advanced_record,
    "build.completed": _build_completed_record,
    "incident.resolved": _incident_resolved_record,
}


class WriterHookDispatchTests(unittest.TestCase):
    """Unit tests for dispatch + default extractors."""

    def setUp(self) -> None:
        clear_hooks()  # ensure clean slate
        # Defaults register lazily on first dispatch.

    def tearDown(self) -> None:
        clear_hooks()

    def test_canonical_event_keys(self) -> None:
        self.assertEqual(set(EVENT_KEYS), set(_ALL_TRIGGER_RECORDS))
        self.assertEqual(len(EVENT_KEYS), 7)

    def test_seven_trigger_points_each_produce_a_draft(self) -> None:
        results: dict[str, list[LessonDraft]] = {}
        for key, factory in _ALL_TRIGGER_RECORDS.items():
            clear_hooks()
            drafts = dispatch(factory())
            results[key] = drafts
            self.assertEqual(
                len(drafts), 1, msg=f"{key}: expected exactly 1 draft, got {len(drafts)}",
            )
        # Coverage: 7/7
        self.assertEqual(len(results), 7)

    def test_verify_needs_review_does_not_fire(self) -> None:
        rec = _verify_pass_record()
        rec["metadata"]["pass_fail"] = "needs_user_review"
        self.assertEqual(dispatch(rec), [])

    def test_unrelated_action_does_not_fire(self) -> None:
        rec = {
            "event_uuid": "x", "project_id": 1, "role": "engineer",
            "subsystem": "build", "action": "llm_call", "actor": "engineer",
            "metadata": {},
        }
        self.assertEqual(dispatch(rec), [])

    def test_failed_phase_advance_does_not_fire(self) -> None:
        rec = _phase_advanced_record()
        rec["metadata"]["status"] = "failed"
        self.assertEqual(dispatch(rec), [])

    def test_drafts_carry_event_key_metadata(self) -> None:
        for key, factory in _ALL_TRIGGER_RECORDS.items():
            clear_hooks()
            d = dispatch(factory())[0]
            self.assertEqual(d.metadata.get("event_key"), key, msg=key)

    def test_drafts_contain_project_id(self) -> None:
        for _key, factory in _ALL_TRIGGER_RECORDS.items():
            clear_hooks()
            d = dispatch(factory())[0]
            self.assertIsNotNone(d.project_id)

    def test_extractor_exception_is_isolated(self) -> None:
        clear_hooks()

        def _boom(_record: dict[str, Any]):
            raise RuntimeError("intentional")

        register_hook("verify.passed", _boom)
        # Should not raise; defaults still fire.
        drafts = dispatch(_verify_pass_record())
        self.assertEqual(len(drafts), 1)  # default still ran
        self.assertEqual(drafts[0].metadata["event_key"], "verify.passed")

    def test_custom_hook_fires_alongside_default(self) -> None:
        clear_hooks()

        def _extra(record: dict[str, Any]) -> LessonDraft:
            return LessonDraft(
                role="custom", lesson_text="custom lesson",
                source_path="audit://test/x", tags=["custom"],
                project_id=record.get("project_id"),
                metadata={"event_key": "verify.passed", "custom": True},
            )

        register_hook("verify.passed", _extra)
        drafts = dispatch(_verify_pass_record())
        self.assertEqual(len(drafts), 2)
        custom = [d for d in drafts if d.metadata.get("custom")]
        self.assertEqual(len(custom), 1)

    def test_register_rejects_unknown_event_key(self) -> None:
        with self.assertRaises(ValueError):
            register_hook("not.real", lambda r: None)


class FlushPendingTests(unittest.TestCase):
    """Drain the in-memory queue through an injected writer."""

    def setUp(self) -> None:
        clear_hooks()

    def tearDown(self) -> None:
        clear_hooks()

    def test_flush_drains_via_injected_writer(self) -> None:
        for factory in _ALL_TRIGGER_RECORDS.values():
            dispatch(factory())
        captured: list[LessonDraft] = []

        def _writer(draft: LessonDraft, _url: str) -> None:
            captured.append(draft)

        n = flush_pending(db_url="postgresql://noop", writer=_writer)
        self.assertEqual(n, 7)
        self.assertEqual(len(captured), 7)
        # All 7 event keys represented.
        keys = {d.metadata["event_key"] for d in captured}
        self.assertEqual(keys, set(_ALL_TRIGGER_RECORDS))

    def test_writer_exception_drops_one_draft_continues_others(self) -> None:
        for factory in _ALL_TRIGGER_RECORDS.values():
            dispatch(factory())

        calls = {"n": 0}

        def _writer(draft: LessonDraft, _url: str) -> None:
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("simulated DB outage")

        n = flush_pending(db_url="postgresql://noop", writer=_writer)
        # 6 successes (one was dropped after raising); call count is 7
        self.assertEqual(n, 6)
        self.assertEqual(calls["n"], 7)

    def test_pending_drafts_is_nondestructive(self) -> None:
        dispatch(_verify_pass_record())
        before = pending_drafts()
        after = pending_drafts()
        self.assertEqual(len(before), 1)
        self.assertEqual(len(after), 1)


class AuditRecordIntegrationTests(unittest.TestCase):
    """Confirm audit_record.write_via_psql wiring calls dispatch.

    We don't run psql here — instead we monkeypatch ``subprocess.run``
    inside the audit module so the persist call returns a synthetic
    event_id, and assert dispatch produced a draft.
    """

    def setUp(self) -> None:
        clear_hooks()

    def tearDown(self) -> None:
        clear_hooks()

    def test_write_via_psql_fires_memory_hook(self) -> None:
        from shared.audit import audit_record as ar

        # Build a real AuditRecord that classifies to verify.passed.
        rec = ar.AuditRecord(
            role="verify", subsystem="verify", action="verify_audit",
            actor="verify",
            metadata={
                "pass_fail": "pass",
                "artifact_uuid": "abcdef1234567890",
                "calibration_band": "high",
                "critical_count": 0, "high_count": 0,
            },
        )
        chained = ar.chain_to_previous(rec, None)

        # Fake the psql subprocess so it returns event_id=999.
        class _FakeProc:
            stdout = "999\n"
            stderr = ""

        original_run = ar.subprocess.run

        def _fake_run(*args, **kwargs):  # type: ignore[no-untyped-def]
            return _FakeProc()

        ar.subprocess.run = _fake_run  # type: ignore[assignment]
        try:
            event_id = ar.write_via_psql(
                chained, db_url="postgresql://noop", skip_redaction=True,
            )
        finally:
            ar.subprocess.run = original_run  # type: ignore[assignment]

        self.assertEqual(event_id, 999)
        # One draft should have been produced + queued.
        drafts = pending_drafts()
        self.assertEqual(len(drafts), 1)
        self.assertEqual(drafts[0].metadata["event_key"], "verify.passed")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
