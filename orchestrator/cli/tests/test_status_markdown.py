"""Tests for ``orchestrator.cli.status_markdown`` (V3 B5).

Covers:
  * Renderer output structure (headings, tables, warnings).
  * ``collect_db`` honours an injected psql runner.
  * ``collect_ledger`` walks JSONL files written by
    :class:`shared.audit.decision_ledger.DecisionLedger`.
  * ``compute_exit_code`` maps state to 0 / 1 / 2.
  * Smoke-cache parser handles realistic ``smoke-test.sh`` summary lines.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from orchestrator.cli.status_markdown import (
    DbSnapshot,
    GitSnapshot,
    HandoffState,
    LedgerSnapshot,
    PhaseCount,
    SmokeSnapshot,
    _parse_phase_counts,
    _parse_smoke_line,
    collect_db,
    collect_ledger,
    collect_smoke,
    compute_exit_code,
    render_markdown,
)

from shared.audit.decision_ledger import (
    Candidate,
    DecisionLedger,
    LedgerEntry,
    PromotionGate,
)


def _state(
    *,
    warnings: tuple[str, ...] = (),
    failures: tuple[str, ...] = (),
    ledger: tuple[LedgerSnapshot, ...] = (),
    smoke: SmokeSnapshot | None = None,
) -> HandoffState:
    return HandoffState(
        generated_at=datetime(2026, 5, 29, 12, 0, tzinfo=timezone.utc),
        spine_home=Path("/tmp/spine"),
        git=GitSnapshot(
            branch="main",
            is_clean=True,
            untracked_count=0,
            modified_count=0,
            ahead_main=0,
            last_commit="abc123 sample",
        ),
        db=DbSnapshot(
            reachable=True,
            error=None,
            phase_counts=(PhaseCount(phase="plan", count=1),),
            dispatches_in_flight=0,
            pending_decisions=0,
        ),
        ledger=ledger,
        smoke=smoke,
        warnings=warnings,
        failures=failures,
    )


# ─── Renderer ───


def test_render_includes_all_sections() -> None:
    md = render_markdown(_state())
    for heading in (
        "# Spine status snapshot",
        "## Readiness",
        "## Git",
        "## Database",
        "## Decision ledger",
        "## Smoke (last cached)",
        "## Warnings / failures",
    ):
        assert heading in md


def test_render_overall_state_reflects_failures() -> None:
    md = render_markdown(_state(failures=("smoke: FAIL=2",)))
    assert "Overall | **fail**" in md
    md_ok = render_markdown(_state())
    assert "Overall | **green**" in md_ok
    md_warn = render_markdown(_state(warnings=("db: unreachable",)))
    assert "Overall | **warning**" in md_warn


def test_render_ledger_table_when_entries_present() -> None:
    snap = LedgerSnapshot(
        project_id="proj-a",
        run_id="run-1",
        entries_seen=3,
        last_verdict="denied",
        last_tier="production",
        last_reasons=("freshness_stale",),
        denials_in_tail=3,
        chain_ok=True,
        chain_reason=None,
    )
    md = render_markdown(_state(ledger=(snap,)))
    assert "| `proj-a` | `run-1` | 3 | denied | production | ok |" in md


def test_render_smoke_section_when_available() -> None:
    smoke = SmokeSnapshot(
        available=True,
        pass_count=99,
        fail_count=0,
        warn_count=1,
        skip_count=0,
        info_count=3,
        last_run_ts="2026-05-29T11:00:00+00:00",
    )
    md = render_markdown(_state(smoke=smoke))
    assert "PASS=99" in md and "FAIL=0" in md


# ─── Exit codes ───


def test_exit_code_zero_when_green() -> None:
    assert compute_exit_code(_state()) == 0


def test_exit_code_one_for_warnings_only() -> None:
    assert compute_exit_code(_state(warnings=("anything",))) == 1


def test_exit_code_two_for_any_failure() -> None:
    assert compute_exit_code(_state(failures=("broken",))) == 2
    # Failures dominate warnings
    assert compute_exit_code(
        _state(failures=("broken",), warnings=("noisy",))
    ) == 2


# ─── Parsers ───


def test_parse_phase_counts_pipe_separated() -> None:
    sql_out = "plan|3\nbuild|1\nverify|0\n"
    rows = list(_parse_phase_counts(sql_out))
    assert rows == [
        PhaseCount(phase="plan", count=3),
        PhaseCount(phase="build", count=1),
        PhaseCount(phase="verify", count=0),
    ]


def test_parse_smoke_line_realistic_summary() -> None:
    line = "PASS=99  FAIL=0  WARN=1  SKIP=0  INFO=3  (total=103)"
    counts = _parse_smoke_line(line)
    assert counts == {
        "pass_count": 99,
        "fail_count": 0,
        "warn_count": 1,
        "skip_count": 0,
        "info_count": 3,
    }


def test_parse_smoke_line_rejects_bad_int() -> None:
    line = "PASS=oops FAIL=0"
    assert _parse_smoke_line(line) is None


# ─── DB collector ───


def test_collect_db_uses_injected_runner() -> None:
    calls: list[str] = []

    def fake_psql(sql: str) -> str:
        calls.append(sql)
        if "current_phase" in sql:
            return "plan|2\nbuild|1\n"
        if "dispatch_in_flight" in sql:
            return "1\n"
        if "approval" in sql:
            return "3\n"
        return ""

    snap = collect_db(psql_runner=fake_psql)
    assert snap.reachable is True
    assert snap.phase_counts == (
        PhaseCount(phase="plan", count=2),
        PhaseCount(phase="build", count=1),
    )
    assert snap.dispatches_in_flight == 1
    assert snap.pending_decisions == 3
    assert len(calls) == 3


def test_collect_db_runner_failure_marks_unreachable() -> None:
    def fake_psql(sql: str) -> str:
        raise RuntimeError("network down")

    snap = collect_db(psql_runner=fake_psql)
    assert snap.reachable is False
    assert snap.error is not None
    assert "network down" in snap.error


def test_collect_db_no_runner_marks_unreachable() -> None:
    snap = collect_db(psql_runner=None)
    assert snap.reachable is False


# ─── Ledger collector ───


def test_collect_ledger_walks_jsonl_tree(tmp_path: Path) -> None:
    ledger = DecisionLedger(project_id="proj-a", run_id="run-1", root=tmp_path)
    for idx, verdict_tier in enumerate(
        [("paper", True), ("production", True), ("production", False)]
    ):
        tier, ok = verdict_tier
        gate = PromotionGate.evaluate(
            tier=tier,
            freshness_passed=ok,
            replay_passed=ok,
        )
        ledger.append(
            LedgerEntry(
                project_id="proj-a",
                run_id="run-1",
                actor="conductor",
                rollout_index=idx,
                candidates=[Candidate(candidate_id=f"c-{idx}", mark="accept")],
                promotion_gate=gate,
            )
        )

    snapshots = collect_ledger(root=tmp_path, tail=10)
    assert len(snapshots) == 1
    snap = snapshots[0]
    assert snap.project_id == "proj-a"
    assert snap.run_id == "run-1"
    assert snap.entries_seen == 3
    assert snap.chain_ok is True
    assert snap.denials_in_tail == 1
    assert snap.last_tier == "production"


def test_collect_ledger_empty_when_no_root(tmp_path: Path) -> None:
    assert collect_ledger(root=tmp_path / "does-not-exist") == ()


# ─── Smoke collector ───


def test_collect_smoke_reads_cached_summary(tmp_path: Path) -> None:
    spine_home = tmp_path
    (spine_home / ".spine").mkdir()
    (spine_home / ".spine" / "last-smoke.txt").write_text(
        "blah blah\n"
        "PASS=99  FAIL=0  WARN=1  SKIP=0  INFO=3  (total=103)\n",
        encoding="utf-8",
    )
    snap = collect_smoke(spine_home)
    assert snap is not None
    assert snap.available is True
    assert snap.pass_count == 99
    assert snap.fail_count == 0


def test_collect_smoke_returns_unavailable_when_missing(tmp_path: Path) -> None:
    snap = collect_smoke(tmp_path)
    assert snap is not None
    assert snap.available is False
