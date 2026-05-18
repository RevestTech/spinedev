"""KG indexer 3-trigger contract tests — Wave 1, V3 §1.2.

Verifies that the three trigger entry points (commit hook / audit
subscriber / periodic sweep) all (a) import + dispatch correctly,
(b) hand off to the canonical indexer / write paths under controlled
fakes, and (c) declare their trigger source.

No real Postgres, no real git, no real KG writes — every collaborator
is monkeypatched.
"""
from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from build.kg import (
    indexer_audit_subscriber as audit_sub,
    indexer_commit_hook as commit_hook,
    indexer_sweep as sweep,
)
from build.kg.indexer.indexer import IndexResult


class CommitHookTriggerTests(unittest.TestCase):
    def test_invalid_sha_returns_error_without_indexing(self) -> None:
        with mock.patch.object(commit_hook, "incremental_index") as m_inc:
            result = commit_hook.run_commit_hook("not-a-sha", repo_root=Path("."))
        m_inc.assert_not_called()
        self.assertEqual(result.fired_trigger, commit_hook.TRIGGER_SOURCE)
        self.assertTrue(result.result.errors)

    def test_valid_sha_calls_incremental_indexer(self) -> None:
        fake = IndexResult(files_indexed=2, node_count=10, edge_count=5)
        with mock.patch.object(commit_hook, "incremental_index", return_value=fake) as m_inc:
            result = commit_hook.run_commit_hook(
                "abc1234", repo_root=Path("."), database_url="postgresql://noop",
            )
        m_inc.assert_called_once()
        self.assertEqual(result.result.node_count, 10)
        self.assertEqual(result.fired_trigger, "commit_hook")

    def test_indexer_exception_is_caught(self) -> None:
        def _boom(*_a: Any, **_k: Any) -> Any:
            raise RuntimeError("DB outage")

        with mock.patch.object(commit_hook, "incremental_index", side_effect=_boom):
            result = commit_hook.run_commit_hook("abc1234", repo_root=Path("."))
        self.assertTrue(result.result.errors)
        self.assertTrue(any("DB outage" in e for e in result.result.errors))

    def test_install_post_commit_hook_writes_file(self) -> None:
        import tempfile, subprocess as sp
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sp.run(["git", "init", "-q"], cwd=root, check=True)
            installed = commit_hook.install_post_commit_hook(root)
            self.assertTrue(installed.exists())
            content = installed.read_text()
            self.assertIn("build.kg.indexer_commit_hook", content)
            # Hook must end with `exit 0` per spec (never block commit).
            self.assertIn("exit 0", content)


class AuditSubscriberTriggerTests(unittest.TestCase):
    def test_subscribed_actions_cover_non_canonical_events(self) -> None:
        # Non-canonical (bundle/charter/directive) actions are the secondary
        # path per V3 §1.2 — assert each is wired.
        for action in (
            "bundle_installed", "bundle_updated", "role_charter_changed",
            "decision_recorded", "directive_dispatched",
        ):
            self.assertIn(action, audit_sub.subscribed_actions())

    def test_handle_record_for_known_action_invokes_writer(self) -> None:
        captured: list[audit_sub.AuditTouch] = []

        def _writer(touch: audit_sub.AuditTouch, _url: str) -> None:
            captured.append(touch)

        record = {
            "event_uuid": "evt-1",
            "action": "bundle_updated",
            "actor": "spine-updater",
            "role": "operator",
            "subsystem": "orchestrator",
            "subject_id": "bundle-foo",
            "metadata": {"bundle_id": "bundle-foo", "version": "1.2.3"},
        }
        touch = audit_sub.handle_record(
            record, db_url="postgresql://noop", writer=_writer,
        )
        self.assertIsNotNone(touch)
        assert touch is not None  # for type checker
        self.assertEqual(touch.node_type, "standards_bundle")
        self.assertEqual(touch.node_subtype, "update")
        self.assertEqual(touch.name, "bundle-foo")
        self.assertEqual(len(captured), 1)

    def test_handle_record_for_unknown_action_no_write(self) -> None:
        captured: list[audit_sub.AuditTouch] = []

        def _writer(touch: audit_sub.AuditTouch, _url: str) -> None:
            captured.append(touch)

        record = {
            "event_uuid": "evt-2", "action": "llm_call",
            "actor": "engineer", "metadata": {},
        }
        touch = audit_sub.handle_record(record, writer=_writer)
        self.assertIsNone(touch)
        self.assertEqual(captured, [])

    def test_install_subscriber_is_idempotent(self) -> None:
        # Reset registration state for test isolation.
        audit_sub._REGISTERED = False  # type: ignore[attr-defined]
        audit_sub.install_subscriber()
        audit_sub.install_subscriber()  # second call no-ops
        self.assertTrue(audit_sub._REGISTERED)  # type: ignore[attr-defined]


class SweepTriggerTests(unittest.TestCase):
    def test_no_anchors_no_work(self) -> None:
        with mock.patch.object(sweep, "_kg_path_anchors", return_value={}), \
             mock.patch.object(sweep, "reindex_file") as m_re:
            result = sweep.run_sweep(Path("."), database_url="postgresql://noop")
        m_re.assert_not_called()
        self.assertEqual(result.files_stale, 0)
        self.assertEqual(result.fired_trigger, "sweep")

    def test_stale_file_triggers_reindex(self) -> None:
        import tempfile, time as _t
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fp = root / "foo.py"
            fp.write_text("x = 1\n")
            # Pretend KG anchor is 10 hours old.
            anchors = {"foo.py": _t.time() - 36000}
            fake_idx = IndexResult(files_indexed=1, node_count=3, edge_count=1)
            with mock.patch.object(sweep, "_kg_path_anchors", return_value=anchors), \
                 mock.patch.object(sweep, "reindex_file", return_value=fake_idx) as m_re:
                result = sweep.run_sweep(root, database_url="postgresql://noop")
            self.assertEqual(result.files_stale, 1)
            self.assertEqual(result.files_reindexed, 1)
            self.assertEqual(result.nodes_added, 3)
            m_re.assert_called_once()

    def test_fresh_file_skipped(self) -> None:
        import tempfile, time as _t
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fp = root / "foo.py"
            fp.write_text("x = 1\n")
            # KG anchor newer than file mtime → nothing stale.
            anchors = {"foo.py": _t.time() + 3600}
            with mock.patch.object(sweep, "_kg_path_anchors", return_value=anchors), \
                 mock.patch.object(sweep, "reindex_file") as m_re:
                result = sweep.run_sweep(root, database_url="postgresql://noop")
            self.assertEqual(result.files_stale, 0)
            m_re.assert_not_called()

    def test_missing_file_skipped(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            anchors = {"vanished.py": 1.0}
            with mock.patch.object(sweep, "_kg_path_anchors", return_value=anchors), \
                 mock.patch.object(sweep, "reindex_file") as m_re:
                result = sweep.run_sweep(root, database_url="postgresql://noop")
            m_re.assert_not_called()
            self.assertEqual(result.files_stale, 0)

    def test_file_limit_caps_reindex_count(self) -> None:
        import tempfile, time as _t
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for i in range(3):
                (root / f"f{i}.py").write_text("x=1\n")
            anchors = {f"f{i}.py": _t.time() - 36000 for i in range(3)}
            fake = IndexResult(files_indexed=1, node_count=1, edge_count=0)
            with mock.patch.object(sweep, "_kg_path_anchors", return_value=anchors), \
                 mock.patch.object(sweep, "reindex_file", return_value=fake) as m_re:
                result = sweep.run_sweep(
                    root, database_url="postgresql://noop", file_limit=2,
                )
            self.assertEqual(result.files_stale, 3)
            self.assertEqual(result.files_reindexed, 2)
            self.assertEqual(m_re.call_count, 2)


class TriggerSourceLabelTests(unittest.TestCase):
    """All three triggers expose a distinguishable source label."""

    def test_distinct_trigger_sources(self) -> None:
        sources = {
            commit_hook.TRIGGER_SOURCE,
            audit_sub.TRIGGER_SOURCE,
            sweep.TRIGGER_SOURCE,
        }
        self.assertEqual(len(sources), 3)
        self.assertEqual(
            sources, {"commit_hook", "audit_subscriber", "sweep"},
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
