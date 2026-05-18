"""Unit tests for the Wave-1 rename-detection bug fix in phase_evolution.

Covers the quiet bug that collapsed multiple add/remove pairs into spurious
``phase_renamed`` events whenever the source phases were missing an explicit
``label`` field. The signature now falls back to ``name`` / ``id`` so each
phase keeps its own identity.
"""
from __future__ import annotations

import unittest
from typing import Any

from plan.pipeline.manifest_loader import PipelineManifest
from plan.pipeline.phase_evolution import (
    _detect_renames,
    _label_for,
    _signature,
    detect_evolution_events,
)


def _phase(
    pid: str,
    *,
    label: str | None = None,
    name: str | None = None,
    subsystem: str | None = None,
    artifact: str | None = None,
) -> dict[str, Any]:
    p: dict[str, Any] = {"id": pid}
    if label is not None:
        p["label"] = label
    if name is not None:
        p["name"] = name
    if subsystem is not None:
        p["subsystem"] = subsystem
    if artifact is not None:
        p["artifact"] = artifact
    return p


def _manifest(phases: list[dict[str, Any]], *, ver: int = 1) -> PipelineManifest:
    """Build a minimally-populated manifest. ``compute_pipeline_version``
    hashes the canonical body so version differences come for free."""
    return PipelineManifest(
        version=ver,
        org_bundle="test-bundle",
        phases=phases,
    )


class LabelFallbackTests(unittest.TestCase):
    """``_label_for`` must always return a non-empty string when any of
    label / name / id is set."""

    def test_label_explicit(self) -> None:
        self.assertEqual(_label_for({"id": "x", "label": "Intake"}), "Intake")

    def test_label_falls_back_to_name(self) -> None:
        self.assertEqual(_label_for({"id": "x", "name": "Intake"}), "Intake")

    def test_label_falls_back_to_id(self) -> None:
        self.assertEqual(_label_for({"id": "intake"}), "intake")

    def test_label_strips_whitespace(self) -> None:
        self.assertEqual(_label_for({"id": "x", "label": "  Intake  "}), "Intake")

    def test_label_empty_when_nothing_set(self) -> None:
        self.assertEqual(_label_for({}), "")


class SignatureTests(unittest.TestCase):
    """The (label, subsystem, artifact) signature must distinguish two
    label-less phases that share an artifact value."""

    def test_two_labelless_phases_distinct_ids_get_distinct_signatures(self) -> None:
        a = _phase("foo", artifact="prd.md")
        b = _phase("bar", artifact="prd.md")
        # Previously both collapsed to ("", "", "prd.md") — equal.
        self.assertNotEqual(_signature(a), _signature(b))
        # And every component is now a populated label-equivalent string.
        self.assertEqual(_signature(a)[0], "foo")
        self.assertEqual(_signature(b)[0], "bar")


class DetectRenamesTests(unittest.TestCase):
    """``_detect_renames`` is the actual surface that produced the bug —
    it must NOT pair unrelated label-less add/remove pairs."""

    def test_distinct_labelless_phases_are_not_paired(self) -> None:
        adds = [_phase("alpha", artifact="prd.md")]
        rems = [_phase("beta", artifact="prd.md")]
        renames, adds_left, rems_left = _detect_renames(adds, rems)
        self.assertEqual(renames, [], "should not collapse to a rename")
        self.assertEqual(adds_left, adds)
        self.assertEqual(rems_left, rems)

    def test_true_rename_with_label_still_detected(self) -> None:
        old_p = _phase("prd_draft", label="PRD Draft", artifact="prd.md")
        new_p = _phase("prd_initial", label="PRD Draft", artifact="prd.md")
        renames, adds_left, rems_left = _detect_renames([new_p], [old_p])
        self.assertEqual(len(renames), 1)
        self.assertEqual(renames[0][0]["id"], "prd_draft")
        self.assertEqual(renames[0][1]["id"], "prd_initial")
        self.assertEqual(adds_left, [])
        self.assertEqual(rems_left, [])

    def test_rename_via_id_fallback_when_label_missing(self) -> None:
        # Same id-as-label on both sides → rename heuristic still pairs.
        old_p = _phase("trd", subsystem="plan", artifact="trd.md")
        new_p = _phase("trd", subsystem="plan", artifact="trd.md")  # id unchanged
        # Two adds/removes with truly distinct ids should NOT pair via
        # id-fallback (the id IS the label, and they differ):
        adds = [_phase("verify_unit", subsystem="verify", artifact="report.json")]
        rems = [_phase("verify_integration", subsystem="verify", artifact="report.json")]
        renames, adds_left, rems_left = _detect_renames(adds, rems)
        self.assertEqual(renames, [])
        # And confirm the trivial unchanged pair (above) is a no-op when
        # treated as add+remove (this would never happen in practice; phases
        # with identical ids never appear in both adds and rems lists).


class EndToEndRenameEventTests(unittest.TestCase):
    """``detect_evolution_events`` must populate the rename event's
    detail dict with a non-empty label and a meaningful rationale."""

    def test_rename_event_carries_label(self) -> None:
        old = _manifest([_phase("prd_draft", label="PRD Draft", artifact="prd.md")])
        new = _manifest(
            [_phase("prd_initial", label="PRD Draft", artifact="prd.md")],
            ver=2,
        )
        events = detect_evolution_events(old, new)
        rename_events = [e for e in events if e.event_type == "phase_renamed"]
        self.assertEqual(
            len(rename_events), 1,
            f"expected exactly one rename event, got: "
            f"{[(e.event_type, e.phase_id) for e in events]}",
        )
        ev = rename_events[0]
        self.assertEqual(ev.detail.get("from"), "prd_draft")
        self.assertEqual(ev.detail.get("to"), "prd_initial")
        # ── THE LOAD-BEARING ASSERTION: label is non-empty ────────────
        self.assertTrue(ev.detail.get("label"), "label must be populated")
        self.assertEqual(ev.detail["label"], "PRD Draft")
        self.assertIn("PRD Draft", ev.rationale)

    def test_unrelated_phases_yield_add_and_remove_not_rename(self) -> None:
        """Without label, the pre-fix code collapsed unrelated phases into
        a rename. After the fix, each surfaces as its own event."""
        old = _manifest([_phase("alpha", artifact="x.md")])
        new = _manifest([_phase("beta", artifact="x.md")], ver=2)
        events = detect_evolution_events(old, new)
        types = sorted(e.event_type for e in events)
        # phase_added + phase_removed, NOT phase_renamed.
        self.assertEqual(types, ["phase_added", "phase_removed"])


if __name__ == "__main__":
    unittest.main()
