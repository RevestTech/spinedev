"""Dedupe helpers for Temporal audit synthesis."""

from __future__ import annotations

from tron.workflows.finding_merge import dedupe_findings_dicts


def test_dedupe_keeps_higher_layer3_on_tie():
    a = {
        "finding_fingerprint": "fp1",
        "confidence": 0.8,
        "deterministic_tool_confirmed": False,
        "layer3_execution": "unverified",
    }
    b = {
        "finding_fingerprint": "fp1",
        "confidence": 0.8,
        "deterministic_tool_confirmed": False,
        "layer3_execution": "verified",
    }
    out = dedupe_findings_dicts([a, b])
    assert len(out) == 1
    assert out[0]["layer3_execution"] == "verified"
