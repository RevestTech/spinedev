"""Unit tests for Tron → application handoff markdown export."""

from __future__ import annotations

from pathlib import Path

from tron.services.scan_handoff_export import (
    TRON_HANDOFF_MANAGED_BEGIN,
    TRON_HANDOFF_MANAGED_END,
    UnmarkedExistingStrategy,
    append_tron_md_activity_log,
    build_tron_post_scan_markdown,
    handoff_templates_dir,
    merge_or_write_managed_file,
    substitute_template,
    tron_handoff_audit_marker,
    wrap_managed_handoff_inner,
    write_audit_handoff_bundle,
)


def test_handoff_templates_dir_exists() -> None:
    d = handoff_templates_dir()
    assert d.is_dir()
    assert (d / "tron-scan-followups.mdc.template").is_file()


def test_substitute_template() -> None:
    s = "Hello {{APP_NAME}} id={{TRON_AUDIT_ID}} base={{TRON_UI_BASE}}"
    assert (
        substitute_template(
            s, app_name="X", audit_id="u1", tron_ui_base="http://h/"
        )
        == "Hello X id=u1 base=http://h"
    )


def test_build_tron_post_scan_markdown_table_and_top() -> None:
    audit = {
        "status": "completed",
        "progress": 100,
        "findings_total": 3,
        "findings_critical": 0,
        "findings_high": 2,
        "findings_medium": 1,
        "findings_low": 0,
        "started_at": "2026-04-21T11:34:14+00:00",
        "completed_at": "2026-04-21T11:39:13+00:00",
    }
    findings = [
        {
            "severity": "medium",
            "file_path": "b.txt",
            "line_start": 2,
            "title": "M1",
            "category": "c",
        },
        {
            "severity": "high",
            "file_path": "a.txt",
            "line_start": 1,
            "title": "H1",
            "category": None,
        },
        {
            "severity": "high",
            "file_path": "z.txt",
            "line_start": 9,
            "title": "H2",
            "category": "x",
        },
    ]
    md = build_tron_post_scan_markdown(
        app_name="App",
        audit_id="aid",
        tron_ui_base="http://localhost:13080",
        audit=audit,
        findings=findings,
    )
    # Header identifies the app and audit.
    assert "— App" in md
    assert "`aid`" in md
    # Severity counts appear in the snapshot table.
    assert "| CRITICAL | 0 |" in md
    assert "| HIGH     | 2 |" in md
    # Each finding renders as a directive with its file location.
    assert "`a.txt:1`" in md
    assert "`z.txt:9`" in md
    assert "`b.txt:2`" in md
    # High findings must precede the medium finding (severity ordering).
    assert md.index("H1") < md.index("M1")
    assert md.index("H2") < md.index("M1")


def test_wrap_managed_handoff_inner() -> None:
    w = wrap_managed_handoff_inner("alpha\n")
    assert w.startswith(TRON_HANDOFF_MANAGED_BEGIN)
    assert TRON_HANDOFF_MANAGED_END in w
    assert "alpha" in w


def test_merge_or_write_replaces_only_managed_region(tmp_path: Path) -> None:
    p = tmp_path / "f.md"
    p.write_text(
        "KEEP_TOP\n"
        + wrap_managed_handoff_inner("old_inner")
        + "\nKEEP_BOTTOM\n",
        encoding="utf-8",
    )
    merge_or_write_managed_file(
        p, "new_inner", unmarked_existing=UnmarkedExistingStrategy.REPLACE
    )
    s = p.read_text(encoding="utf-8")
    assert "KEEP_TOP" in s and "KEEP_BOTTOM" in s
    assert "new_inner" in s and "old_inner" not in s


def test_merge_or_write_prepends_when_unmarked(tmp_path: Path) -> None:
    p = tmp_path / "CLAUDE.md"
    p.write_text("human\n", encoding="utf-8")
    merge_or_write_managed_file(
        p, "tron_managed", unmarked_existing=UnmarkedExistingStrategy.PREPEND
    )
    s = p.read_text(encoding="utf-8")
    assert s.index(TRON_HANDOFF_MANAGED_BEGIN) < s.index("human")
    assert "tron_managed" in s


def test_merge_or_write_replace_drops_unmarked_existing(tmp_path: Path) -> None:
    p = tmp_path / "TRON_POST_SCAN.md"
    p.write_text("stale\n", encoding="utf-8")
    merge_or_write_managed_file(
        p, "fresh", unmarked_existing=UnmarkedExistingStrategy.REPLACE
    )
    s = p.read_text(encoding="utf-8")
    assert "fresh" in s and "stale" not in s


def test_write_audit_handoff_bundle_preserves_tail(tmp_path: Path) -> None:
    rules = tmp_path / ".cursor" / "rules"
    rules.mkdir(parents=True)
    ag = tmp_path / "AGENTS.md"
    ag.write_text(
        wrap_managed_handoff_inner("v0")
        + "\n\n## Local playbook\n\nDo not delete.\n",
        encoding="utf-8",
    )
    audit = {
        "status": "completed",
        "progress": 100,
        "findings_total": 0,
        "findings_critical": 0,
        "findings_high": 0,
        "findings_medium": 0,
        "findings_low": 0,
        "started_at": "2026-04-21T11:34:14+00:00",
        "completed_at": "2026-04-21T11:39:13+00:00",
    }
    write_audit_handoff_bundle(
        tmp_path,
        app_name="App",
        audit_id="new-audit",
        tron_ui_base="http://x/",
        audit=audit,
        findings=[],
        append_tron_md_activity=False,
    )
    text = ag.read_text(encoding="utf-8")
    assert "Do not delete" in text
    assert "new-audit" in text
    assert "v0" not in text


def test_append_tron_md_activity_log_creates_file(tmp_path: Path) -> None:
    audit = {
        "findings_total": 1,
        "findings_critical": 0,
        "findings_high": 1,
        "findings_medium": 0,
        "findings_low": 0,
        "completed_at": "2026-04-21T12:00:00+00:00",
    }
    p = append_tron_md_activity_log(
        tmp_path,
        app_name="Svc",
        audit_id="audit-1",
        tron_ui_base="http://tron/",
        audit=audit,
    )
    assert p is not None
    t = (tmp_path / "tron.md").read_text(encoding="utf-8")
    assert tron_handoff_audit_marker("audit-1") in t
    assert "Tron in this repository" in t
    assert "1 / 0 / 1 / 0 / 0" in t


def test_append_tron_md_activity_log_idempotent(tmp_path: Path) -> None:
    audit = {
        "findings_total": 0,
        "findings_critical": 0,
        "findings_high": 0,
        "findings_medium": 0,
        "findings_low": 0,
        "completed_at": "2026-04-21T12:00:00+00:00",
    }
    append_tron_md_activity_log(
        tmp_path,
        app_name="Svc",
        audit_id="same-id",
        tron_ui_base="http://tron/",
        audit=audit,
    )
    append_tron_md_activity_log(
        tmp_path,
        app_name="Svc",
        audit_id="same-id",
        tron_ui_base="http://tron/",
        audit=audit,
    )
    t = (tmp_path / "tron.md").read_text(encoding="utf-8")
    assert t.count(tron_handoff_audit_marker("same-id")) == 1
