"""Tests for the V3 #27 / B3 instinct hook in
``shared.runtime.role_runtime.complete_directive``.

Covers:
  * Successful completion records an instinct observation under
    SPINE_INSTINCT_ROOT scoped to the project.
  * Failed completion records nothing.
  * Same role + same directive across two runs produce matching
    fingerprints (the corroboration prerequisite for promotion).
  * Different role on the same directive produces a different
    fingerprint.
  * If learning.instinct is unimportable / writes raise, directive
    completion still succeeds (fail-soft per #27).
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from shared.runtime.role_runtime import (
    begin_directive,
    complete_directive,
    fail_directive,
)


def _instinct_root(monkeypatch, tmp_path):
    root = tmp_path / "instincts"
    monkeypatch.setenv("SPINE_INSTINCT_ROOT", str(root))
    return root


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line.strip()]


def test_completion_records_instinct(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _instinct_root(monkeypatch, tmp_path)
    # role_runtime writes under .spine/work via _REPO_ROOT; point it at tmp_path
    monkeypatch.setattr(
        "shared.runtime.role_runtime._directives_root",
        lambda: tmp_path / "work",
    )

    handle = begin_directive(
        project_uuid="proj-a",
        role="engineer",
        directive="Implement REQ-AUTH-7 session rotation",
    )
    complete_directive(handle, report_md="done", ok=True)

    jsonl = root / "proj-a" / f"{handle.directive_id}.jsonl"
    assert jsonl.exists()
    rows = _read_jsonl(jsonl)
    assert len(rows) == 1
    assert rows[0]["instinct"]["pattern"] == "engineer completed directive"
    assert "REQ-AUTH-7" in rows[0]["instinct"]["trigger"]
    assert rows[0]["actor"] == "engineer"


def test_failed_completion_records_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _instinct_root(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "shared.runtime.role_runtime._directives_root",
        lambda: tmp_path / "work",
    )

    handle = begin_directive(
        project_uuid="proj-a",
        role="engineer",
        directive="Implement REQ-AUTH-7",
    )
    fail_directive(handle, error="LLM timeout")

    proj_dir = root / "proj-a"
    # No instinct file should be created for the failed run.
    assert not proj_dir.exists() or not any(proj_dir.glob("*.jsonl"))


def test_same_directive_same_role_share_fingerprint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _instinct_root(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "shared.runtime.role_runtime._directives_root",
        lambda: tmp_path / "work",
    )

    h1 = begin_directive(
        project_uuid="proj-a",
        role="engineer",
        directive="Implement REQ-AUTH-7",
    )
    complete_directive(h1, report_md="done", ok=True)

    h2 = begin_directive(
        project_uuid="proj-a",
        role="engineer",
        directive="Implement REQ-AUTH-7",
    )
    complete_directive(h2, report_md="done", ok=True)

    rows = []
    for path in (root / "proj-a").glob("*.jsonl"):
        rows.extend(_read_jsonl(path))
    assert len(rows) == 2
    # Different record_ids, same fingerprint key inputs (pattern + trigger).
    fps = {(r["instinct"]["pattern"], r["instinct"]["trigger"]) for r in rows}
    assert len(fps) == 1


def test_different_role_changes_fingerprint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _instinct_root(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "shared.runtime.role_runtime._directives_root",
        lambda: tmp_path / "work",
    )

    h1 = begin_directive(
        project_uuid="proj-a",
        role="engineer",
        directive="Implement REQ-AUTH-7",
    )
    complete_directive(h1, report_md="done", ok=True)

    h2 = begin_directive(
        project_uuid="proj-a",
        role="qa",
        directive="Implement REQ-AUTH-7",
    )
    complete_directive(h2, report_md="done", ok=True)

    rows = []
    for path in (root / "proj-a").glob("*.jsonl"):
        rows.extend(_read_jsonl(path))
    assert len(rows) == 2
    patterns = {r["instinct"]["pattern"] for r in rows}
    assert patterns == {"engineer completed directive", "qa completed directive"}


def test_complete_directive_publishes_both_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Successful completion fires directive_complete + instinct_recorded."""
    import asyncio

    from shared.api.realtime.event_publisher import subscribe, unsubscribe

    _instinct_root(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "shared.runtime.role_runtime._directives_root",
        lambda: tmp_path / "work",
    )

    async def body():
        q = subscribe("proj-rt")
        try:
            handle = begin_directive(
                project_uuid="proj-rt",
                role="engineer",
                directive="Implement REQ-RT-1 realtime wiring",
            )
            complete_directive(handle, report_md="done", ok=True)
            await asyncio.sleep(0)

            seen_types = set()
            for _ in range(2):
                evt = await asyncio.wait_for(q.get(), timeout=1.0)
                seen_types.add(evt.event_type)

            assert seen_types == {"directive_complete", "instinct_recorded"}
        finally:
            unsubscribe(q)

    asyncio.run(body())


def test_failed_completion_publishes_directive_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Failure fires directive_complete (verdict=failed) but no instinct."""
    import asyncio

    from shared.api.realtime.event_publisher import subscribe, unsubscribe

    _instinct_root(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "shared.runtime.role_runtime._directives_root",
        lambda: tmp_path / "work",
    )

    async def body():
        q = subscribe("proj-rt2")
        try:
            handle = begin_directive(
                project_uuid="proj-rt2",
                role="engineer",
                directive="this will fail",
            )
            fail_directive(handle, error="boom")
            await asyncio.sleep(0)

            evt = await asyncio.wait_for(q.get(), timeout=1.0)
            assert evt.event_type == "directive_complete"
            assert evt.verdict == "failed"
            assert q.empty()
        finally:
            unsubscribe(q)

    asyncio.run(body())


def test_instinct_failure_is_fail_soft(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _instinct_root(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "shared.runtime.role_runtime._directives_root",
        lambda: tmp_path / "work",
    )

    handle = begin_directive(
        project_uuid="proj-a",
        role="engineer",
        directive="Implement REQ-AUTH-7",
    )

    # Make the instinct store raise on record. Directive completion must
    # still succeed — the role's report is the source of truth, not the
    # observation.
    with patch(
        "learning.instinct.InstinctStore.record",
        side_effect=RuntimeError("disk full"),
    ):
        complete_directive(handle, report_md="done", ok=True)

    status = json.loads(
        (handle.workspace / "status.json").read_text(encoding="utf-8")
    )
    assert status["status"] == "done"
    assert (handle.workspace / "report.md").exists()
