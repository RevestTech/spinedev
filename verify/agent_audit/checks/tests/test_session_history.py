"""Tests for L02 session_history check."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from verify.agent_audit.checks.session_history import (
    check_session_history_layer,
)

_THIRTY_ONE_DAYS = 31 * 24 * 60 * 60


def _write_status(directive_dir: Path, age_seconds: float = 0) -> Path:
    directive_dir.mkdir(parents=True, exist_ok=True)
    status_path = directive_dir / "status.json"
    status_path.write_text(
        json.dumps({"directive_id": directive_dir.name, "status": "done"}),
        encoding="utf-8",
    )
    if age_seconds:
        past = time.time() - age_seconds
        os.utime(status_path, (past, past))
    return status_path


def test_pending_when_work_dir_missing(tmp_path: Path) -> None:
    finding = check_session_history_layer(tmp_path, {})
    assert finding.layer == "L02_session_history"
    assert finding.status == "instrumentation_pending"
    assert finding.severity == "low"


def test_clean_when_directives_fresh(tmp_path: Path) -> None:
    directive_dir = (
        tmp_path / ".spine" / "work" / "proj_a" / "directives" / "dir_001"
    )
    _write_status(directive_dir, age_seconds=0)
    finding = check_session_history_layer(tmp_path, {})
    assert finding.status == "clean"
    assert finding.evidence == ()


def test_warning_on_stale_directive_without_archive(tmp_path: Path) -> None:
    directive_dir = (
        tmp_path / ".spine" / "work" / "proj_a" / "directives" / "dir_old"
    )
    _write_status(directive_dir, age_seconds=_THIRTY_ONE_DAYS)
    finding = check_session_history_layer(tmp_path, {})
    assert finding.status == "warning"
    assert finding.severity == "medium"
    assert any("dir_old" in e for e in finding.evidence)
    assert any("make hygiene" in a for a in finding.next_actions)


def test_stale_directive_with_archive_trace_is_clean(tmp_path: Path) -> None:
    directive_dir = (
        tmp_path / ".spine" / "work" / "proj_a" / "directives" / "dir_arch"
    )
    _write_status(directive_dir, age_seconds=_THIRTY_ONE_DAYS)
    archive_root = tmp_path / ".spine" / "archive"
    archive_root.mkdir(parents=True)
    (archive_root / "dir_arch.tar.gz").write_bytes(b"x")
    finding = check_session_history_layer(tmp_path, {})
    assert finding.status == "clean"


def test_warning_on_forbidden_patterns(tmp_path: Path) -> None:
    directive_dir = (
        tmp_path / ".spine" / "work" / "proj_b" / "directives" / "dir_002"
    )
    _write_status(directive_dir, age_seconds=0)
    (directive_dir / "notes.bak").write_text("oops", encoding="utf-8")
    (directive_dir / "scratch.txt").write_text("scratch", encoding="utf-8")
    (directive_dir / "session.swp").write_bytes(b"swap")
    finding = check_session_history_layer(tmp_path, {})
    assert finding.status == "warning"
    assert finding.severity == "medium"
    joined = " ".join(finding.evidence)
    assert "*.bak" in joined
    assert "scratch.*" in joined
    assert "*.swp" in joined


def test_warning_on_old_pycache(tmp_path: Path) -> None:
    directive_dir = (
        tmp_path / ".spine" / "work" / "proj_c" / "directives" / "dir_003"
    )
    _write_status(directive_dir, age_seconds=0)
    pyc_dir = directive_dir / "__pycache__"
    pyc_dir.mkdir()
    past = time.time() - _THIRTY_ONE_DAYS
    os.utime(pyc_dir, (past, past))
    finding = check_session_history_layer(tmp_path, {})
    assert finding.status == "warning"
    assert any("__pycache__" in e for e in finding.evidence)


def test_skips_files_without_status_json(tmp_path: Path) -> None:
    directive_dir = (
        tmp_path / ".spine" / "work" / "proj_d" / "directives" / "dir_004"
    )
    directive_dir.mkdir(parents=True)
    (directive_dir / "directive.md").write_text("# d", encoding="utf-8")
    finding = check_session_history_layer(tmp_path, {})
    assert finding.status == "clean"


def test_skips_non_directory_entries(tmp_path: Path) -> None:
    work_root = tmp_path / ".spine" / "work"
    work_root.mkdir(parents=True)
    # Stray file at work-root level — should be ignored, not crash.
    (work_root / "stray.txt").write_text("noise", encoding="utf-8")
    # A project dir with no `directives/` sub-tree — should be skipped.
    (work_root / "proj_e").mkdir()
    finding = check_session_history_layer(tmp_path, {})
    assert finding.status == "clean"
